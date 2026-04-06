"""
Уровень 0: слияние списков новостей из разных источников, дедуп, окно времени.

Дедуп:
- при непустом ``link`` — нормализованный URL (схема/host/query в каноническом виде);
- иначе — составной ключ: провайдер, тикер, нормализованный заголовок, час публикации (UTC).

При коллизии ключей оставляем статью с более поздним ``timestamp``; при равенстве — с заполненным ``raw_sentiment``.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from domain import NewsArticle


def merge_news_articles(
    *batches: Iterable[NewsArticle],
    lookback_hours: float = 72.0,
    reference_time: Optional[datetime] = None,
) -> List[NewsArticle]:
    """
    Объединяет произвольное число итерируемых наборов ``NewsArticle``,
    отбрасывает статьи старее ``lookback_hours`` от ``reference_time`` (UTC),
    дедуплицирует и сортирует по убыванию ``timestamp``.
    """
    now = reference_time or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    cutoff = now - timedelta(hours=lookback_hours)
    merged: list[NewsArticle] = []
    for batch in batches:
        merged.extend(batch)

    fresh = [a for a in merged if _as_utc(a.timestamp) >= cutoff]
    by_key: dict[str, NewsArticle] = {}
    for a in fresh:
        key = _dedup_key(a)
        prev = by_key.get(key)
        if prev is None:
            by_key[key] = a
        else:
            by_key[key] = _prefer_article(prev, a)

    out = list(by_key.values())
    out.sort(key=lambda x: _as_utc(x.timestamp), reverse=True)
    return out


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _normalize_title(title: str) -> str:
    return " ".join(title.strip().lower().split())


def _canonical_url(url: str) -> str:
    raw = url.strip()
    p = urlparse(raw)
    if not p.netloc:
        return raw.lower()
    scheme = (p.scheme or "https").lower()
    netloc = p.netloc.lower()
    path = (p.path or "").rstrip("/") or "/"
    query = urlencode(sorted(parse_qsl(p.query)))
    return urlunparse((scheme, netloc, path, "", query, ""))


def _dedup_key(a: NewsArticle) -> str:
    link = (a.link or "").strip()
    if link:
        try:
            return "url:" + _canonical_url(link)
        except Exception:
            return "url_raw:" + link.lower()

    prov = (a.provider_id or "na").strip()
    hour = _as_utc(a.timestamp).strftime("%Y%m%d%H")
    title = _normalize_title(a.title)[:240]
    return f"noguid:{prov}|{a.ticker.value}|{title}|{hour}"


def _prefer_article(a: NewsArticle, b: NewsArticle) -> NewsArticle:
    ta, tb = _as_utc(a.timestamp), _as_utc(b.timestamp)
    if ta != tb:
        return a if ta > tb else b
    if (a.raw_sentiment is not None) != (b.raw_sentiment is not None):
        return a if a.raw_sentiment is not None else b
    return a


def with_normalized_link(a: NewsArticle) -> NewsArticle:
    """Возвращает копию статьи с каноническим ``link``, если он был задан."""
    link = (a.link or "").strip()
    if not link:
        return a
    try:
        canon = _canonical_url(link)
        if canon == link:
            return a
        return replace(a, link=canon)
    except Exception:
        return a
