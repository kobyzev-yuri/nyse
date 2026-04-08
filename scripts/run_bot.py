"""
Запуск NyseBot в режиме long-polling (для разработки и тестирования).

Использование:
    cd /path/to/nyse
    conda run -n py11 python scripts/run_bot.py

Нужные переменные в config.env:
    TELEGRAM_BOT_TOKEN=<token>
    OPENAI_API_KEY=<key>          # для LLM в /signal
    TICKERS_FAST=SNDK,NBIS,...    # опционально
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Корень nyse в sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config_loader

config_loader.load_config_env()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
# httpx/httpcore на INFO пишут полный URL каждого запроса к api.telegram.org — в нём токен бота.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("run_bot")

from bot.nyse_bot import build_application


def main() -> None:
    token = config_loader.get_telegram_bot_token()
    if not token:
        log.error("TELEGRAM_BOT_TOKEN не задан в config.env")
        sys.exit(1)

    proxy = config_loader.get_telegram_proxy()
    if not proxy:
        log.warning(
            "TELEGRAM_PROXY не задан. Если api.telegram.org недоступен напрямую — "
            "добавь в config.env: TELEGRAM_PROXY=socks5://user:pass@host:port"
        )

    log.info("Запуск NyseBot (long-polling)…")
    app = build_application(token, proxy=proxy)
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message"],
    )


if __name__ == "__main__":
    main()
