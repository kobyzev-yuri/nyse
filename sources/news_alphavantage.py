"""Новости и sentiment через Alpha Vantage NEWS_SENTIMENT (как в lse/alphavantage_fetcher)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from urllib.parse import urlencode

import requests

from domain import NewsArticle, Ticker
from .news_shared import symbol_for_provider

logger = logging.getLogger(__name__)

AV_QUERY_URL = "https://www.alphavantage.co/query"


class Source:
    def __init__(
        self,
        api_key: str,
        *,
        max_articles: int = 50,
        lookback_hours: int = 72,
        timeout_sec: int = 90,
    ):
        self.api_key = api_key
        self.max_articles = max(1, min(max_articles, 1000))
        self.lookback_hours = lookback_hours
        self.timeout_sec = timeout_sec

    def get_articles(self, tickers: List[Ticker]) -> List[NewsArticle]:
        if not tickers:
            return []
        tickers_str = ",".join(symbol_for_provider(t) for t in tickers)
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": tickers_str,
            "apikey": self.api_key,
            "limit": str(self.max_articles),
        }
        url = f"{AV_QUERY_URL}?{urlencode(params)}"
        r = requests.get(url, timeout=self.timeout_sec)
        r.raise_for_status()
        data = r.json()

        if data.get("Error Message"):
            logger.warning("Alpha Vantage error: %s", data["Error Message"])
            return []
        if data.get("Note"):
            logger.warning("Alpha Vantage rate limit / note: %s", data["Note"])
            return []
        if data.get("Information"):
            logger.warning("Alpha Vantage: %s", data["Information"])
            return []

        wanted = {symbol_for_provider(t).upper(): t for t in tickers}
        out: List[NewsArticle] = []
        for item in data.get("feed") or []:
            art = self._row_to_article(item, wanted, tickers)
            if art is not None:
                out.append(art)
        out = self._filter_by_time(out)
        logger.info("Alpha Vantage loaded articles: count=%d", len(out))
        return self._sort_newest_first(out)

    def _row_to_article(
        self,
        item: dict,
        wanted: dict[str, Ticker],
        requested: List[Ticker],
    ) -> Optional[NewsArticle]:
        title = (item.get("title") or "").strip()
        if not title:
            return None

        ts = _parse_time_published(item.get("time_published"))
        if ts is None:
            ts = datetime.now(timezone.utc)

        ticker, raw_sent = _pick_ticker_and_sentiment(item, wanted, requested)
        if ticker is None:
            ticker = requested[0]
            raw_sent = _float_or_none(item.get("overall_sentiment_score"))

        return NewsArticle(
            ticker=ticker,
            title=title,
            summary=(item.get("summary") or "").strip() or None,
            timestamp=ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
            link=(item.get("url") or "").strip() or None,
            publisher=(item.get("source") or "").strip() or None,
            provider_id="alphavantage",
            raw_sentiment=raw_sent,
        )

    def _filter_by_time(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        return [a for a in articles if a.timestamp >= cutoff]

    @staticmethod
    def _sort_newest_first(articles: List[NewsArticle]) -> List[NewsArticle]:
        return sorted(articles, key=lambda a: a.timestamp, reverse=True)


def _parse_time_published(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    s = raw.strip()
    try:
        # 20240219T120000
        dt = datetime.strptime(s, "%Y%m%dT%H%M%S")
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        if s.endswith("Z"):
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _float_or_none(v: object) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pick_ticker_and_sentiment(
    item: dict,
    wanted: dict[str, Ticker],
    requested: List[Ticker],
) -> tuple[Optional[Ticker], Optional[float]]:
    """Выбираем тикер из ticker_sentiment, совпадающий с запросом; иначе None."""
    for ent in item.get("ticker_sentiment") or []:
        if not isinstance(ent, dict):
            continue
        sym = (ent.get("ticker") or "").strip().upper()
        if sym in wanted:
            return wanted[sym], _float_or_none(ent.get("ticker_sentiment_score"))
    return None, _float_or_none(item.get("overall_sentiment_score"))
