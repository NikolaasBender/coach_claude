"""Training consistency + re-entry detection.

The tracker is the ground truth for whether the athlete actually lifted. This
system only knows what it *programmed*, which is a very different thing — most
emailed sessions never get logged. So "did a strength session happen" means a
Garmin `strength_training` activity, or a session the athlete bothered to leave
feedback on.

Riding is read separately on purpose: someone who rides hard every week but
hasn't touched a barbell in a month is fit and *detrained*, not unfit. The
re-entry prescription for that athlete is light loads and short sessions, not
easy cardio.

Modes:
  on_track  — lifted within the last 10 days; program normally.
  rusty     — 10-20 days off; ramp back in, cap intensity, add one fun thing.
  off_wagon — 21+ days off (or never recorded); the only goal is making the
              athlete want to come back, so the session is short and playful.
"""

import os
import sqlite3
from datetime import datetime, timedelta, timezone

from . import feedback

DB_PATH = os.environ.get("GARMIN_DB_PATH", "data/garmin.db")

RUSTY_DAYS = 10
OFF_WAGON_DAYS = 21
# Completed sessions in 28 days at or below this = the habit isn't back yet.
# The program is 2x/week (~8 per 28 days), so 3 or fewer is sporadic at best.
HABIT_SESSIONS_28D = 3

# Garmin typeKeys that count as a lifting session.
_STRENGTH_KEYS = ("strength", "weight")


def _parse_date(value):
    """Date out of an ISO timestamp or plain YYYY-MM-DD. None if unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _tracker_strength_dates():
    """Dates of logged strength activities from the Garmin store (newest last)."""
    if not os.path.exists(DB_PATH):
        return []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT start_date, sport_type FROM activities ORDER BY start_date"
            ).fetchall()
    except sqlite3.Error:
        return []
    dates = []
    for start, sport in rows:
        key = (sport or "").lower()
        if any(k in key for k in _STRENGTH_KEYS):
            d = _parse_date(start)
            if d:
                dates.append(d)
    return dates


def _tracker_ride_stats(today, days=7):
    """(ride_count, moving_hours) over the trailing `days` — proof the athlete
    is still active even when they are not lifting."""
    if not os.path.exists(DB_PATH):
        return 0, 0.0
    cutoff = today - timedelta(days=days)
    try:
        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT start_date, sport_type, moving_time FROM activities"
            ).fetchall()
    except sqlite3.Error:
        return 0, 0.0
    count, seconds = 0, 0
    for start, sport, moving in rows:
        d = _parse_date(start)
        key = (sport or "").lower()
        if d and d > cutoff and not any(k in key for k in _STRENGTH_KEYS):
            count += 1
            seconds += int(moving or 0)
    return count, round(seconds / 3600.0, 1)


def _logged_session_dates():
    """Dates the athlete left feedback on — they did that session."""
    dates = []
    for entry in feedback.load():
        d = _parse_date(entry.get("session_date")) or _parse_date(entry.get("logged_at"))
        if d:
            dates.append(d)
    return dates


def assess(now=None):
    """Return the consistency picture used by the prompt, the template
    generator, and the email banner."""
    today = (now or datetime.now(timezone.utc)).date()

    strength_dates = sorted(set(_tracker_strength_dates() + _logged_session_dates()))
    ride_count, ride_hours = _tracker_ride_stats(today)

    last = strength_dates[-1] if strength_dates else None
    days_since = (today - last).days if last else None
    strength_28d = sum(1 for d in strength_dates if (today - d).days <= 28)

    if days_since is None or days_since >= OFF_WAGON_DAYS:
        mode = "off_wagon"
    elif days_since >= RUSTY_DAYS:
        mode = "rusty"
    elif strength_28d <= HABIT_SESSIONS_28D:
        # One isolated session after a long gap is not a habit yet — keep the
        # next couple of sessions easy and fun until the cadence is back.
        mode = "rusty"
    else:
        mode = "on_track"

    return {
        "mode": mode,
        "last_strength": last.isoformat() if last else None,
        "days_since": days_since,
        "strength_28d": strength_28d,
        "ride_count_7d": ride_count,
        "ride_hours_7d": ride_hours,
    }


def _gap_phrase(state):
    days = state["days_since"]
    if days is None:
        return "No completed strength session on record yet"
    return f"Last completed strength session was {days} days ago ({state['last_strength']})"


def _riding_phrase(state):
    if not state["ride_count_7d"]:
        return "No rides logged in the last 7 days either."
    return (
        f"Still riding: {state['ride_count_7d']} activities / "
        f"{state['ride_hours_7d']}h in the last 7 days — aerobically fit, "
        "just detrained for lifting."
    )


REENTRY_RULES = """RE-ENTRY RULES — THIS SESSION MUST BE FUN, NOT PUNISHING:
- SHORT: 30-40 minutes, 4-6 working movements total (rehab warmup still counts
  as the opener but keep it to 3 quick drills).
- Cap EVERY rpe at 7. No near-maximal loads, no grinding, no sets to failure.
- About 60% of normal volume. The compound lead-off stays, but moderate: think
  technique-weight squat/hinge/pull, 3 sets of 5-8, not a heavy top set.
- Limit heavy eccentrics and high-rep novel movements — the athlete will be
  sore for days otherwise and that is how comebacks die.
- Bias selection toward movements that feel athletic and that the athlete has
  said they enjoy: kettlebell swings and complexes/flows, loaded carries,
  low-box jumps, BOSU balance work, circuit or EMOM formats.
- Include ONE deliberate PLAY element — a KB flow, an EMOM, a balance or
  jump-quality challenge, a carry medley — and call it out in coach_notes as
  the fun bit.
- Open coach_notes by welcoming them back in one sentence. No guilt, no
  lecturing about the time off, no "we need to rebuild your base" framing.
- Finish with the athlete wanting the next session, not needing to recover
  from this one."""

RAMP_RULES = """RAMP-BACK RULES (short layoff, not a full reset):
- Cap rpe at 8 and keep the compound lead-off at a confident working weight —
  no max singles, no PR attempts.
- About 75% of normal volume; stop each set 2-3 reps short.
- Include one playful or athletic element (jumps, a carry medley, a KB flow)
  so the session is something to look forward to.
- Acknowledge the gap in ONE short clause in coach_notes, then move on."""


def prompt_section(state):
    """The CONSISTENCY block injected into the LLM prompt."""
    head = (
        "CONSISTENCY / ADHERENCE (from the tracker, not from what was emailed):\n"
        f"- {_gap_phrase(state)}.\n"
        f"- Completed strength sessions in the last 28 days: {state['strength_28d']}.\n"
        f"- {_riding_phrase(state)}\n"
    )
    if state["mode"] == "off_wagon":
        return head + "\nTHE ATHLETE IS COMING BACK AFTER A LAYOFF.\n" + REENTRY_RULES
    if state["mode"] == "rusty":
        return head + "\nTHE ATHLETE HAS BEEN OFF FOR A COUPLE OF WEEKS.\n" + RAMP_RULES
    return head + "\nConsistency is fine — program normally and progress load."


def headline(state):
    """One-line banner for the top of the email, or '' when on track.
    Tolerates a partial or legacy state dict."""
    days = state.get("days_since")
    if state.get("mode") == "off_wagon":
        gap = f"{days} days off" if days is not None else "no sessions on record"
        return (
            f"Welcome back ({gap}). This one is short, light and built to be fun — "
            "the only goal today is showing up."
        )
    if state.get("mode") == "rusty":
        return f"{days} days since your last lift — ramping back in, nothing heavy today."
    return ""
