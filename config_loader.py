"""
Загрузка настроек для nyse: переменные окружения и опционально config.env.

Приоритет: уже установленные os.environ → файл из NYSE_CONFIG_PATH → ./config.env
→ при отсутствии: `../lse/config.env` относительно корня репозитория nyse (удобно в монорепо).

Тесты: по умолчанию **не** требуют config.env; интеграционные тесты с LLM помечайте и
пропускайте без ключа (см. tests/conftest.py).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k:
            out[k] = v
    return out


def _apply_env(overrides: dict[str, str]) -> None:
    for k, v in overrides.items():
        if k not in os.environ or os.environ.get(k, "") == "":
            os.environ[k] = v


def load_config_env() -> None:
    """
    Подмешивает значения из файла в os.environ (не перезаписывает уже заданные переменные).
    """
    path = config_env_path()
    _apply_env(_parse_env_file(path))


def config_env_path() -> Path:
    """Путь к файлу с секретами для загрузки."""
    explicit = os.environ.get("NYSE_CONFIG_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    local = _REPO_ROOT / "config.env"
    if local.is_file():
        return local
    fallback = _REPO_ROOT.parent / "lse" / "config.env"
    return fallback


@dataclass(frozen=True)
class OpenAISettings:
    api_key: str
    base_url: str
    model: str
    temperature: float
    timeout_sec: int


def get_openai_settings() -> Optional[OpenAISettings]:
    """None, если нет ключа — вызывать load_config_env() заранее при необходимости."""
    load_config_env()
    key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    return OpenAISettings(
        api_key=key,
        base_url=(
            os.environ.get("OPENAI_BASE_URL") or "https://api.proxyapi.ru/openai/v1"
        ).strip(),
        model=(os.environ.get("OPENAI_MODEL") or "gpt-4o").strip(),
        temperature=float(os.environ.get("OPENAI_TEMPERATURE") or "0"),
        timeout_sec=int(float(os.environ.get("OPENAI_TIMEOUT") or "60")),
    )


def get_config_value(key: str, default: Optional[str] = None) -> Optional[str]:
    load_config_env()
    return os.environ.get(key, default)
