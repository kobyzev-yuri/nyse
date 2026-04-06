"""Интеграция: config.env и ProxyAPI/OpenAI."""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_openai_settings_loaded(require_openai_settings):
    s = require_openai_settings
    assert len(s.api_key) > 10
    assert s.base_url.startswith("http")
    assert s.model
    assert s.timeout_sec > 0
