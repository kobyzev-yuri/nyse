"""
Protocol-контракт для технического агента.

``LseHeuristicAgent``, ``LlmTechnicalAgent`` и агент из pystockinvest реализуют
этот интерфейс — замена прозрачна для TradeBuilder и бота.

Использование::

    from pipeline.technical import TechnicalAgentProtocol

    def build_trade(agent: TechnicalAgentProtocol, ...) -> Trade:
        sig = agent.predict(ticker, ticker_data, metrics)
        ...

Проверка типов: ``mypy --strict nyse/bot/nyse_bot.py`` после смены реализации.
"""

from __future__ import annotations

from typing import List
from typing import Protocol, runtime_checkable

from domain import TechnicalSignal, Ticker, TickerData, TickerMetrics


@runtime_checkable
class TechnicalAgentProtocol(Protocol):
    """
    Минимальный контракт технического агента.

    Принимает целевой тикер, список рыночных данных всех тикеров (включая
    контекстные — SMH, QQQ) и метрики Finviz → возвращает ``TechnicalSignal``.

    Parameters
    ----------
    ticker :
        Целевой тикер для анализа.
    ticker_data :
        Данные по всем тикерам (GAME_5M + контекст).
        Агент сам выбирает нужные строки по ``td.ticker``.
    metrics :
        Метрики Finviz для всех тикеров (RSI, ATR, beta и т.д.).

    Returns
    -------
    TechnicalSignal
        Структурированный технический сигнал с bias, confidence, summary.
    """

    def predict(
        self,
        ticker: Ticker,
        ticker_data: List[TickerData],
        metrics: List[TickerMetrics],
    ) -> TechnicalSignal:
        ...
