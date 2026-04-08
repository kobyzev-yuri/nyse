"""
Календарный агент с structured LLM — интерфейс как ``pystockinvest/agent/calendar/agent.Agent``.

Использование::

    from pipeline.calendar_llm_agent import CalendarLlmAgent
    from pipeline.llm_factory import get_chat_model

    agent = CalendarLlmAgent(llm=get_chat_model())
    cal = agent.predict(Ticker.NVDA, events)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, Sequence

from domain import CalendarEvent, CalendarSignal, Ticker

from .cache import FileCache
from .calendar_signal_runner import run_calendar_signal_pipeline

if TYPE_CHECKING:
    from config_loader import OpenAISettings
    from langchain_core.language_models.chat_models import BaseChatModel


class CalendarLlmAgent:
    """Аналог ``agent.calendar.Agent`` в pystockinvest с кэшем NYSE."""

    def __init__(
        self,
        llm: Optional["BaseChatModel"] = None,
        *,
        batch_size: Optional[int] = None,
        cache: Optional[FileCache] = None,
        settings: Optional["OpenAISettings"] = None,
    ) -> None:
        self._llm = llm
        self._batch_size = batch_size
        self._cache = cache
        self._settings = settings

    def predict(
        self,
        ticker: Ticker,
        events: Sequence[CalendarEvent],
        *,
        now: Optional[datetime] = None,
    ) -> CalendarSignal:
        return run_calendar_signal_pipeline(
            list(events),
            ticker.value,
            batch_size=self._batch_size,
            cache=self._cache,
            settings=self._settings,
            llm=self._llm,
            now=now or datetime.now(timezone.utc),
        )
