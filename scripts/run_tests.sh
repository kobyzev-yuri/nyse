#!/usr/bin/env bash
# Запуск pytest в conda env py11 (см. docs/testing_telegram_plan.md).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
exec conda run -n py11 python -m pytest tests/ "$@"
