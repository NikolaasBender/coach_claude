# coach_claude Documentation

## Overview

`coach_claude` is an automated strength training coach for a gravel/MTB cyclist with a repaired left shoulder. It generates workouts twice weekly (Mon/Fri 5am) using two LLMs (Nemotron + DeepSeek), validates every proposal against a hard shoulder safety guardrail, and emails side-by-side comparisons with a feedback loop.

## Documentation Index

| Document | Purpose |
|----------|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, data flow, module responsibilities |
| [GETTING_STARTED.md](GETTING_STARTED.md) | Quick start, prerequisites, first run, verification |
| [CONFIGURATION.md](CONFIGURATION.md) | Complete environment variable reference, provider config, athlete profile |
| [SAFETY.md](SAFETY.md) | Shoulder exclusion rules, validation flow, PT review checklist |
| [API.md](API.md) | Module-by-module function/class reference, data schemas |
| [OPERATIONS.md](OPERATIONS.md) | Daily ops, debugging, maintenance, backup, troubleshooting |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Local dev setup, code style, adding providers/exercises, git workflow |

## Quick Navigation

### New User?
→ [GETTING_STARTED.md](GETTING_STARTED.md)

### Configuring the System?
→ [CONFIGURATION.md](CONFIGURATION.md)

### Understanding Safety?
→ [SAFETY.md](SAFETY.md)

### Debugging an Issue?
→ [OPERATIONS.md#debugging](OPERATIONS.md#debugging)

### Adding a Feature?
→ [DEVELOPMENT.md](DEVELOPMENT.md)

### Understanding the Codebase?
→ [ARCHITECTURE.md](ARCHITECTURE.md) → [API.md](API.md)

## Project Structure

```
coach_claude/
├── docs/                    # This documentation
├── src/
│   ├── main.py             # Orchestrator entrypoint
│   ├── llm.py              # LLM providers (Nemotron, DeepSeek)
│   ├── consistency.py      # Layoff detection: adherence modes + re-entry rules
│   ├── exclusions.py       # Hard shoulder safety guardrail
│   ├── templates.py        # Safe fallback workouts
│   ├── history.py          # Persistent session log
│   ├── feedback.py         # Athlete feedback log
│   ├── garmin.py           # Garmin training load + recovery context
│   ├── profile.py          # Athlete profile & equipment
│   ├── web.py              # Flask feedback web app
│   ├── email_send.py       # HTML email + Gmail SMTP
│   ├── shoulder.py         # Left-shoulder check-ins + long-term shoulder log
│   ├── exercise_links.py   # Exercise → YouTube URLs
│   └── setup_garmin.py     # One-time Garmin Connect login
├── data/                   # Mounted volume (history.json, feedback.json, garmin.db, garmin_tokens)
├── .env                    # Your config (NOT committed)
├── .env.example            # Template
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh
├── crontab
└── requirements.txt
```

## Key Concepts

1. **Safety First**: No LLM output reaches the athlete without passing `exclusions.py` validation. The model proposes; code disposes.

2. **Dual-Model Comparison**: Every session is designed by both Nemotron and DeepSeek independently. Email shows them side by side.

3. **Feedback Loop**: Athlete logs rating (1-5), preferred model, and notes via web app. This feeds directly into the next prompt.

4. **Training Load & Recovery Awareness**: Garmin activity data (last 7 days) plus wearable recovery data (sleep, stress, body battery, HRV) inform workout intensity — hard Sunday ride or a rough night's sleep softens Monday leg day.

5. **Mandatory Structure**: Every session includes a shoulder rehab block, a loaded compound lead-off in Main, a rotating hip bridge variant (SL → weighted → BW), and two distinct core patterns — lower-core/anti-extension in Main plus anti-rotation/anti-lateral-flexion in the finisher block.

6. **Consistency & Re-entry**: `consistency.py` scores adherence from Garmin strength activities plus logged feedback (`on_track` / `rusty` / `off_wagon`). After a layoff the session becomes a comeback: shorter (45 or 35 min), RPE-capped, fewer main lifts, one play element, an amber banner on the email, and no deload stacked on top.

7. **Deload Protocol**: Every 5th session (configurable) reduces volume while maintaining movement patterns. Suppressed while in re-entry.

8. **Left-Shoulder Check-ins**: Every session carries four permanent standing questions (apprehension, pain, instability, left vs right) plus 2-3 exercise-specific checks. `shoulder.py` summarizes the full, never-trimmed log into the prompt with directives (instability → no loaded pressing/overhead/hanging + PT check-in; rough → regress; three quiet sessions → progress one left-side movement a notch).

## Support

- **Issues**: Check [OPERATIONS.md#troubleshooting](OPERATIONS.md#troubleshooting) first
- **Safety Changes**: Require PT approval — see [SAFETY.md](SAFETY.md)
- **Development**: Follow [DEVELOPMENT.md](DEVELOPMENT.md) patterns