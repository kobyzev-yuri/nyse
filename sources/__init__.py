"""Пакет источников данных: корень репозитория в sys.path для импорта `domain`."""

from __future__ import annotations

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_rp = str(_root)
if _rp not in sys.path:
    sys.path.insert(0, _rp)

__all__ = [
    "CandlesSource",
    "MetricsSource",
    "EarningsSource",
    "CalendarSource",
    "NewsSource",
    "yfinance_symbol",
    "finviz_symbol",
    "tickers_from_environ",
]


def __getattr__(name: str):
    if name == "CandlesSource":
        from .candles import Source as CandlesSource

        return CandlesSource
    if name == "MetricsSource":
        from .metrics import Source as MetricsSource

        return MetricsSource
    if name == "EarningsSource":
        from .earnings import Source as EarningsSource

        return EarningsSource
    if name == "CalendarSource":
        from .ecalendar import Source as CalendarSource

        return CalendarSource
    if name == "NewsSource":
        from .news import Source as NewsSource

        return NewsSource
    if name in ("yfinance_symbol", "finviz_symbol", "tickers_from_environ"):
        from . import symbols

        return getattr(symbols, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
