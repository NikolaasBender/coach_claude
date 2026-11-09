"""Left-shoulder check-ins: what to ask, and what the answers say over time.

Every session carries two kinds of shoulder questions, and both are permanent:

  STANDING_CHECKS  fixed questions asked after EVERY session, forever. They are
                   code constants rather than model output, so the long-term
                   record stays comparable year over year.
  session checks   2-3 questions tied to specific exercises in today's session
                   (what the landmine press or the single-arm row is testing).
                   The model proposes them; `ensure_checks` validates and
                   backfills so a session can never ship without them.

Answers live in feedback.json under entry["shoulder"]. Standing answers are
keyed by their stable `key` (the key is the long-term contract — reword a
question freely, never repurpose a key); session-specific answers carry their
own question text, since those questions differ every session. Nothing is ever
trimmed — `summary` reads the whole log and reports the long-term trend
alongside the recent picture.

This module deliberately does not import feedback.py (feedback imports this
one to format entries); callers pass the entries in.
"""

import re

KINDS = ("scale", "side", "yesno")

# Answer options per kind. Scale is 0-10; stored as int.
SIDE_OPTIONS = ("left much harder", "left a bit harder", "same", "left easier")
YESNO_OPTIONS = ("no", "yes")

STANDING_CHECKS = [
    {
        "key": "apprehension",
        "kind": "scale",
        "question": "Left-shoulder apprehension — the 'it might slip' feeling — at its worst today (0-10)",
    },
    {
        "key": "pain",
        "kind": "scale",
        "question": "Left-shoulder pain during or after the session (0-10)",
    },
    {
        "key": "instability",
        "kind": "yesno",
        "question": "Any clunk, slip, dead-arm or catching sensation in the left shoulder?",
    },
    {
        "key": "left_vs_right",
        "kind": "side",
        "question": "Single-arm work overall: how did the left side compare with the right?",
    },
]

MAX_SESSION_CHECKS = 3
MIN_SESSION_CHECKS = 2

# Exercises that load the left shoulder enough to be worth asking about.
_LEFT_LOADING = re.compile(
    r"single[\s-]*arm|one[\s-]*arm|half[\s-]*kneeling|landmine|press|\brow\b|chin[\s-]*up|"
    r"pull[\s-]*up|pulldown|carry|plank|crawl|push[\s-]*up|bottoms[\s-]*up|\bball\b|"
    r"external rotation|serratus|scapular|\bhang"
)
_UNILATERAL = re.compile(r"single[\s-]*arm|one[\s-]*arm|half[\s-]*kneeling|suitcase|offset|unilateral")
# Leg-dominant work that can trip the patterns above ("single-leg press").
_LOWER_BODY = re.compile(
    r"squat|single[\s-]*leg|leg press|lunge|step[\s-]*up|bridge|deadlift|\brdl\b|"
    r"romanian|jump|\bhop\b|swing|calf"
)


def _loads_left_shoulder(name):
    low = name.lower()
    return bool(_LEFT_LOADING.search(low)) and not _LOWER_BODY.search(low)


def _exercise_names(workout):
    """[(block_name, exercise_name)] in session order."""
    return [
        (block.get("name", ""), ex.get("name", ""))
        for block in workout.get("blocks", [])
        for ex in block.get("exercises", [])
        if ex.get("name")
    ]


def _match_exercise(name, workout):
    """The workout's own spelling of `name`, or None if it isn't in the session."""
    target = (name or "").strip().lower()
    if not target:
        return None
    for _, ex_name in _exercise_names(workout):
        low = ex_name.lower()
        if target == low or target in low or low in target:
            return ex_name
    return None


def _default_checks(workout, exclude=()):
    """Deterministic exercise-specific checks for the left shoulder. Main and
    finisher work first (that is where it gets loaded), rehab drills last."""
    names = _exercise_names(workout)
    ordered = [n for b, n in names if "rehab" not in b.lower()] + [
        n for b, n in names if "rehab" in b.lower()
    ]
    checks = []
    for name in ordered:
        if name in exclude or not _loads_left_shoulder(name):
            continue
        if _UNILATERAL.search(name.lower()):
            checks.append({
                "exercise": name, "kind": "side",
                "question": f"{name}: left side compared with right?",
            })
        else:
            checks.append({
                "exercise": name, "kind": "scale",
                "question": f"{name}: left-shoulder apprehension on the worst rep (0-10)?",
            })
        if len(checks) >= MIN_SESSION_CHECKS:
            break
    if not checks:
        checks.append({
            "exercise": "", "kind": "yesno",
            "question": "Did you cut range or guard the left shoulder on any rep today?",
        })
    return checks


def ensure_checks(workout):
    """Validate the model's `shoulder_checks` and backfill to at least
    MIN_SESSION_CHECKS. Mutates and returns the workout."""
    valid = []
    seen = set()
    for c in workout.get("shoulder_checks") or []:
        if not isinstance(c, dict):
            continue
        kind = str(c.get("kind", "")).strip().lower()
        question = str(c.get("question", "")).strip()
        exercise = _match_exercise(c.get("exercise"), workout)
        if kind not in KINDS or not question or not exercise or exercise in seen:
            continue
        seen.add(exercise)
        valid.append({"exercise": exercise, "kind": kind, "question": question[:200]})
        if len(valid) >= MAX_SESSION_CHECKS:
            break

    if len(valid) < MIN_SESSION_CHECKS:
        for c in _default_checks(workout, exclude=seen):
            if len(valid) >= MIN_SESSION_CHECKS:
                break
            valid.append(c)

    workout["shoulder_checks"] = valid
    return workout


def session_checks(entry):
    """All session-specific checks for a history entry, deduped across model
    variants. Legacy entries without checks return []."""
    if entry.get("variants"):
        workouts = [v.get("workout", {}) for v in entry["variants"]]
    else:
        workouts = [entry]
    out, seen = [], set()
    for w in workouts:
        for c in w.get("shoulder_checks") or []:
            q = c.get("question", "")
            if q and q not in seen:
                seen.add(q)
                out.append(c)
    return out


def parse_answer(kind, raw):
    """Normalize a submitted answer; None when blank or invalid."""
    raw = (raw or "").strip().lower()
    if not raw:
        return None
    if kind == "scale":
        return int(raw) if raw.isdigit() and 0 <= int(raw) <= 10 else None
    if kind == "side":
        return raw if raw in SIDE_OPTIONS else None
    if kind == "yesno":
        return raw if raw in YESNO_OPTIONS else None
    return None


def _fmt(kind, value):
    return f"{value}/10" if kind == "scale" else str(value)


def format_entry(shoulder):
    """Compact one-line rendering of an entry's shoulder answers."""
    if not shoulder:
        return ""
    bits = []
    standing = shoulder.get("standing") or {}
    for spec in STANDING_CHECKS:
        if spec["key"] in standing:
            label = spec["key"].replace("_", " ")
            bits.append(f"{label} {_fmt(spec['kind'], standing[spec['key']])}")
    for c in shoulder.get("checks") or []:
        name = c.get("exercise") or "guarding"
        bits.append(f"{name} {_fmt(c.get('kind'), c.get('answer'))}")
    return "; ".join(bits)


def _avg(values):
    return sum(values) / len(values) if values else None


def summary(entries):
    """Long-term + recent left-shoulder picture for the LLM prompt, built from
    the WHOLE feedback log (oldest first)."""
    logs = []
    for e in entries:
        sh = e.get("shoulder")
        if sh:
            when = e.get("session_date") or (e.get("logged_at") or "?")[:10]
            logs.append((when, sh))

    if not logs:
        return (
            "LEFT-SHOULDER LOG: nothing logged yet. Program conservatively on the "
            "left side and write good session-specific shoulder_checks so the log "
            "starts filling in."
        )

    def standing(sh, key):
        return (sh.get("standing") or {}).get(key)

    appr = [(w, standing(sh, "apprehension")) for w, sh in logs if standing(sh, "apprehension") is not None]
    pain = [(w, standing(sh, "pain")) for w, sh in logs if standing(sh, "pain") is not None]
    unstable = [w for w, sh in logs if standing(sh, "instability") == "yes"]

    lines = ["LEFT-SHOULDER LOG (athlete-reported, kept forever — adapt to it):"]

    recent = logs[-6:]
    lines.append("Recent sessions (most recent last):")
    for w, sh in recent:
        lines.append(f"  {w}: {format_entry(sh) or 'no answers'}")

    if len(appr) >= 4:
        early = _avg([v for _, v in appr[:3]])
        late = _avg([v for _, v in appr[-3:]])
        direction = "down" if late < early - 0.5 else "up" if late > early + 0.5 else "flat"
        lines.append(
            f"Long-term apprehension: first 3 logs avg {early:.1f}/10 -> last 3 avg "
            f"{late:.1f}/10 ({direction}, {len(appr)} logs since {appr[0][0]})."
        )
    if unstable:
        lines.append(
            f"Instability events ever reported: {len(unstable)} "
            f"(dates: {', '.join(unstable[-5:])})."
        )

    flagged = []
    for w, sh in logs[-8:]:
        for c in sh.get("checks") or []:
            a = c.get("answer")
            if (c.get("kind") == "scale" and isinstance(a, int) and a >= 4) or a == "left much harder":
                flagged.append(f"{c.get('exercise') or 'guarding'} ({_fmt(c.get('kind'), a)} on {w})")
    if flagged:
        lines.append("Movements that bothered the left shoulder recently: " + "; ".join(flagged) + ".")

    # Directives keyed to the most recent log.
    last_w, last = logs[-1]
    last_three = logs[-3:]
    rules = []
    if standing(last, "instability") == "yes":
        rules.append(
            f"The last session ({last_w}) reported a clunk/slip/dead-arm. TODAY: no "
            "loaded pressing, no overhead, no hanging; left-arm work is rehab and "
            "closed-chain stability only. Say in coach_notes to check in with the PT."
        )
    elif (standing(last, "pain") or 0) >= 4 or (standing(last, "apprehension") or 0) >= 6:
        rules.append(
            "Last session was rough on the shoulder: regress left-side load or range "
            "one step and avoid the movements flagged above."
        )
    elif len(last_three) == 3 and all(
        (standing(sh, "apprehension") is not None and standing(sh, "apprehension") <= 2)
        and (standing(sh, "pain") or 0) == 0
        and standing(sh, "instability") != "yes"
        for _, sh in last_three
    ):
        rules.append(
            "Three quiet sessions in a row: progress ONE left-side single-arm "
            "movement a notch (load, tempo, or range) — never into loaded "
            "abduction + external rotation."
        )
    if rules:
        lines.append("ACT ON THIS: " + " ".join(rules))
    return "\n".join(lines)
