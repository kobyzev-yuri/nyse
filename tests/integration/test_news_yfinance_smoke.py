"""Интеграция: Yahoo news через yfinance (сеть)."""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_news_source_returns_articles(load_nyse_config):
    pytest.importorskip("yfinance")
    from domain import Ticker
    from sources.news import Source

    src = Source(max_per_ticker=10, lookback_hours=24 * 7)
    articles = src.get_articles([Ticker.NVDA])
    assert isinstance(articles, list)
    for a in articles[:5]:
        assert a.title.strip()
        assert a.ticker == Ticker.NVDA
