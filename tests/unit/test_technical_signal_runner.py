"""run_technical_signal_pipeline — мок LLM."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from config_loader import OpenAISettings
from domain import Candle, Ticker, TickerData, TickerMetrics
from pipeline.cache import FileCache
from pipeline.market_dto import TechnicalSignalResponse
from pipeline.technical_signal_runner import run_technical_signal_pipeline

_SETTINGS = OpenAISettings(
    api_key="test-key",
    base_url="https://example.com/v1",
    model="gpt-test",
    temperature=0.0,
    timeout_sec=10,
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


def _llm_response() -> TechnicalSignalResponse:
    return TechnicalSignalResponse(
        trend_score=0.2,
        momentum_score=0.1,
        mean_reversion_score=0.0,
        breakout_score=0.0,
        volatility_regime=0.4,
        relative_strength_score=0.0,
        market_alignment_score=0.0,
        exhaustion_score=0.2,
        support_resistance_pressure=0.0,
        tradeability_score=0.6,
        confidence=0.7,
        summary=["Uptrend intact.", "Watch volume."],
    )


def test_pipeline_invokes_structured(tmp_path):
    r = _llm_response()
    structured = MagicMock()
    structured.invoke.return_value = r
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    base = datetime(2026, 4, 1, tzinfo=timezone.utc)
    td = _ticker_data(Ticker.NVDA, base=base)
    m = _metrics(Ticker.NVDA)

    out = run_technical_signal_pipeline(
        Ticker.NVDA,
        [td],
        [m],
        cache=FileCache(tmp_path),
        settings=_SETTINGS,
        llm=llm,
        now=datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert out.confidence == pytest.approx(0.7)
    assert out.target_snapshot.data.ticker == Ticker.NVDA
    llm.with_structured_output.assert_called_once()
    structured.invoke.assert_called_once()
