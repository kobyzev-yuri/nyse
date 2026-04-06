"""Юнит: Alpha Vantage NEWS_SENTIMENT без сети (mock requests)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


@patch("sources.news_alphavantage.requests.get")
def test_alphavantage_maps_feed_to_news_article(mock_get):
    tp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    mock_get.return_value = MagicMock()
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = {
        "feed": [
            {
                "title": "NVDA test headline",
                "summary": "S",
                "url": "https://example.com/n",
                "time_published": tp,
                "source": "TestSource",
                "overall_sentiment_score": "0.11",
                "ticker_sentiment": [
                    {
                        "ticker": "NVDA",
                        "ticker_sentiment_score": "0.25",
                    }
                ],
            }
        ]
    }
    from domain import Ticker
    from sources.news_alphavantage import Source

    arts = Source(api_key="k", lookback_hours=500).get_articles([Ticker.NVDA])
    assert len(arts) == 1
    a = arts[0]
    assert a.provider_id == "alphavantage"
    assert a.title == "NVDA test headline"
    assert a.ticker == Ticker.NVDA
    assert a.raw_sentiment == 0.25


@patch("sources.news_alphavantage.requests.get")
def test_alphavantage_note_returns_empty(mock_get):
    mock_get.return_value = MagicMock()
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = {
        "Note": "Thank you for using Alpha Vantage. Please contact ..."
    }
    from domain import Ticker
    from sources.news_alphavantage import Source

    arts = Source(api_key="k").get_articles([Ticker.NVDA])
    assert arts == []
