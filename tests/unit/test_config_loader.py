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
