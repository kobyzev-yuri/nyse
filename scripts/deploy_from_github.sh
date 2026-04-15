#!/bin/bash
# Автодеплой NYSE (Telegram-бот) на VM при изменениях в GitHub.
# Запускать на сервере из cron или вручную. Требует: git, docker compose, репозиторий в NYSE_REPO_DIR.
#
# Использование:
#   ./scripts/deploy_from_github.sh          # pull, при изменениях — rebuild и перезапуск nyse-bot
#   ./scripts/deploy_from_github.sh --force  # всегда пересобрать и перезапустить
#
# Cron (каждые 10 минут):
#   */10 * * * * /home/USER/nyse/scripts/deploy_from_github.sh >> /home/USER/nyse/logs/deploy.log 2>&1
#
# Мало RAM: остановить сервис перед сборкой
#   NYSE_STOP_BEFORE_BUILD=1 ./scripts/deploy_from_github.sh --force
# Подробный вывод docker build:
#   NYSE_DEPLOY_BUILD_PLAIN=1 ./scripts/deploy_from_github.sh --force

set -e

REPO_DIR="${NYSE_REPO_DIR:-$HOME/nyse}"
SERVICE_NAME="${NYSE_SERVICE_NAME:-nyse-bot}"
CONTAINER_NAME="${NYSE_CONTAINER_NAME:-nyse-bot}"
LOG_DIR="${REPO_DIR}/logs"
FORCE=0

for arg in "$@"; do
    case "$arg" in
        --force) FORCE=1 ;;
    esac
done

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

log "NYSE deploy check started (repo=$REPO_DIR)"

if [ ! -d "$REPO_DIR/.git" ]; then
    log "ERROR: Not a git repo: $REPO_DIR"
    exit 2
fi

cd "$REPO_DIR"

if [ ! -f "$REPO_DIR/config.env" ]; then
    log "WARNING: $REPO_DIR/config.env not found. Create it (e.g. scp from dev machine) before the bot can start."
fi

OLD_HEAD=$(git rev-parse HEAD 2>/dev/null || true)
log "git fetch + pull..."
git fetch origin
git pull --rebase --autostash || { log "ERROR: git pull failed"; exit 3; }
NEW_HEAD=$(git rev-parse HEAD 2>/dev/null || true)

if [ "$FORCE" -eq 1 ] || [ "$OLD_HEAD" != "$NEW_HEAD" ]; then
    log "Changes detected (or --force). Rebuilding and restarting service=$SERVICE_NAME (container=$CONTAINER_NAME)..."
    log "Commits: $OLD_HEAD -> $NEW_HEAD"
    export DOCKER_BUILDKIT=1
    BUILD_ARGS=(build "$SERVICE_NAME")
    if [ -n "${NYSE_DEPLOY_BUILD_PLAIN:-}" ]; then
        BUILD_ARGS=(build --progress=plain "$SERVICE_NAME")
    fi
    if [ "${NYSE_STOP_BEFORE_BUILD:-0}" = "1" ]; then
        log "NYSE_STOP_BEFORE_BUILD=1: stopping service $SERVICE_NAME to free RAM for build..."
        docker compose stop "$SERVICE_NAME" 2>/dev/null || true
    fi
    log "Starting: docker compose ${BUILD_ARGS[*]}"
    time docker compose "${BUILD_ARGS[@]}"
    log "docker compose build finished."
    log "Starting: docker compose up -d $SERVICE_NAME"
    time docker compose up -d "$SERVICE_NAME"
    log "docker compose up finished."
    log "Deploy completed. Container: $CONTAINER_NAME"
else
    log "No changes. Skip rebuild. HEAD=$NEW_HEAD"
fi

exit 0
