"""Strava API integration.

Pulls recent ride data to give the LLM context on training load before it
designs a strength session. A brutal long ride Sunday should soften Monday's
leg day — this makes that automatic.

Auth flow:
  - One-time: run `python -m src.setup_strava` to authorize and save refresh_token.
  - Every run: exchange refresh_token for a fresh access_token (expires hourly).
  - All credentials live in .env, never in code.
"""

import os
from datetime import datetime, timedelta, timezone

import requests

TOKEN_URL = "https://www.strava.com/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"

# Strava suffer score rough thresholds (their proprietary relative effort scale).
_SUFFER_EASY = 50
_SUFFER_MODERATE = 100
_SUFFER_HARD = 150


def _refresh_access_token():
    """Exchange refresh_token for a fresh access_token. Raises on failure."""
    resp = requests.post(TOKEN_URL, data={
        "client_id": os.environ["STRAVA_CLIENT_ID"],
        "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
        "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _fetch_activities(access_token, days=7):
    """Return raw activity list for the last `days` days."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    resp = requests.get(
        ACTIVITIES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"after": int(since.timestamp()), "per_page": 30},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def _classify_effort(activity):
    """Return 'easy', 'moderate', 'hard', or 'very hard' based on suffer score
    or, if missing, moving time (common for GPS-only activities)."""
    score = activity.get("suffer_score") or 0
    hours = activity.get("moving_time", 0) / 3600
    if score:
        if score >= _SUFFER_HARD:
            return "very hard"
        if score >= _SUFFER_MODERATE:
            return "hard"
        if score >= _SUFFER_EASY:
            return "moderate"
        return "easy"
    # Fallback: pure time heuristic
    if hours >= 3:
        return "very hard"
    if hours >= 2:
        return "hard"
    if hours >= 1:
        return "moderate"
    return "easy"


def _summarize(activities):
    """Build a human-readable training load summary for the LLM prompt."""
    if not activities:
        return "No Strava activities in the last 7 days."

    lines = []
    total_hours = 0
    total_elevation = 0

    for a in sorted(activities, key=lambda x: x["start_date"], reverse=True):
        date = datetime.fromisoformat(a["start_date"].replace("Z", "+00:00"))
        day_label = date.strftime("%a %-d %b")
        sport = a.get("sport_type", a.get("type", "Activity"))
        hours = a.get("moving_time", 0) / 3600
        elev = a.get("total_elevation_gain", 0)
        dist_km = a.get("distance", 0) / 1000
        suffer = a.get("suffer_score") or ""
        effort = _classify_effort(a)
        suffer_str = f", suffer score {suffer}" if suffer else ""
        lines.append(
            f"  {day_label}: {sport} {hours:.1f}h, {dist_km:.0f}km, "
            f"{elev:.0f}m elevation{suffer_str} [{effort}]"
        )
        total_hours += hours
        total_elevation += elev

    summary = "\n".join(lines)
    summary += f"\n  Week total: {total_hours:.1f}h riding, {total_elevation:.0f}m elevation gain"
    return summary


def _yesterday_note(activities, session_date):
    """Return a plain-English note about the day-before's activity, or None."""
    yesterday = (session_date - timedelta(days=1)).date()
    yesterday_acts = [
        a for a in activities
        if datetime.fromisoformat(
            a["start_date"].replace("Z", "+00:00")
        ).date() == yesterday
    ]
    if not yesterday_acts:
        return "No ride yesterday — legs should be reasonably fresh."
    efforts = [_classify_effort(a) for a in yesterday_acts]
    hardest = max(efforts, key=lambda e: ["easy","moderate","hard","very hard"].index(e))
    hours = sum(a.get("moving_time", 0) for a in yesterday_acts) / 3600
    return (
        f"Yesterday ({yesterday.strftime('%A')}): {hours:.1f}h riding, "
        f"hardest effort = {hardest}. "
        + ("Reduce lower-body power volume accordingly."
           if hardest in ("hard", "very hard") else
           "Legs should be OK for planned intensity.")
    )


def load_context(session_date=None):
    """Return a dict with 'summary' and 'yesterday_note' for the LLM prompt.

    Returns placeholder strings on any failure (no key, network down, etc.) so
    a Strava outage never blocks a workout from going out.
    """
    if session_date is None:
        session_date = datetime.now(timezone.utc)

    required = ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")
    if not all(os.environ.get(k) for k in required):
        return {
            "summary": "Strava not configured — skipping training load context.",
            "yesterday_note": "",
        }

    try:
        token = _refresh_access_token()
        activities = _fetch_activities(token, days=7)
        return {
            "summary": _summarize(activities),
            "yesterday_note": _yesterday_note(activities, session_date),
        }
    except Exception as e:
        return {
            "summary": f"Strava unavailable ({e}) — proceeding without load context.",
            "yesterday_note": "",
        }
