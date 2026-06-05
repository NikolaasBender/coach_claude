# coach_claude

Auto-generates a strength workout twice a week (Mon & Fri, 5am) and emails it to
you. Built to supplement gravel/MTB cardio training and keep a repaired left
shoulder healthy.

An NVIDIA-hosted LLM designs each session from your profile + recent history
(for progression & variety). Every workout is then checked against a hard
**shoulder safety guardrail** in code — anything risky is rejected and the model
is asked to swap it, falling back to a hand-vetted template if needed. The model
never has the final say on safety.

## How it works

```
history.json ──▶ LLM proposes workout (JSON)
                       │
                       ▼
              guardrail validator (exclusions.py)
                 │ pass            │ fail
                 ▼                 ▼
              email          retry once, else
                             safe template
```

## Setup

1. **Rotate / get an NVIDIA API key** — sign up at https://build.nvidia.com,
   generate a key (`nvapi-...`).
2. **Gmail App Password** — https://myaccount.google.com/apppasswords
   (requires 2FA on your Google account). This is a 16-char password, *not* your
   real one.
3. **Configure:**
   ```bash
   cp .env.example .env
   # edit .env: NVIDIA_API_KEY, GMAIL_ADDRESS, GMAIL_APP_PASSWORD, TZ
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

## Tuning

| What | Where |
|---|---|
| Athlete profile, equipment, day focus | `src/profile.py` |
| Shoulder exclusion rules (the guardrail) | `src/exclusions.py` |
| Safe fallback exercises | `src/templates.py` |
| Deload frequency, model, schedule | `.env`, `crontab` |

## Safety note

The exclusion list encodes general post-labral-repair precautions (no flys /
loaded horizontal abduction, no behind-the-neck, no dips, no upright rows, no
kipping, careful overhead progression). **Get it sanity-checked by your PT**
before trusting an automated sender with an unstable joint. Stop any movement
that pinches.
