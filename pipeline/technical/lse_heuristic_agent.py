"""
Уровень 6: технический агент — эвристический baseline (без БД, без LLM).

Структured-альтернатива с тем же ``TechnicalAgentProtocol``: ``LlmTechnicalAgent``
(как ``pystockinvest/agent/market/agent.py``). В боте: ``NYSE_LLM_TECHNICAL=1``.

Логика: SMA/RSI/vol-based rules из lse/analyst_agent.py, переработанные в
score-поля TechnicalSignal. Нет PostgreSQL, нет ML-модели.

Формула bias идентична pystockinvest/agent/market/agent.py::

    bias = (
        0.30 * trend_score
        + 0.20 * momentum_score
        + 0.15 * breakout_score
        + 0.15 * relative_strength_score
        + 0.10 * support_resistance_pressure
        + 0.10 * market_alignment_score
        - 0.10 * exhaustion_penalty
    )
"""

from __future__ import annotations

import math
import statistics
from typing import Dict, List

from domain import (
    Candle,
    Ticker,
    TickerData,
    TickerMetrics,
    TechnicalSignal,
    TechnicalSnapshot,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции (чистые вычисления)
# ---------------------------------------------------------------------------

def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _pct_change(candles: List[Candle], periods: int) -> float:
    """% изменение цены за последние `periods` свечей."""
    if len(candles) <= periods:
        return 0.0
    old = candles[-periods - 1].close
    if old == 0:
        return 0.0
    return (candles[-1].close - old) / old * 100.0


def _volatility(candles: List[Candle], days: int) -> float:
    """Std dev логарифмических дневных доходностей (в %) за последние `days` свечей."""
    c = candles[-days:] if len(candles) >= days else candles
    if len(c) < 2:
        return 0.5
    changes = [
        math.log(c[i].close / c[i - 1].close) * 100.0
        for i in range(1, len(c))
        if c[i - 1].close > 0
    ]
    return statistics.stdev(changes) if len(changes) > 1 else 0.5


# ---------------------------------------------------------------------------
# Агент
# ---------------------------------------------------------------------------

class LseHeuristicAgent:
    """
    Реализует Protocol TechnicalAgent без внешних зависимостей.

    Источники данных:
    - ``TickerData.daily_candles`` (нужно ≥ 20 свечей для vol_20d; минимум — 5)
    - ``TickerMetrics`` (rsi_14, sma20_pct, sma50_pct, atr, relative_volume, beta)

    Контекстные тикеры (SMH, QQQ) используются для ``market_alignment_score``.

    Score-поля совпадают по смыслу с ``TechnicalSignalResponse`` (``pipeline.market_dto``);
    при LLM они приходят из structured output (промпт: ``pipeline.technical_signal_prompt``).
    """

    # Рыночные индикаторы для market_alignment; если есть — используем их sma20_pct.
    _CONTEXT_TICKERS = {Ticker.SMH, Ticker.QQQ}

    def predict(
        self,
        ticker: Ticker,
        ticker_data: List[TickerData],
        metrics: List[TickerMetrics],
    ) -> TechnicalSignal:
        by_data: Dict[Ticker, TickerData] = {td.ticker: td for td in ticker_data}
        by_metrics: Dict[Ticker, TickerMetrics] = {m.ticker: m for m in metrics}

        td = by_data.get(ticker)
        m = by_metrics.get(ticker)
        if td is None:
            raise ValueError(f"LseHeuristicAgent: no TickerData for {ticker}")
        if m is None:
            raise ValueError(f"LseHeuristicAgent: no TickerMetrics for {ticker}")

        return self._compute(td, m, by_metrics)

    # ------------------------------------------------------------------
    # Основной расчёт
    # ------------------------------------------------------------------

    def _compute(
        self,
        td: TickerData,
        m: TickerMetrics,
        all_metrics: Dict[Ticker, TickerMetrics],
    ) -> TechnicalSignal:
        dc = td.daily_candles
        price = td.current_price if td.current_price > 0 else (dc[-1].close if dc else 0.0)

        change_3d = _pct_change(dc, 3)
        vol_5d    = _volatility(dc, 5)
        vol_20d   = _volatility(dc, 20)

        last5  = dc[-5:]  if len(dc) >= 5  else dc
        last20 = dc[-20:] if len(dc) >= 20 else dc

        high_5d  = max(c.high for c in last5)  if last5  else price
        low_5d   = min(c.low  for c in last5)  if last5  else price
        high_20d = max(c.high for c in last20) if last20 else price
        low_20d  = min(c.low  for c in last20) if last20 else price

        rsi = m.rsi_14

        # -- trend_score: sma20_pct (Finviz); ±10% → ±1.0 ----------------
        trend_score = _clip(m.sma20_pct / 10.0)

        # -- momentum_score: доходность 3д / волатильность ----------------
        momentum_score = _clip(change_3d / max(vol_5d, 0.1))

        # -- mean_reversion_score: RSI-based ------------------------------
        # RSI ≤ 30 → +1.0 (перепродан, ждём отскок вверх)
        # RSI ≥ 70 → -1.0 (перекуплен, ждём откат)
        # линейно между 30 и 70: 50 → 0
        if rsi <= 30:
            mean_reversion_score = 1.0
        elif rsi >= 70:
            mean_reversion_score = -1.0
        else:
            mean_reversion_score = _clip(1.0 - (rsi - 30.0) / 20.0)

        # -- breakout_score: позиция в 5-дневном диапазоне ---------------
        # близко к high5d → +1 (пробой вверх), к low5d → -1 (пробой вниз)
        range_5d = high_5d - low_5d
        if range_5d > 0:
            breakout_score = _clip((price - low_5d) / range_5d * 2.0 - 1.0)
        else:
            breakout_score = 0.0

        # -- volatility_regime: vol_5d / vol_20d --------------------------
        # 0 = тихо, 1 = режим высокой волатильности
        volatility_regime = _clip(vol_5d / max(vol_20d, 0.01), 0.0, 1.0)

        # -- relative_strength_score: relative_volume (Finviz) -----------
        # 1.0 = средний объём → 0, 2.0 → +1, 0.0 → -1
        relative_strength_score = _clip(m.relative_volume - 1.0)

        # -- market_alignment_score --------------------------------------
        market_alignment_score = self._market_alignment(m, all_metrics)

        # -- exhaustion_score: удалённость RSI от нейтрали ---------------
        # 0 = RSI ≈ 50 (нет перегрева), 1 = RSI у краёв (100 или 0)
        exhaustion_score = _clip(abs(rsi - 50.0) / 50.0, 0.0, 1.0)

        # -- support_resistance_pressure: позиция в 20-дневном диапазоне -
        # у low_20d (+1, поддержка снизу), у high_20d (-1, сопротивление сверху)
        range_20d = high_20d - low_20d
        if range_20d > 0:
            pos_20d = (price - low_20d) / range_20d  # 0..1
            support_resistance_pressure = _clip(1.0 - pos_20d * 2.0)
        else:
            support_resistance_pressure = 0.0

        # -- tradeability_score ------------------------------------------
        # Спокойный рынок + повышенный объём = удобно торговать
        vol_ok       = max(0.0, 1.0 - volatility_regime)
        rel_vol_norm = _clip(m.relative_volume / 2.0, 0.0, 1.0)
        tradeability_score = _clip(0.25 + 0.45 * vol_ok + 0.30 * rel_vol_norm, 0.0, 1.0)

        # -- confidence --------------------------------------------------
        signal_clarity = abs(trend_score + momentum_score) / 2.0
        confidence = _clip(
            0.40
            + 0.25 * signal_clarity
            + 0.20 * rel_vol_norm
            + 0.15 * (1.0 - exhaustion_score),
            0.0, 1.0,
        )

        # -- bias: формула идентична pystockinvest/agent/market/agent.py -
        exhaustion_penalty = exhaustion_score * (1.0 if trend_score >= 0 else -1.0)
        bias = _clip(
            0.30 * trend_score
            + 0.20 * momentum_score
            + 0.15 * breakout_score
            + 0.15 * relative_strength_score
            + 0.10 * support_resistance_pressure
            + 0.10 * market_alignment_score
            - 0.10 * exhaustion_penalty
        )

        return TechnicalSignal(
            bias=round(bias, 4),
            trend_score=round(trend_score, 4),
            momentum_score=round(momentum_score, 4),
            mean_reversion_score=round(mean_reversion_score, 4),
            breakout_score=round(breakout_score, 4),
            volatility_regime=round(volatility_regime, 4),
            relative_strength_score=round(relative_strength_score, 4),
            market_alignment_score=round(market_alignment_score, 4),
            exhaustion_score=round(exhaustion_score, 4),
            support_resistance_pressure=round(support_resistance_pressure, 4),
            tradeability_score=round(tradeability_score, 4),
            confidence=round(confidence, 4),
            target_snapshot=TechnicalSnapshot(data=td, metrics=m),
            summary=self._make_summary(bias, trend_score, rsi, volatility_regime, m.atr),
        )

    # ------------------------------------------------------------------
    # Вспомогательные методы
    # ------------------------------------------------------------------

    def _market_alignment(
        self,
        m: TickerMetrics,
        all_metrics: Dict[Ticker, TickerMetrics],
    ) -> float:
        """
        Согласованность с широким рынком.
        Если есть SMH и/или QQQ — усредняем их sma20_pct (±10% → ±1.0).
        Fallback: sma50_pct самого тикера (±20% → ±1.0).
        """
        ctx_scores = [
            _clip(all_metrics[t].sma20_pct / 10.0)
            for t in self._CONTEXT_TICKERS
            if t in all_metrics
        ]
        if ctx_scores:
            return _clip(sum(ctx_scores) / len(ctx_scores))
        return _clip(m.sma50_pct / 20.0)

    @staticmethod
    def _make_summary(
        bias: float,
        trend_score: float,
        rsi: float,
        volatility_regime: float,
        atr: float,
    ) -> list[str]:
        direction = "bullish" if bias > 0 else "bearish"
        strength  = "strong" if abs(bias) > 0.40 else "moderate" if abs(bias) > 0.15 else "weak"
        rsi_note  = (
            f"RSI {rsi:.0f} — overbought." if rsi > 70 else
            f"RSI {rsi:.0f} — oversold."   if rsi < 30 else
            f"RSI {rsi:.0f} — neutral zone."
        )
        vol_note = (
            f"Volatility regime {volatility_regime:.2f} — elevated, use wider stops (ATR={atr:.2f})."
            if volatility_regime > 0.70
            else f"Volatility regime {volatility_regime:.2f} — calm, clean structure (ATR={atr:.2f})."
        )
        return [
            f"Technical bias {bias:+.2f} ({strength} {direction}).",
            f"Trend score {trend_score:+.2f}. {rsi_note}",
            vol_note,
        ]


# ---------------------------------------------------------------------------
# Быстрый smoke-тест (python -m pipeline.technical.lse_heuristic_agent)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    from pathlib import Path

    _root = Path(__file__).resolve().parents[3]
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))

    from datetime import datetime, timezone
    from domain import Candle, Ticker, TickerData, TickerMetrics

    def _fake_candles(n: int, start: float = 100.0, drift: float = 0.5) -> list[Candle]:
        candles = []
        price = start
        for i in range(n):
            price += drift
            candles.append(Candle(
                time=datetime.now(timezone.utc),
                open=price - 0.2,
                high=price + 0.5,
                low=price - 0.5,
                close=price,
                volume=1_000_000.0,
            ))
        return candles

    td = TickerData(
        ticker=Ticker.NBIS,
        current_price=17.40,
        daily_candles=_fake_candles(25, start=15.0, drift=0.10),
        hourly_candles=_fake_candles(48, start=16.5, drift=0.02),
    )
    m = TickerMetrics(
        ticker=Ticker.NBIS,
        perf_week=5.2,
        rsi_14=58.0,
        sma20_pct=4.5,
        sma50_pct=8.0,
        atr=0.85,
        relative_volume=1.8,
        beta=1.4,
    )

    agent = LseHeuristicAgent()
    sig = agent.predict(Ticker.NBIS, [td], [m])
    print(f"bias={sig.bias:+.4f}  conf={sig.confidence:.4f}  tradeable={sig.tradeability_score:.4f}")
    for line in sig.summary:
        print(" ", line)
