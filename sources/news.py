import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from dataclasses import dataclass

from .models import NewsArticle, Ticker
from .symbols import yfinance_symbol
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class ParsedNewsItem:
    id: str
    title: str
    summary: Optional[str]
    timestamp: datetime
    link: Optional[str]
    publisher: Optional[str]


class Source:
    def __init__(
        self,
        max_per_ticker: int,
        lookback_hours: int,
    ):
        self.max_per_ticker = max_per_ticker
        self.lookback_hours = lookback_hours

    def get_articles(self, tickers: List[Ticker]) -> List[NewsArticle]:
        logger.info("Loading articles: hours=%d", self.lookback_hours)

        all_articles: List[NewsArticle] = []
        for ticker in tickers:
            logger.info("Loading news: ticker=%s", ticker.value)
            articles = self._get_articles_for_ticker(ticker)
            all_articles.extend(articles)

        logger.info("Loaded articles: count=%d", len(all_articles))
        return all_articles

    def _get_articles_for_ticker(self, ticker: Ticker) -> List[NewsArticle]:
        raw_news = (
            yf.Ticker(yfinance_symbol(ticker)).get_news(count=self.max_per_ticker)
            or []
        )

        articles = []
        for item in raw_news:
            article = self._parse_news_item(item, ticker)
            if article is None:
                continue
            articles.append(article)

        filtered = self._filter_articles_by_time(articles, self.lookback_hours)

        logger.info(
            "Loaded ticker articles: ticker=%s count=%d",
            ticker.value,
            len(filtered),
        )

        return self._sort_articles_by_time(filtered)

    def _sort_articles_by_time(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        return sorted(
            articles,
            key=lambda article: article.timestamp,
            reverse=True,
        )

    def _filter_articles_by_time(
        self, articles: List[NewsArticle], hours: int
    ) -> List[NewsArticle]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [article for article in articles if article.timestamp >= cutoff]

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
        )
