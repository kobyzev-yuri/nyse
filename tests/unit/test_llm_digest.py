"""Этап F: промпт дайджеста и кэшированный путь (mock LangChain model)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from config_loader import OpenAISettings
from pipeline.cache import FileCache
from pipeline.llm_digest import build_digest_messages, run_lite_digest_cached


_SETTINGS = OpenAISettings(
    api_key="k",
    base_url="https://example.com/v1",
    model="m",
    temperature=0.0,
    timeout_sec=30,
)


def test_build_digest_messages_has_system_and_user():
    msgs = build_digest_messages(["A", "B"])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "A" in msgs[1]["content"] and "B" in msgs[1]["content"]
    assert "JSON" in msgs[1]["content"]


def test_run_lite_digest_cached_uses_cache_second_time(tmp_path):
    """Второй вызов с теми же заголовками должен читать из кэша, не вызывая LLM."""
    cache = FileCache(tmp_path, default_ttl_sec=86400)

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = SimpleNamespace(content="first")

    with patch("pipeline.llm_digest.get_chat_model", return_value=mock_llm):
        r1 = run_lite_digest_cached(
            ["one headline"],
            cache=cache,
            settings=_SETTINGS,
            ttl_sec=3600,
        )
        r2 = run_lite_digest_cached(
            ["one headline"],
            cache=cache,
            settings=_SETTINGS,
            ttl_sec=3600,
        )

    assert r1 == "first"
    assert r2 == "first"
    assert mock_llm.invoke.call_count == 1  # второй раз из кэша


def test_run_lite_digest_returns_llm_content(tmp_path):
    cache = FileCache(tmp_path, default_ttl_sec=3600)
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = SimpleNamespace(
        content='{"bias": 0.5, "summary": "bullish"}'
    )

    with patch("pipeline.llm_digest.get_chat_model", return_value=mock_llm):
        result = run_lite_digest_cached(
            ["Good earnings", "Revenue up"],
            cache=cache,
            settings=_SETTINGS,
            ttl_sec=3600,
        )

    assert "bullish" in result
    mock_llm.invoke.assert_called_once()
