"""Persistent workout history on a mounted Docker volume.

Without this the generator has amnesia and can't progress or rotate variety.
Stored as a JSON list, newest last. Path is configurable so the container can
point it at a mounted volume (/data/history.json).
"""

import json
import os
from datetime import datetime, timezone

HISTORY_PATH = os.environ.get("HISTORY_PATH", "data/history.json")


def load():
    """Return the full history list (oldest first). Empty list if none yet."""
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        # Corrupt/unreadable history should never block a workout from going out.
        return []


def recent(n=4):
    """Return the last n entries (most recent last)."""
    return load()[-n:]


def append(entry: dict):
    """Append one workout entry and persist. Stamps an ISO date if missing."""
    entry.setdefault("date", datetime.now(timezone.utc).date().isoformat())
    data = load()
    data.append(entry)
    os.makedirs(os.path.dirname(HISTORY_PATH) or ".", exist_ok=True)
    with open(HISTORY_PATH, "w") as f:
        json.dump(data, f, indent=2)


def weeks_since_deload():
    """Count workouts since the last deload, used to gate the next one."""
    count = 0
    for entry in reversed(load()):
        if entry.get("deload"):
            break
        count += 1
    return count
