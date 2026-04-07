"""
Уровень 6: TradeBuilder — слияние TechnicalSignal + AggregatedNewsSignal + CalendarSignal
в единое торговое решение (Trade).

Схема fusion идентична pystockinvest/agent/trade_builder.py для совместимости.

    KERIM_REPLACE: веса TECH_WEIGHT / NEWS_WEIGHT могут стать обучаемыми параметрами
    ML-модели Kerima, которая оценивает reliability каждого агента на историческом backtest.
    До этого используем фиксированные веса из калибровки.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from domain import (
    AggregatedNewsSignal,
    CalendarSignal,
    Direction,
    Position,
    PositionType,
    SignalBundle,
    TechnicalSignal,
    Ticker,
    Trade,
)

# ---------------------------------------------------------------------------
# Fusion constants (калибровать по результатам backtest)
# ---------------------------------------------------------------------------

# Веса агентов в fused_bias.
# При отсутствии news_signal вес перераспределяется на technical.
TECH_WEIGHT = 0.55
NEWS_WEIGHT = 0.45

# TP/SL кратность ATR (risk:reward = 2:1)
TP_ATR_MULT = 2.0
SL_ATR_MULT = 1.0

# Минимальная fused_confidence для открытия позиции.
# Ниже → PositionType.NONE (держаться в стороне).
MIN_CONFIDENCE = 0.55

# Минимальный |fused_bias| для открытия позиции.
# Слишком слабый сигнал → NONE даже при высокой confidence.
MIN_ABS_BIAS = 0.15


# ---------------------------------------------------------------------------
# Нейтральный CalendarSignal (до реализации CalendarAgent)
# ---------------------------------------------------------------------------

def neutral_calendar_signal() -> CalendarSignal:
    """Заглушка: нейтральный макрофон без событий календаря."""
    return CalendarSignal(
        broad_equity_bias=0.0,
        rates_pressure=0.0,
        macro_volatility_risk=0.0,
        upcoming_event_risk=0.0,
        inflation_score=0.0,
        employment_score=0.0,
        economic_activity_score=0.0,
        central_bank_score=0.0,
        confidence=0.5,
        summary=["Календарный агент: нет данных (baseline=нейтраль)."],
    )


# ---------------------------------------------------------------------------
# TradeBuilder
# ---------------------------------------------------------------------------

@dataclass
class FusedBias:
    """Промежуточный результат fusion — удобно для логирования и тестов."""
    value: float            # [-1, 1]
    confidence: float       # [0, 1]
    tech_contrib: float
    news_contrib: float
    news_available: bool


class TradeBuilder:
    """
    Принимает SignalBundle (tech + news + calendar) → Trade.

    Использование::

        builder = TradeBuilder()
        trade = builder.build(bundle)

    При отсутствии news_signal (gate=SKIP или LLM не вызывался)
    используется только технический сигнал с весом 1.0.
    """

    def __init__(
        self,
        tech_weight: float = TECH_WEIGHT,
        news_weight: float = NEWS_WEIGHT,
        tp_atr_mult: float = TP_ATR_MULT,
        sl_atr_mult: float = SL_ATR_MULT,
        min_confidence: float = MIN_CONFIDENCE,
        min_abs_bias: float = MIN_ABS_BIAS,
    ) -> None:
        self.tech_weight = tech_weight
        self.news_weight = news_weight
        self.tp_atr_mult = tp_atr_mult
        self.sl_atr_mult = sl_atr_mult
        self.min_confidence = min_confidence
        self.min_abs_bias = min_abs_bias

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, bundle: SignalBundle) -> Trade:
        fused = self._fuse(bundle.technical_signal, bundle.news_signal)
        position, entry_type = self._position(
            fused, bundle.technical_signal, bundle.ticker
        )
        return Trade(
            ticker=bundle.ticker,
            entry_type=entry_type,
            position=position,
            technical_summary=list(bundle.technical_signal.summary),
            news_summary=self._news_summary(bundle.news_signal, fused),
            calendar_summary=list(bundle.calendar_signal.summary),
        )

    def fuse_bias(
        self,
        tech: TechnicalSignal,
        news: Optional[AggregatedNewsSignal],
    ) -> FusedBias:
        """Публичный метод fusion — удобен для тестов и логирования."""
        return self._fuse(tech, news)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _fuse(
        self,
        tech: TechnicalSignal,
        news: Optional[AggregatedNewsSignal],
    ) -> FusedBias:
        if news is not None:
            w_t = self.tech_weight
            w_n = self.news_weight
            value = w_t * tech.bias + w_n * news.bias
            conf  = w_t * tech.confidence + w_n * news.confidence
            return FusedBias(
                value=_clip(value),
                confidence=_clip(conf),
                tech_contrib=round(w_t * tech.bias, 4),
                news_contrib=round(w_n * news.bias, 4),
                news_available=True,
            )
        # news недоступен → 100% технический сигнал
        return FusedBias(
            value=_clip(tech.bias),
            confidence=_clip(tech.confidence),
            tech_contrib=round(tech.bias, 4),
            news_contrib=0.0,
            news_available=False,
        )

    def _position(
        self,
        fused: FusedBias,
        tech: TechnicalSignal,
        ticker: Ticker,
    ) -> tuple[Optional[Position], PositionType]:
        """
        Вычисляет Position и PositionType из fused bias.
        entry/TP/SL считаются от текущей цены ± ATR.
        """
        # Недостаточная уверенность или слабый сигнал → NONE
        if fused.confidence < self.min_confidence or abs(fused.value) < self.min_abs_bias:
            return None, PositionType.NONE

        price = tech.target_snapshot.data.current_price
        atr   = tech.target_snapshot.metrics.atr
        if price <= 0 or atr <= 0:
            return None, PositionType.NONE

        side = Direction.LONG if fused.value > 0 else Direction.SHORT

        if side == Direction.LONG:
            entry       = price
            take_profit = round(price + self.tp_atr_mult * atr, 2)
            stop_loss   = round(price - self.sl_atr_mult * atr, 2)
        else:
            entry       = price
            take_profit = round(price - self.tp_atr_mult * atr, 2)
            stop_loss   = round(price + self.sl_atr_mult * atr, 2)

        return (
            Position(
                side=side,
                entry=round(entry, 2),
                take_profit=take_profit,
                stop_loss=stop_loss,
                confidence=round(fused.confidence, 4),
            ),
            PositionType.MARKET,
        )

    @staticmethod
    def _news_summary(
        news: Optional[AggregatedNewsSignal],
        fused: FusedBias,
    ) -> list[str]:
        if news is None:
            return [f"Новостной сигнал: нет (news_contrib=0, tech-only fusion)."]
        lines = list(news.summary)
        lines.append(
            f"News fusion contrib: {fused.news_contrib:+.3f} "
            f"(bias={news.bias:+.3f}, conf={news.confidence:.2f}, "
            f"items={len(news.items)})"
        )
        return lines


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
