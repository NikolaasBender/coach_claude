# Operations Guide

## Daily Operations

### Check Scheduled Runs
```bash
# View coach logs (cron output)
docker compose logs coach

# Follow live
docker compose logs -f coach
```

Expected log on run days (Mon/Fri ~5am):
```
coach_claude started. Schedule: Mon & Fri 05:00 America/Denver.
[ok] sent monday session (models=[Nemotron], deload=False)
```

### Check Web App
```bash
# Health check
curl http://localhost:8080/healthz
# {"ok": true}

# View logs
docker compose logs web
```

### Verify Data Persistence
```bash
# Check history
docker compose run --rm coach cat /data/history.json | jq '. | length'
# Check feedback
docker compose run --rm coach cat /data/feedback.json | jq '. | length'
```

## Manual Workout Generation

### Test Monday Workout
```bash
docker compose run --rm coach python -m src.main monday
```

### Test Friday Workout
```bash
docker compose run --rm coach python -m src.main friday
```

### Force Deload Test
```bash
# Temporarily override DELOAD_EVERY
docker compose run --rm coach -e DELOAD_EVERY=1 python -m src.main monday
```

## Debugging

### Inspect LLM Prompt
```bash
# Run with debug to see what goes to the model
docker compose run --rm coach python -c "
from src.llm import _build_user_prompt
from src import history, garmin, feedback, templates
from src.profile import SCHEDULE

ctx = {
    'day': 'monday',
    'deload': False,
    'history': history.recent(4),
    'load_summary': history.load_summary(8),
    'garmin': garmin.load_context(),
    'feedback': feedback.summary(6),
    'hip_bridge': templates.hip_bridge(history.count()),
}
prompt = _build_user_prompt(**ctx)
print(prompt[:3000])
print('...')
print(prompt[-500:])
"
```

### Test Exclusion Guardrail
```bash
# Check if an exercise would be rejected
docker compose run --rm coach python -c "
from src.exclusions import check, validate_workout

# Test single exercise
print('fly:', check('dumbbell fly'))
print('bench:', check('wide grip bench press'))
print('glute bridge:', check('weighted glute bridge'))

# Test full workout
workout = {
    'blocks': [{
        'name': 'Test',
        'exercises': [
            {'name': 'band external rotation'},
            {'name': 'dumbbell fly'},  # Should fail
        ]
    }]
}
ok, violations = validate_workout(workout)
print('ok:', ok)
print('violations:', violations)
"
```

### Test Template Generation
```bash
docker compose run --rm coach python -c "
from src.templates import generate
import json

w = generate('monday', False, '2025-01-15', 0)
print(json.dumps(w, indent=2))
"
```

### Test Garmin Context
```bash
docker compose run --rm --entrypoint "" coach python -c "
from src.garmin import load_context
import json
ctx = load_context()
print('=== SUMMARY (7 days) ===')
print(ctx['summary'])
print()
print('=== PATTERN ANALYSIS (3 weeks) ===')
print(ctx['pattern_analysis'])
print()
print('=== RECOVERY (wellness) ===')
print(ctx['recovery'])
"
```

### Test Email Rendering
```bash
docker compose run --rm coach python -c "
from src.email_send import render_html
from src import history

entries = history.load()
if entries:
    html = render_html(entries[-1])
    with open('/tmp/test_email.html', 'w') as f:
        f.write(html)
    print('Written to /tmp/test_email.html')
else:
    print('No history yet')
"
# Then view /tmp/test_email.html in browser
```

### Debug Web App
```bash
# Run locally with debug
docker compose run --rm -p 8080:8080 -e WEB_PORT=8080 coach python -m src.web
# Visit http://localhost:8080
```

## Maintenance Tasks

### Update LLM Providers
Edit `src/llm.py` `PROVIDERS` list:
```python
PROVIDERS = [
    {
        "name": "Nemotron",
        "key_env": "NVIDIA_API_KEY",
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "nvidia/nemotron-3-ultra-550b-a55b",
    },
    {
        "name": "NewModel",
        "key_env": "NEWMODEL_API_KEY",
        "base_url": "https://api.newmodel.com/v1",
        "model": "newmodel-latest",
    },
]
```
Add API key to `.env`, rebuild: `docker compose up -d --build`


### Inspect Garmin 3-Week Pattern Analysis
```bash
# View pattern analysis from DB
docker compose run --rm --entrypoint "" coach python -c "
from src.garmin import load_context
ctx = load_context()
print('=== PATTERN ANALYSIS ===')
print(ctx['pattern_analysis'])
"
```

### View Garmin Database
```bash
# Check activities in DB
docker compose run --rm --entrypoint "" coach python -c "
import sqlite3
conn = sqlite3.connect('/data/garmin.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute('SELECT COUNT(*) as cnt FROM activities')
print('Total activities:', cur.fetchone()['cnt'])
cur.execute('SELECT garmin_id, start_date, moving_time/3600.0 as hours, aerobic_te FROM activities ORDER BY start_date DESC LIMIT 10')
for row in cur.fetchall():
    print(f\"  {row['garmin_id']}: {row['start_date']} - {row['hours']:.2f}h - TE:{row['aerobic_te']}\")
"
```

### Reset Garmin Database (if corrupted)
```bash
docker compose run --rm --entrypoint "" coach rm /data/garmin.db
# Next run will re-fetch 21 days and rebuild
```
### Add Exercise to Template Pools
Edit `src/templates.py`:
1. Add to appropriate pool (`REHAB_BLOCK`, `LOWER_POWER`, etc.)
2. Verify it passes exclusions: `docker compose run --rm coach python -c "from src.exclusions import check; print(check('your exercise name'))"`
3. Add YouTube mapping in `src/exercise_links.py` `_QUERIES`
4. Rebuild

### Modify Exclusion Rules (PT Approval Required)
Edit `src/exclusions.py` `EXCLUSIONS` list. See SAFETY.md for process.

### Rotate Hip Bridge Variants
Automatic — cycles every 3 sessions via `templates.hip_bridge(session_index)`.
Current cycle: Single-leg → Weighted → Bodyweight (paused).

### Adjust Deload Frequency
```bash
# In .env
DELOAD_EVERY=4  # Every 4th session instead of 5th
```
Restart coach: `docker compose restart coach`

### Change Schedule Time
Edit `crontab`:
```
# 6am instead of 5am
0 6 * * 1 cd /app && /usr/local/bin/python -m src.main monday >> /proc/1/fd/1 2>&1
0 6 * * 5 cd /app && /usr/local/bin/python -m src.main friday >> /proc/1/fd/1 2>&1
```
Rebuild: `docker compose up -d --build`

### Update Timezone
```bash
# In .env
TZ=America/Los_Angeles
```
Restart coach: `docker compose restart coach` (entrypoint applies TZ on start)

## Backup & Restore

### Backup Data Volume
```bash
# Tar the data directory
tar -czf coach_claude_backup_$(date +%Y%m%d).tar.gz data/
```

### Restore Data Volume
```bash
tar -xzf coach_claude_backup_20250115.tar.gz
docker compose up -d
```

### Export History as CSV
```bash
docker compose run --rm coach python -c "
import json, csv
from src.history import load

entries = load()
with open('/tmp/history.csv', 'w') as f:
    w = csv.writer(f)
    w.writerow(['date', 'day', 'deload', 'model', 'focus', 'blocks', 'exercises'])
    for e in entries:
        for v in e.get('variants', [{'model': e.get('model'), 'workout': e}]):
            w.writerow([
                e['date'], e['day'], e.get('deload', False),
                v['model'], v['workout'].get('focus', ''),
                len(v['workout'].get('blocks', [])),
                sum(len(b.get('exercises', [])) for b in v['workout'].get('blocks', []))
            ])
print('Exported to /tmp/history.csv')
"
```

## Upgrading

### Pull Latest Image (if using GHCR)
```bash
docker compose pull
docker compose up -d
```

### Rebuild Local Image
```bash
docker compose build --no-cache
docker compose up -d
```

### Update Base Image
Edit `Dockerfile` `FROM python:3.12-slim` → newer version, then rebuild.

## Troubleshooting

### Coach Container Exits Immediately
```bash
docker compose logs coach
# Check for:
# - Missing .env (mount failed)
# - Invalid TZ (entrypoint fails)
# - Cron syntax error
```

### Web App Not Accessible
```bash
# Check port mapping
docker compose ps
# Verify WEB_HOST_PORT in docker-compose.yml
# Check firewall on host (ufw, iptables)
# Try: curl http://localhost:8080/healthz from host
```

### Email Not Sending
```bash
# Test SMTP from container
docker compose run --rm coach python -c "
import smtplib
server = smtplib.SMTP('smtp.gmail.com', 587)
server.starttls()
server.login('you@gmail.com', 'your-app-password')
print('SMOK OK')
server.quit()
"
# Common issues:
# - App password wrong (must be 16 chars, no spaces)
# - 2FA not enabled on Google account
# - Less secure apps not the issue (App Password bypasses this)
```

### Garmin Tokens Expired (~1 year)
```bash
# Re-run the interactive login (email + password + MFA if enabled);
# tokens land on the /data volume automatically — no .env edit needed
docker compose run --rm coach python -m src.setup_garmin
docker compose restart coach
```

### LLM API Errors
```bash
# Check API key validity
docker compose run --rm coach python -c "
import os
from openai import OpenAI

client = OpenAI(
    api_key=os.environ['NVIDIA_API_KEY'],
    base_url='https://integrate.api.nvidia.com/v1'
)
resp = client.chat.completions.create(
    model='nvidia/nemotron-3-ultra-550b-a55b',
    messages=[{'role': 'user', 'content': 'test'}],
    max_tokens=10
)
print(resp.choices[0].message.content)
"
```

### History/Feedback Corruption
```bash
# Reset (loses all history)
docker compose run --rm coach rm /data/history.json /data/feedback.json
docker compose restart coach
```

## Log Locations

| Component | Location |
|-----------|----------|
| Cron runs | `docker compose logs coach` |
| Web app | `docker compose logs web` |
| Manual runs | Stdout of `docker compose run` |
| Email send | Stdout (check for "sent" message) |
| Garmin errors | Stdout (check for "Garmin unavailable", "Garmin activities unavailable", or "[garmin] wellness unavailable") |

## Monitoring Checklist (Weekly)

- [ ] Check `docker compose logs coach` for successful Mon/Fri runs
- [ ] Verify email received (check spam)
- [ ] Log feedback via web app for at least one session
- [ ] Check `docker compose ps` — both containers `Up`
- [ ] Verify `data/history.json`, `data/feedback.json`, and `data/garmin.db` growing
- [ ] Review any exclusion violations in logs (search for "violation")
- [ ] Check Garmin recovery snapshot + pattern analysis appear in email (top section)