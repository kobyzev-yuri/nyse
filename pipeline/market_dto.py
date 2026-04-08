"""
DTO технического (market) агента — зеркало ``pystockinvest/agent/market/dto.py``.

Вход: ``TechnicalAgentInput`` → ``model_dump_json`` в user-промпт.
Выход: ``TechnicalSignalResponse`` — для ``with_structured_output``.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

from pydantic import BaseModel, Field, model_validator


class TechnicalSignalResponse(BaseModel):
    trend_score: float = Field(
        ge=-1.0,
        le=1.0,
        description="Directional short-term trend bias for the target ticker, from -1 bearish to 1 bullish.",
    )
    momentum_score: float = Field(
        ge=-1.0,
        le=1.0,
        description="Short-horizon momentum quality, from -1 negative momentum to 1 positive momentum.",
    )
    mean_reversion_score: float = Field(
        ge=-1.0,
        le=1.0,
        description="Expected pullback/reversal tendency over 1-3 days, from -1 downside reversion to 1 upside reversion.",
    )
    breakout_score: float = Field(
        ge=-1.0,
        le=1.0,
        description="Breakout or breakdown continuation pressure, from -1 bearish breakdown pressure to 1 bullish breakout pressure.",
    )
    volatility_regime: float = Field(
        ge=0.0,
        le=1.0,
        description="Current volatility regime, from 0 calm to 1 highly volatile.",
    )
    relative_strength_score: float = Field(
        ge=-1.0,
        le=1.0,
        description="Relative strength of the target ticker versus contextual market/sector inputs, from -1 weak to 1 strong.",
    )
    market_alignment_score: float = Field(
        ge=-1.0,
        le=1.0,
        description="How aligned the target ticker is with broader market and sector direction, from -1 negatively aligned to 1 positively aligned.",
    )
    exhaustion_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How stretched or exhausted the latest move appears, from 0 not exhausted to 1 highly exhausted.",
    )
    support_resistance_pressure: float = Field(
        ge=-1.0,
        le=1.0,
        description="Pressure from nearby levels, from -1 overhead resistance dominates to 1 nearby support favors upside.",
    )
    tradeability_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How tradable the setup is for a 1-3 day swing, considering structure, volatility, and liquidity.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Model confidence in the technical interpretation.",
    )
    summary: List[str] = Field(
        min_length=2,
        max_length=4,
        description="2 to 4 concise sentences summarizing the technical state for the target ticker over 1-3 trading days.",
    )

    @model_validator(mode="after")
    def validate_summary_items(self) -> TechnicalSignalResponse:
        cleaned = [item.strip() for item in self.summary if item.strip()]
        if len(cleaned) != len(self.summary):
            raise ValueError("summary items must be non-empty strings")
        return self


class CandleFeaturesInput(BaseModel):
    current_price: float = Field(description="Latest observed price of the instrument.")
    change_1d: float = Field(description="Percent price change over the last 1 day.")
    change_3d: float = Field(description="Percent price change over the last 3 days.")
    change_5d: float = Field(description="Percent price change over the last 5 days.")
    range_1d: float = Field(
        description="Intraday high-low range over the last 1 day, usually as a normalized percentage."
    )
    volatility_5d: float = Field(
        description="Recent realized volatility over the last 5 days."
    )
    volume_vs_avg: float = Field(
        description="Current volume relative to the instrument's usual average volume."
    )
    distance_from_5d_high: float = Field(
        description="Distance from the current price to the 5-day high. Smaller absolute distance means price is closer to the recent high."
    )
    distance_from_5d_low: float = Field(
        description="Distance from the current price to the 5-day low. Smaller absolute distance means price is closer to the recent low."
    )
    intraday_change: float = Field(
        description="Percent change from the session open to the current price."
    )
    distance_from_20d_high: float = Field(
        description="Distance from the current price to the 20-day high."
    )
    distance_from_20d_low: float = Field(
        description="Distance from the current price to the 20-day low."
    )
    change_3h: float = Field(description="Percent price change over the last 3 hours.")
    change_6h: float = Field(description="Percent price change over the last 6 hours.")
    change_12h: float = Field(
        description="Percent price change over the last 12 hours."
    )
    change_24h: float = Field(
        description="Percent price change over the last 24 hours."
    )
    distance_from_24h_high: float = Field(
        description="Distance from the current price to the 24-hour high."
    )
    distance_from_24h_low: float = Field(
        description="Distance from the current price to the 24-hour low."
    )
    volume_vs_24h_avg: float = Field(
        description="Current volume relative to the average volume over the last 24 hours."
    )
    body_pct: float = Field(
        description="Candle body size as a fraction of the full candle range."
    )
    upper_wick_pct: float = Field(
        description="Upper wick size as a fraction of the full candle range."
    )
    lower_wick_pct: float = Field(
        description="Lower wick size as a fraction of the full candle range."
    )
    close_position_in_range: float = Field(
        description="Position of the close within the candle range, where lower values are near the low and higher values are near the high."
    )


class MetricsInput(BaseModel):
    perf_week: float = Field(description="Percent performance over the last week.")
    rsi_14: float = Field(description="Relative Strength Index over 14 periods.")
    sma20_pct: float = Field(
        description="Percent distance of current price from the 20-period simple moving average."
    )
    sma50_pct: float = Field(
        description="Percent distance of current price from the 50-period simple moving average."
    )
    atr: float = Field(
        description="Average True Range, representing recent typical price movement size."
    )
    rel_volume: float = Field(
        description="Relative trading volume compared with the instrument's normal baseline."
    )
    beta: float = Field(description="Beta of the instrument relative to the market.")


class TechnicalTickerInput(BaseModel):
    ticker: str = Field(
        min_length=1, description="Ticker symbol for this technical input block."
    )
    candle_features: CandleFeaturesInput = Field(
        description="Candle-derived short-horizon price and volume features."
    )
    metrics: MetricsInput = Field(
        description="Additional technical metrics for the instrument."
    )


class TechnicalAgentInput(BaseModel):
    target: TechnicalTickerInput = Field(
        description="Target ticker data for which the technical prediction must be produced."
    )
    context: List[TechnicalTickerInput] = Field(
        default_factory=list,
        description="Optional contextual ticker inputs used only for market, sector, volatility, and relative-strength reference.",
    )
    current_time: datetime = Field(description="Current UTC time at inference.")
