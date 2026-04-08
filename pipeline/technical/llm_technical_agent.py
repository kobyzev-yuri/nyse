"""
Технический агент с structured LLM — интерфейс как ``pystockinvest/agent/market/agent.Agent``.

Реализует ``TechnicalAgentProtocol`` (``predict`` → ``TechnicalSignal``).

Использование::

    from pipeline.technical import LlmTechnicalAgent
    from pipeline.llm_factory import get_chat_model

    agent = LlmTechnicalAgent(llm=get_chat_model())
    sig = agent.predict(ticker, ticker_data_list, metrics_list)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional, Sequence

from domain import TechnicalSignal, Ticker, TickerData, TickerMetrics

from ..cache import FileCache
from ..technical_signal_runner import run_technical_signal_pipeline

if TYPE_CHECKING:
    from config_loader import OpenAISettings
    from langchain_core.language_models.chat_models import BaseChatModel


class LlmTechnicalAgent:
    """Аналог ``agent.market.Agent`` в pystockinvest с кэшем NYSE."""

    def __init__(
        self,
        llm: Optional["BaseChatModel"] = None,
        *,
        cache: Optional[FileCache] = None,
        settings: Optional["OpenAISettings"] = None,
    ) -> None:
        self._llm = llm
        self._cache = cache
        self._settings = settings

    def predict(
        self,
        ticker: Ticker,
        ticker_data: List[TickerData],
        metrics: List[TickerMetrics],
        *,
        now: Optional[datetime] = None,
    ) -> TechnicalSignal:
        return run_technical_signal_pipeline(
            ticker,
            ticker_data,
            metrics,
            cache=self._cache,
            settings=self._settings,
            llm=self._llm,
            now=now or datetime.now(timezone.utc),
        )
