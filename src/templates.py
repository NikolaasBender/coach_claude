"""Deterministic fallback workout generator.

Used when an LLM is unreachable at 5am, or when its output fails validation
twice. Every exercise here is hand-picked to clear the exclusion guardrail, so
this path is always safe to ship. Variety comes from seeded random selection
keyed on the date.

Three things are guaranteed in EVERY session (template or LLM):
  - a hip bridge variant, rotating single-leg -> weighted -> unweighted
    (see `hip_bridge`),
  - a loaded compound lift leading the Main block (squat/hinge/pull pattern),
    and
  - TWO distinct core patterns: a lower-core/anti-extension movement in Main
    plus an anti-rotation / anti-lateral-flexion movement in the finisher.
"""

import random
import re

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

# Lower-core / anti-extension: leg raises, dead bugs, reverse crunch, rollouts.
LOWER_CORE = [
    {"name": "Lying leg raise", "sets": 3, "reps": "12", "load": "bodyweight", "rpe": 7, "notes": "Lower slowly, keep low back flat to floor."},
    {"name": "Hanging knee raise", "sets": 3, "reps": "10", "load": "bodyweight", "rpe": 7, "notes": "No swing; posterior pelvic tilt. Relaxed shoulders on the bar."},
    {"name": "Hanging straight-leg raise", "sets": 3, "reps": "8", "load": "bodyweight", "rpe": 8, "notes": "Strict, no swing. Shoulders packed, no end-range hang."},
    {"name": "Dead bug", "sets": 3, "reps": "8/side", "load": "bodyweight or light band", "rpe": 6, "notes": "Ribs down, opposite arm/leg, no low-back arch."},
    {"name": "Reverse crunch", "sets": 3, "reps": "15", "load": "bodyweight", "rpe": 6, "notes": "Curl pelvis up, control the lowering."},
    {"name": "Stability-ball knee tuck", "sets": 3, "reps": "12", "load": "bodyweight (ball)", "rpe": 7, "notes": "Plank position, tuck knees in, hips low."},
    {"name": "Stability-ball rollout", "sets": 3, "reps": "10", "load": "bodyweight (ball)", "rpe": 7, "notes": "Anti-extension. Ribs down, stop before the low back arches."},
    {"name": "Hollow-body hold", "sets": 3, "reps": "30s", "load": "bodyweight", "rpe": 7, "notes": "Low back pinned to floor; shorten the lever if it lifts."},
    {"name": "Heel-tap / toe-touch", "sets": 3, "reps": "12/side", "load": "bodyweight", "rpe": 5, "notes": "Lower-ab bias, slow tempo."},
]

# Anti-rotation / anti-lateral-flexion core. One of these every session, in the
# finisher block — this is the second core pattern, not a substitute for the
# lower-core movement above.
ROTATIONAL_CORE = [
    {"name": "Pallof press (band)", "sets": 3, "reps": "12/side", "load": "band", "rpe": 6, "notes": "Anti-rotation, slow. Arms stay in front of the chest."},
    {"name": "Pallof hold (band)", "sets": 3, "reps": "20s/side", "load": "band", "rpe": 6, "notes": "Resist the pull, square hips and shoulders."},
    {"name": "Suitcase carry", "sets": 3, "reps": "30m/side", "load": "70lb KB", "rpe": 7, "notes": "Anti-lateral-flexion, stay tall, shoulder packed."},
    {"name": "Side plank", "sets": 2, "reps": "30s/side", "load": "bodyweight", "rpe": 6, "notes": "Stack shoulders, engage obliques."},
    {"name": "Side plank with top-leg raise", "sets": 2, "reps": "10/side", "load": "bodyweight", "rpe": 7, "notes": "Hips high, no rotation. Bottom shoulder packed."},
    {"name": "Half-kneeling band chop (high-to-low)", "sets": 3, "reps": "12/side", "load": "band", "rpe": 6, "notes": "Rotate through the trunk, arms stay below shoulder height."},
    {"name": "Bird dog", "sets": 3, "reps": "10/side", "load": "bodyweight", "rpe": 5, "notes": "Anti-rotation. Level hips, slow reach."},
]

# Cycling-specific finishers: on-bike power, single-leg stability, loaded carry.
FINISHERS = [
    {"name": "Single-leg RDL", "sets": 3, "reps": "8/side", "load": "light KB", "rpe": 6, "notes": "Balance + posterior chain."},
    {"name": "BOSU single-leg balance reach", "sets": 2, "reps": "30s/side", "load": "bodyweight", "rpe": 5, "notes": "Hip/ankle stability for the bike."},
    {"name": "KB swing intervals (70lb)", "sets": 5, "reps": "30s work / 30s rest", "load": "70lb KB", "rpe": 8, "notes": "Simulate on-bike power phase."},
    {"name": "Farmer carry", "sets": 3, "reps": "40m", "load": "2x70lb KB", "rpe": 6, "notes": "Grip + trunk, tall posture, shoulders packed."},
]

# Comeback sessions: short, athletic, obviously fun. Used instead of the normal
# finisher when the athlete has been off for a while (see consistency.py) — the
# goal is wanting to come back, not optimal stimulus.
PLAY = [
    {"name": "KB flow complex (swing → clean → front squat)", "sets": 4, "reps": "4 rounds of 3 each", "load": "45lb KB", "rpe": 6, "notes": "Smooth and unhurried — this is the fun bit. Put it down if the shoulder talks."},
    {"name": "Low box jump ladder", "sets": 4, "reps": "3", "load": "low box", "rpe": 6, "notes": "Submaximal height, quiet landings, step down. Quality over altitude."},
    {"name": "Farmer carry medley (down and back)", "sets": 3, "reps": "40m", "load": "2x45lb KB", "rpe": 6, "notes": "Race the clock lightly, stay tall, shoulders packed."},
    {"name": "BOSU balance challenge", "sets": 3, "reps": "30s/side", "load": "bodyweight", "rpe": 5, "notes": "See how still you can get. Eyes closed if that gets easy."},
    {"name": "TRX row + goblet squat EMOM (8 min)", "sets": 8, "reps": "6 + 6 each minute", "load": "bodyweight + 45lb KB", "rpe": 6, "notes": "Easy pace, finish each minute with time to spare."},
    {"name": "KB swing EMOM (10 min)", "sets": 10, "reps": "8 each minute", "load": "45lb KB", "rpe": 6, "notes": "Crisp hips, long rest inside each minute."},
]


# --- Movement classification -------------------------------------------------
# main.py reuses these to audit an LLM proposal before it ships: the model is
# asked for a compound lead-off and two core patterns, and these decide whether
# it actually delivered. Matching is on human exercise names because that is all
# the model returns.

_COMPOUND = re.compile(
    r"squat|deadlift|romanian|\brdl\b|\brow\b|chin[\s-]*up|pull[\s-]*up|lunge|"
    r"step[\s-]*up|\bswing\b|floor press|landmine press|overhead press|\bclean\b"
)
# Light stability/isolation work that merely reads as compound. Never counts as
# the session's real loaded lift.
_NOT_COMPOUND = re.compile(
    r"\bband\b|\btrx\b|scapular|straight[\s-]*arm|face pull|balance|bosu|"
    r"single[\s-]*leg rdl|\bjump\b|\bhop\b"
)
_LOWER_CORE_PAT = re.compile(
    r"leg raise|dead ?bug|reverse crunch|knee raise|knee tuck|heel[\s-]*tap|"
    r"toe[\s-]*touch|rollout|hollow|\bv[\s-]*ups?\b|sit[\s-]*up|crunch"
)
_ROTATIONAL_CORE_PAT = re.compile(
    r"pallof|anti[\s-]*rotation|anti[\s-]*lateral|suitcase|side plank|\bchop\b|"
    r"bird[\s-]*dog|windmill|oblique"
)


def is_compound(name: str) -> bool:
    """True for a loaded multi-joint lift (the thing the athlete wants to lead
    with). Bodyweight plyos and band/TRX patterning deliberately do not count."""
    n = (name or "").lower()
    return bool(_COMPOUND.search(n)) and not _NOT_COMPOUND.search(n)


def is_lower_core(name: str) -> bool:
    """True for lower-ab / anti-extension work."""
    return bool(_LOWER_CORE_PAT.search((name or "").lower()))


def is_rotational_core(name: str) -> bool:
    """True for anti-rotation / anti-lateral-flexion work."""
    return bool(_ROTATIONAL_CORE_PAT.search((name or "").lower()))


def pick_lower_core(seed: str) -> dict:
    return dict(random.Random(f"lower-core-{seed}").choice(LOWER_CORE))


def pick_rotational_core(seed: str) -> dict:
    return dict(random.Random(f"rot-core-{seed}").choice(ROTATIONAL_CORE))


def pick_compound(day: str, seed: str) -> dict:
    """A vetted loaded compound for the day's focus."""
    pool = LOWER_POWER if day.lower() == "monday" else UPPER_PULL
    compounds = [x for x in pool if is_compound(x["name"])]
    return dict(random.Random(f"compound-{seed}").choice(compounds))


def hip_bridge(session_index: int) -> dict:
    """Return the mandatory hip bridge variant for this session, cycling
    single-leg -> weighted -> unweighted. `session_index` is the count of prior
    sessions, so consecutive sessions rotate."""
    return dict(HIP_BRIDGES[session_index % len(HIP_BRIDGES)])


def _pick(pool, n, rng):
    return [dict(x) for x in rng.sample(pool, min(n, len(pool)))]


def _pick_main(pool, n, rng):
    """n main-block exercises, always led by a loaded compound lift."""
    compounds = [x for x in pool if is_compound(x["name"])]
    lead = dict(rng.choice(compounds)) if compounds else None
    rest_pool = [x for x in pool if not lead or x["name"] != lead["name"]]
    rest = _pick(rest_pool, n - 1 if lead else n, rng)
    return ([lead] if lead else []) + rest


def generate(day: str, deload: bool, seed: str, session_index: int = 0,
             reentry: bool = False):
    """Build a safe template workout. `day` is 'monday'/'friday'.

    `reentry` is the comeback shape used after a layoff: fewer movements, RPE
    capped, and a play element instead of a hard cycling finisher.
    """
    rng = random.Random(seed)
    is_lower = day.lower() == "monday"
    main_pool = LOWER_POWER if is_lower else UPPER_PULL
    main = _pick_main(main_pool, 2 if reentry else 3, rng)

    # Guaranteed every session: compound lead-off (above), rotating hip bridge,
    # and a lower-core movement.
    bridge = hip_bridge(session_index)
    bridge.pop("variant", None)
    core = _pick(LOWER_CORE, 1, rng)
    main = main + [bridge] + core

    # Second core pattern (anti-rotation) rides with the cycling finisher.
    finisher = _pick(ROTATIONAL_CORE, 1, rng)
    finisher += _pick(PLAY, 1, rng) if reentry else _pick(FINISHERS, 1, rng)

    if deload:
        for ex in main:
            ex["notes"] = "DELOAD: " + ex.get("notes", "")
            ex["rpe"] = max(5, ex.get("rpe", 7) - 2)

    if reentry:
        # Light, short, and capped — soreness is what kills a comeback.
        for ex in main + finisher:
            ex["sets"] = max(2, int(ex.get("sets", 3)) - 1)
            ex["rpe"] = min(7, ex.get("rpe", 7))
            ex["load"] = f"{ex.get('load', '')} (go light — first sessions back)".strip()

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
            "Welcome back — short and light on purpose. Today is about moving "
            "well and enjoying it; the loads come back fast once you're here again."
            if reentry else
            "Deload week — keep it crisp and light, prioritize movement quality."
            if deload else
            "Leave 1-2 reps in reserve on main lifts. Stop any shoulder movement that pinches."
        ),
    }


def SCHEDULE_FOCUS(is_lower):
    return ("lower body power + posterior chain" if is_lower
            else "upper pulling + scapular strength + light overhead")
