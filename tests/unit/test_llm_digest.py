"""Этап F: промпт дайджеста и кэшированный путь (mock completion)."""

from __future__ import annotations

from unittest.mock import patch

from config_loader import OpenAISettings
from pipeline.cache import FileCache
from pipeline.llm_digest import build_digest_messages, run_lite_digest_cached


def test_build_digest_messages_has_system_and_user():
    msgs = build_digest_messages(["A", "B"])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "A" in msgs[1]["content"] and "B" in msgs[1]["content"]
    assert "JSON" in msgs[1]["content"]


def test_run_lite_digest_cached_uses_cache_second_time(tmp_path):
    s = OpenAISettings(
        api_key="k",
        base_url="https://example.com/v1",
        model="m",
        temperature=0.0,
        timeout_sec=30,
    )
    cache = FileCache(tmp_path, default_ttl_sec=86400)
    with patch("pipeline.llm_digest.chat_completion_text", return_value="first") as m:
        r1 = run_lite_digest_cached(
            ["one headline"],
            cache=cache,
            settings=s,
            ttl_sec=3600,
        )
        r2 = run_lite_digest_cached(
            ["one headline"],
            cache=cache,
            settings=s,
            ttl_sec=3600,
        )
    assert r1 == "first" and r2 == "first"
    assert m.call_count == 1
