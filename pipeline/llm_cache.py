"""
Этап F: ключ кэша ответа LLM по хешу входа (модель + версия промпта + messages).

Значение — строка (сырой текст completion), тот же ``FileCache``, что и для новостей.

Запуск из корня nyse: ``python -m pipeline.llm_cache`` (предпочтительно) или
``python pipeline/llm_cache.py`` — второй вариант перезапускает модуль через пакет.
"""

from __future__ import annotations

import hashlib
import json
import runpy
import sys
from pathlib import Path
from typing import Callable

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.llm_cache", run_name="__main__")
    raise SystemExit(0)

from .cache import FileCache

CACHE_KEY_VERSION = "v1"


def cache_key_llm(
    messages: list[dict[str, str]],
    model: str,
    *,
    prompt_version: str = "v1",
) -> str:
    """Стабильный ключ: ``llm|…|hash``."""
    blob = json.dumps(
        {"m": messages, "model": model, "pv": prompt_version},
        sort_keys=True,
        ensure_ascii=False,
    )
    h = hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
    return f"llm|{CACHE_KEY_VERSION}|{prompt_version}|{model}|{h}"


def get_or_set_llm_text(
    cache: FileCache,
    key: str,
    ttl_sec: int,
    fetcher: Callable[[], str],
) -> str:
    """Возвращает закэшированный текст или результат ``fetcher`` (обычно HTTP к LLM)."""
    hit = cache.get(key)
    if hit is not None and isinstance(hit, str):
        return hit
    text = fetcher()
    cache.set(key, text, ttl_sec=ttl_sec)
    return text


def default_llm_file_cache() -> FileCache:
    """``FileCache`` в ``NYSE_CACHE_ROOT`` с TTL ``NYSE_LLM_CACHE_TTL_SEC``."""
    import config_loader

    root = config_loader.nyse_cache_root()
    ttl = config_loader.llm_cache_ttl_sec()
    return FileCache(root, default_ttl_sec=ttl)


if __name__ == "__main__":
    demo = cache_key_llm([{"role": "user", "content": "example"}], "gpt-4o")
    print(demo)
