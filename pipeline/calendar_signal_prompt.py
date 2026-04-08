"""
Промпт календарного structured LLM — как ``pystockinvest/agent/calendar/agent.py``.

Payload: ``CalendarAgentInput.model_dump_json(indent=2)``.
Схема ответа: ``with_structured_output(CalendarSignalResponse)`` (будущий CalendarAgent).

Запуск: ``python -m pipeline.calendar_signal_prompt``.
"""

from __future__ import annotations

import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.calendar_signal_prompt", run_name="__main__")
    raise SystemExit(0)

from domain import CalendarEvent

from .calendar_dto import CalendarAgentInput, CalendarEventInput

# Дословно из pystockinvest/agent/calendar/agent.py
SYSTEM_PROMPT = """
You are a macro calendar analyst for stock prediction.
Your task is to interpret a batch of economic calendar events for a target stock ticker.
You must return exactly one structured output object.

Return only the structured output.
""".strip()


USER_PROMPT_TEMPLATE = """
Interpret the following economic calendar events and assess their potential impact on the target stock.
Analyze in context of short-term price move (over next 1-3 days).

Inputs:
{payload}
""".strip()

PROMPT_VERSION = "v1"


def build_calendar_messages(
    events: Sequence[CalendarEvent],
    ticker: str,
    *,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """
    Два сообщения (system + user) для вызова LLM с structured output.

    ``events`` — батч событий (индексы в JSON 1..n); ``ticker`` — строка, например ``"NVDA"``.
    """
    if not events:
        raise ValueError("events must not be empty")
    ts = now or datetime.now(timezone.utc)
    batch_input = CalendarAgentInput(
        target_ticker=ticker,
        current_time=ts,
        events=[
            CalendarEventInput(
                event_index=i + 1,
                name=e.name,
                category=e.category,
                time=e.time,
                time_state="released" if e.time <= ts else "upcoming",
                country=e.country,
                currency=e.currency.value,
                importance=e.importance.value,
                actual=e.actual,
                forecast=e.forecast,
                previous=e.previous,
            )
            for i, e in enumerate(events)
        ],
    )
    user_content = USER_PROMPT_TEMPLATE.format(
        payload=batch_input.model_dump_json(indent=2),
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


if __name__ == "__main__":
    from domain import CalendarEventImportance, Currency

    ev = CalendarEvent(
        name="CPI",
        category="inflation",
        time=datetime(2026, 4, 8, 14, 0, 0, tzinfo=timezone.utc),
        country="US",
        currency=Currency.USD,
        importance=CalendarEventImportance.HIGH,
        actual=None,
        forecast="3.1",
        previous="3.0",
    )
    msgs = build_calendar_messages([ev], "NVDA")
    print(msgs[1]["content"][:800])
