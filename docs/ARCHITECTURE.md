# Architecture Overview

## System Purpose

`coach_claude` automatically generates a strength workout twice a week (Monday & Friday, 5am local) and emails it to a gravel/MTB cyclist with a repaired left shoulder. Two LLMs (NVIDIA Nemotron and DeepSeek) independently design each session from the same context — athlete profile, multi-week training load, Strava ride data, and recent athlete feedback. The email shows both proposals side by side for comparison.

**Safety is enforced in code, not by the model.** Every LLM proposal is validated against a hard exclusion guardrail (`exclusions.py`) with one corrective retry; if still unsafe, it falls back to a hand-vetted template. The model never has the final say on shoulder safety.

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        ENTRYPOINT (cron)                         │
│  Mon/Fri 05:00 local → python -m src.main [monday|friday]       │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     main.py (orchestrator)                       │
│  1. Determine target day (arg / env / system clock)             │
│  2. Decide deload (every 5th session since last deload)         │
│  3. Gather context:                                              │
│     • Recent history (last 4 sessions)                          │
│     • Multi-week load analysis (exercise freq, avg RPE, focus)  │
│     • Strava 7-day ride summary + yesterday detail              │
│     • Recent athlete feedback (last 6 entries)                  │
│     • Mandatory hip-bridge variant (rotates SL → weighted → BW) │
│  4. For EACH active provider (Nemotron, DeepSeek):              │
│     a. Call LLM with full context                               │
│     b. Validate against exclusions.py                           │
│     c. One retry on failure                                     │
│     d. Fallback to template if still unsafe                     │
│  5. Email all surviving proposals side by side                  │
│  6. Append session to history.json                              │
└───────────────────────────┬──────────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
┌─────────────────────────┐   ┌─────────────────────────┐
│     Feedback Web        │   │      Data Volume        │
│     (Flask, port 8080)  │   │  /data/history.json     │
│                         │   │  /data/feedback.json    │
│ • Lists recent sessions │   └─────────────────────────┘
│ • Logs rating + notes   │
│ • Feeds next prompt     │
└─────────────────────────┘
```

## Container Architecture (Docker Compose)

Two services share one image:

| Service | Command | Purpose |
|---------|---------|---------|
| `coach` | `cron -f` (default) | Runs scheduled workout generation |
| `web` | `python -m src.web` | Always-on Flask feedback app |

Both mount:
- `./data:/data` — persistent history + feedback
- `./.env:/app/.env:ro` — configuration (cron jobs load `.env` via python-dotenv)

## Core Modules

### `src/main.py` — Orchestrator
- Entry point, determines day & deload
- Gathers all context (history, strava, feedback, hip bridge)
- Calls each provider via `llm.generate()`
- Validates with `exclusions.validate_workout()`
- Sends email via `email_send.send()`
- Appends to history

### `src/llm.py` — LLM Layer
- `PROVIDERS` registry: Nemotron + DeepSeek (OpenAI-compatible endpoints)
- Active providers = those with API keys in env
- `_build_user_prompt()`: injects athlete profile, constraints, context
- `generate()`: calls provider, extracts JSON, returns workout dict

### `src/exclusions.py` — Hard Safety Guardrail
- Regex patterns for dangerous movements (posterior labrum repair precautions)
- `check(exercise_name)` → list of violation reasons
- `validate_workout(workout)` → (ok, violations)
- `PROMPT_CONSTRAINTS` injected into LLM prompt to reduce rejections

### `src/templates.py` — Deterministic Fallback
- Pre-vetted exercise pools (all clear exclusions)
- `generate(day, deload, seed, session_index)` → safe workout
- Guarantees: hip bridge (rotating), lower-core movement every session

### `src/history.py` — Persistent Session Log
- `data/history.json` on mounted volume
- `recent(n)`, `count()`, `append()`
- `load_summary(n_sessions)` → human-readable for LLM prompt
- `weeks_since_deload()` → gates deload scheduling

### `src/feedback.py` — Athlete Feedback Log
- `data/feedback.json` on mounted volume
- Web app writes; generator reads `recent(n)` → `summary(n)` for prompt
- Tracks: rating (1-5), preferred_model, notes, session_date, day

### `src/strava.py` — Training Load Context
- OAuth refresh token flow (one-time setup via `setup_strava.py`)
- `load_context(session_date)` → `{summary, yesterday_note}`
- Classifies rides by suffer score: easy/moderate/hard/very hard

### `src/profile.py` — Athlete Profile (Single Source of Truth)
- `ATHLETE`: discipline, role, experience, session_minutes
- `SHOULDER`: side, history, status, always_include_rehab
- `EQUIPMENT`: list available to LLM/templates
- `SCHEDULE`: day → focus mapping
- `FINISHER_THEMES`: cycling-relevant finisher categories

### `src/web.py` — Feedback Web App (Flask)
- `/` — lists recent sessions with feedback forms
- `/generate` — manual trigger (one-at-a-time lock)
- `/feedback` — POST endpoint for rating + notes
- `/healthz` — health check
- Jinja-free: renders HTML via Python string templates

### `src/email_send.py` — Email Rendering & Delivery
- `render_html(session)`: side-by-side variant tables with exercise links
- `send(session)`: Gmail SMTP (port 587, STARTTLS, App Password)
- Uses `exercise_links.get_url()` for YouTube search links

### `src/exercise_links.py` — Exercise → YouTube Mapping
- Curated `_QUERIES` dict for known exercises
- Fallback: generic YouTube search for unknown names

### `src/setup_strava.py` — One-Time OAuth Helper
- Runs `python -m src.setup_strava`
- Opens browser, exchanges code for refresh_token
- Outputs token for `.env`

## Data Flow Summary

```
cron (5am Mon/Fri)
       │
       ▼
main.py ──▶ history.json (read)
       │
       ├─▶ strava.load_context() ──▶ Strava API
       │
       ├─▶ feedback.summary() ──▶ feedback.json (read)
       │
       ├─▶ templates.hip_bridge(session_index)
       │
       ├─▶ llm.generate() × N providers
       │       │
       │       ├─▶ LLM API (Nemotron / DeepSeek)
       │       │
       │       └─▶ exclusions.validate_workout()
       │               │
       │               ├─ pass → keep
       │               └─ fail → retry once → templates.generate()
       │
       ├─▶ email_send.render_html() + send()
       │
       └─▶ history.append() ──▶ history.json (write)

Web app (port 8080)
       │
       ├─▶ GET /  ──▶ reads history.json + feedback.json
       │
       ├─▶ POST /generate ──▶ main.py flow (with lock)
       │
       └─▶ POST /feedback ──▶ feedback.append() ──▶ feedback.json (write)
```

## Safety Invariant

> **No exercise reaches the athlete without passing `exclusions.validate_workout()`.**

- LLM proposals: validated, one retry, then template fallback
- Template exercises: pre-vetted, guaranteed safe
- Guardrail runs on *exercise name* (substring/regex match) — false positives are acceptable; false negatives are not

## Configuration

All via `.env` (see `.env.example`):
- API keys: `NVIDIA_API_KEY`, `DEEPSEEK_API_KEY`
- Gmail: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `EMAIL_TO`
- Strava: `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`, `STRAVA_REFRESH_TOKEN`
- Behavior: `DELOAD_EVERY`, `TZ`, `WEB_URL`, `FORCE_DAY`
- Paths: `HISTORY_PATH`, `FEEDBACK_PATH` (default to `/data/...` in Docker)