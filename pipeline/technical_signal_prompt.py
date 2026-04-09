"""
Промпт технического (market) structured LLM — как ``pystockinvest/agent/market/agent.py``.

Payload: ``TechnicalAgentInput.model_dump_json(indent=2)``.
Схема ответа: ``with_structured_output(TechnicalSignalResponse)``.

Контекстные тикеры в JSON — с **их** символами (исправление shadowing ``ticker`` в исходном pystockinvest).

Запуск: ``python -m pipeline.technical_signal_prompt``.
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
    runpy.run_module("pipeline.technical_signal_prompt", run_name="__main__")
    raise SystemExit(0)

from domain import TechnicalSnapshot, Ticker, TickerData, TickerMetrics

from .market_dto import MetricsInput, TechnicalAgentInput, TechnicalTickerInput
from .tech.agents.candle_features import calculate_candle_features

# Дословно из pystockinvest/agent/market/agent.py
SYSTEM_PROMPT = """
You are a short-horizon technical market analyst for stock prediction.
Your task is to interpret technical price, candle, volume, and metric inputs for a target ticker over a 1-3 trading day horizon.
Return only the structured output.
""".strip()


USER_PROMPT_TEMPLATE = """
Analyze the following structured technical input for the target ticker over a 1-3 trading day horizon.

Input:
{payload}
""".strip()

PROMPT_VERSION = "v1"


def _to_metrics_input(metrics: TickerMetrics) -> MetricsInput:
    return MetricsInput(
        perf_week=metrics.perf_week,
        rsi_14=metrics.rsi_14,
        sma20_pct=metrics.sma20_pct,
        sma50_pct=metrics.sma50_pct,
        atr=metrics.atr,
        rel_volume=metrics.relative_volume,
        beta=metrics.beta,
    )


def technical_agent_input_from_domain(
    ticker: Ticker,
    ticker_data: Sequence[TickerData],
    metrics: Sequence[TickerMetrics],
    *,
    current_time: datetime | None = None,
) -> TechnicalAgentInput:
    """
    Собирает ``TechnicalAgentInput`` из доменных списков (как ``_to_agent_input`` в pystockinvest market agent).

    Контекст — все пары (TickerData, TickerMetrics), кроме целевого тикера.
    """
    metrics_by_ticker = {m.ticker: m for m in metrics}
    ticker_data_by_ticker = {td.ticker: td for td in ticker_data}

    target_metrics = metrics_by_ticker.get(ticker)
    if target_metrics is None:
        raise ValueError(f"metrics for target ticker {ticker} not found")

    target_data = ticker_data_by_ticker.get(ticker)
    if target_data is None:
        raise ValueError(f"ticker data for target ticker {ticker} not found")

    context: dict[Ticker, TechnicalSnapshot] = {}
    for td in ticker_data:
        ctx_ticker = td.ticker
        if ctx_ticker == ticker:
            continue
        ctx_m = metrics_by_ticker.get(ctx_ticker)
        if ctx_m is None:
            continue
        context[ctx_ticker] = TechnicalSnapshot(data=td, metrics=ctx_m)

    ts = current_time or datetime.now(timezone.utc)

    return TechnicalAgentInput(
        current_time=ts,
        target=TechnicalTickerInput(
            ticker=ticker.value,
            candle_features=calculate_candle_features(target_data),
            metrics=_to_metrics_input(target_metrics),
        ),
        context=[
            TechnicalTickerInput(
                ticker=ctx_ticker.value,
                candle_features=calculate_candle_features(snap.data),
                metrics=_to_metrics_input(snap.metrics),
            )
            for ctx_ticker, snap in context.items()
        ],
    )


def build_technical_signal_messages(
    ticker: Ticker,
    ticker_data: Sequence[TickerData],
    metrics: Sequence[TickerMetrics],
    *,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """Два сообщения (system + user) для ``with_structured_output(TechnicalSignalResponse)``."""
    batch_input = technical_agent_input_from_domain(
        ticker, ticker_data, metrics, current_time=now
    )
    user_content = USER_PROMPT_TEMPLATE.format(
        payload=batch_input.model_dump_json(indent=2),
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


if __name__ == "__main__":
    print("Run tests or import build_technical_signal_messages with real TickerData.")
