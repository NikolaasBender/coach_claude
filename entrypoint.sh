#!/bin/sh
set -e

# Apply the timezone so cron's 5am fires in LOCAL time, not UTC.
# TZ comes from the .env / compose environment.
if [ -n "$TZ" ] && [ -f "/usr/share/zoneinfo/$TZ" ]; then
  ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime
  echo "$TZ" > /etc/timezone
fi

echo "coach_claude started. Schedule: Mon & Fri 05:00 ${TZ:-UTC}."

# `web` starts the feedback web app instead of the cron scheduler.
if [ "$1" = "web" ]; then
  echo "Starting feedback web app on port ${WEB_PORT:-8080}."
  exec python -m src.web
fi

# Day arguments run the workout script directly instead of starting cron
# (e.g. `docker compose run --rm coach monday`). Handy for test sends.
case "$1" in
  monday|friday) exec python -m src.main "$@" ;;
esac

# Anything else is a verbatim command, e.g. the one-time Garmin login:
#   docker compose run --rm coach python -m src.setup_garmin
if [ $# -gt 0 ]; then
  exec "$@"
fi

# cron reads the container env via the .env file (python-dotenv), so we don't
# need to export anything here. Run cron in the foreground to keep PID 1 alive.
exec cron -f
