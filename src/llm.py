"""NVIDIA-hosted LLM layer (OpenAI-compatible endpoint).

Asks the model to design a workout as structured JSON, given the athlete
profile, hard shoulder constraints, and recent history (for progression and
variety). The caller validates the result against exclusions.py before trusting
it — this module never gets the final say on safety.
"""

import json
import os

from openai import OpenAI

from . import profile as P
from .exclusions import PROMPT_CONSTRAINTS

BASE_URL = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
MODEL = os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b")

SYSTEM = """You are a strength coach for an advanced cyclist. You design ONE
session at a time. You MUST obey the hard shoulder rules without exception.
You return ONLY a single JSON object, no prose, no markdown fences.

JSON schema:
{
  "focus": string,
  "deload": boolean,
  "coach_notes": string,
  "blocks": [
    {"name": string, "exercises": [
      {"name": string, "sets": number, "reps": string,
       "load": string, "rpe": number, "notes": string}
    ]}
  ]
}

Always include exactly three blocks in order:
1. "Shoulder rehab warmup"  2. "Main"  3. "Cycling finisher".
Keep total session to ~55 minutes for an advanced lifter."""


def _build_user_prompt(day, deload, history, strava=None):
    equip = "\n".join(f"- {e}" for e in P.EQUIPMENT)
    equip += f"\n\nNOTE: {P.EQUIPMENT_NOTES}"
    hist = json.dumps(history, indent=2) if history else "none yet (first session)"

    strava_section = ""
    if strava:
        summary = strava.get("summary", "")
        yesterday = strava.get("yesterday_note", "")
        strava_section = f"""
RECENT TRAINING LOAD (last 7 days from Strava — use this to calibrate intensity):
{summary}

DAY-BEFORE NOTE: {yesterday}
"""

    return f"""Design the {day.upper()} session.

ATHLETE: {P.ATHLETE['experience']}, {P.ATHLETE['training_role']}.
Sport: {P.ATHLETE['discipline']}. Session target: {P.ATHLETE['session_minutes']} min.
Primary focus for {day}: {P.SCHEDULE.get(day.lower(), 'general strength')}.

{PROMPT_CONSTRAINTS}

EQUIPMENT AVAILABLE (use only these):
{equip}

DELOAD THIS SESSION: {deload}. If true, cut volume/intensity ~40%.
{strava_section}
RECENT STRENGTH HISTORY (progress sensibly — vary exercises week to week,
nudge load/reps where the athlete handled it well):
{hist}

Return the JSON object now."""


def _extract_json(text: str):
    """Pull the first balanced JSON object out of a model response."""
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object in model output")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start:i + 1])
    raise ValueError("unbalanced JSON in model output")


def generate(day, deload, history, strava=None, extra_note=None):
    """Call the LLM and return a parsed workout dict. Raises on failure so the
    caller can fall back to templates."""
    api_key = os.environ["NVIDIA_API_KEY"]
    client = OpenAI(base_url=BASE_URL, api_key=api_key)

    user = _build_user_prompt(day, deload, history, strava=strava)
    if extra_note:
        # Used on retry to tell the model which exercises it must replace.
        user += f"\n\nIMPORTANT FIX: {extra_note}"

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.8,
        top_p=0.95,
        max_tokens=8192,
    )
    content = resp.choices[0].message.content or ""
    workout = _extract_json(content)
    workout["source"] = "llm"
    workout["day"] = day
    workout["deload"] = bool(deload)
    return workout
