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
│  2. consistency.assess() → on_track / rusty / off_wagon         │
│  3. Decide deload (every 5th session; suppressed in re-entry)   │
│  4. Gather context:                                             │
│     • Recent history (last 4 sessions)                          │
│     • Multi-week load analysis (exercise freq, avg RPE, focus)  │
│     • Garmin 3-week pattern analysis + 7-day summary + yesterday│
│     • Wellness recovery: sleep, stress, body battery, HRV       │
│     • Recent athlete feedback (last 6 entries)                  │
│     • Mandatory hip-bridge variant (rotates SL → weighted → BW) │
│     • Consistency state (layoff gap, 28-day count, riding)      │
│  5. Call Nemotron LLM with full context                         │
│     a. Validate against exclusions.py                           │
│     b. One retry on failure                                     │
│     c. Fallback to template (reentry=) if still unsafe          │
│     d. Backfill required content (compound + both core patterns)│
│  6. Email: comeback banner + trend read + recovery + graph      │
│  7. Append session to history.json (incl. consistency state)    │
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
- Entry point, determines day; runs `consistency.assess()` first and sets `reentry = mode != "on_track"`
- Deload is suppressed while in re-entry (a comeback is already light)
- Gathers all context (history, garmin, feedback, hip bridge, consistency state)
- Calls each provider via `llm.generate()`
- Validates with `exclusions.validate_workout()`
- `_ensure_hip_bridge()` then `_ensure_required_content()` backfill the mandated compound lead-off, lower-core and anti-rotation movements from the vetted template pools
- Sends email via `email_send.send()`
- Appends to history (session dict carries `consistency`)

### `src/llm.py` — LLM Layer
- `PROVIDERS` registry: **Nemotron only** (OpenAI-compatible endpoint)
- Active provider = Nemotron when `NVIDIA_API_KEY` is set in env
- `SESSION_MINUTES = {"off_wagon": 35, "rusty": 45}` — session target by consistency mode, else `profile.ATHLETE['session_minutes']`
- `_build_user_prompt()`: injects athlete profile, constraints, context, and the CONSISTENCY block from `consistency.prompt_section()`
- REQUIRED CONTENT block demands a loaded compound lead-off, the mandated hip bridge (harder version when the rotation calls for unweighted), two distinct core patterns, week-to-week variety, and coach_notes that acknowledge the recent block
- `generate()`: calls provider, extracts JSON, returns workout dict

### `src/consistency.py` — Adherence & Re-entry
- Truth source is the tracker, not what was emailed: Garmin `strength_training` activities in `data/garmin.db` plus dates the athlete logged feedback on
- Riding activity is read separately (`ride_count_7d`, `ride_hours_7d`) — still riding but not lifting = aerobically fit, detrained for lifting
- `assess(now=None)` → `{mode, last_strength, days_since, strength_28d, ride_count_7d, ride_hours_7d}`
- Modes: `on_track`; `rusty` (10–20 days off, or ≤3 completed sessions in 28 days); `off_wagon` (21+ days off, or nothing on record)
- Thresholds: `RUSTY_DAYS=10`, `OFF_WAGON_DAYS=21`, `HABIT_SESSIONS_28D=3`
- `prompt_section(state)` → CONSISTENCY block with RE-ENTRY RULES / RAMP-BACK RULES for the prompt; `headline(state)` → one-line email banner (`""` when on track)
- No new env vars: reads `GARMIN_DB_PATH` and the feedback log

### `src/exclusions.py` — Hard Safety Guardrail
- Regex patterns for dangerous movements (posterior labrum repair precautions)
- `check(exercise_name)` → list of violation reasons
- `validate_workout(workout)` → (ok, violations)
- `PROMPT_CONSTRAINTS` injected into LLM prompt to reduce rejections

### `src/templates.py` — Deterministic Fallback
- Pre-vetted exercise pools (all clear exclusions): `LOWER_POWER`, `UPPER_PULL`, `HIP_BRIDGES`, `LOWER_CORE`, `ROTATIONAL_CORE` (anti-rotation / anti-lateral-flexion), `FINISHERS` (cycling-specific), `PLAY` (comeback/fun)
- `generate(day, deload, seed, session_index=0, reentry=False)` → safe workout; the Main block is always led by a loaded compound (`_pick_main`)
- `reentry=True`: 2 main lifts instead of 3, one set fewer, RPE capped at 7, loads annotated "go light", a `PLAY` item instead of a `FINISHERS` item, and comeback coach_notes
- Guarantees every session: compound lead-off, rotating hip bridge, a lower-core movement, and an anti-rotation movement in the finisher block
- Classifier helpers reused by `main.py` to audit LLM proposals: `is_compound`, `is_lower_core`, `is_rotational_core`, `pick_compound`, `pick_lower_core`, `pick_rotational_core`

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
- `render_html(session)`: **amber comeback banner** (from `consistency.headline(session["consistency"])`, shown only when not on track), then the **coach's trend read (LLM narrative), then recovery (Garmin) box, then the 3-week volume graph** (effort-colored table bars + trend lines; text-box fallback for legacy sessions), then side-by-side variant tables with exercise links
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
       ├─▶ consistency.assess() ──▶ garmin.db (strength + rides) + feedback.json
       │       └─▶ mode → prompt_section() (prompt), reentry flag, email banner
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
