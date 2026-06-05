"""Deterministic fallback workout generator.

Used when the LLM is unreachable at 5am, or when its output fails validation
twice. Every exercise here is hand-picked to clear the exclusion guardrail, so
this path is always safe to ship. Variety comes from seeded random selection
keyed on the date.
"""

import random

# All pools below are pre-vetted against exclusions.py.

REHAB_BLOCK = [
    {"name": "Band external rotation (elbow at side)", "sets": 2, "reps": "15/side", "load": "light band", "rpe": 5, "notes": "Slow, controlled. No pain."},
    {"name": "TRX scapular retraction (Y/T, low)", "sets": 2, "reps": "12", "load": "bodyweight", "rpe": 5, "notes": "Squeeze shoulder blades, no shrug."},
    {"name": "Band pull-apart", "sets": 2, "reps": "15", "load": "light band", "rpe": 5, "notes": "Keep ribs down."},
]

LOWER_POWER = [
    {"name": "Box jump", "sets": 4, "reps": "3", "load": "moderate box", "rpe": 7, "notes": "Step down, reset each rep."},
    {"name": "Back squat", "sets": 4, "reps": "5", "load": "RPE 7-8", "rpe": 8, "notes": "Brace, full depth if mobility allows."},
    {"name": "Kettlebell swing (70lb)", "sets": 4, "reps": "10", "load": "70lb KB", "rpe": 7, "notes": "Hip snap, neutral spine."},
    {"name": "Bulgarian split squat", "sets": 3, "reps": "8/side", "load": "KB goblet or DB", "rpe": 7, "notes": "Front knee tracks toe."},
    {"name": "Romanian deadlift", "sets": 3, "reps": "8", "load": "RPE 7", "rpe": 7, "notes": "Hinge, feel hamstrings."},
    {"name": "Single-leg glute bridge", "sets": 3, "reps": "12/side", "load": "bodyweight or band", "rpe": 6, "notes": "Floor-based. Drive through heel, squeeze at top."},
]

UPPER_PULL = [
    {"name": "Chin-up (controlled, neutral or supinated)", "sets": 4, "reps": "5-6", "load": "bodyweight, add load if easy", "rpe": 7, "notes": "No kipping. Full control at bottom."},
    {"name": "Single-arm KB row", "sets": 4, "reps": "8/side", "load": "45 or 70lb KB", "rpe": 7, "notes": "Brace core, no twist."},
    {"name": "Landmine press (light)", "sets": 3, "reps": "8/side", "load": "light", "rpe": 6, "notes": "Overhead progression, neutral path, pain-free."},
    {"name": "TRX inverted row", "sets": 3, "reps": "12", "load": "bodyweight angle", "rpe": 7, "notes": "Scaps first, body rigid."},
    {"name": "Face pull (band)", "sets": 3, "reps": "15", "load": "band", "rpe": 6, "notes": "External rotation through, elbows high."},
]

FINISHERS = [
    {"name": "Suitcase carry", "sets": 3, "reps": "30m/side", "load": "70lb KB", "rpe": 6, "notes": "Anti-lateral-flexion, stay tall."},
    {"name": "Pallof press (band)", "sets": 3, "reps": "12/side", "load": "band", "rpe": 6, "notes": "Anti-rotation, slow."},
    {"name": "Single-leg RDL", "sets": 3, "reps": "8/side", "load": "light KB", "rpe": 6, "notes": "Balance + posterior chain."},
    {"name": "BOSU single-leg balance reach", "sets": 2, "reps": "30s/side", "load": "bodyweight", "rpe": 5, "notes": "Hip/ankle stability for the bike."},
]


def _pick(pool, n, rng):
    return [dict(x) for x in rng.sample(pool, min(n, len(pool)))]


def generate(day: str, deload: bool, seed: str):
    """Build a safe template workout. `day` is 'monday'/'friday'."""
    rng = random.Random(seed)
    is_lower = day.lower() == "monday"
    main_pool = LOWER_POWER if is_lower else UPPER_PULL
    main = _pick(main_pool, 3, rng)
    finisher = _pick(FINISHERS, 1, rng)

    if deload:
        for ex in main:
            ex["notes"] = "DELOAD: " + ex.get("notes", "")
            ex["rpe"] = max(5, ex.get("rpe", 7) - 2)

    return {
        "source": "template",
        "day": day,
        "focus": SCHEDULE_FOCUS(is_lower),
        "deload": deload,
        "blocks": [
            {"name": "Shoulder rehab warmup", "exercises": [dict(x) for x in REHAB_BLOCK]},
            {"name": "Main", "exercises": main},
            {"name": "Cycling finisher", "exercises": finisher},
        ],
        "coach_notes": (
            "Deload week — keep it crisp and light, prioritize movement quality."
            if deload else
            "Leave 1-2 reps in reserve on main lifts. Stop any shoulder movement that pinches."
        ),
    }


def SCHEDULE_FOCUS(is_lower):
    return ("lower body power + posterior chain" if is_lower
            else "upper pulling + scapular strength + light overhead")
