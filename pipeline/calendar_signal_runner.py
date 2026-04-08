"""
Оркестратор календарного structured LLM → ``domain.CalendarSignal``.

Паттерн как ``pystockinvest/agent/calendar/agent.py`` + кэш как ``news_signal_runner``::

    structured_llm = llm.with_structured_output(CalendarSignalResponse)
    response = structured_llm.invoke([SystemMessage(...), HumanMessage(...)])
"""

from __future__ import annotations

import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence, cast

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.calendar_signal_runner", run_name="__main__")
    raise SystemExit(0)

from domain import CalendarEvent, CalendarSignal

from .cache import FileCache
from .calendar_dto import CalendarSignalResponse
from .calendar_signal_aggregator import aggregate_calendar_responses
from .calendar_signal_prompt import PROMPT_VERSION, build_calendar_messages
from .calendar_signal_schema import llm_response_to_calendar_signal
from .chunked import chunked
from .llm_cache import cache_key_llm, default_llm_file_cache, get_or_set_llm_text
from .llm_factory import get_chat_model
from .trade_builder import neutral_calendar_signal

if TYPE_CHECKING:
    from config_loader import OpenAISettings
    from langchain_core.language_models.chat_models import BaseChatModel


def run_calendar_signal_pipeline(
    events: Sequence[CalendarEvent],
    ticker: str,
    *,
    batch_size: Optional[int] = None,
    cache: Optional[FileCache] = None,
    settings: Optional["OpenAISettings"] = None,
    ttl_sec: Optional[int] = None,
    llm: Optional["BaseChatModel"] = None,
    now: Optional[datetime] = None,
) -> CalendarSignal:
    """
    Structured LLM по экономическому календарю.

    Пустой ``events`` → ``neutral_calendar_signal()`` (без вызова LLM).
    Несколько батчей → агрегация как в pystockinvest ``agent/calendar``.
    """
    evs = list(events)
    if not evs:
        return neutral_calendar_signal()

    import config_loader

    s = settings if settings is not None else config_loader.get_openai_settings()
    if s is None:
        raise RuntimeError("OpenAI settings missing (OPENAI_API_KEY)")

    from .lc_shim import HumanMessage, SystemMessage

    _now = now or datetime.now(timezone.utc)
    _llm = llm if llm is not None else get_chat_model(s)
    structured_llm = _llm.with_structured_output(CalendarSignalResponse)

    c = cache if cache is not None else default_llm_file_cache()
    ttl = ttl_sec if ttl_sec is not None else config_loader.llm_cache_ttl_sec()

    responses: list[CalendarSignalResponse] = []

    for batch_idx, batch in enumerate(chunked(evs, batch_size)):
        msg_dicts = build_calendar_messages(batch, ticker, now=_now)
        lc_messages = [
            SystemMessage(content=msg_dicts[0]["content"]),
            HumanMessage(content=msg_dicts[1]["content"]),
        ]
        # Суффикс батча: при одинаковом составе событий в разных чанках JSON совпадает —
        # иначе ключ кэша дублируется (см. chunked CPI + CPI).
        key = cache_key_llm(
            msg_dicts,
            s.model,
            prompt_version=f"{PROMPT_VERSION}|batch{batch_idx}",
        )

        def fetcher() -> str:
            response = cast(CalendarSignalResponse, structured_llm.invoke(lc_messages))
            return response.model_dump_json()

        raw_json = get_or_set_llm_text(c, key, ttl, fetcher)
        try:
            responses.append(CalendarSignalResponse.model_validate_json(raw_json))
        except Exception as exc:
            raise ValueError(
                f"Cached/returned LLM JSON invalid for calendar {ticker}: {exc!r}\n---\n{raw_json[:500]}"
            ) from exc

    aggregated = aggregate_calendar_responses(responses)
    return llm_response_to_calendar_signal(aggregated)


if __name__ == "__main__":
    print(
        "run_calendar_signal_pipeline — импортируйте из pipeline.calendar_signal_runner.\n"
        "Smoke с API: задайте OPENAI_API_KEY и вызовите с реальными CalendarEvent."
    )
