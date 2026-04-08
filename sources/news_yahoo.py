"""Новости только через Yahoo Finance (yfinance.get_news)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import yfinance as yf

from domain import NewsArticle, Ticker
from .symbols import yfinance_symbol

logger = logging.getLogger(__name__)


class YahooSource:
    """Один провайдер: Yahoo / yfinance (provider_id=yfinance)."""

    def __init__(
        self,
        max_per_ticker: int,
        lookback_hours: int,
    ):
        self.max_per_ticker = max_per_ticker
        self.lookback_hours = lookback_hours

    def get_articles(self, tickers: List[Ticker]) -> List[NewsArticle]:
        logger.info("Yahoo: loading articles hours=%d", self.lookback_hours)
        all_articles: List[NewsArticle] = []
        for ticker in tickers:
            logger.info("Yahoo: ticker=%s", ticker.value)
            all_articles.extend(self._get_articles_for_ticker(ticker))
        logger.info("Yahoo: total count=%d", len(all_articles))
        return all_articles

    def _get_articles_for_ticker(self, ticker: Ticker) -> List[NewsArticle]:
        raw_news = (
            yf.Ticker(yfinance_symbol(ticker)).get_news(count=self.max_per_ticker)
            or []
        )
        articles: List[NewsArticle] = []
        for item in raw_news:
            article = self._parse_news_item(item, ticker)
            if article is not None:
                articles.append(article)
        filtered = self._filter_articles_by_time(articles, self.lookback_hours)
        logger.info(
            "Yahoo: ticker=%s count=%d",
            ticker.value,
            len(filtered),
        )
        return self._sort_articles_by_time(filtered)

    def _sort_articles_by_time(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        return sorted(articles, key=lambda a: a.timestamp, reverse=True)

    def _filter_articles_by_time(
        self, articles: List[NewsArticle], hours: int
    ) -> List[NewsArticle]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [a for a in articles if a.timestamp >= cutoff]

    def _parse_news_item(self, item, ticker: Ticker) -> Optional[NewsArticle]:
        content = item.get("content", {})
        title = content.get("title")
        pub_date = content.get("pubDate")
        if not title or not pub_date:
            return None
        provider = content.get("provider") or {}
        click = content.get("clickThroughUrl") or {}
        canonical = content.get("canonicalUrl") or {}
        return NewsArticle(
            ticker=ticker,
            title=title,
            summary=content.get("summary"),
            timestamp=datetime.fromisoformat(pub_date.replace("Z", "+00:00")),
            link=click.get("url") or canonical.get("url"),
            publisher=provider.get("displayName"),
            provider_id="yfinance",
        )
