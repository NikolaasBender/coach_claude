"""Garmin Connect integration.

Pulls recent activities AND daily wellness (sleep, stress, body battery, HRV,
resting HR) from Garmin Connect (via the `garminconnect` library) and turns
them into training-load + recovery context for the workout LLM prompt.

Auth flow:
  - One-time: run `python -m src.setup_garmin` to log in (MFA supported) and
    save OAuth tokens to GARMIN_TOKENS_PATH. Tokens last ~1 year; the password
    is never stored.
  - Every run: resume the session from the saved tokens via Garmin().login().

Persistence:
  - Activities + daily wellness stored in SQLite (data/garmin.db), keyed by
    Garmin activity ID / calendar date.
  - On each run: fetch 21 days of activities + 7 days of wellness, upsert,
    then build the 3-week pattern analysis and recovery snapshot from the DB.
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Garmin aerobic Training Effect (0.0-5.0 scale) thresholds.
_TE_MODERATE = 2.0
_TE_HARD = 3.0
_TE_VERY_HARD = 4.0

# Database path (mounted volume in Docker)
DB_PATH = Path(os.environ.get("GARMIN_DB_PATH", "data/garmin.db"))


def _tokens_store() -> str:
    """The token store path handed to garminconnect (dir or explicit .json)."""
    return os.environ.get("GARMIN_TOKENS_PATH", "data/garmin_tokens")


def _token_file() -> Path:
    """Resolve the actual token file, mirroring garminconnect's own logic:
    a directory (or any non-.json path) gets 'garmin_tokens.json' appended."""
    p = Path(_tokens_store()).expanduser()
    return p if p.suffix.lower() == ".json" else p / "garmin_tokens.json"


def _dt(iso: str) -> datetime:
    """Parse our stored ISO-8601 timestamps (defensive about 'Z' suffixes)."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _init_db():
    """Initialize SQLite database with activities + wellness tables."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY,
                garmin_id INTEGER UNIQUE NOT NULL,
                name TEXT,
                sport_type TEXT,
                start_date TEXT NOT NULL,
                moving_time INTEGER,
                distance REAL,
                total_elevation_gain REAL,
                aerobic_te REAL,
                training_load REAL,
                avg_hr REAL,
                raw_json TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_activities_start_date
            ON activities(start_date)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS wellness (
                id INTEGER PRIMARY KEY,
                date TEXT UNIQUE NOT NULL,
                sleep_seconds INTEGER,
                sleep_score REAL,
                sleep_quality TEXT,
                avg_stress REAL,
                max_stress REAL,
                resting_hr REAL,
                body_battery_high REAL,
                body_battery_low REAL,
                hrv_last_night REAL,
                hrv_status TEXT,
                steps INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def _parse_start(a: dict) -> str | None:
    """Normalize Garmin's 'YYYY-MM-DD HH:MM:SS' GMT stamp to ISO 8601 UTC."""
    raw = (a.get("startTimeGMT") or a.get("startTimeLocal") or "").replace("T", " ")
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _normalize(a: dict) -> dict | None:
    """Flatten one raw Garmin activity into our storage/analysis shape.

    Every downstream function (summary, yesterday note, pattern analysis)
    consumes this shape, which matches the DB columns 1:1. Garmin marks all
    fields optional, so absent metrics degrade to 0/None rather than raising.
    """
    garmin_id = a.get("activityId")
    start = _parse_start(a)
    if not garmin_id or not start:
        return None
    return {
        "garmin_id": garmin_id,
        "name": a.get("activityName"),
        "sport_type": (a.get("activityType") or {}).get("typeKey") or "activity",
        "start_date": start,
        "moving_time": int(a.get("movingDuration") or a.get("duration") or 0),
        "distance": float(a.get("distance") or 0.0),
        "total_elevation_gain": float(a.get("elevationGain") or 0.0),
        "aerobic_te": a.get("aerobicTrainingEffect"),
        "training_load": a.get("activityTrainingLoad"),
        "avg_hr": a.get("averageHR"),
        "raw_json": json.dumps(a),
    }


def _upsert_activities(activities: list[dict]) -> int:
    """Upsert normalized activities by Garmin ID. Returns rows touched."""
    _init_db()
    if not activities:
        return 0
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        count = 0
        for a in activities:
            cur.execute("""
                INSERT INTO activities (garmin_id, name, sport_type, start_date,
                                      moving_time, distance, total_elevation_gain,
                                      aerobic_te, training_load, avg_hr, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(garmin_id) DO UPDATE SET
                    name=excluded.name,
                    sport_type=excluded.sport_type,
                    start_date=excluded.start_date,
                    moving_time=excluded.moving_time,
                    distance=excluded.distance,
                    total_elevation_gain=excluded.total_elevation_gain,
                    aerobic_te=excluded.aerobic_te,
                    training_load=excluded.training_load,
                    avg_hr=excluded.avg_hr,
                    raw_json=excluded.raw_json
            """, (
                a["garmin_id"], a["name"], a["sport_type"], a["start_date"],
                a["moving_time"], a["distance"], a["total_elevation_gain"],
                a["aerobic_te"], a["training_load"], a["avg_hr"], a["raw_json"],
            ))
            if cur.rowcount > 0:
                count += 1
        conn.commit()
    return count


def _fetch_3weeks(client) -> list[dict]:
    """Fetch + normalize activities for the last 21 days (lib paginates)."""
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=21)
    raw = client.get_activities_by_date(start.isoformat(), end.isoformat())
    return [n for n in (_normalize(a) for a in raw) if n]


def _classify_effort(activity):
    """Return 'easy', 'moderate', 'hard', or 'very hard' based on Garmin's
    aerobic Training Effect or, if missing, moving time (e.g. manual entries)."""
    te = activity.get("aerobic_te") or 0
    hours = (activity.get("moving_time") or 0) / 3600
    if te:
        if te >= _TE_VERY_HARD:
            return "very hard"
        if te >= _TE_HARD:
            return "hard"
        if te >= _TE_MODERATE:
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
        return "No Garmin activities in the last 7 days."

    lines = []
    total_hours = 0
    total_elevation = 0

    for a in sorted(activities, key=lambda x: x["start_date"], reverse=True):
        date = _dt(a["start_date"])
        day_label = date.strftime("%a %-d %b")
        sport = a.get("sport_type", "activity")
        hours = a.get("moving_time", 0) / 3600
        elev = a.get("total_elevation_gain", 0)
        dist_km = a.get("distance", 0) / 1000
        te = a.get("aerobic_te")
        effort = _classify_effort(a)
        te_str = f", TE {te:.1f}" if te else ""
        lines.append(
            f"  {day_label}: {sport} {hours:.1f}h, {dist_km:.0f}km, "
            f"{elev:.0f}m elevation{te_str} [{effort}]"
        )
        total_hours += hours
        total_elevation += elev

    summary = "\n".join(lines)
    summary += f"\n  Week total: {total_hours:.1f}h training, {total_elevation:.0f}m elevation gain"
    return summary


def _yesterday_note(activities, session_date):
    """Return a plain-English note about the day-before's activity, or None."""
    yesterday = (session_date - timedelta(days=1)).date()
    yesterday_acts = [a for a in activities if _dt(a["start_date"]).date() == yesterday]
    if not yesterday_acts:
        return "No activity yesterday — legs should be reasonably fresh."
    efforts = [_classify_effort(a) for a in yesterday_acts]
    hardest = max(efforts, key=lambda e: ["easy","moderate","hard","very hard"].index(e))
    hours = sum(a.get("moving_time", 0) for a in yesterday_acts) / 3600
    return (
        f"Yesterday ({yesterday.strftime('%A')}): {hours:.1f}h training, "
        f"hardest effort = {hardest}. "
        + ("Reduce lower-body power volume accordingly."
           if hardest in ("hard", "very hard") else
           "Legs should be OK for planned intensity.")
    )

def _pattern_data() -> dict:
    """Structured 3-week pattern from stored activities.

    Returns {"weeks": [...], "trend_lines": [...]}, both empty when nothing is
    stored. Single source of truth for the LLM prompt text
    (_analyze_3week_pattern) and the email volume graph (email_send).
    """
    _init_db()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        # Get activities from last 21 days
        since = (datetime.now(timezone.utc) - timedelta(days=21)).isoformat()
        rows = conn.execute("""
            SELECT * FROM activities
            WHERE start_date >= ?
            ORDER BY start_date
        """, (since,)).fetchall()

    if not rows:
        return {"weeks": [], "trend_lines": []}

    # Group by ISO week
    grouped = defaultdict(list)
    for r in rows:
        grouped[_dt(r["start_date"]).strftime("%Y-W%U")].append(r)

    weeks = []
    prev_hours = None
    for week_key, acts in sorted(grouped.items()):
        total_hours = sum(a["moving_time"] for a in acts) / 3600
        effort_counts = {e: 0 for e in ("easy", "moderate", "hard", "very hard")}
        effort_hours = {e: 0.0 for e in ("easy", "moderate", "hard", "very hard")}
        dow_counts = defaultdict(int)
        for a in acts:
            effort = _classify_effort(dict(a))
            effort_counts[effort] += 1
            effort_hours[effort] += a["moving_time"] / 3600
            dow_counts[_dt(a["start_date"]).strftime("%a")] += 1

        delta = ""
        if prev_hours is not None:
            d = total_hours - prev_hours
            if abs(d) < 0.5:
                delta = " (steady)"
            elif d > 0:
                delta = f" (+{d:.1f}h ↑)"
            else:
                delta = f" ({d:.1f}h ↓)"
        prev_hours = total_hours

        weeks.append({
            "week": week_key,
            "count": len(acts),
            "hours": total_hours,
            "km": sum(a["distance"] for a in acts) / 1000,
            "elev": sum(a["total_elevation_gain"] for a in acts),
            "effort_counts": effort_counts,
            "effort_hours": effort_hours,
            "days": ", ".join(f"{d}:{c}" for d, c in sorted(dow_counts.items())),
            "delta": delta,
        })

    trend_lines = []
    if len(weeks) >= 2:
        overall = weeks[-1]["hours"] - weeks[0]["hours"]
        if overall > 1:
            trend_lines.append(f"→ Trend: Volume increasing (+{overall:.1f}h over 3 weeks)")
        elif overall < -1:
            trend_lines.append(f"→ Trend: Volume decreasing ({overall:.1f}h over 3 weeks)")
        else:
            trend_lines.append(f"→ Trend: Volume stable ({overall:+.1f}h over 3 weeks)")

    # Weekend vs weekday
    wknd = sum(a["moving_time"] for a in rows if _dt(a["start_date"]).weekday() >= 5) / 3600
    wkdy = sum(a["moving_time"] for a in rows if _dt(a["start_date"]).weekday() < 5) / 3600
    trend_lines.append(f"→ Weekend: {wknd:.1f}h vs Weekday: {wkdy:.1f}h")

    return {"weeks": weeks, "trend_lines": trend_lines}


def _analyze_3week_pattern(data=None) -> str:
    """Render _pattern_data() as the text block used in the LLM prompt."""
    if data is None:
        data = _pattern_data()
    if not data["weeks"]:
        return "No Garmin activities in the last 3 weeks."

    lines = ["3-WEEK TRAINING PATTERN ANALYSIS:"]
    for w in data["weeks"]:
        lines.append(
            f"  Week {w['week']}: {w['count']} activities, {w['hours']:.1f}h, "
            f"{w['km']:.0f}km, {w['elev']:.0f}m elev{w['delta']}"
        )
        ec = w["effort_counts"]
        lines.append(f"    Effort: {ec['easy']}E {ec['moderate']}M {ec['hard']}H {ec['very hard']}VH")
        lines.append(f"    Days: {w['days']}")
    lines.extend(f"  {t}" for t in data["trend_lines"])
    return "\n".join(lines)


def _pos(v):
    """Garmin uses 0/-1/-2 sentinels for 'no data' — collapse them to None."""
    return v if isinstance(v, (int, float)) and v > 0 else None


def _extract_wellness_day(date_str: str, summary: dict, sleep: dict, hrv: dict) -> dict:
    """Flatten one day's wellness payloads into a wellness-table row.

    Key spellings verified against garminconnect 0.3.11: the daily summary
    uses averageStressLevel while the sleep DTO nests sleepScores.overall.
    Everything is optional — non-synced days yield None columns.
    """
    dto = (sleep or {}).get("dailySleepDTO") or {}
    overall = (dto.get("sleepScores") or {}).get("overall") or {}
    hrv_summary = (hrv or {}).get("hrvSummary") or {}
    return {
        "date": date_str,
        "sleep_seconds": _pos(dto.get("sleepTimeSeconds")),
        "sleep_score": _pos(overall.get("value")),
        "sleep_quality": overall.get("qualifierKey"),
        "avg_stress": _pos(summary.get("averageStressLevel")),
        "max_stress": _pos(summary.get("maxStressLevel")),
        "resting_hr": _pos(summary.get("restingHeartRate")),
        "body_battery_high": _pos(summary.get("bodyBatteryHighestValue")),
        "body_battery_low": summary.get("bodyBatteryLowestValue"),
        "hrv_last_night": _pos(hrv_summary.get("lastNightAvg")),
        "hrv_status": hrv_summary.get("status"),
        "steps": _pos(summary.get("totalSteps")),
    }


def _fetch_wellness(client, days: int = 7) -> list[dict]:
    """Fetch per-day wellness for the last `days` days (today inclusive).

    Every endpoint fails independently per day: watch-sync gaps, privacy
    settings, and HTTP 204s are normal, so a day with no data is skipped.
    Uses the local calendar date — Garmin daily data is calendar-local.
    """
    rows = []
    today = datetime.now().date()
    for i in range(days):
        d = (today - timedelta(days=i)).isoformat()
        summary, sleep, hrv = {}, {}, {}
        try:
            summary = client.get_user_summary(d) or {}
        except Exception:
            pass
        try:
            sleep = client.get_sleep_data(d) or {}
        except Exception:
            pass
        try:
            hrv = client.get_hrv_data(d) or {}
        except Exception:
            pass
        row = _extract_wellness_day(d, summary, sleep, hrv)
        if any(v is not None for k, v in row.items() if k != "date"):
            rows.append(row)
    return rows


def _upsert_wellness(rows: list[dict]) -> int:
    """Upsert wellness rows by calendar date. COALESCE keeps a metric from an
    earlier sync if a later fetch comes back without it (e.g. pre-sync 5am run)."""
    _init_db()
    if not rows:
        return 0
    cols = ("date", "sleep_seconds", "sleep_score", "sleep_quality", "avg_stress",
            "max_stress", "resting_hr", "body_battery_high", "body_battery_low",
            "hrv_last_night", "hrv_status", "steps")
    updates = ", ".join(f"{c}=COALESCE(excluded.{c}, {c})" for c in cols[1:])
    placeholders = ", ".join("?" * len(cols))
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.cursor()
        count = 0
        for r in rows:
            cur.execute(
                f"INSERT INTO wellness ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(date) DO UPDATE SET {updates}",
                tuple(r[c] for c in cols),
            )
            if cur.rowcount > 0:
                count += 1
        conn.commit()
    return count


def _recovery_summary(session_date=None) -> str:
    """Build the sleep/stress/recovery snapshot for the LLM prompt and email.

    Uses the most recent stored value per metric (the watch may not have
    synced yet when the 5am cron fires) against 7-day averages as baseline.
    Returns "" when the wellness table has nothing recent.
    """
    if session_date is None:
        session_date = datetime.now(timezone.utc)
    _init_db()
    since = (session_date - timedelta(days=7)).date().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM wellness WHERE date >= ? ORDER BY date DESC", (since,)
        ).fetchall()]
    if not rows:
        return ""

    today_s = session_date.date().isoformat()

    def latest(key):
        return next((r for r in rows if r.get(key) is not None), None)

    def avg(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    def day_label(date_str):
        if date_str == today_s:
            return "today"
        return datetime.fromisoformat(date_str).strftime("%a %-d %b")

    lines = []

    s = latest("sleep_seconds")
    if s:
        label = "Sleep last night" if s["date"] == today_s else f"Sleep ({day_label(s['date'])})"
        line = f"  {label}: {s['sleep_seconds'] / 3600:.1f}h"
        if s.get("sleep_score"):
            qual = f" {s['sleep_quality']}" if s.get("sleep_quality") else ""
            line += f", score {s['sleep_score']:.0f}{qual}"
        a_h, a_sc = avg("sleep_seconds"), avg("sleep_score")
        if a_h:
            line += f" — 7-day avg {a_h / 3600:.1f}h" + (f", score {a_sc:.0f}" if a_sc else "")
        lines.append(line)

    st = next((r for r in rows if r.get("avg_stress") is not None and r["date"] != today_s),
              None) or latest("avg_stress")
    if st:
        line = f"  Stress ({day_label(st['date'])}): avg {st['avg_stress']:.0f}/100"
        if st.get("max_stress"):
            line += f", max {st['max_stress']:.0f}"
        a = avg("avg_stress")
        if a:
            line += f" — 7-day avg {a:.0f}"
        lines.append(line)

    bb = latest("body_battery_high")
    if bb:
        line = f"  Body battery ({day_label(bb['date'])}): high {bb['body_battery_high']:.0f}"
        if bb.get("body_battery_low") is not None:
            line += f", low {bb['body_battery_low']:.0f}"
        lines.append(line)

    hr = latest("resting_hr")
    if hr:
        line = f"  Resting HR: {hr['resting_hr']:.0f} bpm"
        a = avg("resting_hr")
        if a:
            line += f" (7-day avg {a:.0f})"
        lines.append(line)

    hv = latest("hrv_last_night") or latest("hrv_status")
    if hv:
        parts = []
        if hv.get("hrv_last_night"):
            parts.append(f"{hv['hrv_last_night']:.0f} ms")
        if hv.get("hrv_status"):
            parts.append(str(hv["hrv_status"]))
        lines.append(f"  HRV ({day_label(hv['date'])}): " + ", ".join(parts))

    a = avg("steps")
    if a:
        lines.append(f"  Daily steps, 7-day avg: {a:,.0f}")

    return "\n".join(lines)


def load_context(session_date=None):
    """Return LLM prompt context: 'summary', 'yesterday_note',
    'pattern_analysis' (+ structured 'pattern_weeks'/'pattern_trend' for the
    email graph), and 'recovery' (sleep/stress/body-battery snapshot).

    Fetches 21 days of activities plus 7 days of wellness, upserts both to
    SQLite, then builds the analyses. Each part degrades independently to
    placeholder strings — a Garmin outage never blocks a workout.
    """
    if session_date is None:
        session_date = datetime.now(timezone.utc)

    empty = {
        "summary": "Garmin not configured — skipping training load context.",
        "yesterday_note": "",
        "pattern_analysis": "",
        "pattern_weeks": [],
        "pattern_trend": "",
        "recovery": "",
    }
    if not _token_file().exists():
        return empty

    try:
        # Deferred import: a missing/broken garminconnect install must degrade
        # to "no load context", never block the workout email.
        from garminconnect import Garmin

        client = Garmin()
        client.login(_tokens_store())
    except Exception as e:
        empty["summary"] = f"Garmin unavailable ({e}) — proceeding without load context."
        return empty

    ctx = {}
    try:
        # Fetch 3 weeks of activities and persist
        activities_3w = _fetch_3weeks(client)
        _upsert_activities(activities_3w)
        # Last 7 days for summary/yesterday
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        activities_7d = [a for a in activities_3w if _dt(a["start_date"]) >= cutoff]
        ctx["summary"] = _summarize(activities_7d)
        ctx["yesterday_note"] = _yesterday_note(activities_7d, session_date)
        pattern = _pattern_data()
        ctx["pattern_analysis"] = _analyze_3week_pattern(pattern)
        ctx["pattern_weeks"] = pattern["weeks"]
        ctx["pattern_trend"] = "\n".join(pattern["trend_lines"])
    except Exception as e:
        ctx["summary"] = f"Garmin activities unavailable ({e}) — proceeding without load context."
        ctx["yesterday_note"] = ""
        ctx["pattern_analysis"] = ""
        ctx["pattern_weeks"] = []
        ctx["pattern_trend"] = ""

    try:
        # Wellness (sleep, stress, body battery, HRV, resting HR) -> recovery
        _upsert_wellness(_fetch_wellness(client))
        ctx["recovery"] = _recovery_summary(session_date)
    except Exception as e:
        print(f"[garmin] wellness unavailable: {e}", file=sys.stderr)
        ctx["recovery"] = ""

    return ctx
