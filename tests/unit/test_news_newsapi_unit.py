"""Юнит: NewsAPI без сети (mock requests)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def newsapi_ok_response():
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = {
        "status": "ok",
        "articles": [
            {
                "title": "NVDA headline",
                "description": "Body",
                "url": "https://example.com/n",
                "publishedAt": "2025-06-01T12:00:00Z",
                "source": {"name": "Example"},
            }
        ],
    }
    return m


@patch("sources.news_newsapi.requests.get")
def test_newsapi_maps_to_news_article(mock_get, newsapi_ok_response):
    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    newsapi_ok_response.json.return_value["articles"][0]["publishedAt"] = now_iso
    mock_get.return_value = newsapi_ok_response
    from domain import Ticker
    from sources.news_newsapi import Source

    s = Source(api_key="test-key", max_articles=10, lookback_hours=72)
    arts = s.get_articles([Ticker.NVDA])
    assert len(arts) == 1
    a = arts[0]
    assert a.ticker == Ticker.NVDA
    assert a.title == "NVDA headline"
    assert a.provider_id == "newsapi"
    assert a.publisher == "Example"


@patch("sources.news_newsapi.requests.get")
def test_newsapi_status_error_returns_empty(mock_get):
    mock_get.return_value.raise_for_status = MagicMock()
    mock_get.return_value.json.return_value = {
        "status": "error",
        "code": "rateLimited",
    }
    from domain import Ticker
    from sources.news_newsapi import Source

    arts = Source(api_key="k", lookback_hours=72).get_articles([Ticker.NVDA])
    assert arts == []
