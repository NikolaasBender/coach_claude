"""Entrypoint: decide today's day, generate a safe workout, email it, log it.

Flow:
  1. Determine target day (monday/friday) — from arg, env, or system clock.
  2. Decide deload (every 5th session since last deload).
  3. Try LLM -> validate against shoulder guardrail -> one retry -> else template.
  4. Email it and append to history.

Safe by construction: anything the LLM proposes is rejected if it trips the
exclusion list, and a hand-vetted template is always available as a fallback.
"""

import os
import sys
import traceback
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()  # cron in a container does NOT inherit env — load .env explicitly

from . import history, llm, strava, templates
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


def build_workout(day, deload, recent, strava_ctx):
    """LLM with validation + one retry, falling back to a safe template."""
    try:
        workout = llm.generate(day, deload, recent, strava=strava_ctx)
        ok, violations = validate_workout(workout)
        if ok:
            return workout
        print(f"[guardrail] LLM tripped exclusions: {violations}", file=sys.stderr)

        # One corrective retry, naming the offending exercises.
        fix = "Remove/replace these — they violate the shoulder rules: " + "; ".join(violations)
        workout = llm.generate(day, deload, recent, strava=strava_ctx, extra_note=fix)
        ok, violations = validate_workout(workout)
        if ok:
            return workout
        print(f"[guardrail] retry still unsafe: {violations} -> template", file=sys.stderr)
    except Exception as e:
        print(f"[llm] failed ({e}) -> template", file=sys.stderr)

    seed = f"{day}-{datetime.now().date().isoformat()}"
    return templates.generate(day, deload, seed)


def main():
    day = target_day()
    deload = history.weeks_since_deload() >= (DELOAD_EVERY - 1)
    recent = history.recent(4)
    strava_ctx = strava.load_context()

    workout = build_workout(day, deload, recent, strava_ctx)

    # Final safety net: a template should always pass, but never email an
    # unvalidated workout.
    ok, violations = validate_workout(workout)
    if not ok:
        raise RuntimeError(f"refusing to send unsafe workout: {violations}")

    send(workout)
    history.append(workout)
    print(f"[ok] sent {day} workout (source={workout.get('source')}, deload={deload})")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
