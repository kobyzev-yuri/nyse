"""Новости через NewsAPI v2 (https://newsapi.org)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode

import requests

from domain import NewsArticle, Ticker
from .news_shared import symbol_for_provider

logger = logging.getLogger(__name__)

NEWSAPI_EVERYTHING = "https://newsapi.org/v2/everything"


class Source:
    def __init__(
        self,
        api_key: str,
        *,
        max_articles: int = 50,
        lookback_hours: int = 48,
        timeout_sec: int = 30,
    ):
        self.api_key = api_key
        self.max_articles = max(1, min(max_articles, 100))
        self.lookback_hours = lookback_hours
        self.timeout_sec = timeout_sec

    def get_articles(self, tickers: List[Ticker]) -> List[NewsArticle]:
        if not tickers:
            return []
        out: List[NewsArticle] = []
        for t in tickers:
            out.extend(self._fetch_for_ticker(t))
        logger.info("NewsAPI loaded articles: count=%d", len(out))
        return self._sort_newest_first(out)

    def _fetch_for_ticker(self, ticker: Ticker) -> List[NewsArticle]:
        if ticker == Ticker.GENERAL:
            q = "stock market OR earnings OR federal reserve"
        else:
            q = symbol_for_provider(ticker)

        now = datetime.now(timezone.utc)
        from_dt = now - timedelta(hours=self.lookback_hours)
        params = {
            "q": q,
            "from": from_dt.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "to": now.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": self.max_articles,
            "apiKey": self.api_key,
        }
        url = f"{NEWSAPI_EVERYTHING}?{urlencode(params)}"
        r = requests.get(url, timeout=self.timeout_sec)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "ok":
            logger.warning("NewsAPI error: %s", data)
            return []

        articles: List[NewsArticle] = []
        for row in data.get("articles") or []:
            art = self._row_to_article(row, ticker)
            if art is not None:
                articles.append(art)
        return self._filter_by_time(articles)

    def _row_to_article(self, row: dict, ticker: Ticker) -> Optional[NewsArticle]:
        title = (row.get("title") or "").strip()
        if not title:
            return None
        pub = row.get("publishedAt") or ""
        if not pub:
            return None
        ts = _parse_newsapi_time(pub)
        if ts is None:
            return None
        src = row.get("source") or {}
        publisher = src.get("name") if isinstance(src, dict) else None
        return NewsArticle(
            ticker=ticker,
            title=title,
            summary=(row.get("description") or "").strip() or None,
            timestamp=ts,
            link=(row.get("url") or "").strip() or None,
            publisher=publisher,
            provider_id="newsapi",
        )

    def _filter_by_time(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        return [a for a in articles if a.timestamp >= cutoff]

    @staticmethod
    def _sort_newest_first(articles: List[NewsArticle]) -> List[NewsArticle]:
        return sorted(articles, key=lambda a: a.timestamp, reverse=True)


def _parse_newsapi_time(s: str) -> Optional[datetime]:
    s = s.strip()
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except ValueError:
        return None
