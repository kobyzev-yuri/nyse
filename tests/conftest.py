"""
Общая конфигурация pytest: корень репозитория в sys.path для `import pipeline`, `import domain` и `import tests.support`.
Все модули тестов в `tests/unit/` используют эти фикстуры.

Конфигурация секретов (LLM, ProxyAPI, Telegram): в обычных юнит-тестах не используется.
См. docs/configuration.md и `config_loader.py`.

Фикстуры:
- `load_nyse_config` — подмешать `config.env` / `NYSE_CONFIG_PATH` / `../lse/config.env`.
- `require_openai_settings` — `load_nyse_config` + skip, если нет `OPENAI_API_KEY`.
- `require_newsapi_key` / `require_marketaux_key` / `require_alphavantage_key` — skip без ключей.
- `require_telegram_token` — TELEGRAM_BOT_TOKEN из config.env или skip.
- `require_telegram_settings` — токен + chat_id или skip.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture
def repo_root() -> Path:
    return _ROOT


@pytest.fixture
def tmp_cache_dir(tmp_path: Path) -> Path:
    d = tmp_path / "nyse_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def utc_now() -> datetime:
    return datetime(2026, 4, 5, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def default_thresholds():
    from pipeline import ThresholdConfig

    return ThresholdConfig()


@pytest.fixture
def load_nyse_config():
    """Подмешать переменные из config.env (для integration-тестов)."""
    import config_loader

    config_loader.load_config_env()
    return True


@pytest.fixture
def require_openai_settings(load_nyse_config):
    """Настройки OpenAI/ProxyAPI или skip, если ключ не задан."""
    import config_loader

    s = config_loader.get_openai_settings()
    if s is None:
        pytest.skip("Нет OPENAI_API_KEY: создайте nyse/config.env из config.env.example")
    return s


@pytest.fixture
def require_newsapi_key(load_nyse_config):
    import config_loader

    k = config_loader.get_newsapi_key()
    if not k:
        pytest.skip("Нет NEWSAPI_KEY в config.env")
    return k


@pytest.fixture
def require_marketaux_key(load_nyse_config):
    import config_loader

    k = config_loader.get_marketaux_api_key()
    if not k:
        pytest.skip("Нет MARKETAUX_API_KEY в config.env")
    return k


@pytest.fixture
def require_alphavantage_key(load_nyse_config):
    import config_loader

    k = config_loader.get_alphavantage_api_key()
    if not k:
        pytest.skip("Нет ALPHAVANTAGE_KEY в config.env")
    return k


@pytest.fixture(scope="session")
def game5m_tickers(tmp_path_factory):
    """
    Список тикеров GAME_5M из TICKERS_FAST (config.env) или дефолт SNDK,NBIS,ASML,MU,LITE,CIEN.

    Используйте этот фикстур во всех integration-тестах вместо хардкода Ticker.NVDA.
    """
    import config_loader

    config_loader.load_config_env()
    tickers = config_loader.get_game5m_tickers()
    assert tickers, "get_game5m_tickers() вернул пустой список"
    return tickers


@pytest.fixture(scope="session")
def game5m_primary(tmp_path_factory):
    """
    Первичный тикер GAME_5M для smoke-тестов (первый в TICKERS_FAST, обычно SNDK).
    """
    import config_loader

    config_loader.load_config_env()
    tickers = config_loader.get_game5m_tickers()
    assert tickers, "get_game5m_tickers() вернул пустой список"
    return tickers[0]


@pytest.fixture(scope="session")
def require_finbert(tmp_path_factory):
    """
    Проверяет что transformers установлен и FinBERT доступен.
    Возвращает имя модели. Skip если transformers нет.

    Модель может быть задана через SENTIMENT_MODEL в config.env,
    по умолчанию ProsusAI/finbert.
    """
    transformers = pytest.importorskip("transformers", reason="pip install transformers")
    import config_loader
    config_loader.load_config_env()
    return config_loader.get_sentiment_model_name()


@pytest.fixture
def require_telegram_token(load_nyse_config):
    """TELEGRAM_BOT_TOKEN из config.env или skip."""
    import config_loader

    token = config_loader.get_telegram_bot_token()
    if not token:
        pytest.skip(
            "Нет TELEGRAM_BOT_TOKEN в config.env — "
            "добавьте: TELEGRAM_BOT_TOKEN=<токен от @BotFather>"
        )
    return token


@pytest.fixture
def require_telegram_settings(load_nyse_config):
    """
    Токен + chat_id из config.env. Skip, если чего-то не хватает.

    Возвращает (token: str, chat_id: str).
    Задайте в config.env:
      TELEGRAM_BOT_TOKEN=...
      TELEGRAM_SIGNAL_CHAT_ID=...  (или TELEGRAM_SIGNAL_CHAT_IDS=id1,id2)
    """
    import config_loader

    token = config_loader.get_telegram_bot_token()
    if not token:
        pytest.skip("Нет TELEGRAM_BOT_TOKEN в config.env")

    chat_id = config_loader.get_telegram_chat_id()
    if not chat_id:
        pytest.skip(
            "Нет TELEGRAM_SIGNAL_CHAT_ID / TELEGRAM_SIGNAL_CHAT_IDS в config.env"
        )

    return token, chat_id
