"""Persistent workout history on a mounted Docker volume.

Without this the generator has amnesia and can't progress, rotate variety, or
reason about accumulated load. Stored as a JSON list, newest last. Path is
configurable so the container can point it at a mounted volume
(/data/history.json).

Two entry shapes coexist (the loader tolerates both):
  - legacy flat workout: {"day", "deload", "blocks": [...], ...}
  - session with model variants: {"day", "deload", "date",
        "variants": [{"model": "...", "workout": {...}}, ...]}
"""

import json
import os
from collections import Counter
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


def _workouts(entry):
    """Return the workout dict(s) inside an entry, tolerating both shapes."""
    if isinstance(entry, dict) and entry.get("variants"):
        return [v.get("workout", {}) for v in entry["variants"]]
    return [entry]


def _representative(entry):
    """One workout dict standing in for the session (first variant / the entry)."""
    ws = _workouts(entry)
    return ws[0] if ws else {}


def recent(n=4):
    """Return the last n entries (most recent last)."""
    return load()[-n:]


def count():
    """Total number of recorded sessions — used to rotate the hip bridge."""
    return len(load())


def append(entry: dict):
    """Append one session entry and persist. Stamps an ISO date if missing."""
    entry.setdefault("date", datetime.now(timezone.utc).date().isoformat())
    data = load()
    data.append(entry)
    os.makedirs(os.path.dirname(HISTORY_PATH) or ".", exist_ok=True)
    with open(HISTORY_PATH, "w") as f:
        json.dump(data, f, indent=2)


def weeks_since_deload():
    """Count sessions since the last deload, used to gate the next one."""
    n = 0
    for entry in reversed(load()):
        if entry.get("deload"):
            break
        n += 1
    return n


def load_summary(n_sessions=8):
    """Human-readable multi-week strength-load summary for the prompt.

    Gives the model an at-a-glance picture of what it has recently programmed so
    it can (a) progress sensibly, (b) rotate variety instead of repeating, and
    (c) explicitly acknowledge the recent block in its coach_notes.
    """
    entries = load()[-n_sessions:]
    if not entries:
        return "No prior strength sessions on record — this is session #1."

    lines = []
    ex_counter = Counter()
    rpes = []

    for entry in entries:
        w = _representative(entry)
        date = entry.get("date") or w.get("date") or "?"
        day = (entry.get("day") or w.get("day") or "").title()
        deload = " [DELOAD]" if entry.get("deload") or w.get("deload") else ""
        focus = w.get("focus", "")

        main_names = []
        for block in w.get("blocks", []):
            if block.get("name", "").lower() == "main":
                for ex in block.get("exercises", []):
                    nm = ex.get("name", "")
                    main_names.append(nm)
                    ex_counter[nm] += 1
                    if isinstance(ex.get("rpe"), (int, float)):
                        rpes.append(ex["rpe"])
        main_str = ", ".join(main_names) if main_names else "(no main block recorded)"
        lines.append(f"  {date} {day}{deload} — {focus}\n      main: {main_str}")

    recent_block = "\n".join(lines)

    # What's been hit most often lately (so the model can deliberately vary).
    frequent = ", ".join(f"{name} (x{c})" for name, c in ex_counter.most_common(6)) or "n/a"
    avg_rpe = f"{sum(rpes) / len(rpes):.1f}" if rpes else "n/a"

    return (
        f"LAST {len(entries)} SESSIONS (most recent last):\n{recent_block}\n\n"
        f"Most-used main exercises in this block: {frequent}.\n"
        f"Average main-lift RPE across this block: {avg_rpe}.\n"
        "Progress sensibly from here, ROTATE away from the most-used movements "
        "for variety, and briefly acknowledge this recent block in coach_notes."
    )
