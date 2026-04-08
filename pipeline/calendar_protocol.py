"""
Protocol календарного агента — как ``CalendarAgent`` в ``pystockinvest/agent/agent.py``.
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from domain import CalendarEvent, CalendarSignal, Ticker


@runtime_checkable
class CalendarAgentProtocol(Protocol):
    def predict(self, ticker: Ticker, events: List[CalendarEvent]) -> CalendarSignal: ...
