"""
Интеграция: внешние источники (yfinance, Finviz, Investing.com) на GAME_5M тикерах.

Приоритет: первичный тикер из TICKERS_FAST (обычно SNDK).
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_candles_yfinance_daily(game5m_primary):
    """Daily свечи для первичного GAME_5M тикера."""
    pytest.importorskip("yfinance")
    from sources.candles import Source

    src = Source(with_prepostmarket=False)
    out = src.get_daily_candles([game5m_primary], days=7)
    assert game5m_primary in out, f"yfinance не вернул свечей для {game5m_primary.value}"
    candles = out[game5m_primary]
    assert len(candles) >= 1
    c = candles[-1]
    assert c.open > 0 and c.close > 0


@pytest.mark.integration
def test_candles_yfinance_hourly(game5m_primary):
    """Hourly свечи для первичного GAME_5M тикера."""
    pytest.importorskip("yfinance")
    from sources.candles import Source

    out = Source(with_prepostmarket=False).get_hourly_candles([game5m_primary], days=5)
    assert game5m_primary in out
    candles = out[game5m_primary]
    if not candles:
        pytest.skip(f"Yahoo не вернул часовых свечей для {game5m_primary.value}")
    assert candles[-1].close > 0


@pytest.mark.integration
def test_candles_all_game5m(game5m_tickers):
    """Daily свечи для всех GAME_5M тикеров — хотя бы половина должна вернуть данные."""
    pytest.importorskip("yfinance")
    from sources.candles import Source

    out = Source(with_prepostmarket=False).get_daily_candles(game5m_tickers, days=7)
    found = [t for t in game5m_tickers if out.get(t)]
    print(f"\nCandles OK: {[t.value for t in found]}")
    print(f"Candles missing: {[t.value for t in game5m_tickers if t not in found]}")
    assert len(found) >= len(game5m_tickers) // 2, \
        f"Менее половины GAME_5M тикеров вернули свечи: {[t.value for t in found]}"


@pytest.mark.integration
def test_metrics_finviz_primary(game5m_primary):
    """Finviz-метрики для первичного GAME_5M тикера."""
    pytest.importorskip("finvizfinance")
    from sources.metrics import Source

    try:
        metrics = Source().get_metrics([game5m_primary])
    except Exception as exc:
        pytest.skip(f"Finviz недоступен: {exc}")

    m = metrics[0]
    assert m.ticker == game5m_primary
    assert m.rsi_14 > 0
    assert m.atr > 0
    print(f"\n[{game5m_primary.value}] RSI={m.rsi_14:.1f}  ATR={m.atr:.2f}  "
          f"SMA20={m.sma20_pct:+.1f}%  RelVol={m.relative_volume:.2f}")


@pytest.mark.integration
def test_metrics_finviz_all_game5m(game5m_tickers):
    """Finviz-метрики для всех GAME_5M тикеров."""
    pytest.importorskip("finvizfinance")
    from sources.metrics import Source

    try:
        metrics = Source().get_metrics(game5m_tickers)
    except Exception as exc:
        pytest.skip(f"Finviz недоступен: {exc}")

    by_ticker = {m.ticker: m for m in metrics}
    print()
    for t in game5m_tickers:
        if t in by_ticker:
            m = by_ticker[t]
            print(f"  {t.value:6s}  RSI={m.rsi_14:.0f}  "
                  f"SMA20={m.sma20_pct:+.1f}%  ATR={m.atr:.2f}")
        else:
            print(f"  {t.value:6s}  — нет метрик")

    found = [t for t in game5m_tickers if t in by_ticker]
    assert len(found) >= 1, "Finviz не вернул метрик ни для одного GAME_5M тикера"


@pytest.mark.integration
def test_earnings_yfinance(game5m_primary):
    """Дата earnings для первичного GAME_5M тикера."""
    pytest.importorskip("yfinance")
    from sources.earnings import Source

    rows = Source().get_closest_earnings([game5m_primary])
    if not rows:
        pytest.skip(f"Yahoo не вернул дат earnings для {game5m_primary.value}")
    e = rows[0]
    assert e.ticker == game5m_primary
    assert e.next_earnings_date > e.prev_earnings_date
    print(f"\n[{game5m_primary.value}] next earnings: {e.next_earnings_date.date()}")


@pytest.mark.integration
def test_calendar_investing(load_nyse_config):
    """Экономический календарь (USD события)."""
    from domain import Currency
    from sources.ecalendar import Source

    ev = Source([Currency.USD]).get_calendar()
    assert isinstance(ev, list)
    if ev:
        assert ev[0].name
        assert ev[0].currency == Currency.USD


@pytest.mark.integration
def test_news_yahoo_game5m_primary(game5m_primary):
    """Новости Yahoo для первичного GAME_5M тикера."""
    pytest.importorskip("yfinance")
    from sources.news import Source

    articles = Source(max_per_ticker=10, lookback_hours=24 * 7).get_articles([game5m_primary])
    assert isinstance(articles, list)
    if not articles:
        pytest.skip(f"Yahoo не вернул новостей для {game5m_primary.value}")
    for a in articles[:5]:
        assert a.title.strip()
        assert a.ticker == game5m_primary
    print(f"\n[{game5m_primary.value}] {len(articles)} articles, "
          f"last: '{articles[0].title[:60]}'")
