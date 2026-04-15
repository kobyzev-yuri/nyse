# Nyse Telegram bot + pipeline (long-polling). Секреты не в образе: смонтируйте ./config.env
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --no-cache-dir -U pip \
  && pip install --no-cache-dir -e .

ENV NYSE_CONFIG_PATH=/app/config.env
ENV PYTHONUNBUFFERED=1

CMD ["python", "scripts/run_bot.py"]
