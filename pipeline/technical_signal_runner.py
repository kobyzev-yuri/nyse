"""
Оркестратор технического structured LLM → ``domain.TechnicalSignal``.

Паттерн как ``pystockinvest/agent/market/agent.py`` + кэш как ``news_signal_runner``.
"""

from __future__ import annotations

import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Sequence, cast

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.technical_signal_runner", run_name="__main__")
    raise SystemExit(0)

from domain import TechnicalSignal, TechnicalSnapshot, Ticker, TickerData, TickerMetrics

from .cache import FileCache
from .llm_cache import cache_key_llm, default_llm_file_cache, get_or_set_llm_text
from .llm_factory import get_chat_model
from .market_dto import TechnicalSignalResponse
from .technical_signal_prompt import PROMPT_VERSION, build_technical_signal_messages
from .technical_signal_schema import llm_response_to_technical_signal

if TYPE_CHECKING:
    from config_loader import OpenAISettings
    from langchain_core.language_models.chat_models import BaseChatModel


def _target_snapshot(
    ticker: Ticker,
    ticker_data: Sequence[TickerData],
    metrics: Sequence[TickerMetrics],
) -> TechnicalSnapshot:
    by_td = {td.ticker: td for td in ticker_data}
    by_m = {m.ticker: m for m in metrics}
    td = by_td.get(ticker)
    m = by_m.get(ticker)
    if td is None:
        raise ValueError(f"ticker data for {ticker} not found")
    if m is None:
        raise ValueError(f"metrics for {ticker} not found")
    return TechnicalSnapshot(data=td, metrics=m)


def run_technical_signal_pipeline(
    ticker: Ticker,
    ticker_data: Sequence[TickerData],
    metrics: Sequence[TickerMetrics],
    *,
    cache: Optional[FileCache] = None,
    settings: Optional["OpenAISettings"] = None,
    ttl_sec: Optional[int] = None,
    llm: Optional["BaseChatModel"] = None,
    now: Optional[datetime] = None,
) -> TechnicalSignal:
    """
    Один вызов structured LLM по ``TechnicalAgentInput`` (как ``pystockinvest.agent.market``).

    Требуются непустые ``daily_candles`` / ``hourly_candles`` для расчёта признаков
    (см. ``pipeline.technical.candle_features``).
    """
    import config_loader

    s = settings if settings is not None else config_loader.get_openai_settings()
    if s is None:
        raise RuntimeError("OpenAI settings missing (OPENAI_API_KEY)")

    from .lc_shim import HumanMessage, SystemMessage

    _now = now or datetime.now(timezone.utc)
    td_list: List[TickerData] = list(ticker_data)
    m_list: List[TickerMetrics] = list(metrics)

    snapshot = _target_snapshot(ticker, td_list, m_list)

    msg_dicts = build_technical_signal_messages(
        ticker, td_list, m_list, now=_now,
    )

    _llm = llm if llm is not None else get_chat_model(s)
    structured_llm = _llm.with_structured_output(TechnicalSignalResponse)

    lc_messages = [
        SystemMessage(content=msg_dicts[0]["content"]),
        HumanMessage(content=msg_dicts[1]["content"]),
    ]

    c = cache if cache is not None else default_llm_file_cache()
    ttl = ttl_sec if ttl_sec is not None else config_loader.llm_cache_ttl_sec()
    key = cache_key_llm(msg_dicts, s.model, prompt_version=PROMPT_VERSION)

    def fetcher() -> str:
        response = cast(TechnicalSignalResponse, structured_llm.invoke(lc_messages))
        return response.model_dump_json()

    raw_json = get_or_set_llm_text(c, key, ttl, fetcher)

    try:
        llm_response = TechnicalSignalResponse.model_validate_json(raw_json)
    except Exception as exc:
        raise ValueError(
            f"Cached/returned LLM JSON invalid for technical {ticker.value}: {exc!r}\n---\n{raw_json[:500]}"
        ) from exc

    return llm_response_to_technical_signal(llm_response, snapshot)


if __name__ == "__main__":
    print(
        "run_technical_signal_pipeline — импортируйте из pipeline.technical_signal_runner.\n"
        "Нужны TickerData с ≥25 дневных и часовых свечей для candle_features."
    )
