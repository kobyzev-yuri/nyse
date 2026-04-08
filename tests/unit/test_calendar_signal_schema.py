"""calendar_signal_schema: JSON → CalendarSignalResponse → domain.CalendarSignal."""

from __future__ import annotations

import json

import pytest

from domain import CalendarSignal
from pipeline.calendar_signal_schema import (
    CalendarSignalResponse,
    llm_response_to_calendar_signal,
    parse_calendar_signal_json,
)


def _sample_dict():
    return {
        "broad_equity_bias": 0.2,
        "rates_pressure": -0.1,
        "macro_volatility_risk": 0.3,
        "upcoming_event_risk": 0.4,
        "inflation_score": 0.0,
        "employment_score": 0.1,
        "economic_activity_score": -0.05,
        "central_bank_score": 0.0,
        "confidence": 0.75,
        "summary": ["First line.", "Second line."],
    }


def test_parse_and_domain():
    r = parse_calendar_signal_json(json.dumps(_sample_dict()))
    assert isinstance(r, CalendarSignalResponse)
    d = llm_response_to_calendar_signal(r)
    assert isinstance(d, CalendarSignal)
    assert d.broad_equity_bias == pytest.approx(0.2)
    assert len(d.summary) == 2


def test_summary_too_short_raises():
    bad = _sample_dict()
    bad["summary"] = ["only one"]
    with pytest.raises(Exception):
        parse_calendar_signal_json(json.dumps(bad))
