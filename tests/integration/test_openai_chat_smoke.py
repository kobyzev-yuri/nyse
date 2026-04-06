"""Один реальный HTTP вызов к OpenAI-совместимому API (ProxyAPI), если есть ключ."""

from __future__ import annotations

import pytest
import requests


@pytest.mark.integration
def test_chat_completion_smoke(require_openai_settings):
    from pipeline.llm_client import chat_completion_text

    try:
        out = chat_completion_text(
            [{"role": "user", "content": "Reply with exactly: OK"}],
            settings=require_openai_settings,
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        pytest.skip(f"Сеть до API недоступна: {type(e).__name__}")
    assert isinstance(out, str)
    assert len(out.strip()) >= 1
