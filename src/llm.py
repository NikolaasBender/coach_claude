"""LLM layer — multi-provider (OpenAI-compatible endpoints).

Each session is designed by EVERY configured provider (currently NVIDIA's
Nemotron and DeepSeek). The models see the same brief: athlete profile, hard
shoulder constraints, Strava load, multi-week strength-load analysis, recent
athlete feedback, and the mandatory hip-bridge variant for the day. main.py
validates each proposal against exclusions.py before trusting it, then the email
shows the surviving proposals side by side for comparison.

This module never gets the final say on safety.
"""

import json
import os

from openai import OpenAI

from . import profile as P
from .exclusions import PROMPT_CONSTRAINTS

# Provider registry. A provider is "active" when its API key is present in the
# environment, so dropping a key cleanly disables that model.
PROVIDERS = [
    {
        "name": "nemotron",
        "label": "Nemotron",
        "key_env": "NVIDIA_API_KEY",
        "base_url": os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1"),
        "model": os.environ.get("NVIDIA_MODEL", "nvidia/nemotron-3-ultra-550b-a55b"),
        "create_kwargs": {"temperature": 0.8, "top_p": 0.95},
    },
    {
        "name": "deepseek",
        "label": "DeepSeek",
        "key_env": "DEEPSEEK_API_KEY",
        "base_url": os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        # deepseek-v4-pro is a reasoning model: enable extended thinking.
        "create_kwargs": {
            "temperature": 0.8,
            "reasoning_effort": "high",
            "extra_body": {"thinking": {"type": "enabled"}},
        },
    },
]

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


def active_providers():
    """Return the provider configs that have an API key configured."""
    return [p for p in PROVIDERS if os.environ.get(p["key_env"])]


def _build_user_prompt(day, deload, history, strava=None, load_summary="",
                       feedback="", hip_bridge=None):
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

    load_section = f"\nSTRENGTH-LOAD ANALYSIS (recent weeks):\n{load_summary}\n" if load_summary else ""
    feedback_section = f"\n{feedback}\n" if feedback else ""

    bridge_line = ""
    if hip_bridge:
        bridge_line = (
            "\nMANDATORY THIS SESSION — include EXACTLY this hip bridge variant in "
            f"the Main block (do not substitute): \"{hip_bridge['name']}\" "
            f"({hip_bridge.get('reps','')}, {hip_bridge.get('load','')}). "
            "It rotates single-leg -> weighted -> unweighted across sessions.\n"
        )

    return f"""Design the {day.upper()} session.

ATHLETE: {P.ATHLETE['experience']}, {P.ATHLETE['training_role']}.
Sport: {P.ATHLETE['discipline']}. Session target: {P.ATHLETE['session_minutes']} min.
Primary focus for {day}: {P.SCHEDULE.get(day.lower(), 'general strength')}.

{PROMPT_CONSTRAINTS}

EQUIPMENT AVAILABLE (use only these):
{equip}

DELOAD THIS SESSION: {deload}. If true, cut volume/intensity ~40%.
{strava_section}{load_section}{feedback_section}{bridge_line}
REQUIRED CONTENT EVERY SESSION:
- The mandatory hip bridge variant named above (in Main).
- At least one dedicated LOWER-CORE movement (e.g. lying/hanging leg raise,
  dead bug, reverse crunch). Prefer lower-ab/anti-extension work over generic planks.
- Deliberately vary exercises week to week; rotate away from what was used most
  in the recent block. Nudge load/reps up where the athlete handled it well.
- In coach_notes, briefly ACKNOWLEDGE the recent training block and feedback
  (what you're carrying over, progressing, or backing off).

RECENT STRENGTH HISTORY (full recent entries for reference):
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


def generate(provider, day, deload, history, strava=None, load_summary="",
             feedback="", hip_bridge=None, extra_note=None):
    """Call one provider's LLM and return a parsed workout dict.

    Raises on failure so the caller can retry or fall back to templates.
    `provider` is one of the PROVIDERS dicts.
    """
    api_key = os.environ[provider["key_env"]]
    client = OpenAI(base_url=provider["base_url"], api_key=api_key)

    user = _build_user_prompt(
        day, deload, history, strava=strava,
        load_summary=load_summary, feedback=feedback, hip_bridge=hip_bridge,
    )
    if extra_note:
        # Used on retry to tell the model which exercises it must replace.
        user += f"\n\nIMPORTANT FIX: {extra_note}"

    resp = client.chat.completions.create(
        model=provider["model"],
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        max_tokens=8192,
        **provider.get("create_kwargs", {}),
    )
    content = resp.choices[0].message.content or ""
    workout = _extract_json(content)
    workout["source"] = "llm"
    workout["model"] = provider["label"]
    workout["day"] = day
    workout["deload"] = bool(deload)
    return workout
