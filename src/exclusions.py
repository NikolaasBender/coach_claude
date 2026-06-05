"""Hard safety guardrail for the left shoulder.

The LLM proposes exercises; this module disposes. Any movement matching the
exclusion patterns is rejected regardless of what the model wants. An unstable,
surgically-repaired joint must never depend on the model behaving.

Rationale (anterior labrum repair + recurrent anterior dislocations):
the danger zone is loaded ABDUCTION + EXTERNAL ROTATION (the "cocking" position)
and end-range anterior translation.
"""

import re

# Each entry: (human reason, list of regex patterns matched against exercise name)
# Patterns are lowercased substring/word matches. Keep them broad — false
# positives (a safe lift wrongly blocked) are cheap; a missed bad lift is not.
EXCLUSIONS = [
    (
        "outward/lateral fly and loaded horizontal abduction — direct anterior strain",
        [r"\bfly", r"\bflye", r"lateral raise", r"reverse pec", r"pec deck",
         r"horizontal abduction"],
    ),
    (
        "behind-the-neck press/pulldown — forces ER at abduction (cocking position)",
        [r"behind[\s-]*the[\s-]*neck", r"\bbtn\b"],
    ),
    (
        "dips — heavy anterior loading at end range",
        [r"\bdip\b", r"\bdips\b"],
    ),
    (
        "upright row — impingement risk",
        [r"upright row"],
    ),
    (
        "kipping / ballistic pull-ups — uncontrolled end-range ER strain",
        [r"kipping", r"butterfly pull", r"ballistic pull"],
    ),
    (
        "wide-grip / deep barbell bench — anterior translation at end range",
        [r"wide[\s-]*grip bench", r"wide[\s-]*grip press"],
    ),
    (
        "explicit cocking-position cues — abduction + external rotation under load",
        [r"cocking position", r"abduction.*external rotation",
         r"external rotation.*abduction"],
    ),
]


def check(exercise_name: str):
    """Return list of (reason) violations for an exercise name. Empty == safe."""
    name = (exercise_name or "").lower()
    hits = []
    for reason, patterns in EXCLUSIONS:
        for pat in patterns:
            if re.search(pat, name):
                hits.append(reason)
                break
    return hits


def validate_workout(workout: dict):
    """Scan every exercise in a workout dict.

    Returns (ok: bool, violations: list[str]). `workout` is expected to have
    blocks -> exercises -> name. Tolerant of missing keys.
    """
    violations = []
    for block in workout.get("blocks", []):
        for ex in block.get("exercises", []):
            name = ex.get("name", "")
            for reason in check(name):
                violations.append(f"{name!r}: {reason}")
    return (len(violations) == 0, violations)


# Plain-text constraints injected into the LLM prompt so it avoids these up front.
PROMPT_CONSTRAINTS = """HARD SHOULDER RULES (left shoulder, anterior labrum repair, recurrent dislocations):
- NO flys, lateral raises, reverse-pec, or any loaded horizontal abduction.
- NO behind-the-neck pressing or pulldowns.
- NO dips. NO upright rows. NO kipping/ballistic pull-ups.
- NO wide-grip or deep end-range barbell bench (limit ROM, neutral/close grip only).
- AVOID loading the abduction + external-rotation ("cocking") position.
- Overhead pressing is ALLOWED but must start light (band/TRX/landmine/KB) and progress slowly.
- ALWAYS open with a shoulder rehab block: band external rotation, scapular control,
  controlled TRX/row patterning."""
