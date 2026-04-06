"""Юнит: sources.news_shared."""

from __future__ import annotations

from domain import Ticker
from sources.news_shared import symbol_for_provider


def test_symbol_for_provider_strips_vix_caret():
    assert symbol_for_provider(Ticker.VIX) == "VIX"
    assert symbol_for_provider(Ticker.NVDA) == "NVDA"
