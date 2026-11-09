# Module Reference

## `src/main.py` — Orchestrator

### `target_day() -> str`
Determines target day from: CLI arg (`monday`/`friday`), `FORCE_DAY` env, or system clock (defaults to Monday if not Mon/Fri).

### `build_variant(provider, day, deload, ctx) -> dict`
Generates one provider's proposal:
1. Calls `llm.generate()` with full context (including `consistency=ctx["consistency"]`)
2. Validates via `exclusions.validate_workout()`
3. One retry on failure (asks LLM to swap bad exercises)
4. Ensures mandatory hip bridge present via `_ensure_hip_bridge()`, then backfills required content via `_ensure_required_content()`
5. Falls back to `templates.generate(..., reentry=ctx["consistency"]["mode"] != "on_track")` if still unsafe

Returns workout dict with `model`, `workout`, `focus`, `coach_notes`.

### `_find_block(workout, name) -> dict`
Returns the named block from `workout["blocks"]` (case-insensitive), creating and appending it with an empty `exercises` list if the model omitted it.

### `_ensure_required_content(workout, day, seed) -> None`
Backfills the non-negotiable content the prompt asks for, so a thin proposal never ships short. Runs after `_ensure_hip_bridge()`. Using `templates.is_compound` / `is_lower_core` / `is_rotational_core` over every exercise name in the workout:
- no loaded compound → `templates.pick_compound(day, seed)` inserted at the front of the `Main` block
- no lower-core movement → `templates.pick_lower_core(seed)` appended to `Main`
- no anti-rotation movement → `templates.pick_rotational_core(seed)` appended to `Cycling finisher`

Each backfill logs a `[content]` line to stderr. Everything added comes from the pre-vetted template pools, so the guardrail invariant holds.

### `main() -> None`
Full orchestration:
1. `day = target_day()`
2. `state = consistency.assess()`; `reentry = state["mode"] != "on_track"`
3. `deload = history.weeks_since_deload() >= (DELOAD_EVERY - 1) and not reentry` — a comeback is already light
4. `garmin_ctx = garmin.load_context()` → includes `pattern_analysis`, `pattern_weeks`/`pattern_trend`, `recovery`
5. `ctx = { recent, load_summary, feedback, garmin, bridge, session_index, consistency, shoulder_log }` — `shoulder_log = shoulder.summary(feedback.load())` (whole feedback history, not a recent window)
6. `trend = llm.trend_analysis(providers[0], ctx, day, deload)` — LLM trend read (best-effort, "" on failure)
7. Call Nemotron via `build_variant()` (single provider); with no providers configured, `templates.generate(..., reentry=reentry)` only
   - `shoulder.ensure_checks(v["workout"])` then runs on every variant (LLM or template) before final validation
8. `email_send.send(session)` with `consistency` banner + `trend_analysis` + `recovery` + pattern volume graph at top
9. `history.append(session)` — the session dict carries `"consistency": state`

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

### `TREND_SYSTEM: str`
System prompt for the trend read: 3-5 grounded plain-text lines plus a closing `Today: ...` line; interprets the data instead of repeating it.

### `trend_analysis(provider, ctx, day="", deload=False) -> str`
Writes the short "coach's trend read" narrative that opens the email:
1. Assembles available context: Garmin `pattern_analysis`, 7-day `summary`, `recovery`, strength `load_summary`, athlete `feedback`, today's day/deload
2. Calls the provider with `TREND_SYSTEM` (no JSON — plain text)
3. Strips a leaked `<think>...</think>` block if present

Best-effort: returns `""` on any failure or when no context exists, so the email always sends.

### `SESSION_MINUTES: dict[str, int]`
Session length by consistency mode: `{"off_wagon": 35, "rusty": 45}`. Any other mode falls back to `profile.ATHLETE["session_minutes"]` (55).

### `_build_user_prompt(day, deload, history, garmin=None, load_summary="", feedback="", hip_bridge=None, consistency=None, shoulder_log="") -> str`
Builds the full user prompt injected into every LLM call. Includes:
- Athlete profile + shoulder constraints
- Equipment list
- Day focus and session target in minutes (from `SESSION_MINUTES` for the consistency mode)
- CONSISTENCY block from `consistency.prompt_section()` — omitted when no state is passed
- Multi-week load summary
- Garmin 7-day training load summary + yesterday detail
- Current recovery state (sleep, stress, body battery, HRV) — omitted when empty
- Recent athlete feedback
- Left-shoulder log (`shoulder_log`, from `shoulder.summary()`) — omitted when empty
- Mandatory hip bridge variant for today
- `PROMPT_CONSTRAINTS` from exclusions
- **REQUIRED CONTENT EVERY SESSION**: a genuinely loaded compound lift leading the Main block (bodyweight plyos, band and TRX work do not count); the mandated hip bridge, made demanding when the rotation calls for the unweighted variant; TWO distinct core patterns — a lower-core / anti-extension movement in Main *and* an anti-rotation / anti-lateral-flexion movement in the Cycling finisher (the hip bridge satisfies neither); SINGLE-SIDED WORK — at least one single-arm upper-body movement and one single-leg movement, LEFT SIDE FIRST with the right matching the left's reps and load, notes starting "Left first, right matches." and naming the compensation to watch; deliberate week-to-week variety; coach_notes acknowledging the recent block and feedback

### `SYSTEM: str`
System prompt with the JSON schema. Besides `blocks`/`focus`/`coach_notes`, the schema includes `shoulder_checks: [{"exercise", "question", "kind": "scale"|"side"|"yesno"}]` — 2-3 post-session questions about the left shoulder, each tied to an exercise in this session by exact name; must not repeat the standing questions.

### `generate(provider, day, deload, history, garmin=None, load_summary="", feedback="", hip_bridge=None, consistency=None, shoulder_log="", extra_note=None) -> dict`
Calls one provider's OpenAI-compatible endpoint:
1. Creates `OpenAI` client with provider's `base_url` + API key
2. Sends `SYSTEM` + user prompt (built with the same context, including `consistency` and `shoulder_log`)
3. Extracts JSON from response via `_extract_json()`
4. Returns parsed workout dict

**Raises** on API error or JSON parse failure.

### `_extract_json(text: str) -> dict`
Pulls first balanced JSON object from model output (handles markdown fences, extra text).

---

## `src/exclusions.py` — Safety Guardrail

### `EXCLUSIONS: list[tuple[str, list[str]]]`
List of `(reason, [patterns])`. Patterns are regex, matched case-insensitive against exercise name. Includes "overhead ball slams / wall balls / overhead throws — ballistic end-range overhead load" (`\bslams?\b`, `wall[\s-]*balls?`, `overhead (throw|toss|pass)`).

### `check(exercise_name: str) -> list[str]`
Returns list of violation reasons for a single exercise name. Empty = safe.

### `validate_workout(workout: dict) -> tuple[bool, list[str]]`
Scans all exercises in `workout["blocks"][*]["exercises"][*]["name"]`.
Returns `(ok, violations)` where `violations` = list of `"{exercise_name}: {reason}"`.

### `PROMPT_CONSTRAINTS: str`
Plain-text constraints injected into LLM prompt (see SAFETY.md), incl. "Weighted-ball work stays at or below chest height: NO slams, wall balls, or overhead throws."

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
Lower-core / anti-extension pool (leg raises, hanging knee and straight-leg raises, dead bug, reverse crunch, stability-ball knee tuck and rollout, hollow-body hold, heel taps).

### `ROTATIONAL_CORE: list[dict]`
Anti-rotation / anti-lateral-flexion pool (Pallof press and hold, suitcase carry, side plank and side plank with top-leg raise, half-kneeling band chop, bird dog). One of these rides in the finisher block every session — the second core pattern, not a substitute for `LOWER_CORE`.

### `FINISHERS: list[dict]`
Cycling-specific finishers (single-leg RDL, BOSU balance reach, KB swing intervals, farmer carry).

### `PLAY: list[dict]`
Comeback/fun movements (KB flow complex, low box jump ladder, farmer carry medley, BOSU balance challenge, TRX row + goblet squat EMOM, KB swing EMOM). Used instead of `FINISHERS` on re-entry sessions.

### `is_compound(name: str) -> bool`
True for a loaded multi-joint lift (squat, deadlift/RDL, row, chin-up, lunge, step-up, swing, floor/landmine/overhead press, clean). Band, TRX, scapular, balance/BOSU, single-leg RDL and jump/hop names are excluded, so stability work never counts as the session's real lift.

### `is_lower_core(name: str) -> bool`
True for lower-ab / anti-extension work (leg raise, dead bug, reverse crunch, knee raise/tuck, heel tap, toe touch, rollout, hollow, V-up, sit-up, crunch).

### `is_rotational_core(name: str) -> bool`
True for anti-rotation / anti-lateral-flexion work (Pallof, anti-rotation/anti-lateral, suitcase, side plank, chop, bird dog, windmill, oblique).

### `pick_compound(day: str, seed: str) -> dict`
A vetted loaded compound from `LOWER_POWER` (monday) or `UPPER_PULL` (otherwise), chosen deterministically from `seed`.

### `pick_lower_core(seed: str) -> dict`
Deterministic pick from `LOWER_CORE`.

### `pick_rotational_core(seed: str) -> dict`
Deterministic pick from `ROTATIONAL_CORE`.

### `hip_bridge(session_index: int) -> dict`
Returns mandatory hip bridge variant for this session index (cycles every 3).

### `generate(day: str, deload: bool, seed: str, session_index: int = 0, reentry: bool = False) -> dict`
Builds a complete safe workout:
- Seeded RNG from `seed` (date string) for reproducibility
- `day` = "monday" or "friday" → picks focus and main pool
- Main block = 3 exercises (2 when `reentry`), always led by a loaded compound via `_pick_main()`, then the rotating hip bridge and a `LOWER_CORE` movement
- Finisher block = one `ROTATIONAL_CORE` movement plus one `FINISHERS` item (one `PLAY` item when `reentry`)
- `deload` = prefixes "DELOAD:" on main-block notes and drops RPE by 2 (floor 5)
- `reentry` = one set fewer (floor 2), RPE capped at 7, loads annotated "(go light — first sessions back)", and comeback coach_notes
- Guarantees: rehab block, compound lead-off, hip bridge, lower-core movement, anti-rotation movement
- Returns workout dict with `blocks`, `focus`, `coach_notes`

### `SCHEDULE_FOCUS(is_lower: bool) -> str`
Returns focus string for day type.

### `_left_first(exercises) -> None`
Prefixes "Left first, right matches." to the notes of unilateral template exercises (reps containing "/side", or names with single-arm/leg, suitcase, split squat, lunge, step-up, half-kneeling, skater). Applied to main + finisher.

---

## `src/shoulder.py` — Left-Shoulder Check-ins

Does not import `feedback.py` (feedback imports it); callers pass entries in.

### `KINDS = ("scale", "side", "yesno")` / `SIDE_OPTIONS` / `YESNO_OPTIONS`
Answer kinds. `scale` = int 0-10; `SIDE_OPTIONS = ("left much harder", "left a bit harder", "same", "left easier")`; `YESNO_OPTIONS = ("no", "yes")`.

### `STANDING_CHECKS: list[dict]`
Fixed `{key, kind, question}` asked after every session forever (code constants, not model output): `apprehension` (scale), `pain` (scale), `instability` (yesno — clunk/slip/dead-arm/catching), `left_vs_right` (side — single-arm work left vs right).

### `MIN_SESSION_CHECKS = 2` / `MAX_SESSION_CHECKS = 3`
Bounds on session-specific checks.

### `ensure_checks(workout) -> dict`
Validates the model's `shoulder_checks` (dict, kind in `KINDS`, non-empty question truncated to 200 chars, exercise must match one in the session, one check per exercise, max `MAX_SESSION_CHECKS`) and backfills to `MIN_SESSION_CHECKS` with deterministic defaults from exercises that load the left shoulder (leg-dominant work excluded; non-rehab blocks first). Unilateral → `side` question, else `scale`; if nothing qualifies, a `yesno` "cut range or guard" question. Mutates and returns the workout.

### `session_checks(entry) -> list[dict]`
All session checks for a history entry, deduped by question across variants. `[]` for legacy entries.

### `parse_answer(kind, raw)`
Normalizes a submitted answer: scale → int 0-10; side → member of `SIDE_OPTIONS`; yesno → member of `YESNO_OPTIONS`. `None` when blank/invalid.

### `format_entry(shoulder) -> str`
One-line rendering of an entry's shoulder answers (e.g. `apprehension 2/10; pain 0/10; …`).

### `summary(entries) -> str`
LEFT-SHOULDER LOG for the prompt, built from the WHOLE feedback log (never trimmed): recent 6 logs, long-term apprehension trend (first 3 vs last 3 avg when ≥4 logs), all-time instability events, movements flagged in the last 8 logs (scale ≥4 or "left much harder"). Then `ACT ON THIS` directives keyed to the latest log:
- instability "yes" → no loaded pressing, no overhead, no hanging; left-arm work is rehab + closed-chain only; coach_notes tell the athlete to check in with the PT
- else pain ≥4 or apprehension ≥6 → regress left-side load or range one step, avoid flagged movements
- else last 3 logs all apprehension ≤2, pain 0, no instability → progress ONE left-side single-arm movement a notch, never into loaded abduction + external rotation

With no logs: a "nothing logged yet, program conservatively" line.

---

## `src/consistency.py` — Adherence & Re-entry Detection

Truth source is the tracker, not what was emailed: Garmin `strength_training` activities stored in `data/garmin.db` (path from `GARMIN_DB_PATH`) plus the dates the athlete left feedback on. Riding is read separately, so "still riding but not lifting" reads as fit-but-detrained. No new env vars.

### `RUSTY_DAYS: int = 10` / `OFF_WAGON_DAYS: int = 21` / `HABIT_SESSIONS_28D: int = 3`
Layoff thresholds. `HABIT_SESSIONS_28D` is the number of completed sessions in 28 days at or below which the habit is not back yet (the program is 2×/week, ~8 per 28 days).

### `assess(now=None) -> dict`
Returns `{"mode", "last_strength", "days_since", "strength_28d", "ride_count_7d", "ride_hours_7d"}`.

Mode rules:
- `off_wagon` — nothing on record, or `days_since >= OFF_WAGON_DAYS` (21+)
- `rusty` — `days_since >= RUSTY_DAYS` (10–20), or `strength_28d <= HABIT_SESSIONS_28D`
- `on_track` — otherwise

### `prompt_section(state) -> str`
The CONSISTENCY block injected into the LLM prompt: gap phrase, 28-day completed-session count, riding phrase, then `REENTRY_RULES` (off_wagon), `RAMP_RULES` (rusty), or a one-line "program normally" note.

### `REENTRY_RULES: str` / `RAMP_RULES: str`
Prompt text for the two comeback shapes. Re-entry: 30–40 min, 4–6 working movements, every RPE capped at 7, ~60% volume, one deliberate play element, welcoming coach_notes. Ramp-back: RPE capped at 8, ~75% volume, one playful element, gap acknowledged in one clause.

### `headline(state) -> str`
One-line amber banner for the top of the email; `""` when on track. Tolerates a partial or legacy state dict.

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
  2025-01-15 Monday: 4/5, preferred Nemotron — "felt solid" [shoulder: apprehension 2/10; pain 0/10; instability no]
  2025-01-10 Friday: 3/5, preferred DeepSeek — "shoulder tweak on landmine"
```
Each entry with shoulder answers gets a `[shoulder: …]` suffix (`shoulder.format_entry`).
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

## `src/garmin.py` — Garmin Training Load Context, 3-Week Pattern Analysis & Recovery

### `load_context(session_date=None) -> dict`
Returns `{"summary": str, "yesterday_note": str, "pattern_analysis": str, "pattern_weeks": list, "pattern_trend": str, "recovery": str}` for LLM prompt and email.

**Flow:**
1. `_token_file()` check — missing tokens → `"Garmin not configured — skipping training load context."`
2. `Garmin().login(_tokens_store())` — resumes saved OAuth tokens; login failure → `"Garmin unavailable (...)"`
3. `_fetch_3weeks(client)` — fetch + normalize last 21 days of activities
4. `_upsert_activities(activities)` — idempotent upsert to SQLite (`data/garmin.db`) by Garmin activity ID
5. Filter last 7 days for summary/yesterday
6. `_summarize(activities_7d)` — builds human-readable 7-day summary
7. `_yesterday_note(activities_7d, session_date)` — specific note on day-before activity
8. `_pattern_data()` — structured 3-week rollup → `pattern_weeks` + `pattern_trend` (email graph) and `_analyze_3week_pattern(data)` → `pattern_analysis` text (LLM prompt)
9. `_fetch_wellness(client)` + `_upsert_wellness(rows)` — last 7 days of wellness (sleep, stress, body battery, HRV)
10. `_recovery_summary(session_date)` — recovery snapshot from stored wellness

Each part degrades independently to placeholder/empty strings — a Garmin outage never blocks a workout.

### `_tokens_store() -> str`
Token store path handed to garminconnect: `GARMIN_TOKENS_PATH` env or default `data/garmin_tokens`.

### `_token_file() -> Path`
Resolves the actual token file (mirrors garminconnect's own logic): the path itself when it ends in `.json`, else `garmin_tokens.json` inside it.

### `_dt(iso: str) -> datetime`
Parses stored ISO-8601 timestamps (defensive about `Z` suffixes).

### `_init_db()`
Creates the `activities` and `wellness` tables (plus the `idx_activities_start_date` index) if missing.

### `_parse_start(a: dict) -> str | None`
Normalizes Garmin's `YYYY-MM-DD HH:MM:SS` GMT stamp (`startTimeGMT`, falling back to `startTimeLocal`) to ISO 8601 UTC.

### `_normalize(a: dict) -> dict | None`
Flattens one raw Garmin activity into the storage/analysis shape (matches DB columns 1:1). Pulls `activityId`, `activityName`, `activityType.typeKey`, `movingDuration`/`duration`, `distance`, `elevationGain`, `aerobicTrainingEffect`, `activityTrainingLoad`, `averageHR`. Returns `None` without an ID or start time; absent metrics degrade to 0/None rather than raising.

### `_upsert_activities(activities: list[dict]) -> int`
Upserts normalized activities by `garmin_id` (INSERT ... ON CONFLICT). Returns count of rows touched.

### `_fetch_3weeks(client) -> list[dict]`
Fetches activities for the last 21 days via `get_activities_by_date` (the garminconnect lib paginates). Returns normalized activity list.

### `_classify_effort(activity) -> str`
Classifies by Garmin aerobic Training Effect (0.0–5.0 scale):
- `very hard` ≥ 4.0
- `hard` ≥ 3.0
- `moderate` ≥ 2.0
- `easy` < 2.0

Fallback when TE is absent (e.g. manual entries) is a moving-time heuristic: ≥ 3h very hard, ≥ 2h hard, ≥ 1h moderate, else easy.

### `_summarize(activities) -> str`
Per-activity lines (sport, hours, km, elevation, TE, effort class) plus week totals: training hours and elevation gain.

### `_yesterday_note(activities, session_date) -> str`
Plain-English note on the day-before's training: hours, hardest effort, and a volume cue for today's session.

### `_pattern_data() -> dict`
Structured 3-week rollup from stored activities: `{"weeks": [...], "trend_lines": [...]}`. Each week: `week`, `count`, `hours`, `km`, `elev`, `effort_counts`, `effort_hours`, `days`, `delta`. Single source of truth for the prompt text and the email graph.

### `_analyze_3week_pattern(data=None) -> str`
Renders `_pattern_data()` as the text block used in the LLM prompt, including:
- Weekly breakdown: activities, hours, distance, elevation, effort distribution (E/M/H/VH), day-of-week pattern
- Trend detection: volume increasing/decreasing/stable over 3 weeks
- Weekend vs weekday split

### `_pos(v)`
Collapses Garmin's 0/-1/-2 "no data" sentinels to `None`.

### `_extract_wellness_day(date_str, summary, sleep, hrv) -> dict`
Flattens one day's wellness payloads into a wellness-table row: `dailySleepDTO.sleepTimeSeconds`, `sleepScores.overall.value`/`qualifierKey`, `averageStressLevel`/`maxStressLevel`, `restingHeartRate`, `bodyBatteryHighestValue`/`bodyBatteryLowestValue`, `hrvSummary.lastNightAvg`/`status`, `totalSteps`. Everything is optional — non-synced days yield `None` columns.

### `_fetch_wellness(client, days=7) -> list[dict]`
Per-day wellness for the last 7 days (today inclusive, local calendar dates). Three calls per day — `get_user_summary(d)`, `get_sleep_data(d)`, `get_hrv_data(d)` — each fails independently; days with no data at all are skipped.

### `_upsert_wellness(rows: list[dict]) -> int`
Upserts wellness rows by calendar `date` with `COALESCE` updates, so a later sparse fetch (e.g. pre-sync 5am run) never erases an earlier metric.

### `_recovery_summary(session_date=None) -> str`
Recovery snapshot from stored wellness — most recent value per metric vs 7-day averages: last-night sleep (hours + score + quality), stress for the most recent full day, body battery high/low, resting HR, HRV (ms + status), 7-day avg daily steps. Returns `""` when the wellness table has nothing recent.

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

Table `wellness` (one row per local calendar date):
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
---

## `src/profile.py` — Athlete Profile

### `ATHLETE: dict`
Static athlete metadata (discipline, role, experience, session_minutes).

### `SHOULDER: dict`
Shoulder specifics (side, history, status, always_include_rehab).

### `EQUIPMENT_NOTES: str`
Human-readable equipment constraints (no bench).

### `EQUIPMENT: list[str]`
Available equipment for prompt injection (incl. 10lb/25lb handheld weight plates and an 8lb weighted ball — nothing overhead).

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
Accepts form: `session_date`, `day`, `rating` (1-5), `preferred_model`, `notes`, plus shoulder fields `std_<key>` (one per standing check) and `chk_<i>_q` / `chk_<i>_ex` / `chk_<i>_kind` / `chk_<i>_a` per session check. Saved if any of model/notes/rating/shoulder answers is present (shoulder-only submissions count). Appends to `feedback.json`. Redirects to `/`.

#### `GET /healthz` → `healthz()`
Returns `{"ok": True}`.

### Template Rendering (Jinja-free)
- `_render_card(entry, fb_for_session)` — session card with feedback form (includes the shoulder check-in; logged feedback shows a "Shoulder: …" line)
- `_shoulder_fields(entry)` — "Left shoulder check-in" section: standing questions + up to `_MAX_FORM_CHECKS` session checks as dropdowns (`_answer_select`); question/exercise/kind in hidden fields
- `_shoulder_answers(form)` — validated `{"standing": {...}, "checks": [...]}` via `shoulder.parse_answer`, or `None` if nothing answered
- `_render_workout_detail(model_label, workout)` — expandable workout blocks
- `_render_latest(entry)` — hero card for most recent session
- `_render_exercise_rows(exercises)` — exercise table rows with YouTube links

---

## `src/email_send.py` — Email Rendering & Delivery

### `_variants(session) -> list[tuple[str, dict]]`
Normalizes session to `[(model_label, workout_dict), ...]`.

### `_table(workout: dict) -> str`
Renders workout blocks as HTML tables with exercise links.

### `_context_box(title: str, text: str) -> str`
Module-level helper: renders a monospace context block (recovery snapshot; legacy text fallback for the pattern) with `html.escape`d text.

### `_pattern_graph(weeks: list, trend: str) -> str`
Email-safe 3-week volume graph: table-based stacked bars (inline styles only — no JS/images, survives Gmail). Bar length ∝ weekly hours scaled to the biggest week; segments colored by effort-hours share (easy→very hard); stats line per week; effort legend; the `→ Trend:`/`→ Weekend:` lines kept below. Returns `""` for empty weeks.

### `render_html(session: dict) -> str`
Full HTML email with:
- **Coach's trend read box** (LLM narrative from `session.trend_analysis`, green accent), then **Recovery (Garmin) box** (from `session.recovery`, via `_context_box`), then the **3-week volume graph** (from `session.pattern_weeks` + `session.pattern_trend`, via `_pattern_graph`; falls back to the `_context_box` text block for legacy sessions with only `pattern_analysis`)
- Day + deload banner
- Variant table (single Nemotron proposal)
- Coach notes per variant
- **LEFT SHOULDER CHECK-IN** box: standing + session questions ("notice these during the session, log them after")
- "Log Feedback" CTA button (links to `WEB_URL`; text mentions the check-in)
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

## `src/setup_garmin.py` — One-Time Garmin Login

### `main() -> None`
Interactive CLI:
1. Reads `GARMIN_EMAIL` from env to prefill the login email (prompts if unset)
2. Prompts for password (never stored) and MFA code
3. `Garmin(email, password, prompt_mfa=...).login(tokens)` — OAuth tokens (valid ~1 year) auto-saved to `GARMIN_TOKENS_PATH`
4. Sanity check: fetches last-7-days activities, prints count + token path

**Usage:** `python -m src.setup_garmin`

---

## Data Schemas

### Session Entry (`history.json`)
```json
{
  "day": "monday",
  "deload": false,
  "date": "2025-01-15",
  "source": "llm",
  "variants": [
    {
      "model": "Nemotron",
      "workout": { "blocks": [...], "focus": "...", "coach_notes": "..." }
    }
  ],
  "pattern_analysis": "3-WEEK TRAINING PATTERN ANALYSIS:\n  15-21d (1–7 Jan): 4 activities, 8.5h, 250km, 3200m elev\n    Effort: 1E 2M 1H 0VH\n    Days: Mon:1, Wed:1, Sat:1, Sun:1\n  ...",
  "pattern_weeks": [{"label": "15-21d", "range": "1–7 Jan", "count": 4, "hours": 8.5, "km": 250, "elev": 3200, "effort_counts": {"easy": 1, "moderate": 2, "hard": 1, "very hard": 0}, "effort_hours": {"easy": 1.5, "moderate": 4.0, "hard": 3.0, "very hard": 0.0}, "days": "Mon:1, Sat:1, Sun:1, Wed:1", "delta": " (+1.2h ↑)"}],
  "pattern_trend": "→ Trend: Volume stable (+0.3h over 3 weeks)\n→ Weekend: 9.1h vs Weekday: 7.2h",
  "recovery": "  Sleep last night: 7.4h, score 82 GOOD — 7-day avg 7.1h, score 78\n  Stress (Tue 14 Jan): avg 28/100, max 71 — 7-day avg 31\n  ...",
  "trend_analysis": "- Volume stable around 8h/week with weekend-loaded rides\n- Recovery solid: sleep and HRV at baseline\nToday: keep planned intensity, progress hip thrust load.",
  "consistency": {"mode": "rusty", "last_strength": "2025-01-02", "days_since": 13, "strength_28d": 2, "ride_count_7d": 4, "ride_hours_7d": 7.8}
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
  "coach_notes": "Rotated away from KB swings used last Monday...",
  "shoulder_checks": [
    { "exercise": "single-arm landmine press", "question": "Landmine press: left side compared with right?", "kind": "side" }
  ]
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
  "shoulder": {
    "standing": {"apprehension": 2, "pain": 0, "instability": "no", "left_vs_right": "left a bit harder"},
    "checks": [{"exercise": "single-arm landmine press", "question": "Landmine press: left side compared with right?", "kind": "side", "answer": "same"}]
  },
  "logged_at": "2025-01-15T18:30:00+00:00"
}
```
`shoulder` is optional; question text is stored with each answer so records stay readable if wording changes.

---

## Utility Functions (Cross-Module)

### `src/main.py`
- `_ensure_hip_bridge(workout, bridge)` — inserts mandatory hip bridge if missing
- `_find_block(workout, name)` — fetches or creates a named block
- `_ensure_required_content(workout, day, seed)` — backfills compound lead-off, lower-core and anti-rotation movements from the vetted pools

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
- `_pick_main(pool, n, rng)` — `n` main-block exercises, always led by a loaded compound