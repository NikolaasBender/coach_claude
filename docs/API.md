# Module Reference

## `src/main.py` — Orchestrator

### `target_day() -> str`
Determines target day from: CLI arg (`monday`/`friday`), `FORCE_DAY` env, or system clock (defaults to Monday if not Mon/Fri).

### `build_variant(provider, day, deload, ctx) -> dict`
Generates one provider's proposal:
1. Calls `llm.generate()` with full context
2. Validates via `exclusions.validate_workout()`
3. One retry on failure (asks LLM to swap bad exercises)
4. Falls back to `templates.generate()` if still unsafe
4. Ensures mandatory hip bridge present via `_ensure_hip_bridge()`

Returns workout dict with `model`, `workout`, `focus`, `coach_notes`.

### `main() -> None`
Full orchestration:
1. `day = target_day()`
2. `deload = (history.weeks_since_deload() >= DELOAD_EVERY)`
3. `strava_ctx = strava.load_context()` → includes `pattern_analysis`
4. `ctx = { history, load_summary, strava, feedback, hip_bridge }`
5. Call Nemotron via `build_variant()` (single provider)
6. `email_send.send(session)` with `pattern_analysis` at top
7. `history.append(session)`

### `PROVIDERS: list[dict]`
Registry of provider configs. Each:
```python
{
    "name": "Nemotron",
    "key_env": "NVIDIA_API_KEY",
    "base_url": "https://integrate.api.nvidia.com/v1",
    "model": "nvidia/nemotron-3-ultra-550b-a55b",
}
```

### `active_providers() -> list[dict]`
Returns providers with non-empty API key in environment.

### `_build_user_prompt(day, deload, history, strava, load_summary, feedback, hip_bridge) -> str`
Builds the full user prompt injected into every LLM call. Includes:
- Athlete profile + shoulder constraints
- Equipment list
- Day focus
- Multi-week load summary
- Strava 7-day summary + yesterday detail
- Recent athlete feedback
- Mandatory hip bridge variant for today
- `PROMPT_CONSTRAINTS` from exclusions

### `generate(provider, day, deload, history, strava, load_summary, feedback, hip_bridge, extra_note=None) -> dict`
Calls one provider's OpenAI-compatible endpoint:
1. Creates `OpenAI` client with provider's `base_url` + API key
2. Sends `SYSTEM` + user prompt
3. Extracts JSON from response via `_extract_json()`
4. Returns parsed workout dict

**Raises** on API error or JSON parse failure.

### `_extract_json(text: str) -> dict`
Pulls first balanced JSON object from model output (handles markdown fences, extra text).

---

## `src/exclusions.py` — Safety Guardrail

### `EXCLUSIONS: list[tuple[str, list[str]]]`
List of `(reason, [patterns])`. Patterns are regex, matched case-insensitive against exercise name.

### `check(exercise_name: str) -> list[str]`
Returns list of violation reasons for a single exercise name. Empty = safe.

### `validate_workout(workout: dict) -> tuple[bool, list[str]]`
Scans all exercises in `workout["blocks"][*]["exercises"][*]["name"]`.
Returns `(ok, violations)` where `violations` = list of `"{exercise_name}: {reason}"`.

### `PROMPT_CONSTRAINTS: str`
Plain-text constraints injected into LLM prompt (see SAFETY.md).

---

## `src/templates.py` — Deterministic Fallback

### `REHAB_BLOCK: list[dict]`
Shoulder rehab exercises (all pre-vetted).

### `LOWER_POWER: list[dict]`
Lower body power pool.

### `UPPER_PULL: list[dict]`
Upper pulling pool.

### `HIP_BRIDGES: list[dict]`
Rotating mandatory hip bridges (3 variants, cycle SL → weighted → BW).

### `LOWER_CORE: list[dict]`
Lower-core emphasis pool.

### `FINISHERS: list[dict]`
General core / cycling finishers pool.

### `hip_bridge(session_index: int) -> dict`
Returns mandatory hip bridge variant for this session index (cycles every 3).

### `generate(day: str, deload: bool, seed: str, session_index: int = 0) -> dict`
Builds a complete safe workout:
- Seeded RNG from `seed` (date string) for reproducibility
- `day` = "monday" or "friday" → picks focus
- `deload` = reduces volume (fewer sets/exercises)
- Guarantees: rehab block, hip bridge, lower-core movement
- Returns workout dict with `blocks`, `focus`, `coach_notes`

### `SCHEDULE_FOCUS(is_lower: bool) -> str`
Returns focus string for day type.

---

## `src/history.py` — Persistent Session Log

### `HISTORY_PATH: str`
From `HISTORY_PATH` env or default `data/history.json`.

### `load() -> list[dict]`
Returns full history (oldest first). Empty list if file missing/corrupt.

### `recent(n=4) -> list[dict]`
Last `n` entries (most recent last).

### `count() -> int`
Total sessions recorded.

### `append(entry: dict) -> None`
Appends entry, stamps ISO date if missing, persists to JSON.

### `weeks_since_deload() -> int`
Counts sessions since last `deload: true` entry. Used to gate next deload.

### `load_summary(n_sessions=8) -> str`
Human-readable multi-week strength load summary for LLM prompt.
Includes: session count, exercise frequency, avg RPE, recent focus distribution, deload cadence.

### `_workouts(entry) -> list[dict]`
Normalizes entry to list of workout dicts (handles both single-workout and multi-variant entries).

### `_representative(entry) -> dict`
First workout dict from entry.

---

## `src/feedback.py` — Athlete Feedback Log

### `FEEDBACK_PATH: str`
From `FEEDBACK_PATH` env or default `data/feedback.json`.

### `load() -> list[dict]`
Returns full feedback (oldest first).

### `append(entry: dict) -> None`
Appends entry, stamps UTC `logged_at`, persists.

### `recent(n=6) -> list[dict]`
Last `n` entries.

### `summary(n=6) -> str`
Human-readable digest for LLM prompt:
```
RECENT ATHLETE FEEDBACK (adapt to this...):
  2025-01-15 Monday: 4/5, preferred Nemotron — "felt solid"
  2025-01-10 Friday: 3/5, preferred DeepSeek — "shoulder tweak on landmine"
```
Returns "No athlete feedback logged yet." if empty.

**Feedback entry schema:**
```json
{
  "session_date": "2025-01-15",
  "day": "monday",
  "rating": 4,
  "preferred_model": "Nemotron",
  "notes": "felt solid",
  "logged_at": "2025-01-15T18:30:00+00:00"
}
```

---

## `src/strava.py` — Strava Training Load Context & 3-Week Pattern Analysis

### `load_context(session_date=None) -> dict`
Returns `{"summary": str, "yesterday_note": str | None, "pattern_analysis": str}` for LLM prompt and email.

**Flow:**
1. `_refresh_access_token()` — exchanges `STRAVA_REFRESH_TOKEN` for fresh access token
2. `_fetch_3weeks(access_token)` — paginated fetch of last 21 days of activities
3. `_upsert_activities(activities)` — idempotent upsert to SQLite (`data/strava.db`) by Strava activity ID
4. Filter last 7 days for summary/yesterday
5. `_summarize(activities_7d)` — builds human-readable 7-day summary
6. `_yesterday_note(activities_7d, session_date)` — specific note on day-before ride
7. `_analyze_3week_pattern()` — builds 3-week pattern analysis from stored DB data

### `_fetch_3weeks(access_token) -> list[dict]`
Fetches activities for last 21 days with pagination (100 per page). Returns full activity list.

### `_upsert_activities(activities: list[dict]) -> int`
Upserts activities by `strava_id` (INSERT ... ON CONFLICT). Returns count of new/updated rows.

### `_analyze_3week_pattern() -> str`
Analyzes last 3 weeks of stored activities and returns pattern summary including:
- Weekly breakdown: rides, hours, distance, elevation, effort distribution (E/M/H/VH), day-of-week pattern
- Trend detection: volume increasing/decreasing/stable over 3 weeks
- Weekend vs weekday split

### `_classify_effort(activity) -> str`
Classifies ride by suffer score:
- `very hard` > 150
- `hard` > 100
- `moderate` > 50
- `easy` ≤ 50

### `_summarize(activities) -> str`
Aggregates: ride count, total suffer score, avg suffer, hardest ride, distribution.

### Database Schema
Table `activities` (keyed by Strava activity ID):
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PRIMARY KEY | Auto-increment |
| `strava_id` | INTEGER UNIQUE NOT NULL | Strava activity ID |
| `name` | TEXT | Activity name |
| `sport_type` | TEXT | e.g., "Ride", "GravelRide" |
| `start_date` | TEXT | ISO 8601 timestamp |
| `moving_time` | INTEGER | Seconds |
| `distance` | REAL | Meters |
| `total_elevation_gain` | REAL | Meters |
| `suffer_score` | INTEGER | Strava relative effort |
| `raw_json` | TEXT | Full activity JSON for future use |
| `created_at` | TEXT | Auto timestamp |

Index on `start_date` for fast time-range queries.
---

## `src/profile.py` — Athlete Profile

### `ATHLETE: dict`
Static athlete metadata (discipline, role, experience, session_minutes).

### `SHOULDER: dict`
Shoulder specifics (side, history, status, always_include_rehab).

### `EQUIPMENT_NOTES: str`
Human-readable equipment constraints (no bench).

### `EQUIPMENT: list[str]`
Available equipment for prompt injection.

### `SCHEDULE: dict[str, str]`
Day → focus mapping.

### `FINISHER_THEMES: list[str]`
Cycling-relevant finisher categories.

---

## `src/web.py` — Feedback Web App (Flask)

### `app = Flask(__name__)`
Flask application.

### `_generate_lock / _generating / _generate_error`
Thread safety for manual generation (single-user home app).

### Routes

#### `GET /` → `index()`
Renders session history with feedback forms. Reads `history.json` + `feedback.json`, merges feedback by `session_date`.

#### `POST /generate` → `generate()`
Triggers workout generation via `main.main()` in background thread (with lock). Redirects to `/`.

#### `POST /feedback` → `submit_feedback()`
Accepts form: `session_date`, `day`, `rating` (1-5), `preferred_model`, `notes`. Appends to `feedback.json`. Redirects to `/`.

#### `GET /healthz` → `healthz()`
Returns `{"ok": True}`.

### Template Rendering (Jinja-free)
- `_render_card(entry, fb_for_session)` — session card with feedback form
- `_render_workout_detail(model_label, workout)` — expandable workout blocks
- `_render_latest(entry)` — hero card for most recent session
- `_render_exercise_rows(exercises)` — exercise table rows with YouTube links

---

## `src/email_send.py` — Email Rendering & Delivery

### `_variants(session) -> list[tuple[str, dict]]`
Normalizes session to `[(model_label, workout_dict), ...]`.

### `_table(workout: dict) -> str`
Renders workout blocks as HTML tables with exercise links.

### `render_html(session: dict) -> str`
Full HTML email with:
- **3-week pattern analysis at top** (from `session.pattern_analysis`)
- Day + deload banner
- Variant table (single Nemotron proposal)
- Coach notes per variant
- "Log Feedback" CTA button (links to `WEB_URL`)
- Comparison hint (only when multiple variants)

### `send(session: dict) -> None`
Sends via Gmail SMTP (port 587, STARTTLS):
- From: `GMAIL_ADDRESS`
- To: `EMAIL_TO` or `GMAIL_ADDRESS`
- Subject: `Strength — {Day} {date} (Nemotron)`

---

## `src/exercise_links.py` — Exercise → YouTube

### `_QUERIES: dict[str, str]`
Curated exercise name → YouTube search query mapping (optimized for form/tutorial results).

### `get_url(exercise_name: str) -> str`
Returns YouTube URL:
1. Exact match in `_QUERIES` (case-insensitive)
2. Fallback: generic YouTube search for exercise name

---

## `src/setup_strava.py` — One-Time OAuth

### `main() -> None`
Interactive CLI:
1. Reads `STRAVA_CLIENT_ID` + `STRAVA_CLIENT_SECRET` from env
2. Opens browser to Strava authorization URL
3. Prompts for redirect URL with `code=`
4. Exchanges code for `refresh_token` + `access_token`
5. Prints `STRAVA_REFRESH_TOKEN=...` for `.env`

**Usage:** `python -m src.setup_strava`

---

## Data Schemas

### Session Entry (`history.json`)
```json
{
  "date": "2025-01-15",
  "day": "monday",
  "deload": false,
  "variants": [
    {
      "model": "Nemotron",
      "workout": { "blocks": [...], "focus": "...", "coach_notes": "..." },
      "source": "llm"
    }
  ],
  "pattern_analysis": "3-WEEK TRAINING PATTERN ANALYSIS:\n  Week 2025-W01: 4 rides, 8.5h, 250km, 3200m elev (+1.2h ↑)\n    Effort: 1E 2M 1H 0VH\n    Days: Mon:1, Wed:1, Sat:1, Sun:1\n  ...",
  "strava_summary": "...",
  "feedback_summary": "..."
}
```

### Workout Dict
```json
{
  "blocks": [
    {
      "name": "Shoulder Rehab",
      "exercises": [
        { "name": "band external rotation (elbow at side)", "sets": 2, "reps": "15/side", "rpe": 5 }
      ]
    },
    {
      "name": "Main",
      "exercises": [
        { "name": "single-leg glute bridge", "sets": 3, "reps": "10/leg", "rpe": 7 },
        { "name": "goblet squat", "sets": 3, "reps": "8", "rpe": 8 }
      ]
    }
  ],
  "focus": "lower body power + posterior chain",
  "coach_notes": "Rotated away from KB swings used last Monday..."
}
```

### Feedback Entry (`feedback.json`)
```json
{
  "session_date": "2025-01-15",
  "day": "monday",
  "rating": 4,
  "preferred_model": "Nemotron",
  "notes": "felt solid, shoulder good",
  "logged_at": "2025-01-15T18:30:00+00:00"
}
```

---

## Utility Functions (Cross-Module)

### `src/main.py`
- `_ensure_hip_bridge(workout, bridge)` — inserts mandatory hip bridge if missing

### `src/web.py`
- `_session_models(entry)` — extracts model labels from entry
- `_session_focus(entry)` — extracts focus string
- `_main_exercises(workout)` — flattens exercises from main block
- `_session_workouts(entry)` — normalizes to `[(label, workout), ...]`
- `_feedback_index()` — maps `session_date -> [feedback_entries]`
- `_rating_stars(n)` — returns ★/☆ string
- `_esc(s)` — HTML escape

### `src/templates.py`
- `_pick(pool, n, rng)` — samples `n` unique exercises from pool