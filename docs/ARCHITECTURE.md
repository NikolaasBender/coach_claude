# Architecture Overview

## System Purpose

`coach_claude` automatically generates a strength workout twice a week (Monday & Friday, 5am local) and emails it to a gravel/MTB cyclist with a repaired left shoulder. **NVIDIA Nemotron** designs each session from athlete profile, multi-week training load, Garmin Connect data (activities with a 3-week pattern analysis, plus daily wellness for a recovery snapshot), and recent athlete feedback.

**Safety is enforced in code, not by the model.** Every LLM proposal is validated against a hard exclusion guardrail (`exclusions.py`) with one corrective retry; if still unsafe, it falls back to a hand-vetted template. The model never has the final say on shoulder safety.

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        ENTRYPOINT (cron)                        │
│  Mon/Fri 05:00 local → python -m src.main [monday|friday]       │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     main.py (orchestrator)                      │
│  1. Determine target day (arg / env / system clock)             │
│  2. Decide deload (every 5th session since last deload)         │
│  3. Gather context:                                             │
│     • Recent history (last 4 sessions)                          │
│     • Multi-week load analysis (exercise freq, avg RPE, focus)  │
│     • Garmin 3-week pattern analysis + 7-day summary + yesterday│
│     • Wellness recovery: sleep, stress, body battery, HRV       │
│     • Recent athlete feedback (last 6 entries)                  │
│     • Mandatory hip-bridge variant (rotates SL → weighted → BW) │
│  4. Call Nemotron LLM with full context                         │
│     a. Validate against exclusions.py                           │
│     b. One retry on failure                                     │
│     c. Fallback to template if still unsafe                     │
│  5. Email: trend read + recovery + volume graph at top          │
│  6. Append session to history.json                              │
└───────────────────────────┬─────────────────────────────────────┘
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
┌─────────────────────────┐   ┌─────────────────────────┐
│     Feedback Web        │   │      Data Volume        │
│     (Flask, port 8080)  │   │  /data/history.json     │
│                         │   │  /data/feedback.json    │
│ • Lists recent sessions │   │  /data/garmin.db        │
│ • Logs rating + notes   │   │  /data/garmin_tokens/   │
│ • Feeds next prompt     │   └─────────────────────────┘
└───────────────────────────────────────────────────────┘

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
- Gathers all context (history, garmin, feedback, hip bridge)
- Calls each provider via `llm.generate()`
- Validates with `exclusions.validate_workout()`
- Sends email via `email_send.send()`
- Appends to history

### `src/llm.py` — LLM Layer
- `PROVIDERS` registry: **Nemotron only** (OpenAI-compatible endpoint)
- Active provider = Nemotron when `NVIDIA_API_KEY` is set in env
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

### `src/garmin.py` — Training Load Context, Pattern Analysis & Recovery
- Resumes saved OAuth tokens via `Garmin().login()` (one-time setup via `setup_garmin.py` — tokens last ~1 year, password never stored)
- **SQLite persistence** (`data/garmin.db`): two tables —
  - `activities` keyed by Garmin activity ID
  - `wellness` keyed by calendar date (COALESCE upserts, so a sparse later sync never erases earlier data)
- `_fetch_3weeks()`: 21-day activity fetch via `get_activities_by_date` (garminconnect lib paginates)
- `_fetch_wellness()`: per-day wellness for the last 7 days — sleep, stress, body battery, HRV, resting HR, steps
- `_pattern_data()` + `_analyze_3week_pattern()`: structured weekly rollups feeding both the prompt text and the email volume graph:
  - Weekly breakdown: activities, hours, distance, elevation, effort distribution (E/M/H/VH), day-of-week pattern
  - Trend detection: volume increasing/decreasing/stable over 3 weeks
  - Weekend vs weekday split
- `_recovery_summary()`: sleep/stress/body-battery/HRV snapshot vs 7-day averages
- `load_context(session_date)` → `{summary, yesterday_note, pattern_analysis, pattern_weeks, pattern_trend, recovery}` — each part degrades independently; a Garmin outage never blocks a workout
- Classifies efforts by Garmin aerobic Training Effect (0–5): easy/moderate/hard/very hard (moving-time fallback)

### `src/profile.py` — Athlete Profile (Single Source of Truth)
- `ATHLETE`: discipline, role, experience, session_minutes
- `SHOULDER`: side, history, status, always_include_rehab
- `EQUIPMENT`: list available to LLM/templates
- `SCHEDULE`: day → focus mapping
- `FINISHER_THEMES`: cycling-relevant finisher categories

### `src/web.py` — Feedback Web App (Flask)
### `src/email_send.py` — Email Rendering & Delivery
- `render_html(session)`: **coach's trend read (LLM narrative), then recovery (Garmin) box, then the 3-week volume graph** (effort-colored table bars + trend lines; text-box fallback for legacy sessions), then side-by-side variant tables with exercise links
- `send(session)`: Gmail SMTP (port 587, STARTTLS, App Password)
- Uses `exercise_links.get_url()` for YouTube search links
- Jinja-free: renders HTML via Python string templates
### `src/exercise_links.py` — Exercise → YouTube Mapping
- Curated `_QUERIES` dict for known exercises
- Fallback: generic YouTube search for unknown names

### `src/setup_garmin.py` — One-Time Garmin Login
- Runs `python -m src.setup_garmin`
- Interactive email + password + MFA prompt (`GARMIN_EMAIL` optionally prefills)
- Saves OAuth tokens to `GARMIN_TOKENS_PATH`; sanity-checks by fetching last-7-days activities

## Data Flow Summary

cron (5am Mon/Fri)
       │
       ▼
main.py ──▶ history.json (read)
       │
       ├─▶ garmin.load_context() ──▶ Garmin Connect (garminconnect lib)
       │       │
       │       ├─▶ _fetch_3weeks() (21 days) + _fetch_wellness() (7 days)
       │       │       → upsert to garmin.db (activities + wellness)
       │       ├─▶ _pattern_data() → pattern_weeks/pattern_trend (graph) + pattern_analysis (prompt text)
       │       └─▶ _recovery_summary() → recovery
       │
       ├─▶ feedback.summary() ──▶ feedback.json (read)
       │
       ├─▶ templates.hip_bridge(session_index)
       │
       ├─▶ llm.generate() (Nemotron)
       │       │
       │       ├─▶ LLM API
       │       │
       │       └─▶ exclusions.validate_workout()
       │               │
       │               ├─ pass → keep
       │               └─ fail → retry once → templates.generate()
       │
       ├─▶ email_send.render_html() + send() (trend read + recovery + pattern graph at top)
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
- API keys: `NVIDIA_API_KEY` (DeepSeek removed)
- Gmail: `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `EMAIL_TO`
- Garmin: `GARMIN_EMAIL` (optional, prefills one-time login)
- Garmin paths: `GARMIN_TOKENS_PATH` (default: `data/garmin_tokens`), `GARMIN_DB_PATH` (default: `data/garmin.db`)
- Behavior: `DELOAD_EVERY`, `TZ`, `WEB_URL`, `FORCE_DAY`
- Paths: `HISTORY_PATH`, `FEEDBACK_PATH` (default to `/data/...` in Docker)
