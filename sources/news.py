"""
Публичный вход для новостей: Yahoo + опционально NewsAPI, Marketaux, Alpha Vantage, RSS.

Реализация слияния: ``news_merge.fetch_merged_news``; Yahoo-одиночка: ``news_yahoo.YahooSource``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from domain import NewsArticle, Ticker

from .news_merge import fetch_merged_news


@dataclass
class ParsedNewsItem:
    """Совместимость со старым API (почти не используется)."""

    id: str
    title: str
    summary: Optional[str]
    timestamp: datetime
    link: Optional[str]
    publisher: Optional[str]


class Source:
    """
    Загрузка новостей для тикеров.

    Источники: **всегда** Yahoo; дополнительно — при ключах в ``config.env``:
    ``NEWSAPI_KEY``, ``MARKETAUX_API_KEY``, ``ALPHAVANTAGE_KEY``;
    RSS — ``NYSE_NEWS_RSS_URLS`` (через запятую), только если в запросе **один** тикер.
    """

    def __init__(
        self,
        max_per_ticker: int,
        lookback_hours: int,
    ):
        self.max_per_ticker = max_per_ticker
        self.lookback_hours = lookback_hours

    def get_articles(self, tickers: List[Ticker]) -> List[NewsArticle]:
        return fetch_merged_news(
            tickers,
            max_per_ticker=self.max_per_ticker,
            lookback_hours=self.lookback_hours,
        )
