"""run_calendar_signal_pipeline — мок LLM, без сети."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from config_loader import OpenAISettings
from domain import CalendarEvent, CalendarEventImportance, Currency
from pipeline.cache import FileCache
from pipeline.calendar_dto import CalendarSignalResponse
from pipeline.calendar_signal_runner import run_calendar_signal_pipeline

_SETTINGS = OpenAISettings(
    api_key="test-key",
    base_url="https://example.com/v1",
    model="gpt-test",
    temperature=0.0,
    timeout_sec=10,
)


def _event() -> CalendarEvent:
    return CalendarEvent(
        name="CPI",
        category="inflation",
        time=datetime(2026, 4, 8, 14, 0, 0, tzinfo=timezone.utc),
        country="US",
        currency=Currency.USD,
        importance=CalendarEventImportance.HIGH,
        actual=None,
        forecast="3.0",
        previous="2.9",
    )


def _response_dict():
    return {
        "broad_equity_bias": 0.1,
        "rates_pressure": 0.0,
        "macro_volatility_risk": 0.2,
        "upcoming_event_risk": 0.3,
        "inflation_score": 0.0,
        "employment_score": 0.0,
        "economic_activity_score": 0.0,
        "central_bank_score": 0.0,
        "confidence": 0.8,
        "summary": ["Macro calm.", "Watch releases."],
    }


def test_empty_events_neutral_no_llm(tmp_path):
    llm = MagicMock()
    out = run_calendar_signal_pipeline(
        [],
        "NVDA",
        cache=FileCache(tmp_path),
        settings=_SETTINGS,
        llm=llm,
    )
    assert out.broad_equity_bias == pytest.approx(0.0)
    llm.with_structured_output.assert_not_called()


def test_single_batch_invokes_structured(tmp_path):
    r = CalendarSignalResponse.model_validate(_response_dict())
    structured = MagicMock()
    structured.invoke.return_value = r
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    out = run_calendar_signal_pipeline(
        [_event()],
        "NVDA",
        cache=FileCache(tmp_path),
        settings=_SETTINGS,
        llm=llm,
        now=datetime(2026, 4, 8, 15, 0, 0, tzinfo=timezone.utc),
    )
    assert out.confidence == pytest.approx(0.8)
    llm.with_structured_output.assert_called_once()
    structured.invoke.assert_called_once()


def test_two_batches_aggregate(tmp_path):
    r = CalendarSignalResponse.model_validate(_response_dict())
    structured = MagicMock()
    structured.invoke.return_value = r
    llm = MagicMock()
    llm.with_structured_output.return_value = structured

    evs = [_event(), _event()]
    out = run_calendar_signal_pipeline(
        evs,
        "NVDA",
        batch_size=1,
        cache=FileCache(tmp_path),
        settings=_SETTINGS,
        llm=llm,
        now=datetime(2026, 4, 8, 15, 0, 0, tzinfo=timezone.utc),
    )
    assert structured.invoke.call_count == 2
    assert out.broad_equity_bias == pytest.approx(0.1)
