"""LLM layer — multi-provider (OpenAI-compatible endpoints).

Each session is designed by EVERY configured provider (currently NVIDIA's
Nemotron and DeepSeek). The models see the same brief: athlete profile, hard
shoulder constraints, Garmin training load + recovery state, multi-week
strength-load analysis, recent athlete feedback, and the mandatory hip-bridge
variant for the day. main.py validates each proposal against exclusions.py
before trusting it, then the email shows the surviving proposals side by side.

This module also writes the short "coach's trend read" narrative that opens
the email (trend_analysis) — best-effort, never blocking.

This module never gets the final say on safety.
"""

import json
import os
import sys

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


TREND_SYSTEM = """You are the same strength coach reviewing an advanced
cyclist's recent training before writing today's session. Produce a SHORT
plain-text trend read for the top of the workout email.

Rules:
- 3 to 5 lines, each starting with "- ", max ~120 words total.
- Ground every line in the data given: riding volume/intensity trajectory,
  strength-session consistency, recovery/sleep/stress state.
- Finish with one extra line starting "Today: " — what the trend implies
  for this session.
- No markdown headers, no JSON, no preamble. Interpret the numbers, don't
  just repeat them."""


def trend_analysis(provider, ctx, day="", deload=False):
    """One short LLM narrative about multi-week training trends for the email.

    Best-effort: returns "" on any failure or when there is no data worth
    analyzing, so the email always sends.
    """
    try:
        garmin = ctx.get("garmin") or {}
        parts = []
        if garmin.get("pattern_analysis"):
            parts.append(garmin["pattern_analysis"])
        if garmin.get("summary"):
            parts.append("LAST 7 DAYS OF TRAINING:\n" + garmin["summary"])
        if garmin.get("recovery"):
            parts.append("CURRENT RECOVERY SNAPSHOT:\n" + garmin["recovery"])
        if ctx.get("load_summary"):
            parts.append("STRENGTH-LOAD ANALYSIS (gym sessions):\n" + ctx["load_summary"])
        if ctx.get("feedback"):
            parts.append(ctx["feedback"])
        if not parts:
            return ""
        if day:
            parts.append(f"TODAY'S SESSION: {day}, deload={bool(deload)}")

        client = OpenAI(base_url=provider["base_url"],
                        api_key=os.environ[provider["key_env"]])
        resp = client.chat.completions.create(
            model=provider["model"],
            messages=[
                {"role": "system", "content": TREND_SYSTEM},
                {"role": "user", "content": "\n\n".join(parts) + "\n\nWrite the trend read now."},
            ],
            max_tokens=4096,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Some reasoning models leak a think-block into content; drop it.
        if text.startswith("<think>") and "</think>" in text:
            text = text.split("</think>", 1)[1].strip()
        return text
    except Exception as e:
        print(f"[llm:trend] failed ({e}) — sending email without trend read", file=sys.stderr)
        return ""


def _build_user_prompt(day, deload, history, garmin=None, load_summary="",
                       feedback="", hip_bridge=None):
    equip = "\n".join(f"- {e}" for e in P.EQUIPMENT)
    equip += f"\n\nNOTE: {P.EQUIPMENT_NOTES}"
    hist = json.dumps(history, indent=2) if history else "none yet (first session)"

    garmin_section = ""
    if garmin:
        summary = garmin.get("summary", "")
        yesterday = garmin.get("yesterday_note", "")
        garmin_section = f"""
RECENT TRAINING LOAD (last 7 days from Garmin — use this to calibrate intensity):
{summary}

DAY-BEFORE NOTE: {yesterday}
"""

    recovery = garmin.get("recovery", "") if garmin else ""
    recovery_section = ""
    if recovery:
        recovery_section = f"""
CURRENT RECOVERY STATE (Garmin wearable — sleep, stress, body battery, HRV):
{recovery}
Use this to modulate today's session: short/poor sleep, elevated stress, low
body battery, or unbalanced HRV -> trim volume/intensity and bias toward
technique, mobility, and core; fully recovered -> allow planned progression.
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
{garmin_section}{recovery_section}{load_section}{feedback_section}{bridge_line}
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


def generate(provider, day, deload, history, garmin=None, load_summary="",
             feedback="", hip_bridge=None, extra_note=None):
    """Call one provider's LLM and return a parsed workout dict.

    Raises on failure so the caller can retry or fall back to templates.
    `provider` is one of the PROVIDERS dicts.
    """
    api_key = os.environ[provider["key_env"]]
    client = OpenAI(base_url=provider["base_url"], api_key=api_key)

    user = _build_user_prompt(
        day, deload, history, garmin=garmin,
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
