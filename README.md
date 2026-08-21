# coach_claude

## Overview

`coach_claude` is an automated strength training coach for a gravel/MTB cyclist with a repaired left shoulder. It generates workouts twice weekly (Mon/Fri 5am) using **NVIDIA Nemotron**, validates every proposal against a hard shoulder safety guardrail, and emails the workout with a **Garmin recovery snapshot** (sleep, stress, body battery, HRV) and a **3-week Garmin pattern analysis** at the top and a feedback loop.
independently from your profile, multi-week training load, and recent feedback.
The email shows both side by side so you can compare and pick. Every proposal is
checked against a hard **shoulder safety guardrail** in code — anything risky is
rejected and the model is asked to swap it, falling back to a hand-vetted
template if needed. The model never has the final say on safety.

## How it works

```
history.json + load analysis + Garmin (training load + recovery) + feedback
        │
        ▼
  each model (Nemotron, DeepSeek) proposes a workout (JSON)
        │
        ▼
  guardrail validator (exclusions.py)
     │ pass            │ fail
     ▼                 ▼
  email BOTH      retry once, else
  side by side    safe template
        │
        ▼
  feedback web app (port 8080) ──▶ feedback.json ──▶ next prompt
```

### What each session now guarantees

- **Load awareness** — a multi-week digest of what's been programmed (exercise
  frequency, avg RPE, recent focus) goes into the prompt, and the model
  acknowledges the recent block in its coach notes.
- **Recovery awareness** — the coach also sees your Garmin wearable data (last
  night's sleep, stress, body battery, HRV) and modulates the session: run-down
  days trim volume toward technique/mobility/core, recovered days progress as
  planned.
- **A hip bridge every time**, rotating single-leg → weighted → unweighted.
- **A dedicated lower-core movement** (leg raises, dead bugs, reverse crunch…).
- **More variety** — larger exercise pools; the model is told to rotate away
  from whatever it used most recently.

## Feedback web app

An always-on Flask app (second container, port `8080`) lists recent sessions and
lets you log a rating, which coach you preferred, and notes. It writes to
`data/feedback.json` on the shared volume, which feeds straight back into the
next prompt. Reach it on your LAN at `http://<pi-host>:8080` — set that same URL
as `WEB_URL` in `.env` so the workout emails link to it.

## Setup

1. **API keys** — an NVIDIA key (`nvapi-...`) from https://build.nvidia.com and
   a DeepSeek key (`sk-...`) from https://platform.deepseek.com. Either can be
   left blank to disable that model; if both are set you get both proposals.
2. **Gmail App Password** — https://myaccount.google.com/apppasswords
   (requires 2FA on your Google account). This is a 16-char password, *not* your
   real one.
3. **Configure:**
   ```bash
   cp .env.example .env
   # edit .env: NVIDIA_API_KEY, DEEPSEEK_API_KEY, GMAIL_ADDRESS,
   #            GMAIL_APP_PASSWORD, WEB_URL, TZ
   ```
   ⚠️ Set `TZ` to your actual timezone (e.g. `America/Denver`) or 5am will fire
   in the wrong zone.
4. **Run:**
   ```bash
   docker compose up -d --build
   ```
   It now sits idle and fires Mon & Fri at 5am local.

## Test it now (send yourself one immediately)

```bash
# build first
docker compose build
# one-off run for a given day, ignores the schedule
docker compose run --rm coach python -m src.main monday
```

Run the feedback app locally without Docker:

```bash
pip install -r requirements.txt
python -m src.web   # serves on http://localhost:8080
```

## Tuning

| What | Where |
|---|---|
| Athlete profile, equipment, day focus | `src/profile.py` |
| Shoulder exclusion rules (the guardrail) | `src/exclusions.py` |
| Safe fallback exercises, hip-bridge rotation, core pool | `src/templates.py` |
| LLM providers (Nemotron / DeepSeek) | `src/llm.py` `PROVIDERS` |
| Feedback web app | `src/web.py` |
| Deload frequency, models, web port, schedule | `.env`, `crontab` |

## Safety note

The exclusion list encodes general post-labral-repair precautions (no flys /
loaded horizontal abduction, no behind-the-neck, no dips, no upright rows, no
kipping, careful overhead progression). **Get it sanity-checked by your PT**
before trusting an automated sender with an unstable joint. Stop any movement
that pinches.
