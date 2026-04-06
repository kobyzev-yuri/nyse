"""Интеграция: NewsAPI, Marketaux, Alpha Vantage, RSS (сеть). Ключевые API — skip без env."""

from __future__ import annotations

import pytest
import requests

# Публичная RSS-лента (без ключа); при смене URL обновите тест.
BBC_WORLD_RSS = "https://feeds.bbci.co.uk/news/world/rss.xml"


@pytest.mark.integration
def test_newsapi_live(require_newsapi_key):
    from domain import Ticker
    from sources.news_newsapi import Source

    src = Source(
        api_key=require_newsapi_key,
        max_articles=5,
        lookback_hours=72,
    )
    try:
        articles = src.get_articles([Ticker.NVDA])
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        pytest.skip(f"NewsAPI HTTP {code}: {e}")
    assert isinstance(articles, list)
    for a in articles[:3]:
        assert a.title.strip()
        assert a.provider_id == "newsapi"
        assert a.ticker == Ticker.NVDA


@pytest.mark.integration
def test_marketaux_live(require_marketaux_key):
    from domain import Ticker
    from sources.news_marketaux import Source

    src = Source(
        api_key=require_marketaux_key,
        max_articles=5,
        lookback_hours=72,
    )
    try:
        articles = src.get_articles([Ticker.NVDA])
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        pytest.skip(f"Marketaux HTTP {code}: {e}")
    assert isinstance(articles, list)
    for a in articles[:3]:
        assert a.title.strip()
        assert a.provider_id == "marketaux"
        assert a.ticker == Ticker.NVDA


@pytest.mark.integration
def test_alphavantage_news_sentiment_live(require_alphavantage_key):
    from domain import Ticker
    from sources.news_alphavantage import Source

    src = Source(
        api_key=require_alphavantage_key,
        max_articles=10,
        lookback_hours=72 * 14,
    )
    try:
        articles = src.get_articles([Ticker.NVDA])
    except requests.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        pytest.skip(f"Alpha Vantage HTTP {code}: {e}")
    assert isinstance(articles, list)
    if not articles:
        pytest.skip(
            "Alpha Vantage вернул 0 статей (лимит free tier / пустой feed / Note в JSON)"
        )
    for a in articles[:3]:
        assert a.title.strip()
        assert a.provider_id == "alphavantage"
        assert a.ticker == Ticker.NVDA


@pytest.mark.integration
def test_rss_bbc_world_feed(load_nyse_config):
    from domain import Ticker
    from sources.news_rss import Source

    src = Source(
        BBC_WORLD_RSS,
        ticker=Ticker.GENERAL,
        lookback_hours=24 * 14,
        max_items=15,
    )
    try:
        articles = src.get_articles([Ticker.GENERAL])
    except (requests.HTTPError, requests.RequestException) as e:
        pytest.skip(f"RSS fetch failed: {e}")
    assert isinstance(articles, list)
    if not articles:
        pytest.skip("RSS вернул 0 статей в окне (или парсер не совпал с форматом ленты)")
    for a in articles[:5]:
        assert a.title.strip()
        assert a.provider_id == "rss"
        assert a.ticker == Ticker.GENERAL
