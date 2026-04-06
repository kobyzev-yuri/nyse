"""Юнит: Marketaux без сети (mock requests)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


@patch("sources.news_marketaux.requests.get")
def test_marketaux_maps_entity_sentiment(mock_get):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    mock_get.return_value = MagicMock()
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = {
        "data": [
            {
                "title": "NVDA headline",
                "description": "D",
                "url": "https://x.com/a",
                "published_at": now_iso,
                "source": "reuters.com",
                "entities": [
                    {
                        "symbol": "NVDA",
                        "sentiment_score": 0.42,
                    }
                ],
            }
        ]
    }
    from domain import Ticker
    from sources.news_marketaux import Source

    arts = Source(api_key="tok", lookback_hours=72).get_articles([Ticker.NVDA])
    assert len(arts) == 1
    a = arts[0]
    assert a.provider_id == "marketaux"
    assert a.raw_sentiment == pytest.approx(0.42)
    assert a.title == "NVDA headline"


@patch("sources.news_marketaux.requests.get")
def test_marketaux_general_averages_entity_sentiment(mock_get):
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    mock_get.return_value = MagicMock()
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = {
        "data": [
            {
                "title": "Macro",
                "published_at": now_iso,
                "url": "https://x.com/m",
                "source": "src",
                "entities": [
                    {"symbol": "A", "sentiment_score": 0.2},
                    {"symbol": "B", "sentiment_score": 0.4},
                ],
            }
        ]
    }
    from domain import Ticker
    from sources.news_marketaux import Source

    arts = Source(api_key="tok", lookback_hours=72).get_articles([Ticker.GENERAL])
    assert len(arts) == 1
    assert arts[0].raw_sentiment == pytest.approx(0.3)
