"""
Этап E: файловый кэш для сырья новостей и агрегата чернового импульса (TTL, без БД).

Ключи — строки с префиксами ``raw|``, ``draft|``; значения — JSON через ``FileCache``.
Версия формата в ключе: при смене схемы поднимите ``CACHE_KEY_VERSION``.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Callable, List, Optional

from domain import NewsArticle, Ticker

from ..cache import FileCache
from ..types import DraftImpulse

CACHE_KEY_VERSION = "v1"


def cache_key_raw_news(provider_id: str, ticker: str, extra: str = "") -> str:
    """Кэш сырого списка статей с провайдера (например после одного HTTP-запроса)."""
    x = extra.strip() if extra else "-"
    return f"raw|{CACHE_KEY_VERSION}|{provider_id}|{ticker}|{x}"


def cache_key_draft_aggregate(ticker: str, window_hours: int, half_life_hours: float) -> str:
    """Кэш сериализованного ``DraftImpulse`` для окна и параметров затухания."""
    return f"draft|{CACHE_KEY_VERSION}|{ticker}|w{window_hours}|h{half_life_hours}"


def serialize_news_article(a: NewsArticle) -> dict:
    d = {
        "ticker": a.ticker.value,
        "title": a.title,
        "timestamp": a.timestamp.isoformat(),
        "summary": a.summary,
        "link": a.link,
        "publisher": a.publisher,
        "provider_id": a.provider_id,
        "raw_sentiment": a.raw_sentiment,
        "cheap_sentiment": a.cheap_sentiment,
    }
    return d


def deserialize_news_article(d: dict) -> NewsArticle:
    ts_raw = d["timestamp"]
    if isinstance(ts_raw, str):
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    else:
        ts = ts_raw
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    tv = d["ticker"]
    try:
        ticker = Ticker(tv)
    except ValueError:
        ticker = Ticker[tv]
    return NewsArticle(
        ticker=ticker,
        title=d["title"],
        timestamp=ts,
        summary=d.get("summary"),
        link=d.get("link"),
        publisher=d.get("publisher"),
        provider_id=d.get("provider_id"),
        raw_sentiment=d.get("raw_sentiment"),
        cheap_sentiment=d.get("cheap_sentiment"),
    )


def get_or_set_articles(
    cache: FileCache,
    key: str,
    ttl_sec: int,
    fetcher: Callable[[], List[NewsArticle]],
) -> List[NewsArticle]:
    """
    Возвращает список статей из кэша или вызывает ``fetcher``, сохраняет JSON-список.
    """
    hit = cache.get(key)
    if hit is not None:
        if not isinstance(hit, list):
            return []
        return [deserialize_news_article(x) for x in hit]
    articles = fetcher()
    payload = [serialize_news_article(a) for a in articles]
    cache.set(key, payload, ttl_sec=ttl_sec)
    return articles


def get_or_set_draft_impulse(
    cache: FileCache,
    key: str,
    ttl_sec: int,
    compute: Callable[[], DraftImpulse],
) -> DraftImpulse:
    """Кэширует ``DraftImpulse`` (как dict через ``dataclasses.asdict``)."""
    hit = cache.get(key)
    if hit is not None and isinstance(hit, dict):
        try:
            return DraftImpulse(**hit)
        except (TypeError, ValueError):
            pass
    d = compute()
    cache.set(key, asdict(d), ttl_sec=ttl_sec)
    return d


def default_news_file_cache() -> FileCache:
    """``FileCache`` в ``NYSE_CACHE_ROOT`` с TTL по умолчанию для сырья."""
    import config_loader

    root = config_loader.nyse_cache_root()
    ttl = config_loader.news_raw_cache_ttl_sec()
    return FileCache(root, default_ttl_sec=ttl)
