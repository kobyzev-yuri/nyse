"""Этап F: ключ LLM-кэша и get_or_set строки."""

from __future__ import annotations

from typing import List

from pipeline.cache import FileCache
from pipeline.llm_cache import cache_key_llm, get_or_set_llm_text


def test_cache_key_llm_stable_for_same_input():
    m = [{"role": "user", "content": "a"}]
    k1 = cache_key_llm(m, "gpt-4o", prompt_version="v1")
    k2 = cache_key_llm(m, "gpt-4o", prompt_version="v1")
    assert k1 == k2
    assert k1.startswith("llm|")


def test_cache_key_llm_differs_by_model():
    m = [{"role": "user", "content": "a"}]
    assert cache_key_llm(m, "gpt-4o", prompt_version="v1") != cache_key_llm(
        m, "gpt-4o-mini", prompt_version="v1"
    )


def test_get_or_set_llm_text_calls_fetcher_once(tmp_path):
    cache = FileCache(tmp_path, default_ttl_sec=3600)
    calls: List[int] = []

    def fetcher() -> str:
        calls.append(1)
        return "ok"

    k = "llm|test|key"
    assert get_or_set_llm_text(cache, k, 3600, fetcher) == "ok"
    assert get_or_set_llm_text(cache, k, 3600, fetcher) == "ok"
    assert len(calls) == 1
