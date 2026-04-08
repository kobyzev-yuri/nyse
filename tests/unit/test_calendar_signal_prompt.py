"""Промпт build_calendar_messages (календарь, как pystockinvest calendar agent)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from domain import CalendarEvent, CalendarEventImportance, Currency
from pipeline.calendar_signal_prompt import PROMPT_VERSION, build_calendar_messages


def _ev(name: str = "CPI") -> CalendarEvent:
    return CalendarEvent(
        name=name,
        category="inflation",
        time=datetime(2026, 4, 8, 14, 0, 0, tzinfo=timezone.utc),
        country="US",
        currency=Currency.USD,
        importance=CalendarEventImportance.HIGH,
        actual=None,
        forecast="3.1",
        previous="3.0",
    )


def test_returns_two_messages():
    msgs = build_calendar_messages([_ev()], "NVDA")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_user_payload_json_after_inputs():
    now = datetime(2026, 4, 8, 15, 0, 0, tzinfo=timezone.utc)
    msgs = build_calendar_messages([_ev()], "NVDA", now=now)
    user = msgs[1]["content"]
    idx = user.index("Inputs:\n") + len("Inputs:\n")
    payload = json.loads(user[idx:])
    assert payload["target_ticker"] == "NVDA"
    assert payload["events"][0]["event_index"] == 1
    assert payload["events"][0]["name"] == "CPI"
    assert payload["events"][0]["time_state"] == "released"


def test_upcoming_time_state():
    future = datetime(2026, 4, 10, 14, 0, 0, tzinfo=timezone.utc)
    now = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
    ev = CalendarEvent(
        name="NFP",
        category="employment",
        time=future,
        country="US",
        currency=Currency.USD,
        importance=CalendarEventImportance.HIGH,
        actual=None,
        forecast=None,
        previous=None,
    )
    msgs = build_calendar_messages([ev], "MU", now=now)
    user = msgs[1]["content"]
    idx = user.index("Inputs:\n") + len("Inputs:\n")
    payload = json.loads(user[idx:])
    assert payload["events"][0]["time_state"] == "upcoming"


def test_empty_events_raises():
    with pytest.raises(ValueError):
        build_calendar_messages([], "NVDA")


def test_prompt_version():
    assert isinstance(PROMPT_VERSION, str) and len(PROMPT_VERSION) >= 1
