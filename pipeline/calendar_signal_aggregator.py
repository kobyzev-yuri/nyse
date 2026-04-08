"""
Агрегация нескольких ``CalendarSignalResponse`` (несколько батчей событий).

Дословно ``pystockinvest/agent/calendar/agent.py::_aggregate_responses``.
"""

from __future__ import annotations

from statistics import mean
from typing import List

from .calendar_dto import CalendarSignalResponse


def aggregate_calendar_responses(signals: List[CalendarSignalResponse]) -> CalendarSignalResponse:
    if not signals:
        raise ValueError("signals must not be empty")

    if len(signals) == 1:
        return signals[0]

    def avg(values: List[float], weights: List[float]) -> float:
        total_weight = sum(weights)
        if total_weight == 0:
            return mean(values)
        return sum(v * w for v, w in zip(values, weights)) / total_weight

    weights = [max(signal.confidence, 0.01) for signal in signals]
    best_summary_signal = max(signals, key=lambda s: s.confidence)

    return CalendarSignalResponse(
        broad_equity_bias=avg([s.broad_equity_bias for s in signals], weights),
        rates_pressure=avg([s.rates_pressure for s in signals], weights),
        upcoming_event_risk=avg([s.upcoming_event_risk for s in signals], weights),
        inflation_score=avg([s.inflation_score for s in signals], weights),
        employment_score=avg([s.employment_score for s in signals], weights),
        central_bank_score=avg([s.central_bank_score for s in signals], weights),
        confidence=mean([s.confidence for s in signals]),
        summary=best_summary_signal.summary,
        macro_volatility_risk=avg([s.macro_volatility_risk for s in signals], weights),
        economic_activity_score=avg([s.economic_activity_score for s in signals], weights),
    )
