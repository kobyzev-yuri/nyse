"""
Единое сопоставление Ticker → строка символа для внешних API.

Yahoo/yfinance: значение enum (после исправления BNO = «BNO»), VIX = ^VIX.
Finviz: для индекса VIX страница котировки обычно по ETF VIXY, не по ^VIX.
"""

from __future__ import annotations

import os
from typing import Iterable, List

from .models import Ticker

_FINVIZ_OVERRIDES = {
    # Finviz quote screener: VIX index как ^VIX часто недоступен; VIXY — близкий ETF.
    Ticker.VIX: "VIXY",
}


def yfinance_symbol(ticker: Ticker) -> str:
    """Символ для yfinance (свечи, earnings, news, fast_info)."""
    return ticker.value


def finviz_symbol(ticker: Ticker) -> str:
    """Символ для finvizfinance (скринер/фундамент)."""
    return _FINVIZ_OVERRIDES.get(ticker, ticker.value)


def tickers_from_environ(
    default: Iterable[Ticker] | None = None,
    env_var: str = "NYSE_TICKERS",
) -> List[Ticker]:
    """
    Список тикеров из переменной окружения `NYSE_TICKERS` (через запятую),
    например: NYSE_TICKERS=NVDA,MU,^VIX — значения должны совпадать с Ticker.value.

    Если переменная пуста — возвращается default или полный перечень Ticker.
    """
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        if default is not None:
            return list(default)
        return list(Ticker)

    out: List[Ticker] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(Ticker(part))
        except ValueError:
            try:
                out.append(Ticker[part])
            except KeyError as e:
                raise ValueError(f"Unknown ticker {part!r} in {env_var}") from e
    return out
