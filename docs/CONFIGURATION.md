# Configuration Reference

## Environment Variables (`.env`)

All configuration lives in `.env` at the project root. Copy `.env.example` to `.env` and fill in.

### Required

| Variable | Example | Description |
|----------|---------|-------------|
| `NVIDIA_API_KEY` | `nvapi-abc123...` | NVIDIA Nemotron API key from build.nvidia.com. At least one LLM key required. |
| `GMAIL_ADDRESS` | `you@gmail.com` | Sender Gmail address. |
| `GMAIL_APP_PASSWORD` | `abcd efgh ijkl mnop` | 16-char App Password (spaces ignored). Generate at myaccount.google.com/apppasswords (requires 2FA). |
| `TZ` | `America/Denver` | IANA timezone. **Critical** — cron uses this for 5am local timing. |

### Highly Recommended

| Variable | Example | Description |
|----------|---------|-------------|
| `WEB_URL` | `http://orangepi.local:8080` | Public URL of feedback web app. Included in workout emails as "Log Feedback" link. |
| `GARMIN_EMAIL` | `you@example.com` | Optional — prefills the one-time Garmin login (`python -m src.setup_garmin`). |
| `GARMIN_TOKENS_PATH` | `/data/garmin_tokens` | Where Garmin OAuth tokens are saved (mounted volume in Docker). Tokens last ~1 year; your password is never stored. |
| `GARMIN_DB_PATH` | `/data/garmin.db` | Path to Garmin SQLite database (mounted volume in Docker). |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `EMAIL_TO` | `GMAIL_ADDRESS` | Recipient email. Useful if sender ≠ recipient. |
| `DELOAD_EVERY` | `5` | Deload every N sessions (counted from last deload). |
| `FORCE_DAY` | (empty) | Force `monday` or `friday` for manual test runs. Leave blank in production. |
| `HISTORY_PATH` | `/data/history.json` | Path to history file (mounted volume in Docker). |
| `FEEDBACK_PATH` | `/data/feedback.json` | Path to feedback file (mounted volume in Docker). |
| `WEB_PORT` | `8080` | Port the Flask app listens on inside container. |
| `WEB_HOST_PORT` | `8080` | Host port mapped to container port 8080 (docker-compose.yml). |
| `NVIDIA_BASE_URL` | `https://integrate.api.nvidia.com/v1` | Override Nemotron endpoint. |
| `NVIDIA_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b` | Override Nemotron model. |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | Override DeepSeek endpoint. |
| `DEEPSEEK_MODEL` | `deepseek-v4-pro` | Override DeepSeek model. |

## Provider Configuration (`src/llm.py`)

Providers are defined in the `PROVIDERS` list. Each entry:

```python
{
    "name": "Nemotron",           # Display name in email
    "key_env": "NVIDIA_API_KEY",  # Env var for API key
    "base_url": "...",            # OpenAI-compatible base URL
    "model": "...",               # Model identifier
}
```

A provider is **active** only when its `key_env` is set and non-empty. Drop a key to disable that model cleanly.

Current default:
- **Nemotron**: NVIDIA's Nemotron 3 Ultra (via build.nvidia.com)

Uses OpenAI-compatible `/chat/completions` endpoint.

## Athlete Profile (`src/profile.py`)

Single source of truth. Edit here to retune the athlete.

### `ATHLETE`
```python
{
    "discipline": "gravel cycling + downhill MTB racing",
    "training_role": "cyclist who lifts for shoulder health and on-bike power",
    "experience": "advanced lifter",
    "session_minutes": 55,  # hard ceiling ~60
}
```

### `SHOULDER`
```python
{
    "side": "left",
    "history": "anterior labrum repair 5y ago, 3 recurrent anterior dislocations from crashes",
    "status": "light overhead cleared, progressing load gradually",
    "always_include_rehab": True,
}
```
Injected into every LLM prompt and used by exclusions guardrail.

### `EQUIPMENT`
List of available equipment. Injected into prompts so LLM/templates pick valid exercises.

```python
[
    "olympic barbell + full plate set",
    "45lb kettlebell",
    "70lb kettlebell",
    "light dumbbells / fixed free weights (~10lb and up)",
    "BOSU ball",
    "stability / yoga ball",
    "pull-up bar",
    "TRX straps",
    "plyo / jump box",
    "elastic resistance bands",
]
```
**Note**: No bench available — hip thrusts and bench press variations are avoided.

### `SCHEDULE`
Day → focus mapping. Both days always open with shoulder rehab block.

```python
{
    "monday": "lower body power + posterior chain (core woven in)",
    "friday": "upper body pulling + scapular strength + light overhead progression",
}
```

### `FINISHER_THEMES`
Cycling-relevant finisher categories the generator can draw from.

```python
[
    "hip hinge",
    "single-leg stability",
    "loaded carry",
    "anti-rotation core",
]
```

## Shoulder Exclusions (`src/exclusions.py`)

Hard guardrail patterns. **Edit with PT approval only.**

Each entry: `(human_reason, [regex_patterns])`. Patterns matched case-insensitively against exercise name.

| Category | Patterns | Rationale |
|----------|----------|-----------|
| Horizontal abduction / flys | `\bfly`, `\bflye`, `lateral raise`, `reverse pec`, `pec deck`, `horizontal abduction` | Direct anterior strain |
| Behind-the-neck | `behind[\s-]*the[\s-]*neck`, `\bbtn\b` | Forces ER at abduction (cocking position) |
| Dips | `\bdip\b`, `\bdips\b` | Heavy anterior loading at end range |
| Upright rows | `upright row` | Impingement risk |
| Kipping/ballistic pull-ups | `kipping`, `butterfly pull`, `ballistic pull` | Uncontrolled end-range ER strain |
| Wide-grip bench | `wide[\s-]*grip bench`, `wide[\s-]*grip press` | Anterior translation at end range |
| Cocking position cues | `cocking position`, `abduction.*external rotation`, `external rotation.*abduction` | Abduction + ER under load |

### `PROMPT_CONSTRAINTS`
Plain-text version injected into every LLM prompt so models avoid these up front:

```
HARD SHOULDER RULES (left shoulder, anterior labrum repair, recurrent dislocations):
- NO flys, lateral raises, reverse-pec, or any loaded horizontal abduction.
- NO behind-the-neck pressing or pulldowns.
- NO dips. NO upright rows. NO kipping/ballistic pull-ups.
- NO wide-grip or deep end-range barbell bench (limit ROM, neutral/close grip only).
- AVOID loading the abduction + external-rotation ("cocking") position.
- Overhead pressing is ALLOWED but must start light (band/TRX/landmine/KB) and progress slowly.
- ALWAYS open with a shoulder rehab block: band external rotation, scapular control, controlled TRX/row patterning.
```

## Template Exercise Pools (`src/templates.py`)

All exercises pre-vetted against exclusions. Pools:

- `REHAB_BLOCK` — Shoulder rehab (band ER, scapular work, face pulls)
- `LOWER_POWER` — Lower body power (squats, deadlifts, jumps, KB swings)
- `UPPER_PULL` — Upper pulling (chin-ups, rows, landmine press)
- `HIP_BRIDGES` — Rotating mandatory: single-leg → weighted → bodyweight
- `LOWER_CORE` — Lower-core emphasis (leg raises, dead bugs, reverse crunch)
- `FINISHERS` — General core, carries, cycling-specific finishers

### Guaranteed Every Session
1. **Shoulder rehab block** (from `REHAB_BLOCK`)
2. **Mandatory hip bridge** (rotating variant from `HIP_BRIDGES`)
3. **Dedicated lower-core movement** (from `LOWER_CORE`)

## Garmin Training Load, Pattern Analysis & Recovery (`src/garmin.py`)

The system fetches 21 days of Garmin Connect activities plus 7 days of daily wellness data, persists both to a SQLite database (`data/garmin.db`), and builds a 3-week pattern analysis and a recovery snapshot that appear at the top of every workout email.

Authentication is a one-time interactive login (`python -m src.setup_garmin` — MFA supported); scheduled runs resume from OAuth tokens saved to `GARMIN_TOKENS_PATH`. No client ID/secret or app registration needed.

### Database Schema

Table `activities` (keyed by Garmin activity ID):
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Auto-increment |
| `garmin_id` | INTEGER UNIQUE NOT NULL | Garmin activity ID |
| `name` | TEXT | Activity name |
| `sport_type` | TEXT | Garmin typeKey, e.g. "cycling", "gravel_cycling", "strength_training" |
| `start_date` | TEXT | ISO 8601 UTC timestamp |
| `moving_time` | INTEGER | Seconds |
| `distance` | REAL | Meters |
| `total_elevation_gain` | REAL | Meters |
| `aerobic_te` | REAL | Garmin aerobic Training Effect (0.0–5.0) |
| `training_load` | REAL | Garmin activity training load |
| `avg_hr` | REAL | Average heart rate |
| `raw_json` | TEXT | Full activity JSON for future use |
| `created_at` | TEXT | Auto timestamp |

Index on `start_date` for fast time-range queries.

Table `wellness` (one row per local calendar date; upserts use `COALESCE`, so a later sparse sync never erases earlier data):
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Auto-increment |
| `date` | TEXT UNIQUE NOT NULL | Local calendar date |
| `sleep_seconds` | INTEGER | Sleep duration in seconds |
| `sleep_score` | REAL | Garmin sleep score (0–100) |
| `sleep_quality` | TEXT | Garmin qualifier key (e.g. "GOOD") |
| `avg_stress` | REAL | Average stress (0–100) |
| `max_stress` | REAL | Max stress |
| `resting_hr` | REAL | Resting heart rate |
| `body_battery_high` | REAL | Body battery daily high |
| `body_battery_low` | REAL | Body battery daily low |
| `hrv_last_night` | REAL | Last-night average HRV (ms) |
| `hrv_status` | TEXT | HRV status (e.g. "BALANCED") |
| `steps` | INTEGER | Total daily steps |
| `created_at` | TEXT | Auto timestamp |

Garmin's 0/-1 "no data" sentinels are collapsed to NULL before storage.

### Effort Classification

Activities are classified by Garmin aerobic Training Effect (0.0–5.0):

| Effort | Threshold |
|--------|-----------|
| `very hard` | TE ≥ 4.0 |
| `hard` | TE ≥ 3.0 |
| `moderate` | TE ≥ 2.0 |
| `easy` | TE < 2.0 |

When TE is absent (e.g. manual entries), a moving-time heuristic applies: ≥ 3h very hard, ≥ 2h hard, ≥ 1h moderate, else easy.

### Pattern Analysis Output

The `_analyze_3week_pattern()` function produces (buckets are trailing 7-day
blocks anchored to today, not calendar weeks — calendar weeks would split the
21-day window into four partial buckets):

```
3-WEEK TRAINING PATTERN ANALYSIS:
  15-21d (1–7 Jan): 4 activities, 8.5h, 250km, 3200m elev
    Effort: 1E 2M 1H 0VH
    Days: Mon:1, Wed:1, Sat:1, Sun:1
  8-14d (8–14 Jan): 3 activities, 7.3h, 210km, 2800m elev (-1.2h ↓)
    Effort: 2E 1M 0H 0VH
    Days: Tue:1, Fri:1, Sun:1
  last 7d (15–21 Jan): 5 activities, 9.8h, 300km, 3500m elev (+2.5h ↑)
    Effort: 1E 3M 1H 0VH
    Days: Mon:1, Wed:1, Thu:1, Sat:1, Sun:1
  → Trend: Volume increasing (+1.3h over 3 weeks)
  → Weekend: 5.2h vs Weekday: 4.6h
```

This text is injected into the LLM prompt via `garmin.load_context()` → `pattern_analysis`. The email instead renders the same data (`pattern_weeks` + `pattern_trend`) as an effort-colored weekly volume graph with the `→ Trend:`/`→ Weekend:` lines kept beneath it.

### Recovery Snapshot

`_recovery_summary()` builds a snapshot from the stored wellness rows — most recent value per metric against 7-day averages: last-night sleep (hours + score + quality), stress for the most recent full day, body battery high/low, resting HR, HRV, and 7-day average daily steps.

It reaches the workout via `garmin.load_context()` → `recovery`: injected into the LLM prompt as a "CURRENT RECOVERY STATE" section (telling the model to trim volume on poor sleep/high stress/low body battery/unbalanced HRV) and rendered in the email's "RECOVERY (GARMIN)" box above the pattern graph. Empty when no wellness data is stored.

## Docker Compose Overrides

Create `docker-compose.override.yml` for local tweaks (not committed):

```yaml
services:
  coach:
    environment:
      - FORCE_DAY=monday  # Test Monday workout on any day
  web:
    ports:
      - "8081:8080"       # Avoid port conflict on host
```

## Crontab (`crontab`)

```
0 5 * * 1 cd /app && /usr/local/bin/python -m src.main monday >> /proc/1/fd/1 2>&1
0 5 * * 5 cd /app && /usr/local/bin/python -m src.main friday >> /proc/1/fd/1 2>&1
```

- Runs at 5:00 **container local time** (set by `TZ` via entrypoint.sh)
- Output goes to container stdout (view with `docker compose logs coach`)
- To change schedule, edit crontab and rebuild: `docker compose up -d --build`

## Entrypoint (`entrypoint.sh`)

Handles three modes:

```bash
# Default: start cron scheduler
docker compose up -d coach

# Feedback web app
docker compose up -d web
# or: docker compose run --rm coach web

# Manual test run (bypasses cron)
docker compose run --rm coach python -m src.main monday
docker compose run --rm coach python -m src.main friday
```

Applies `TZ` to container so cron fires in correct local time.