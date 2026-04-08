"""Промпт technical / market (как pystockinvest agent/market)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from domain import Candle, Ticker, TickerData, TickerMetrics
from pipeline.technical_signal_prompt import (
    PROMPT_VERSION,
    build_technical_signal_messages,
    technical_agent_input_from_domain,
)


def _candle_row(t: datetime, close: float) -> Candle:
    o = close - 0.05
    return Candle(
        time=t,
        open=o,
        high=close + 0.1,
        low=close - 0.1,
        close=close,
        volume=1_000_000.0,
    )


def _ticker_data(ticker: Ticker, *, base: datetime) -> TickerData:
    daily = [_candle_row(base + timedelta(days=i), 100.0 + i * 0.1) for i in range(25)]
    hourly = [_candle_row(base + timedelta(hours=i), 100.0 + i * 0.01) for i in range(25)]
    return TickerData(
        ticker=ticker,
        current_price=daily[-1].close,
        daily_candles=daily,
        hourly_candles=hourly,
    )


def _metrics(ticker: Ticker) -> TickerMetrics:
    return TickerMetrics(
        ticker=ticker,
        perf_week=1.0,
        rsi_14=55.0,
        sma20_pct=2.0,
        sma50_pct=1.0,
        atr=2.5,
        relative_volume=1.1,
        beta=1.2,
    )


def test_technical_agent_input_context_tickers_distinct():
    """Контекстные блоки должны иметь свой ``ticker``, не целевой (shadowing fix)."""
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    td_nvda = _ticker_data(Ticker.NVDA, base=base)
    td_qqq = _ticker_data(Ticker.QQQ, base=base)
    m_nvda = _metrics(Ticker.NVDA)
    m_qqq = _metrics(Ticker.QQQ)
    inp = technical_agent_input_from_domain(
        Ticker.NVDA,
        [td_nvda, td_qqq],
        [m_nvda, m_qqq],
        current_time=datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert inp.target.ticker == "NVDA"
    assert len(inp.context) == 1
    assert inp.context[0].ticker == "QQQ"


def test_build_messages_payload_shape():
    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    td_nvda = _ticker_data(Ticker.NVDA, base=base)
    m_nvda = _metrics(Ticker.NVDA)
    msgs = build_technical_signal_messages(
        Ticker.NVDA,
        [td_nvda],
        [m_nvda],
        now=datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert len(msgs) == 2
    user = msgs[1]["content"]
    idx = user.index("Input:\n") + len("Input:\n")
    payload = json.loads(user[idx:])
    assert payload["target"]["ticker"] == "NVDA"
    assert "candle_features" in payload["target"]
    assert "metrics" in payload["target"]
    assert payload["context"] == []


def test_prompt_version():
    assert isinstance(PROMPT_VERSION, str) and len(PROMPT_VERSION) >= 1
