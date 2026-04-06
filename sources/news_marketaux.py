"""Новости через Marketaux v1 (entity + sentiment_score)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode

import requests

from domain import NewsArticle, Ticker
from .news_shared import symbol_for_provider

logger = logging.getLogger(__name__)

MARKETAUX_NEWS_ALL = "https://api.marketaux.com/v1/news/all"


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
        logger.info("Marketaux loaded articles: count=%d", len(out))
        return self._sort_newest_first(out)

    def _fetch_for_ticker(self, ticker: Ticker) -> List[NewsArticle]:
        params: dict[str, str] = {
            "language": "en",
            "limit": str(self.max_articles),
            "filter_entities": "true",
            "api_token": self.api_key,
        }
        if ticker != Ticker.GENERAL:
            params["symbols"] = symbol_for_provider(ticker)
        else:
            params["search"] = "stock market"

        url = f"{MARKETAUX_NEWS_ALL}?{urlencode(params)}"
        r = requests.get(url, timeout=self.timeout_sec)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data") or []
        articles: List[NewsArticle] = []
        for row in rows:
            art = self._row_to_article(row, ticker)
            if art is not None:
                articles.append(art)
        return self._filter_by_time(articles)

    def _row_to_article(self, row: dict, ticker: Ticker) -> Optional[NewsArticle]:
        title = (row.get("title") or "").strip()
        if not title:
            return None
        pub = row.get("published_at") or ""
        if not pub:
            return None
        ts = _parse_iso_z(pub)
        if ts is None:
            return None
        sym = symbol_for_provider(ticker) if ticker != Ticker.GENERAL else None
        raw_sent = _sentiment_for_symbol(row.get("entities") or [], sym)
        return NewsArticle(
            ticker=ticker,
            title=title,
            summary=(row.get("description") or row.get("snippet") or "").strip()
            or None,
            timestamp=ts,
            link=(row.get("url") or "").strip() or None,
            publisher=(row.get("source") or "").strip() or None,
            provider_id="marketaux",
            raw_sentiment=raw_sent,
        )

    def _filter_by_time(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        return [a for a in articles if a.timestamp >= cutoff]

    @staticmethod
    def _sort_newest_first(articles: List[NewsArticle]) -> List[NewsArticle]:
        return sorted(articles, key=lambda a: a.timestamp, reverse=True)


def _parse_iso_z(s: str) -> Optional[datetime]:
    s = s.strip()
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _sentiment_for_symbol(
    entities: list, symbol: Optional[str]
) -> Optional[float]:
    if not symbol:
        # GENERAL: среднее по entity sentiment, если есть
        scores = []
        for e in entities:
            if isinstance(e, dict) and e.get("sentiment_score") is not None:
                try:
                    scores.append(float(e["sentiment_score"]))
                except (TypeError, ValueError):
                    continue
        if not scores:
            return None
        return sum(scores) / len(scores)
    sym_u = symbol.upper()
    for e in entities:
        if not isinstance(e, dict):
            continue
        if (e.get("symbol") or "").upper() == sym_u:
            try:
                return float(e["sentiment_score"])
            except (TypeError, ValueError):
                return None
    return None
