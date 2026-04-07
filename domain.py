import enum
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional


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
    summary: List[str]
    items: List[NewsSignal]


# --------- Level 6: technical signal, calendar signal, trade output ---------
# Контракт полей идентичен pystockinvest/agent/models.py и pystockinvest/domain.py,
# чтобы при слиянии репозиториев diff был минимальным.

# --- TickerData (свечи + текущая цена) ---

@dataclass
class TickerData:
    ticker: Ticker
    current_price: float
    daily_candles: List[Candle]
    hourly_candles: List[Candle]


@dataclass(frozen=True)
class TechnicalSnapshot:
    """Срез данных для одного тикера: цены + метрики."""
    data: TickerData
    metrics: TickerMetrics


# --- TechnicalSignal (выход TechnicalAgent) ---

@dataclass
class TechnicalSignal:
    """
    Технический сигнал на 1-3 торговых дня.
    Поля и формула bias идентичны pystockinvest/agent/models.py.
    """
    bias: float                         # [-1, 1]: взвешенная сумма score-полей
    trend_score: float                  # [-1, 1]: направление краткосрочного тренда
    momentum_score: float               # [-1, 1]: сила и качество импульса
    mean_reversion_score: float         # [-1, 1]: ожидание отката/разворота
    breakout_score: float               # [-1, 1]: давление пробоя/пробития
    volatility_regime: float            # [0, 1]:  0=спокойно, 1=высокая волатильность
    relative_strength_score: float      # [-1, 1]: сила тикера относительно рынка/сектора
    market_alignment_score: float       # [-1, 1]: согласованность с широким рынком
    exhaustion_score: float             # [0, 1]:  0=не перегрет, 1=исчерпан
    support_resistance_pressure: float  # [-1, 1]: +1=поддержка снизу, -1=сопротивление сверху
    tradeability_score: float           # [0, 1]:  качество сетапа для входа
    confidence: float                   # [0, 1]:  уверенность агента
    target_snapshot: TechnicalSnapshot
    summary: List[str]


# --- CalendarSignal (выход CalendarAgent) ---

@dataclass
class CalendarSignal:
    """
    Макро-сигнал из экономического календаря.
    Поля идентичны pystockinvest/agent/models.py.
    """
    broad_equity_bias: float        # [-1, 1]: общий фон для акций по событиям
    rates_pressure: float           # [0, 1]:  давление на ставки (CPI, FOMC)
    macro_volatility_risk: float    # [0, 1]:  риск макро-волатильности
    upcoming_event_risk: float      # [0, 1]:  риск от ближайших HIGH-событий
    inflation_score: float          # [-1, 1]: инфляционное давление
    employment_score: float         # [-1, 1]: сигнал по занятости
    economic_activity_score: float  # [-1, 1]: активность экономики
    central_bank_score: float       # [-1, 1]: сигнал от центробанков
    confidence: float               # [0, 1]
    summary: List[str]


# --- Trade output (выход TradeBuilder) ---

class Direction(enum.Enum):
    LONG = "long"
    SHORT = "short"


class PositionType(enum.Enum):
    MARKET = "market"
    LIMIT = "limit"
    NONE = "none"


@dataclass(frozen=True)
class Position:
    side: Direction
    entry: float
    take_profit: float
    stop_loss: float
    confidence: float


@dataclass
class Trade:
    """
    Итоговое торговое решение после слияния всех трёх агентов.
    Структура идентична pystockinvest/domain.py.
    """
    ticker: Ticker
    entry_type: PositionType
    position: Optional[Position]
    technical_summary: List[str]
    news_summary: List[str]
    calendar_summary: List[str]


# --- SignalBundle (вход TradeBuilder) ---

@dataclass(frozen=True)
class SignalBundle:
    """Три сигнала для одного тикера — вход в TradeBuilder."""
    ticker: Ticker
    technical_signal: TechnicalSignal
    news_signal: Optional[AggregatedNewsSignal]
    calendar_signal: CalendarSignal
