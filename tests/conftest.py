"""
Общая конфигурация pytest: корень репозитория в sys.path для `import pipeline` и `import domain`.
Все модули тестов в `tests/unit/` используют эти фикстуры.

Конфигурация секретов (LLM, ProxyAPI): в обычных юнит-тестах не используется.
См. docs/configuration.md и `config_loader.py`.

Фикстуры:
- `load_nyse_config` — подмешать `config.env` / `NYSE_CONFIG_PATH` / `../lse/config.env`.
- `require_openai_settings` — `load_nyse_config` + skip, если нет `OPENAI_API_KEY`.
- `require_newsapi_key` / `require_marketaux_key` / `require_alphavantage_key` — skip без ключей в config.env.
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
