"""Юнит: news_merge без сети (мок Yahoo)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

from domain import NewsArticle, Ticker


def test_fetch_merged_news_empty_when_yahoo_returns_empty():
    from sources.news_merge import fetch_merged_news

    with patch("sources.news_yahoo.YahooSource") as ycls:
        ycls.return_value.get_articles.return_value = []
        out = fetch_merged_news(
            [Ticker.NVDA],
            max_per_ticker=5,
            lookback_hours=48,
        )
    assert out == []


def test_fetch_merged_news_caps_per_ticker():
    from sources.news_merge import fetch_merged_news

    now = datetime.now(timezone.utc)
    arts = [
        NewsArticle(
            ticker=Ticker.NVDA,
            title=f"t{i}",
            summary=None,
            timestamp=now,
            link=f"https://x/{i}",
            publisher="p",
            provider_id="yfinance",
        )
        for i in range(10)
    ]
    with patch("sources.news_yahoo.YahooSource") as ycls:
        ycls.return_value.get_articles.return_value = arts
        out = fetch_merged_news(
            [Ticker.NVDA],
            max_per_ticker=3,
            lookback_hours=48,
        )
    assert len(out) == 3
