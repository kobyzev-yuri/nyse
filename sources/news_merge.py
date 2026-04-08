"""
Объединение новостей: Yahoo + опционально NewsAPI, Marketaux, Alpha Vantage, RSS.

Дедуп и окно времени: ``pipeline.ingest.merge_news_articles``.
Ключи API читаются из ``config_loader`` (те же, что в lse).
"""

from __future__ import annotations

import logging
from typing import List

from domain import NewsArticle, Ticker
from pipeline.ingest import merge_news_articles

log = logging.getLogger(__name__)


def _per_ticker_cap(
    articles: List[NewsArticle],
    tickers: List[Ticker],
    max_per_ticker: int,
) -> List[NewsArticle]:
    out: List[NewsArticle] = []
    for t in tickers:
        sub = [a for a in articles if a.ticker == t]
        sub.sort(key=lambda a: a.timestamp, reverse=True)
        out.extend(sub[: max(1, max_per_ticker)])
    return out


def fetch_merged_news(
    tickers: List[Ticker],
    max_per_ticker: int,
    lookback_hours: int,
) -> List[NewsArticle]:
    """
    Загружает все доступные источники, объединяет и ограничивает число статей на тикер.

    Всегда: Yahoo (yfinance).
    Если заданы ключи в config.env: NewsAPI, Marketaux, Alpha Vantage.
    Если ``NYSE_NEWS_RSS_URLS``: RSS (только при одном тикере в запросе — макро-ленты
    привязываются к этому тикеру).
    """
    import config_loader

    config_loader.load_config_env()

    if not tickers:
        return []

    batches: List[List[NewsArticle]] = []
    fetch_cap = max(max_per_ticker, 25)

    # --- Yahoo (обязательно) ---
    try:
        from .news_yahoo import YahooSource

        yh = YahooSource(max_per_ticker=fetch_cap, lookback_hours=lookback_hours)
        batches.append(yh.get_articles(tickers))
    except Exception as exc:
        log.warning("Yahoo news failed: %s", exc)

    # --- NewsAPI ---
    k_newsapi = config_loader.get_newsapi_key()
    if k_newsapi:
        try:
            from .news_newsapi import Source as NewsAPISource

            batches.append(
                NewsAPISource(
                    k_newsapi,
                    max_articles=min(100, fetch_cap * len(tickers)),
                    lookback_hours=lookback_hours,
                ).get_articles(tickers)
            )
        except Exception as exc:
            log.warning("NewsAPI failed: %s", exc)

    # --- Marketaux ---
    k_mx = config_loader.get_marketaux_api_key()
    if k_mx:
        try:
            from .news_marketaux import Source as MarketauxSource

            batches.append(
                MarketauxSource(
                    k_mx,
                    max_articles=min(100, fetch_cap),
                    lookback_hours=lookback_hours,
                ).get_articles(tickers)
            )
        except Exception as exc:
            log.warning("Marketaux failed: %s", exc)

    # --- Alpha Vantage (один запрос на список тикеров) ---
    k_av = config_loader.get_alphavantage_api_key()
    if k_av:
        try:
            from .news_alphavantage import Source as AVSource

            batches.append(
                AVSource(
                    k_av,
                    max_articles=min(200, fetch_cap * max(1, len(tickers))),
                    lookback_hours=lookback_hours,
                ).get_articles(tickers)
            )
        except Exception as exc:
            log.warning("Alpha Vantage news failed: %s", exc)

    # --- RSS: одна тема — один тикер (иначе дублирование по N тикерам) ---
    rss_urls = config_loader.get_news_rss_feed_urls()
    if rss_urls and len(tickers) == 1:
        primary = tickers[0]
        from .news_rss import Source as RssSource

        for url in rss_urls:
            try:
                batches.append(
                    RssSource(
                        url,
                        ticker=primary,
                        lookback_hours=lookback_hours,
                        max_items=60,
                    ).get_articles([primary])
                )
            except Exception as exc:
                log.warning("RSS %s failed: %s", url[:48], exc)
    elif rss_urls and len(tickers) > 1:
        log.debug("RSS skipped: len(tickers)=%d > 1", len(tickers))

    if not batches:
        return []

    merged = merge_news_articles(*batches, lookback_hours=float(lookback_hours))
    capped = _per_ticker_cap(merged, tickers, max_per_ticker)
    log.info(
        "Merged news: tickers=%s total_after_cap=%d (sources tried: %d)",
        [t.value for t in tickers],
        len(capped),
        len(batches),
    )
    return capped
