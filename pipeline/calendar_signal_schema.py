"""
Уровень 6a: разбор structured ответа LLM календаря → ``domain.CalendarSignal``.

Модель ответа — ``pipeline/calendar_dto.py::CalendarSignalResponse`` (как в pystockinvest ``agent/calendar``).
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
    runpy.run_module("pipeline.calendar_signal_schema", run_name="__main__")
    raise SystemExit(0)

from domain import CalendarSignal

from .calendar_dto import CalendarSignalResponse

# Реэкспорт DTO
from .calendar_dto import CalendarAgentInput, CalendarEventInput  # noqa: F401


def strip_json_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def parse_calendar_signal_json(raw: str) -> CalendarSignalResponse:
    text = strip_json_fence(raw)
    data: Any = json.loads(text)
    if isinstance(data, dict):
        return CalendarSignalResponse.model_validate(data)
    raise ValueError("JSON must be an object")


def llm_response_to_calendar_signal(response: CalendarSignalResponse) -> CalendarSignal:
    """Как ``CalendarAgent._to_domain_signal`` в pystockinvest."""
    return CalendarSignal(
        broad_equity_bias=response.broad_equity_bias,
        rates_pressure=response.rates_pressure,
        macro_volatility_risk=response.macro_volatility_risk,
        upcoming_event_risk=response.upcoming_event_risk,
        inflation_score=response.inflation_score,
        employment_score=response.employment_score,
        economic_activity_score=response.economic_activity_score,
        central_bank_score=response.central_bank_score,
        confidence=response.confidence,
        summary=list(response.summary),
    )


if __name__ == "__main__":
    sample = {
        "broad_equity_bias": 0.1,
        "rates_pressure": 0.0,
        "macro_volatility_risk": 0.3,
        "upcoming_event_risk": 0.2,
        "inflation_score": 0.0,
        "employment_score": 0.0,
        "economic_activity_score": 0.0,
        "central_bank_score": 0.0,
        "confidence": 0.7,
        "summary": ["One.", "Two."],
    }
    r = parse_calendar_signal_json(json.dumps(sample))
    d = llm_response_to_calendar_signal(r)
    print("domain summary len:", len(d.summary), "bias:", d.broad_equity_bias)
