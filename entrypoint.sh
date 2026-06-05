#!/bin/sh
set -e

# Apply the timezone so cron's 5am fires in LOCAL time, not UTC.
# TZ comes from the .env / compose environment.
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
  ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
  echo "$TZ" > /etc/timezone
fi

echo "coach_claude started. Schedule: Mon & Fri 05:00 ${TZ:-UTC}."

# If arguments are passed (e.g. `docker compose run coach monday`), run the
# workout script directly instead of starting cron. Handy for test sends.
if [ $# -gt 0 ]; then
  exec python -m src.main "$@"
fi

# cron reads the container env via the .env file (python-dotenv), so we don't
# need to export anything here. Run cron in the foreground to keep PID 1 alive.
exec cron -f
