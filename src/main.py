"""Entrypoint: decide today's day, generate safe workouts, email them, log them.

Flow:
  1. Determine target day (monday/friday) — from arg, env, or system clock.
  2. Decide deload (every 5th session since last deload).
  3. Gather context: recent history, multi-week load analysis, Garmin load,
     recent athlete feedback, and the rotating mandatory hip-bridge variant.
  4. Ask EVERY configured model (Nemotron + DeepSeek) for a session. Each is
     validated against the shoulder guardrail with one corrective retry, then
     falls back to a hand-vetted template if still unsafe.
  5. Email all surviving proposals side by side and append the session to history.

Safe by construction: anything a model proposes is rejected if it trips the
exclusion list, and a template is always available as a fallback.
"""

import os
import sys
import traceback
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()  # cron in a container does NOT inherit env — load .env explicitly

from . import feedback, garmin, history, llm, templates
from .email_send import send
from .exclusions import validate_workout

DELOAD_EVERY = int(os.environ.get("DELOAD_EVERY", "5"))


def target_day():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if arg in ("monday", "friday"):
        return arg
    env = os.environ.get("FORCE_DAY", "").lower()
    if env in ("monday", "friday"):
        return env
    today = datetime.now().strftime("%A").lower()
    return today if today in ("monday", "friday") else "monday"


def _ensure_hip_bridge(workout, bridge):
    """Guarantee the mandated hip bridge is present (user requirement: every
    session). If no bridge exists in any block, append it to the Main block."""
    has_bridge = any(
        "bridge" in ex.get("name", "").lower()
        for block in workout.get("blocks", [])
        for ex in block.get("exercises", [])
    )
    if has_bridge:
        return
    ex = dict(bridge)
    ex.pop("variant", None)
    for block in workout.get("blocks", []):
        if block.get("name", "").lower() == "main":
            block.setdefault("exercises", []).append(ex)
            return
    # No Main block? Add one so the requirement still holds.
    workout.setdefault("blocks", []).append({"name": "Main", "exercises": [ex]})


def build_variant(provider, day, deload, ctx):
    """One provider's proposal: LLM with validation + one retry, else template."""
    label = provider["label"]
    try:
        workout = llm.generate(
            provider, day, deload, ctx["recent"], garmin=ctx["garmin"],
            load_summary=ctx["load_summary"], feedback=ctx["feedback"],
            hip_bridge=ctx["bridge"],
        )
        ok, violations = validate_workout(workout)
        if not ok:
            print(f"[guardrail:{label}] tripped exclusions: {violations}", file=sys.stderr)
            fix = "Remove/replace these — they violate the shoulder rules: " + "; ".join(violations)
            workout = llm.generate(
                provider, day, deload, ctx["recent"], garmin=ctx["garmin"],
                load_summary=ctx["load_summary"], feedback=ctx["feedback"],
                hip_bridge=ctx["bridge"], extra_note=fix,
            )
            ok, violations = validate_workout(workout)
        if ok:
            _ensure_hip_bridge(workout, ctx["bridge"])
            return workout
        print(f"[guardrail:{label}] retry still unsafe: {violations} -> template", file=sys.stderr)
    except Exception as e:
        print(f"[llm:{label}] failed ({e}) -> template", file=sys.stderr)

    # Fallback: a safe template, tagged with this provider's label.
    seed = f"{label}-{day}-{datetime.now().date().isoformat()}"
    workout = templates.generate(day, deload, seed, session_index=ctx["session_index"])
    workout["model"] = f"{label} (fallback: template)"
    return workout


def main():
    day = target_day()
    deload = history.weeks_since_deload() >= (DELOAD_EVERY - 1)
    session_index = history.count()

    garmin_ctx = garmin.load_context()
    pattern_analysis = garmin_ctx.get("pattern_analysis", "")
    recovery = garmin_ctx.get("recovery", "")
    pattern_weeks = garmin_ctx.get("pattern_weeks", [])
    pattern_trend = garmin_ctx.get("pattern_trend", "")

    ctx = {
        "recent": history.recent(4),
        "load_summary": history.load_summary(),
        "feedback": feedback.summary(),
        "garmin": garmin_ctx,
        "bridge": templates.hip_bridge(session_index),
        "session_index": session_index,
    }

    providers = llm.active_providers()
    trend = llm.trend_analysis(providers[0], ctx, day=day, deload=deload) if providers else ""
    if not providers:
        print("[warn] no LLM providers configured — using template only", file=sys.stderr)
        seed = f"template-{day}-{datetime.now().date().isoformat()}"
        w = templates.generate(day, deload, seed, session_index=session_index)
        variants = [{"model": "Template", "workout": w}]
    else:
        variants = []
        for provider in providers:
            w = build_variant(provider, day, deload, ctx)
            variants.append({"model": w.get("model", provider["label"]), "workout": w})

    # Final safety net: never email an unvalidated workout.
    for v in variants:
        ok, violations = validate_workout(v["workout"])
        if not ok:
            raise RuntimeError(f"refusing to send unsafe workout ({v['model']}): {violations}")

    session = {
        "day": day,
        "deload": deload,
        "date": datetime.now().date().isoformat(),
        "source": "llm" if providers else "template",
        "variants": variants,
        "pattern_analysis": pattern_analysis,
        "recovery": recovery,
        "pattern_weeks": pattern_weeks,
        "pattern_trend": pattern_trend,
        "trend_analysis": trend,
    }

    send(session)
    history.append(session)
    models = ", ".join(v["model"] for v in variants)
    print(f"[ok] sent {day} session (models=[{models}], deload={deload})")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
