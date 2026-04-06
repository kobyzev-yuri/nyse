"""
Этап E: кэш списков новостей и ``DraftImpulse`` (файлы, TTL).

Запуск: ``python -m pytest tests/unit/test_news_cache.py -v`` или ``python tests/unit/test_news_cache.py``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from domain import NewsArticle, Ticker
from pipeline import (
    FileCache,
    NewsImpactChannel,
    ScoredArticle,
    cache_key_draft_aggregate,
    cache_key_raw_news,
    deserialize_news_article,
    draft_impulse,
    get_or_set_articles,
    get_or_set_draft_impulse,
    serialize_news_article,
)


def _article(**kwargs) -> NewsArticle:
    defaults = dict(
        ticker=Ticker.NVDA,
        title="t",
        timestamp=datetime(2026, 1, 2, 15, 0, 0, tzinfo=timezone.utc),
        summary="s",
        link="https://x.com/a",
        publisher="p",
        provider_id="yfinance",
        raw_sentiment=None,
        cheap_sentiment=0.1,
    )
    defaults.update(kwargs)
    return NewsArticle(**defaults)


def test_serialize_news_article_roundtrip():
    a = _article()
    d = serialize_news_article(a)
    b = deserialize_news_article(d)
    assert b.title == a.title
    assert b.ticker == a.ticker
    assert b.cheap_sentiment == pytest.approx(0.1)
    assert b.timestamp == a.timestamp


def test_get_or_set_articles_invokes_fetch_only_once(tmp_cache_dir):
    c = FileCache(tmp_cache_dir, default_ttl_sec=3600)
    key = cache_key_raw_news("yfinance", "NVDA")
    m = MagicMock(
        return_value=[_article(title="once")],
    )
    r1 = get_or_set_articles(c, key, 3600, m)
    r2 = get_or_set_articles(c, key, 3600, m)
    assert m.call_count == 1
    assert len(r1) == 1 and len(r2) == 1
    assert r1[0].title == "once"


def test_get_or_set_articles_expires(tmp_cache_dir):
    c = FileCache(tmp_cache_dir, default_ttl_sec=1)
    key = cache_key_raw_news("newsapi", "NVDA", "q=test")
    m = MagicMock(return_value=[_article()])
    get_or_set_articles(c, key, ttl_sec=1, fetcher=m)
    assert m.call_count == 1
    time.sleep(1.2)
    get_or_set_articles(c, key, ttl_sec=1, fetcher=m)
    assert m.call_count == 2


def test_get_or_set_draft_impulse_cached(tmp_cache_dir):
    c = FileCache(tmp_cache_dir, default_ttl_sec=3600)
    key = cache_key_draft_aggregate("NVDA", 48, 12.0)
    t0 = datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    scored = [
        ScoredArticle(t0, 0.2, NewsImpactChannel.INCREMENTAL),
    ]

    def compute():
        return draft_impulse(scored, now=t0)

    d1 = get_or_set_draft_impulse(c, key, 3600, compute)
    d2 = get_or_set_draft_impulse(c, key, 3600, compute)
    assert d1.draft_bias_incremental == d2.draft_bias_incremental
    assert d1.articles_incremental == 1


def test_cache_key_draft_aggregate_stable():
    assert "draft|" in cache_key_draft_aggregate("NVDA", 48, 12.0)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--tb=short", "-rA"]))
