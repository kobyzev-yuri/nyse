"""
Structured ответ LLM «market/technical» → ``domain.TechnicalSignal``.

Формула ``bias`` — как ``pystockinvest/agent/market/agent.py::_technical_bias``.
"""

from __future__ import annotations

import json
import re
import runpy
import sys
from pathlib import Path
from typing import Any

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.technical_signal_schema", run_name="__main__")
    raise SystemExit(0)

from domain import TechnicalSignal, TechnicalSnapshot

from .market_dto import TechnicalSignalResponse

# Реэкспорт DTO
from .market_dto import (  # noqa: F401
    CandleFeaturesInput,
    MetricsInput,
    TechnicalAgentInput,
    TechnicalTickerInput,
)


def strip_json_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def parse_technical_signal_json(raw: str) -> TechnicalSignalResponse:
    text = strip_json_fence(raw)
    data: Any = json.loads(text)
    if isinstance(data, dict):
        return TechnicalSignalResponse.model_validate(data)
    raise ValueError("JSON must be an object")


def technical_bias_from_response(resp: TechnicalSignalResponse) -> float:
    exhaustion_penalty = resp.exhaustion_score * (1.0 if resp.trend_score >= 0 else -1.0)
    return (
        0.30 * resp.trend_score
        + 0.20 * resp.momentum_score
        + 0.15 * resp.breakout_score
        + 0.15 * resp.relative_strength_score
        + 0.10 * resp.support_resistance_pressure
        + 0.10 * resp.market_alignment_score
        - 0.10 * exhaustion_penalty
    )


def llm_response_to_technical_signal(
    response: TechnicalSignalResponse,
    target_snapshot: TechnicalSnapshot,
) -> TechnicalSignal:
    """Как ``MarketAgent._to_domain_signal`` в pystockinvest."""
    bias = technical_bias_from_response(response)
    return TechnicalSignal(
        bias=round(bias, 4),
        trend_score=response.trend_score,
        momentum_score=response.momentum_score,
        mean_reversion_score=response.mean_reversion_score,
        breakout_score=response.breakout_score,
        volatility_regime=response.volatility_regime,
        relative_strength_score=response.relative_strength_score,
        market_alignment_score=response.market_alignment_score,
        exhaustion_score=response.exhaustion_score,
        support_resistance_pressure=response.support_resistance_pressure,
        tradeability_score=response.tradeability_score,
        confidence=response.confidence,
        target_snapshot=target_snapshot,
        summary=list(response.summary),
    )


if __name__ == "__main__":
    sample = {
        "trend_score": 0.1,
        "momentum_score": 0.0,
        "mean_reversion_score": 0.0,
        "breakout_score": 0.0,
        "volatility_regime": 0.5,
        "relative_strength_score": 0.0,
        "market_alignment_score": 0.0,
        "exhaustion_score": 0.0,
        "support_resistance_pressure": 0.0,
        "tradeability_score": 0.6,
        "confidence": 0.7,
        "summary": ["A.", "B."],
    }
    r = parse_technical_signal_json(json.dumps(sample))
    from domain import Ticker, TickerData, TickerMetrics
    from datetime import datetime, timezone

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
    ts = llm_response_to_technical_signal(r, snap)
    print("bias:", ts.bias)
