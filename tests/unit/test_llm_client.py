"""Этап F: chat completion без сети (mock HTTP)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import config_loader
from config_loader import OpenAISettings
from pipeline.llm_client import chat_completion_text


def test_chat_completion_text_parses_content():
    s = OpenAISettings(
        api_key="k",
        base_url="https://example.com/v1",
        model="m",
        temperature=0.0,
        timeout_sec=30,
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": '{"bias": 0.1}'}}],
    }
    post = MagicMock(return_value=mock_resp)

    out = chat_completion_text(
        [{"role": "user", "content": "hi"}],
        settings=s,
        post=post,
    )
    assert out == '{"bias": 0.1}'
    post.assert_called_once()
    call_kw = post.call_args[1]
    assert call_kw["json"]["model"] == "m"


def test_chat_completion_text_raises_without_settings(monkeypatch):
    monkeypatch.setattr(config_loader, "get_openai_settings", lambda: None)
    with pytest.raises(RuntimeError, match="OpenAI settings"):
        chat_completion_text([{"role": "user", "content": "x"}], post=MagicMock())
