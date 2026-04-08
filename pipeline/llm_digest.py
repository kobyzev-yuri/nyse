"""
Этап F: короткий «lite» дайджест по заголовкам (промпт + опционально кэшированный вызов).

Полный structured LLM (news runner) — отдельно; здесь только заготовка для микро-режима LITE.

Запуск из корня nyse: ``python -m pipeline.llm_digest`` или ``python pipeline/llm_digest.py``.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.llm_digest", run_name="__main__")
    raise SystemExit(0)

from .cache import FileCache

if TYPE_CHECKING:
    from config_loader import OpenAISettings
from .llm_cache import cache_key_llm, default_llm_file_cache, get_or_set_llm_text
from .llm_factory import get_chat_model


def build_digest_messages(
    article_titles: Sequence[str],
    *,
    max_titles: int = 20,
) -> list[dict[str, str]]:
    """Сообщения для одного вызова chat: сжатый список заголовков → JSON bias/summary."""
    lines = "\n".join(f"- {str(t)[:500]}" for t in list(article_titles)[:max_titles])
    user = (
        f"Headlines:\n{lines}\n\n"
        'Reply with a single JSON object: {"bias": <float -1..1>, "summary": "<one sentence>"}'
    )
    return [
        {
            "role": "system",
            "content": "You summarize news headlines for a trading bias estimate. Be concise.",
        },
        {"role": "user", "content": user},
    ]


def run_lite_digest_cached(
    article_titles: Sequence[str],
    *,
    cache: Optional[FileCache] = None,
    settings: Optional["OpenAISettings"] = None,
    prompt_version: str = "v1",
    ttl_sec: Optional[int] = None,
) -> str:
    """
    Дайджест через ``chat_completion_text`` с кэшем по ``cache_key_llm``.

    Требует ``OPENAI_API_KEY`` (иначе ``RuntimeError``).
    """
    import config_loader

    s = settings if settings is not None else config_loader.get_openai_settings()
    if s is None:
        raise RuntimeError("OpenAI settings missing (OPENAI_API_KEY)")
    messages = build_digest_messages(list(article_titles))
    key = cache_key_llm(messages, s.model, prompt_version=prompt_version)
    c = cache if cache is not None else default_llm_file_cache()
    ttl = ttl_sec if ttl_sec is not None else config_loader.llm_cache_ttl_sec()

    from .lc_shim import HumanMessage, SystemMessage

    _llm = get_chat_model(s)
    lc_messages = [
        SystemMessage(content=messages[0]["content"]),
        HumanMessage(content=messages[1]["content"]),
    ]

    def fetcher() -> str:
        resp = _llm.invoke(lc_messages)
        return resp.content if hasattr(resp, "content") else str(resp)

    return get_or_set_llm_text(c, key, ttl, fetcher)


if __name__ == "__main__":
    print(json.dumps(build_digest_messages(["demo headline"]), ensure_ascii=False, indent=2))
