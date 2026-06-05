FROM python:3.12-slim

# cron for scheduling, tzdata so TZ actually takes effect.
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY crontab /etc/cron.d/coach
COPY entrypoint.sh /entrypoint.sh

RUN chmod 0644 /etc/cron.d/coach \
    && crontab /etc/cron.d/coach \
    && chmod +x /entrypoint.sh

# /data is a mounted volume for persistent history.
VOLUME ["/data"]

ENTRYPOINT ["/entrypoint.sh"]
CMD []
