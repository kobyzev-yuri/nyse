"""
Общая конфигурация pytest: корень репозитория в sys.path для `import pipeline` и `import domain`.
Все модули тестов в `tests/unit/` используют эти фикстуры.

Конфигурация секретов (LLM, ProxyAPI): в обычных юнит-тестах не используется.
См. docs/configuration.md и `config_loader.py`. Для опциональных интеграционных тестов —
фикстура `load_nyse_config` (подгружает config.env по NYSE_CONFIG_PATH или config.env).
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
    """Опционально: подмешать переменные из config.env (для integration-тестов с LLM)."""
    import config_loader

    config_loader.load_config_env()
    return True
