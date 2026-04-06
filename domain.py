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
    # Лента без привязки к одному тикеру (RSS макро и т.п.)
    GENERAL = "GENERAL"

    def is_stock(self):
        return self not in {
            Ticker.QQQ,
            Ticker.SMH,
            Ticker.TLT,
            Ticker.VIX,
            Ticker.BNO,
            Ticker.GENERAL,
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
    provider_id: Optional[str] = None  # yfinance, newsapi, marketaux, rss, …
    raw_sentiment: Optional[float] = None  # −1…1, если провайдер отдаёт (Marketaux entity)
    cheap_sentiment: Optional[float] = None  # −1…1: уровень 2 (API или локальная модель)


# --------- Level 5: structured LLM signal (align with pystockinvest `agent/models.py`) ---------
# Контракт полей — тот же, что у Kerima / NewsSignalAgent, чтобы позже склеить репозитории.


class NewsTimeHorizon(str, enum.Enum):
    INTRADAY = "intraday"
    SHORT = "1-3d"
    MEDIUM = "3-7d"
    LONG = "long"


class NewsSurprise(str, enum.Enum):
    NONE = "none"
    MINOR = "minor"
    SIGNIFICANT = "significant"
    MAJOR = "major"


class NewsImpact(str, enum.Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class NewsRelevance(str, enum.Enum):
    MENTION = "mention"
    RELATED = "related"
    PRIMARY = "primary"


@dataclass
class NewsSignal:
    """Один сигнал на статью после structured LLM (уровень 5)."""

    sentiment: float
    impact_strength: NewsImpact
    relevance: NewsRelevance
    surprise: NewsSurprise
    time_horizon: NewsTimeHorizon
    confidence: float


@dataclass
class AggregatedNewsSignal:
    """Агрегат по окну/батчу статей (как `AggregatedNewsSignal` в pystockinvest)."""

    bias: float
    confidence: float
    summary: list[str]
    items: list[NewsSignal]
