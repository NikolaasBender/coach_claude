# Getting Started

## Prerequisites

- Docker + Docker Compose
- Gmail account with 2FA enabled (for App Password)
- NVIDIA API key (free from [build.nvidia.com](https://build.nvidia.com))
- DeepSeek API key (from [platform.deepseek.com](https://platform.deepseek.com)) — optional but recommended
- Strava account (optional but recommended for training load context)

## Quick Start

```bash
# 1. Clone and enter project
git clone <repo>
cd coach_claude

# 2. Copy env template and fill in YOUR values
cp .env.example .env
# edit .env with your keys (see Configuration below)

# 3. Build and start
docker compose up -d --build

# 4. Verify it's running
docker compose logs -f coach
# Should show: "coach_claude started. Schedule: Mon & Fri 05:00 <your TZ>."
```

The system now sits idle and fires Monday & Friday at 5am local time.

## Test It Now (Send a Workout Immediately)

```bash
# Build first (if not already)
docker compose build

# One-off run for a given day, ignores the schedule
docker compose run --rm coach python -m src.main monday
# or
docker compose run --rm coach python -m src.main friday
```

Check your email — you should receive a side-by-side comparison of both models' proposals.

## Run Feedback Web App Locally (Without Docker)

```bash
pip install -r requirements.txt
python -m src.web   # serves on http://localhost:8080
```

## Configuration (`.env`)

| Variable | Required | Description |
|----------|----------|-------------|
| `NVIDIA_API_KEY` | Yes* | NVIDIA Nemotron key (`nvapi-...`) |
| `DEEPSEEK_API_KEY` | No | DeepSeek key (`sk-...`) — enables dual-model comparison |
| `GMAIL_ADDRESS` | Yes | Your Gmail address |
| `GMAIL_APP_PASSWORD` | Yes | 16-char App Password (NOT your login password) |
| `EMAIL_TO` | No | Recipient (defaults to `GMAIL_ADDRESS`) |
| `WEB_URL` | Yes* | Public URL of feedback app (e.g. `http://orangepi.local:8080`) |
| `TZ` | Yes | Your IANA timezone (e.g. `America/Denver`) — **critical for 5am timing** |
| `DELOAD_EVERY` | No | Deload every N sessions (default: 5) |
| `STRAVA_CLIENT_ID` | No | Strava app Client ID |
| `STRAVA_CLIENT_SECRET` | No | Strava app Client Secret |
| `STRAVA_REFRESH_TOKEN` | No | From one-time OAuth (run `python -m src.setup_strava`) |
| `FORCE_DAY` | No | Force `monday` or `friday` for testing (leave blank in prod) |
| `HISTORY_PATH` | No | Default: `/data/history.json` |
| `FEEDBACK_PATH` | No | Default: `/data/feedback.json` |

*At least one LLM key required. `WEB_URL` needed for feedback links in emails.

### Gmail App Password

1. Enable 2FA on your Google account
2. Visit: https://myaccount.google.com/apppasswords
3. Generate app password for "Mail" → "Other (custom name)" → `coach_claude`
4. Copy the 16-char password (no spaces) to `GMAIL_APP_PASSWORD`

### Strava Setup (Optional)

1. Register app at https://www.strava.com/settings/api
   - App Name: `coach_claude`
   - Website: `http://localhost`
   - Authorization Callback Domain: `localhost`
2. Copy Client ID + Client Secret to `.env`
3. Run one-time OAuth:
   ```bash
   docker compose run --rm coach python -m src.setup_strava
   ```
4. Paste the output `STRAVA_REFRESH_TOKEN=...` into `.env`
5. Restart: `docker compose up -d`

## Directory Structure

```
coach_claude/
├── src/
│   ├── main.py           # Orchestrator entrypoint
│   ├── llm.py            # LLM providers (Nemotron, DeepSeek)
│   ├── exclusions.py     # Hard shoulder safety guardrail
│   ├── templates.py      # Safe fallback workouts
│   ├── history.py        # Persistent session log
│   ├── feedback.py       # Athlete feedback log
│   ├── strava.py         # Strava training load context
│   ├── profile.py        # Athlete profile & equipment
│   ├── web.py            # Flask feedback web app
│   ├── email_send.py     # HTML email + Gmail SMTP
│   ├── exercise_links.py # Exercise → YouTube URLs
│   └── setup_strava.py   # One-time Strava OAuth
├── data/                 # Mounted volume (history.json, feedback.json)
├── .env                  # Your config (NOT committed)
├── .env.example          # Template
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── crontab
└── requirements.txt
```

## Verify Deployment

```bash
# Check containers
docker compose ps

# View coach logs (scheduled runs)
docker compose logs coach

# View web app logs
docker compose logs web

# Health check web app
curl http://localhost:8080/healthz
# {"ok": true}

# Manual test run
docker compose run --rm coach python -m src.main monday
```

## Common Issues

| Symptom | Fix |
|---------|-----|
| Email not sent | Check `GMAIL_APP_PASSWORD` is 16 chars, no spaces; 2FA enabled |
| Wrong time zone | Set `TZ` to valid IANA zone (e.g. `America/Los_Angeles`) |
| Strava not working | Run `setup_strava` again; check token not expired |
| Web app not accessible | Check `WEB_HOST_PORT` in compose; firewall on Pi |
| "No module named src" | Run from `/app` inside container; use `docker compose run coach ...` |