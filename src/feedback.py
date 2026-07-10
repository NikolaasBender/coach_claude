"""Athlete feedback log on the mounted Docker volume.

The web app (src/web.py) writes entries here after each session; the generator
reads the recent ones back into the prompt so the coaching actually adapts to
how sessions felt. Also tracks which model the athlete preferred, so the
Nemotron-vs-DeepSeek comparison produces a signal over time.
"""

import json
import os
from datetime import datetime, timezone

FEEDBACK_PATH = os.environ.get("FEEDBACK_PATH", "data/feedback.json")


def load():
    """Return the full feedback list (oldest first). Empty list if none yet."""
    if not os.path.exists(FEEDBACK_PATH):
        return []
    try:
        with open(FEEDBACK_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def append(entry: dict):
    """Append one feedback entry and persist. Stamps a UTC timestamp."""
    entry.setdefault("logged_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    data = load()
    data.append(entry)
    os.makedirs(os.path.dirname(FEEDBACK_PATH) or ".", exist_ok=True)
    with open(FEEDBACK_PATH, "w") as f:
        json.dump(data, f, indent=2)


def recent(n=6):
    """Return the last n feedback entries (most recent last)."""
    return load()[-n:]


def summary(n=6):
    """Human-readable recent-feedback digest for the prompt, or a neutral note."""
    entries = recent(n)
    if not entries:
        return "No athlete feedback logged yet."

    lines = []
    for e in entries:
        when = e.get("session_date") or e.get("logged_at", "?")
        day = (e.get("day") or "").title()
        rating = e.get("rating")
        rating_str = f"{rating}/5" if rating else "no rating"
        pref = e.get("preferred_model")
        pref_str = f", preferred {pref}" if pref else ""
        notes = (e.get("notes") or "").strip()
        notes_str = f' — "{notes}"' if notes else ""
        lines.append(f"  {when} {day}: {rating_str}{pref_str}{notes_str}")

    return (
        "RECENT ATHLETE FEEDBACK (adapt to this — respect what felt too hard/easy "
        "or bothered the shoulder):\n" + "\n".join(lines)
    )
