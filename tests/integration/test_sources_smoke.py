"""Интеграция: все внешние источники (сеть). Без API-ключей (кроме уже заданных в окружении)."""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_candles_yfinance_daily(load_nyse_config):
    pytest.importorskip("yfinance")
    from domain import Ticker
    from sources.candles import Source

    src = Source(with_prepostmarket=False)
    out = src.get_daily_candles([Ticker.NVDA], days=7)
    assert Ticker.NVDA in out
    candles = out[Ticker.NVDA]
    assert len(candles) >= 1
    c0 = candles[-1]
    assert c0.open > 0 and c0.close > 0


@pytest.mark.integration
def test_candles_yfinance_hourly(load_nyse_config):
    pytest.importorskip("yfinance")
    from domain import Ticker
    from sources.candles import Source

    out = Source(with_prepostmarket=False).get_hourly_candles([Ticker.NVDA], days=5)
    assert Ticker.NVDA in out
    candles = out[Ticker.NVDA]
    if not candles:
        pytest.skip("Yahoo не вернул часовых свечей")
    c0 = candles[-1]
    assert c0.open > 0 and c0.close > 0


@pytest.mark.integration
def test_metrics_finviz(load_nyse_config):
    pytest.importorskip("finvizfinance")
    from domain import Ticker
    from sources.metrics import Source

    m = Source().get_metrics([Ticker.NVDA])[0]
    assert m.ticker == Ticker.NVDA
    assert m.rsi_14 is not None


@pytest.mark.integration
def test_earnings_yfinance(load_nyse_config):
    pytest.importorskip("yfinance")
    from domain import Ticker
    from sources.earnings import Source

    rows = Source().get_closest_earnings([Ticker.NVDA])
    if not rows:
        pytest.skip("Yahoo не вернул дат earnings для NVDA")
    e = rows[0]
    assert e.ticker == Ticker.NVDA
    assert e.next_earnings_date > e.prev_earnings_date


@pytest.mark.integration
def test_calendar_investing(load_nyse_config):
    from domain import Currency
    from sources.ecalendar import Source

    ev = Source([Currency.USD]).get_calendar()
    assert isinstance(ev, list)
    if ev:
        assert ev[0].name
        assert ev[0].currency == Currency.USD


@pytest.mark.integration
def test_news_yahoo(load_nyse_config):
    pytest.importorskip("yfinance")
    from domain import Ticker
    from sources.news import Source

    articles = Source(max_per_ticker=10, lookback_hours=24 * 7).get_articles([Ticker.NVDA])
    assert isinstance(articles, list)
    if not articles:
        pytest.skip("Yahoo не вернул новостей за окно")
    for a in articles[:5]:
        assert a.title.strip()
        assert a.ticker == Ticker.NVDA
