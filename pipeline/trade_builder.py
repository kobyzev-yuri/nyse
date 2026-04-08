"""
Уровень 6: TradeBuilder — порт логики ``pystockinvest/agent/trade.py``.

Слияние TechnicalSignal + AggregatedNewsSignal + CalendarSignal в Trade.
Веса bias, формула confidence, пороги входа, LIMIT/MARKET, entry и TP/SL по ATR —
**как в pystockinvest**, для совместимости с общим репозиторием агентов.

Дополнительно (только NYSE): ``FusedBias`` и ``fuse_bias()`` — для отображения
в Telegram/HTML; числа согласованы с тем же ``final_bias`` и ``_final_confidence``.
"""

from __future__ import annotations

from dataclasses import dataclass
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

# Веса final_bias — как в pystockinvest/agent/trade.py
W_TECH = 0.55
W_NEWS = 0.30
W_CAL = 0.15


# ---------------------------------------------------------------------------
# Нейтральный CalendarSignal (нет событий / LLM выключен / нет API-ключа)
# ---------------------------------------------------------------------------


def neutral_calendar_signal() -> CalendarSignal:
    """Заглушка: нейтральный макрофон без событий."""
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
# FusedBias — для UI (соответствует разложению final_bias)
# ---------------------------------------------------------------------------


@dataclass
class FusedBias:
    """Итог fusion и вклады по каналам (55% / 30% / 15%)."""

    value: float  # final_bias ∈ [-1, 1]
    confidence: float  # _final_confidence
    tech_contrib: float  # W_TECH * tech.bias
    news_contrib: float  # W_NEWS * news.bias (0 если нет новостей)
    cal_contrib: float  # W_CAL * calendar.broad_equity_bias
    news_available: bool  # AggregatedNewsSignal не None


class TradeBuilder:
    """
    Как ``pystockinvest.agent.trade.TradeBuilder``::

        final_bias = 0.55*tech + 0.30*news + 0.15*calendar
        confidence = f(tech_conf, news_conf, cal_conf, final_bias, cal_risk)
        позиция при tradeability >= 0.4 и |final_bias| > 0.2 (по знаку LONG/SHORT)
    """

    def build(self, signals: SignalBundle) -> Trade:
        tech_bias = signals.technical_signal.bias
        news_bias = signals.news_signal.bias if signals.news_signal is not None else 0.0
        calendar_bias = signals.calendar_signal.broad_equity_bias
        calendar_risk = signals.calendar_signal.upcoming_event_risk

        final_bias = W_TECH * tech_bias + W_NEWS * news_bias + W_CAL * calendar_bias

        confidence = self._final_confidence(
            technical_signal=signals.technical_signal,
            news_signal=signals.news_signal,
            calendar_signal=signals.calendar_signal,
            final_bias=final_bias,
        )

        entry_type = self._entry_type(
            technical_signal=signals.technical_signal,
            news_signal=signals.news_signal,
            calendar_risk=calendar_risk,
        )

        position = self._build_position(
            signals=signals,
            final_bias=final_bias,
            confidence=confidence,
        )

        return Trade(
            ticker=signals.ticker,
            entry_type=entry_type if position else PositionType.NONE,
            position=position,
            technical_summary=list(signals.technical_signal.summary),
            news_summary=(
                list(signals.news_signal.summary)
                if signals.news_signal is not None
                else []
            ),
            calendar_summary=list(signals.calendar_signal.summary),
        )

    def fuse_bias(
        self,
        tech: TechnicalSignal,
        news: Optional[AggregatedNewsSignal],
        calendar: Optional[CalendarSignal] = None,
    ) -> FusedBias:
        """
        Тот же ``final_bias`` и ``_final_confidence``, что и в ``build``,
        для логирования и Telegram. Если ``calendar`` не передан — neutral.
        """
        cal = calendar if calendar is not None else neutral_calendar_signal()
        tech_b = tech.bias
        news_b = news.bias if news is not None else 0.0
        cal_b = cal.broad_equity_bias

        value = W_TECH * tech_b + W_NEWS * news_b + W_CAL * cal_b
        value = _clip(value)

        conf = self._final_confidence(
            technical_signal=tech,
            news_signal=news,
            calendar_signal=cal,
            final_bias=value,
        )

        return FusedBias(
            value=value,
            confidence=conf,
            tech_contrib=round(W_TECH * tech_b, 4),
            news_contrib=round(W_NEWS * news_b, 4),
            cal_contrib=round(W_CAL * cal_b, 4),
            news_available=news is not None,
        )

    @staticmethod
    def _final_confidence(
        technical_signal: TechnicalSignal,
        news_signal: Optional[AggregatedNewsSignal],
        calendar_signal: CalendarSignal,
        final_bias: float,
    ) -> float:
        tech_conf = technical_signal.confidence
        news_conf = news_signal.confidence if news_signal is not None else 0.0
        cal_conf = calendar_signal.confidence
        cal_risk = calendar_signal.upcoming_event_risk

        agreement_bonus = min(abs(final_bias), 1.0) * 0.15
        raw = 0.50 * tech_conf + 0.30 * news_conf + 0.20 * cal_conf + agreement_bonus
        penalized = raw * (1.0 - 0.35 * cal_risk)
        return max(0.0, min(1.0, penalized))

    def _build_position(
        self,
        signals: SignalBundle,
        final_bias: float,
        confidence: float,
    ) -> Optional[Position]:
        technical_signal = signals.technical_signal
        snapshot = signals.technical_signal.target_snapshot

        if technical_signal.tradeability_score < 0.40:
            return None

        if final_bias > 0.20:
            side = Direction.LONG
        elif final_bias < -0.20:
            side = Direction.SHORT
        else:
            return None

        entry = self._entry_price(
            side=side,
            entry_type=self._entry_type(
                technical_signal=signals.technical_signal,
                news_signal=signals.news_signal,
                calendar_risk=signals.calendar_signal.upcoming_event_risk,
            ),
            current_price=snapshot.data.current_price,
            atr=snapshot.metrics.atr,
        )

        stop_loss, take_profit = self._risk_levels(
            side=side,
            entry=entry,
            atr=snapshot.metrics.atr,
            volatility_regime=technical_signal.volatility_regime,
        )

        return Position(
            side=side,
            entry=entry,
            take_profit=take_profit,
            stop_loss=stop_loss,
            confidence=confidence,
        )

    @staticmethod
    def _entry_type(
        technical_signal: TechnicalSignal,
        news_signal: Optional[AggregatedNewsSignal],
        calendar_risk: float,
    ) -> PositionType:
        breakout_preferred = (
            abs(technical_signal.breakout_score)
            >= abs(technical_signal.mean_reversion_score)
            and technical_signal.exhaustion_score < 0.65
            and calendar_risk < 0.75
        )
        urgent_news = abs(news_signal.bias) > 0.40 if news_signal is not None else False

        if breakout_preferred and urgent_news:
            return PositionType.MARKET
        return PositionType.LIMIT

    @staticmethod
    def _entry_price(
        side: Direction,
        entry_type: PositionType,
        current_price: float,
        atr: float,
    ) -> float:
        if entry_type == PositionType.MARKET:
            return round(current_price, 4)
        if side == Direction.LONG:
            return round(current_price - 0.25 * atr, 4)
        return round(current_price + 0.25 * atr, 4)

    @staticmethod
    def _risk_levels(
        side: Direction,
        entry: float,
        atr: float,
        volatility_regime: float,
    ) -> tuple[float, float]:
        stop_mult = 1.0 + 0.4 * volatility_regime
        tp_mult = 1.8 + 0.5 * (1.0 - volatility_regime)

        if side == Direction.LONG:
            stop_loss = entry - stop_mult * atr
            take_profit = entry + tp_mult * atr
        else:
            stop_loss = entry + stop_mult * atr
            take_profit = entry - tp_mult * atr

        return round(stop_loss, 4), round(take_profit, 4)


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))
