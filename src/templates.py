"""Deterministic fallback workout generator.

Used when an LLM is unreachable at 5am, or when its output fails validation
twice. Every exercise here is hand-picked to clear the exclusion guardrail, so
this path is always safe to ship. Variety comes from seeded random selection
keyed on the date.

Two things are guaranteed in EVERY session (template or LLM):
  - a hip bridge variant, rotating single-leg -> weighted -> unweighted
    (see `hip_bridge`), and
  - a dedicated lower-core movement (leg raises, dead bugs, etc.).
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
    {"name": "Front squat", "sets": 4, "reps": "5", "load": "RPE 7", "rpe": 7, "notes": "Elbows high, upright torso."},
    {"name": "Kettlebell swing (70lb)", "sets": 4, "reps": "10", "load": "70lb KB", "rpe": 7, "notes": "Hip snap, neutral spine."},
    {"name": "Bulgarian split squat", "sets": 3, "reps": "8/side", "load": "KB goblet or DB", "rpe": 7, "notes": "Front knee tracks toe."},
    {"name": "Romanian deadlift", "sets": 3, "reps": "8", "load": "RPE 7", "rpe": 7, "notes": "Hinge, feel hamstrings."},
    {"name": "Conventional deadlift", "sets": 4, "reps": "4", "load": "RPE 8", "rpe": 8, "notes": "Reset each rep, neutral spine."},
    {"name": "Trap-bar-style KB deadlift", "sets": 4, "reps": "6", "load": "70lb KB", "rpe": 7, "notes": "Vertical shins, drive floor away."},
    {"name": "Reverse lunge", "sets": 3, "reps": "8/side", "load": "KB goblet or DB", "rpe": 7, "notes": "Step back, control the descent."},
    {"name": "Lateral lunge", "sets": 3, "reps": "8/side", "load": "light KB", "rpe": 6, "notes": "Frontal-plane strength for the bike."},
    {"name": "Weighted step-up", "sets": 3, "reps": "8/side", "load": "DB or KB", "rpe": 7, "notes": "Tall box, drive through heel, no push-off."},
    {"name": "Goblet squat", "sets": 3, "reps": "10", "load": "45 or 70lb KB", "rpe": 7, "notes": "Elbows inside knees, upright."},
    {"name": "Single-leg press (BOSU) / skater squat", "sets": 3, "reps": "6/side", "load": "bodyweight or light DB", "rpe": 7, "notes": "Control the descent, knee tracks toe."},
]

UPPER_PULL = [
    {"name": "Chin-up (controlled, neutral or supinated)", "sets": 4, "reps": "5-6", "load": "bodyweight, add load if easy", "rpe": 7, "notes": "No kipping. Full control at bottom."},
    {"name": "Single-arm KB row", "sets": 4, "reps": "8/side", "load": "45 or 70lb KB", "rpe": 7, "notes": "Brace core, no twist."},
    {"name": "Landmine press (light)", "sets": 3, "reps": "8/side", "load": "light", "rpe": 6, "notes": "Overhead progression, neutral path, pain-free."},
    {"name": "TRX inverted row", "sets": 3, "reps": "12", "load": "bodyweight angle", "rpe": 7, "notes": "Scaps first, body rigid."},
    {"name": "Face pull (band)", "sets": 3, "reps": "15", "load": "band", "rpe": 6, "notes": "External rotation through, elbows high."},
    {"name": "Neutral-grip DB floor press", "sets": 3, "reps": "8", "load": "moderate DB", "rpe": 6, "notes": "Elbows ~45deg, limited ROM at floor, no bench."},
    {"name": "Half-kneeling KB overhead press (light)", "sets": 3, "reps": "8/side", "load": "light KB", "rpe": 6, "notes": "Start light, ribs down, pain-free ROM only."},
    {"name": "Bent-over barbell row (neutral spine)", "sets": 4, "reps": "8", "load": "RPE 7", "rpe": 7, "notes": "Hinge, pull to belly, no jerk."},
    {"name": "TRX Y raise (low load, scapular)", "sets": 3, "reps": "12", "load": "bodyweight angle", "rpe": 6, "notes": "Below shoulder height, no shrug."},
    {"name": "Chest-supported DB row (on ball)", "sets": 3, "reps": "10", "load": "moderate DB", "rpe": 7, "notes": "Chest on stability ball, retract then row."},
    {"name": "Band/TRX straight-arm pulldown", "sets": 3, "reps": "15", "load": "band", "rpe": 6, "notes": "Lats, keep neutral shoulder."},
]

# Rotating mandatory hip bridge — one variant EVERY session, cycling in this
# order: single-leg -> weighted -> unweighted. All floor-based (no bench).
HIP_BRIDGES = [
    {"name": "Single-leg glute bridge", "sets": 3, "reps": "12/side", "load": "bodyweight", "rpe": 6, "notes": "Floor-based. Drive through heel, squeeze at top, level hips.", "variant": "single-leg"},
    {"name": "Weighted glute bridge (barbell/KB on hips, floor)", "sets": 3, "reps": "10", "load": "barbell or 70lb KB across hips", "rpe": 7, "notes": "Shoulders on floor, full hip extension, 1-sec pause at top.", "variant": "weighted"},
    {"name": "Glute bridge (bodyweight, paused)", "sets": 3, "reps": "15", "load": "bodyweight", "rpe": 5, "notes": "2-sec pause at top, ribs down, drive through heels.", "variant": "unweighted"},
]

# Lower-core emphasis: leg raises, dead bugs, reverse crunch patterns.
LOWER_CORE = [
    {"name": "Lying leg raise", "sets": 3, "reps": "12", "load": "bodyweight", "rpe": 7, "notes": "Lower slowly, keep low back flat to floor."},
    {"name": "Hanging knee raise", "sets": 3, "reps": "10", "load": "bodyweight", "rpe": 7, "notes": "No swing; posterior pelvic tilt. Relaxed shoulders on the bar."},
    {"name": "Dead bug", "sets": 3, "reps": "8/side", "load": "bodyweight or light band", "rpe": 6, "notes": "Ribs down, opposite arm/leg, no low-back arch."},
    {"name": "Reverse crunch", "sets": 3, "reps": "15", "load": "bodyweight", "rpe": 6, "notes": "Curl pelvis up, control the lowering."},
    {"name": "Stability-ball knee tuck", "sets": 3, "reps": "12", "load": "bodyweight (ball)", "rpe": 7, "notes": "Plank position, tuck knees in, hips low."},
    {"name": "Heel-tap / toe-touch", "sets": 3, "reps": "12/side", "load": "bodyweight", "rpe": 5, "notes": "Lower-ab bias, slow tempo."},
]

# General / anti-rotation / carry core + cycling finishers.
FINISHERS = [
    {"name": "Suitcase carry", "sets": 3, "reps": "30m/side", "load": "70lb KB", "rpe": 6, "notes": "Anti-lateral-flexion, stay tall."},
    {"name": "Pallof press (band)", "sets": 3, "reps": "12/side", "load": "band", "rpe": 6, "notes": "Anti-rotation, slow."},
    {"name": "Single-leg RDL", "sets": 3, "reps": "8/side", "load": "light KB", "rpe": 6, "notes": "Balance + posterior chain."},
    {"name": "BOSU single-leg balance reach", "sets": 2, "reps": "30s/side", "load": "bodyweight", "rpe": 5, "notes": "Hip/ankle stability for the bike."},
    {"name": "Side plank", "sets": 2, "reps": "30s/side", "load": "bodyweight", "rpe": 6, "notes": "Stack shoulders, engage obliques."},
    {"name": "KB swing intervals (70lb)", "sets": 5, "reps": "30s work / 30s rest", "load": "70lb KB", "rpe": 8, "notes": "Simulate on-bike power phase."},
    {"name": "Farmer carry", "sets": 3, "reps": "40m", "load": "2x70lb KB", "rpe": 6, "notes": "Grip + trunk, tall posture."},
]


def hip_bridge(session_index: int) -> dict:
    """Return the mandatory hip bridge variant for this session, cycling
    single-leg -> weighted -> unweighted. `session_index` is the count of prior
    sessions, so consecutive sessions rotate."""
    return dict(HIP_BRIDGES[session_index % len(HIP_BRIDGES)])


def _pick(pool, n, rng):
    return [dict(x) for x in rng.sample(pool, min(n, len(pool)))]


def generate(day: str, deload: bool, seed: str, session_index: int = 0):
    """Build a safe template workout. `day` is 'monday'/'friday'."""
    rng = random.Random(seed)
    is_lower = day.lower() == "monday"
    main_pool = LOWER_POWER if is_lower else UPPER_PULL
    main = _pick(main_pool, 3, rng)

    # Guaranteed every session: rotating hip bridge + a lower-core movement.
    bridge = hip_bridge(session_index)
    bridge.pop("variant", None)
    core = _pick(LOWER_CORE, 1, rng)
    main = main + [bridge] + core

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
