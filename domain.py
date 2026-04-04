import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


# --------- Ticker ----------
class Ticker(enum.Enum):
    SNDK = "SNDK"
    QQQ = "QQQ"
    SMH = "SMH"
    MU = "MU"
    NVDA = "NVDA"
    TLT = "TLT"
    VIX = "^VIX"
    BNO = "BNO"
    MSFT = "MSFT"
    META = "META"
    AMZN = "AMZN"
    ASML = "ASML"
    LITE = "LITE"
    CIEN = "CIEN"
    NBIS = "NBIS"
    ORCL = "ORCL"

    def is_stock(self):
        return self not in {
            Ticker.QQQ,
            Ticker.SMH,
            Ticker.TLT,
            Ticker.VIX,
            Ticker.BNO,
        }


# --------- Calendar ----------
class Currency(enum.Enum):
    USD = "USD"
    CHF = "CHF"
    GBP = "GBP"
    JPY = "JPY"
    EUR = "EUR"
    UNKNOWN = "UNKNOWN"


class CalendarEventImportance(enum.Enum):
    HIGH = "high"
    MODERATE = "moderate"


@dataclass
class CalendarEvent:
    name: str
    category: str
    time: datetime
    country: str
    currency: Currency
    importance: CalendarEventImportance
    actual: Optional[str]
    forecast: Optional[str]
    previous: Optional[str]


# --------- Candles ----------
@dataclass
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class Period(enum.Enum):
    Day = "Day"
    Hour = "Hour"
    Minute = "Minute"


# --------- Earnings ----------
@dataclass
class Earnings:
    ticker: Ticker
    prev_earnings_date: Optional[datetime]
    next_earnings_date: Optional[datetime]


# --------- Metrics ----------
@dataclass(frozen=True)
class TickerMetrics:
    ticker: Ticker
    perf_week: float
    rsi_14: float
    sma20_pct: float
    sma50_pct: float
    atr: float
    relative_volume: float
    beta: float


# --------- News ----------
@dataclass
class NewsArticle:
    ticker: Ticker
    title: str
    timestamp: datetime
    summary: Optional[str]
    link: Optional[str]
    publisher: Optional[str]
