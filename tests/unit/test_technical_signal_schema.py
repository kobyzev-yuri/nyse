"""technical_signal_schema: bias formula + domain mapping."""

from __future__ import annotations

import json

import pytest

from domain import TechnicalSnapshot, Ticker, TickerData, TickerMetrics
from pipeline.market_dto import TechnicalSignalResponse
from pipeline.technical_signal_schema import (
    llm_response_to_technical_signal,
    parse_technical_signal_json,
    technical_bias_from_response,
)


def test_bias_formula_matches_pystockinvest_weights():
    r = TechnicalSignalResponse(
        trend_score=1.0,
        momentum_score=0.0,
        mean_reversion_score=0.0,
        breakout_score=0.0,
        volatility_regime=0.0,
        relative_strength_score=0.0,
        market_alignment_score=0.0,
        exhaustion_score=0.0,
        support_resistance_pressure=0.0,
        tradeability_score=0.5,
        confidence=0.5,
        summary=["a", "b"],
    )
    assert technical_bias_from_response(r) == pytest.approx(0.30 * 1.0)


def test_llm_to_domain():
    d = {
        "trend_score": 0.0,
        "momentum_score": 0.0,
        "mean_reversion_score": 0.0,
        "breakout_score": 0.0,
        "volatility_regime": 0.5,
        "relative_strength_score": 0.0,
        "market_alignment_score": 0.0,
        "exhaustion_score": 0.0,
        "support_resistance_pressure": 0.0,
        "tradeability_score": 0.5,
        "confidence": 0.6,
        "summary": ["x", "y"],
    }
    resp = parse_technical_signal_json(json.dumps(d))
    snap = TechnicalSnapshot(
        data=TickerData(
            ticker=Ticker.NVDA,
            current_price=100.0,
            daily_candles=[],
            hourly_candles=[],
        ),
        metrics=TickerMetrics(
            ticker=Ticker.NVDA,
            perf_week=0.0,
            rsi_14=50.0,
            sma20_pct=0.0,
            sma50_pct=0.0,
            atr=1.0,
            relative_volume=1.0,
            beta=1.0,
        ),
    )
    ts = llm_response_to_technical_signal(resp, snap)
    assert ts.confidence == pytest.approx(0.6)
    assert len(ts.summary) == 2
