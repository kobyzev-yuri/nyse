"""Тесты загрузчика конфигурации без реальных секретов."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import config_loader


def test_config_env_path_respects_nyse_config_path(monkeypatch, tmp_path):
    p = tmp_path / "secrets.env"
    p.write_text("OPENAI_API_KEY=from_file\n", encoding="utf-8")
    monkeypatch.setenv("NYSE_CONFIG_PATH", str(p))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    config_loader.load_config_env()
    assert os.environ.get("OPENAI_API_KEY") == "from_file"


def test_get_openai_settings_none_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("NYSE_CONFIG_PATH", raising=False)
    monkeypatch.setattr(config_loader, "config_env_path", lambda: Path("/nonexistent"))
    assert config_loader.get_openai_settings() is None


def test_llm_cache_ttl_sec_default(monkeypatch):
    monkeypatch.delenv("NYSE_LLM_CACHE_TTL_SEC", raising=False)
    assert config_loader.llm_cache_ttl_sec() == 86400


def test_llm_cache_ttl_sec_override(monkeypatch):
    monkeypatch.setenv("NYSE_LLM_CACHE_TTL_SEC", "3600")
    assert config_loader.llm_cache_ttl_sec() == 3600


def test_news_lookback_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv("NYSE_NEWS_LOOKBACK_SIGNAL_HOURS", raising=False)
    monkeypatch.delenv("NYSE_NEWS_LOOKBACK_NEWS_HOURS", raising=False)
    monkeypatch.setattr(config_loader, "config_env_path", lambda: tmp_path / "missing.env")
    assert config_loader.news_lookback_hours_signal() == 72
    assert config_loader.news_lookback_hours_news_cmd() == 48


def test_news_lookback_env_override(monkeypatch):
    monkeypatch.setenv("NYSE_NEWS_LOOKBACK_SIGNAL_HOURS", "96")
    monkeypatch.setenv("NYSE_NEWS_LOOKBACK_NEWS_HOURS", "24")
    assert config_loader.news_lookback_hours_signal() == 96
    assert config_loader.news_lookback_hours_news_cmd() == 24
