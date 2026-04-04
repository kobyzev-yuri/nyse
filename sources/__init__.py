"""Пакет источников данных: корень репозитория в sys.path для импорта `domain`."""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
_rp = str(_root)
if _rp not in sys.path:
    sys.path.insert(0, _rp)

from .candles import Source as CandlesSource
from .metrics import Source as MetricsSource
from .earnings import Source as EarningsSource
from .ecalendar import Source as CalendarSource
from .news import Source as NewsSource
from .symbols import finviz_symbol, tickers_from_environ, yfinance_symbol

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
