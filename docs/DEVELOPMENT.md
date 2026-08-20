# Development Guide

## Local Development Setup

### Prerequisites
- Python 3.12+
- Docker + Docker Compose (for full stack)
- `uv` or `pip` for dependency management

### Install Dependencies
```bash
# Using uv (recommended)
uv pip install -r requirements.txt

# Or pip
pip install -r requirements.txt
```

### Run Without Docker
```bash
# Set env vars
export $(cat .env | xargs)  # or source .env

# Run generator manually
python -m src.main monday

# Run web app
python -m src.web  # http://localhost:8080
```

### Run Tests
```bash
# No formal test suite yet — manual verification:
# 1. Generate workout
python -m src.main monday
# 2. Check email received
# 3. Check history.json updated
# 4. Visit web app, submit feedback
# 5. Verify feedback.json updated
```

## Code Style

### Formatting
```bash
# Install ruff
uv pip install ruff

# Format
ruff format src/

# Lint
ruff check src/
```

### Type Hints
- Use type hints on all public functions
- `from __future__ import annotations` at top of modules
- Run `ruff check` — it catches type issues via pyright

### Imports
- Standard library first
- Third-party second
- Local (`from . import ...`) third
- Alphabetical within each group

## Adding a New LLM Provider

### 1. Add to `src/llm.py` PROVIDERS
```python
PROVIDERS = [
    # ... existing ...
    {
        "name": "NewProvider",
        "key_env": "NEWPROVIDER_API_KEY",
        "base_url": "https://api.newprovider.com/v1",
        "model": "newprovider-model-name",
    },
]
```

### 2. Add API Key to `.env`
```
NEWPROVIDER_API_KEY=sk-xxx...
```

### 3. Verify OpenAI Compatibility
The provider must support:
- `POST /chat/completions`
- OpenAI-compatible request/response format
- `model` parameter
- `messages` array with `role`/`content`

### 4. Test
```bash
docker compose run --rm coach python -c "
from src.llm import active_providers
print([p['name'] for p in active_providers()])
# Should include 'NewProvider'
"
```

### 5. Rebuild
```bash
docker compose up -d --build
```

## Adding Template Exercises

### 1. Choose Pool
Edit `src/templates.py`:
- `REHAB_BLOCK` — shoulder rehab
- `LOWER_POWER` — lower body power
- `UPPER_PULL` — upper pulling
- `HIP_BRIDGES` — hip bridge variants (3 only, cycle)
- `LOWER_CORE` — lower-core emphasis
- `FINISHERS` — general finishers

### 2. Add Exercise Dict
```python
{
    "name": "exercise name",
    "sets": 3,
    "reps": "8-10",
    "rpe": 7,
    "notes": "optional cue",
}
```

### 3. Verify Safety
```bash
python -c "from src.exclusions import check; print(check('your exercise name'))"
# Must return []
```

### 4. Add YouTube Link
Edit `src/exercise_links.py` `_QUERIES`:
```python
"your exercise name": "youtube search query for form tutorial",
```

### 5. Test Template Generation
```bash
python -c "
from src.templates import generate
import json
w = generate('monday', False, '2025-01-15', 0)
print(json.dumps(w, indent=2))
"
```

## Modifying Exclusion Rules

**Requires PT approval.** See SAFETY.md.

### 1. Edit `src/exclusions.py`
```python
EXCLUSIONS = [
    # ... existing ...
    ("your reason", [r"pattern1", r"pattern2"]),
]
```

### 2. Update `PROMPT_CONSTRAINTS`
Keep plain-text version in sync for LLM prompt.

### 3. Test
```bash
python -c "
from src.exclusions import check, validate_workout
print(check('exercise that should be blocked'))
print(check('exercise that should pass'))
"
```

### 4. Rebuild
```bash
docker compose up -d --build
```

## Adding Feedback Fields

### 1. Update `src/feedback.py` `append()`
Accept new fields in entry dict.

### 2. Update `src/web.py` form + handler
- Add form field in `_render_card()`
- Read in `submit_feedback()`

### 3. Update `src/feedback.py` `summary()`
Include new fields in LLM prompt digest.

### 4. Update `src/email_send.py` if needed
Include in email if relevant.

## Modifying Email Template

Edit `src/email_send.py`:
- `render_html()` — full HTML structure
- `_table()` — workout block tables
- `compare_hint` — comparison text
- `feedback_cta` — feedback button

### Test Rendering
```bash
python -c "
from src.email_send import render_html
from src import history
entries = history.load()
if entries:
    html = render_html(entries[-1])
    with open('/tmp/email.html', 'w') as f:
        f.write(html)
    print('Open /tmp/email.html in browser')
"
```

## Modifying Strava Integration

### Scopes
Current: `activity:read` only. To add more:
1. Update `REQUIRED_SCOPE` in `setup_strava.py`
2. Re-run OAuth: `python -m src.setup_strava`
3. Update `.env` with new refresh token

### Activity Filtering
Edit `src/strava.py`:
- `_fetch_activities()` — change `days` parameter
- `_classify_effort()` — adjust suffer score thresholds
- `_summarize()` — change summary format
- `_yesterday_note()` — change detail level

## Adding Scheduled Runs

### 1. Edit `crontab`
```
# Add new line (cron syntax: min hour day month dow)
0 6 * * 3 cd /app && /usr/local/bin/python -m src.main wednesday >> /proc/1/fd/1 2>&1
```

### 2. Update `src/main.py` `target_day()`
Add "wednesday" to valid days.

### 3. Update `src/profile.py` `SCHEDULE`
Add focus for Wednesday.

### 4. Rebuild
```bash
docker compose up -d --build
```

## Docker Development

### Build with Cache
```bash
docker compose build
```

### Build No Cache (for dependency changes)
```bash
docker compose build --no-cache
```

### Run Interactive Shell in Container
```bash
docker compose run --rm coach sh
# or bash
docker compose run --rm coach bash
```

### Run One-Off Commands
```bash
# Any python module
docker compose run --rm coach python -m src.module arg1 arg2

# Arbitrary command
docker compose run --rm coach ls -la /data
```

### View Container Filesystem
```bash
docker compose run --rm coach find /app -name "*.py" | head -20
```

## Git Workflow

### Branching
- `main` — production deployments
- Feature branches for changes
- PRs to `main` trigger CI build

### Commit Messages
Follow Conventional Commits:
```
feat: add new LLM provider support
fix: handle missing feedback gracefully
docs: update safety documentation
refactor: extract email rendering to separate module
test: add exclusion guardrail verification
chore: update base image to python:3.13
```

### CI Pipeline (`.github/workflows/build.yml`)
- Triggers on push to `main`
- Builds multi-arch (amd64 + arm64)
- Pushes to GHCR: `ghcr.io/<owner>/coach_claude:latest`
- Uses Docker layer caching (GHA cache)

### Local Pre-Commit Checks
```bash
# Format + lint
ruff format src/ && ruff check src/

# Verify build
docker compose build

# Quick functional test
docker compose run --rm coach python -m src.main monday
```

## Debugging Tips

### Print LLM Prompt/Response
```python
# In src/llm.py generate(), add temporarily:
print("=== PROMPT ===")
print(user_prompt)
print("=== RESPONSE ===")
print(resp.choices[0].message.content)
```

### Trace Exclusion Violations
```python
# In src/exclusions.py validate_workout(), add:
print(f"Checking: {name} -> {hits}")
```

### Inspect History/Feedback Data
```bash
docker compose run --rm coach python -c "
import json
from src.history import load as hload
from src.feedback import load as fload
print('History:', len(hload()))
print('Feedback:', len(fload()))
for e in hload()[-2:]:
    print(json.dumps(e, indent=2)[:500])
"
```

### Profile Performance
```bash
docker compose run --rm coach python -m cProfile -o profile.stats -m src.main monday
# Analyze with: python -c "import pstats; p = pstats.Stats('profile.stats'); p.sort_stats('cumulative').print_stats(20)"
```

## Common Patterns

### Safe Dictionary Access
```python
# Use .get() with defaults throughout
workout.get("blocks", [])
block.get("exercises", [])
ex.get("name", "")
```

### Date Handling
- Use `datetime.now(timezone.utc).isoformat(timespec="seconds")` for timestamps
- Store dates as ISO strings (`YYYY-MM-DD`)
- Parse with `datetime.fromisoformat()`

### JSON Persistence
```python
# Atomic write pattern used in history.py / feedback.py
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
with open(path, "w") as f:
    json.dump(data, f, indent=2)
```

### Thread Safety (Web App)
```python
# Global lock for single-user generation
_generate_lock = threading.Lock()
_generating = False

with _generate_lock:
    if _generating:
        return "busy"
    _generating = True
try:
    # do work
finally:
    _generating = False
```

## File Change Impact Map

| File | Affects | Rebuild Required |
|------|---------|------------------|
| `src/main.py` | Orchestration, email, history | Yes |
| `src/llm.py` | LLM calls, providers, prompts | Yes |
| `src/exclusions.py` | Safety guardrail, LLM prompt | Yes |
| `src/templates.py` | Fallback workouts, hip bridge | Yes |
| `src/history.py` | Session persistence, load summary | Yes |
| `src/feedback.py` | Feedback persistence, prompt digest | Yes |
| `src/strava.py` | Training load context | Yes |
| `src/profile.py` | Athlete config, equipment, schedule | Yes |
| `src/web.py` | Web UI, feedback submission | Yes |
| `src/email_send.py` | Email HTML, SMTP sending | Yes |
| `src/exercise_links.py` | Exercise YouTube links | Yes |
| `src/setup_strava.py` | One-time OAuth only | No (not in image) |
| `Dockerfile` | Base image, deps, entrypoint | Yes |
| `docker-compose.yml` | Services, ports, volumes | Yes |
| `entrypoint.sh` | TZ setup, command routing | Yes |
| `crontab` | Schedule | Yes |
| `requirements.txt` | Python deps | Yes |
| `.env` | Runtime config | No (mounted) |

## Performance Notes

- LLM calls are the bottleneck (~10-30s each)
- Web app uses lock to prevent concurrent generation
- History/feedback are small JSON files (< 100 KB typical)
- No database — file I/O is fast enough
- Cron runs sequentially (one day at a time)

## Future Enhancement Ideas

- [ ] Add third LLM provider (e.g., Groq, Together)
- [ ] Structured logging (JSON) for log aggregation
- [ ] Metrics endpoint (Prometheus) on web app
- [ ] Automated exclusion testing in CI
- [ ] Web app: session comparison view
- [ ] Web app: export history/feedback as CSV
- [ ] Per-exercise RPE tracking in feedback
- [ ] Strava: power/HR data if available
- [ ] Periodization: mesocycle planning