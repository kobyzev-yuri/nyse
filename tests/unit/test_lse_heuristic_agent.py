"""Unit-тесты для LseHeuristicAgent (уровень 6, технический сигнал)."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from domain import Candle, Ticker, TickerData, TickerMetrics
from pipeline.technical import LseHeuristicAgent


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

def _candles(n: int, start: float = 100.0, drift: float = 0.5, noise: float = 0.3) -> list[Candle]:
    """Генерирует список свечей с заданным дрейфом."""
    result = []
    price = start
    for i in range(n):
        price += drift
        result.append(Candle(
            time=datetime.now(timezone.utc),
            open=price - noise,
            high=price + noise,
            low=price - noise,
            close=price,
            volume=1_000_000.0,
        ))
    return result


def _metrics(
    ticker: Ticker = Ticker.NBIS,
    rsi: float = 55.0,
    sma20_pct: float = 3.0,
    sma50_pct: float = 5.0,
    rel_vol: float = 1.5,
    atr: float = 0.80,
    beta: float = 1.2,
    perf_week: float = 2.0,
) -> TickerMetrics:
    return TickerMetrics(
        ticker=ticker,
        perf_week=perf_week,
        rsi_14=rsi,
        sma20_pct=sma20_pct,
        sma50_pct=sma50_pct,
        atr=atr,
        relative_volume=rel_vol,
        beta=beta,
    )


def _td(
    ticker: Ticker = Ticker.NBIS,
    price: float = 17.40,
    n_daily: int = 25,
    drift: float = 0.10,
) -> TickerData:
    return TickerData(
        ticker=ticker,
        current_price=price,
        daily_candles=_candles(n_daily, start=price - drift * n_daily, drift=drift),
        hourly_candles=_candles(48, start=price - 0.5, drift=0.01),
    )


# ---------------------------------------------------------------------------
# Базовые контракты
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_all_fields_in_range(self):
        agent = LseHeuristicAgent()
        sig = agent.predict(Ticker.NBIS, [_td()], [_metrics()])

        assert -1.0 <= sig.bias <= 1.0
        assert -1.0 <= sig.trend_score <= 1.0
        assert -1.0 <= sig.momentum_score <= 1.0
        assert -1.0 <= sig.mean_reversion_score <= 1.0
        assert -1.0 <= sig.breakout_score <= 1.0
        assert  0.0 <= sig.volatility_regime <= 1.0
        assert -1.0 <= sig.relative_strength_score <= 1.0
        assert -1.0 <= sig.market_alignment_score <= 1.0
        assert  0.0 <= sig.exhaustion_score <= 1.0
        assert -1.0 <= sig.support_resistance_pressure <= 1.0
        assert  0.0 <= sig.tradeability_score <= 1.0
        assert  0.0 <= sig.confidence <= 1.0

    def test_summary_non_empty(self):
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics()])
        assert len(sig.summary) >= 1
        assert all(isinstance(s, str) and s.strip() for s in sig.summary)

    def test_snapshot_references_input(self):
        td = _td()
        m = _metrics()
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [td], [m])
        assert sig.target_snapshot.data is td
        assert sig.target_snapshot.metrics is m

    def test_missing_ticker_raises(self):
        with pytest.raises(ValueError, match="TickerData"):
            LseHeuristicAgent().predict(Ticker.MU, [_td(Ticker.NBIS)], [_metrics(Ticker.NBIS)])

    def test_missing_metrics_raises(self):
        with pytest.raises(ValueError, match="TickerMetrics"):
            LseHeuristicAgent().predict(Ticker.MU, [_td(Ticker.MU)], [_metrics(Ticker.NBIS)])


# ---------------------------------------------------------------------------
# trend_score
# ---------------------------------------------------------------------------

class TestTrendScore:
    def test_bullish_sma_gives_positive(self):
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(sma20_pct=8.0)])
        assert sig.trend_score > 0

    def test_bearish_sma_gives_negative(self):
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(sma20_pct=-8.0)])
        assert sig.trend_score < 0

    def test_capped_at_1(self):
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(sma20_pct=50.0)])
        assert sig.trend_score == 1.0

    def test_capped_at_minus1(self):
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(sma20_pct=-50.0)])
        assert sig.trend_score == -1.0


# ---------------------------------------------------------------------------
# mean_reversion_score (RSI-based)
# ---------------------------------------------------------------------------

class TestMeanReversionScore:
    def test_oversold_rsi_gives_plus1(self):
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(rsi=25.0)])
        assert sig.mean_reversion_score == 1.0

    def test_overbought_rsi_gives_minus1(self):
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(rsi=75.0)])
        assert sig.mean_reversion_score == -1.0

    def test_neutral_rsi_near_zero(self):
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(rsi=50.0)])
        assert abs(sig.mean_reversion_score) < 0.1

    def test_monotone_in_rsi(self):
        """mean_reversion_score убывает при росте RSI."""
        agent = LseHeuristicAgent()
        scores = [
            agent.predict(Ticker.NBIS, [_td()], [_metrics(rsi=r)]).mean_reversion_score
            for r in [20, 35, 50, 65, 80]
        ]
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))


# ---------------------------------------------------------------------------
# exhaustion_score
# ---------------------------------------------------------------------------

class TestExhaustionScore:
    def test_neutral_rsi_is_zero_exhaustion(self):
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(rsi=50.0)])
        assert sig.exhaustion_score == pytest.approx(0.0, abs=0.01)

    def test_extreme_rsi_gives_high_exhaustion(self):
        for rsi in [5.0, 95.0]:
            sig = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(rsi=rsi)])
            assert sig.exhaustion_score > 0.8


# ---------------------------------------------------------------------------
# volatility_regime
# ---------------------------------------------------------------------------

class TestVolatilityRegime:
    def test_stable_candles_give_low_regime(self):
        # свечи без drift и без noise → очень низкая волатильность
        candles = [
            Candle(time=datetime.now(timezone.utc),
                   open=100.0, high=100.1, low=99.9, close=100.0, volume=1e6)
            for _ in range(25)
        ]
        td = TickerData(Ticker.NBIS, 100.0, candles, candles[:48])
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [td], [_metrics()])
        assert sig.volatility_regime < 0.5

    def test_volatile_candles_give_high_regime(self):
        # чередующиеся большие движения → высокая волатильность
        candles = []
        for i in range(25):
            price = 100.0 + (5.0 if i % 2 == 0 else -5.0)
            candles.append(Candle(
                time=datetime.now(timezone.utc),
                open=price, high=price + 1, low=price - 1, close=price, volume=1e6,
            ))
        td = TickerData(Ticker.NBIS, 100.0, candles, candles[:48])
        sig = LseHeuristicAgent().predict(Ticker.NBIS, [td], [_metrics()])
        assert sig.volatility_regime > 0.5


# ---------------------------------------------------------------------------
# market_alignment_score
# ---------------------------------------------------------------------------

class TestMarketAlignmentScore:
    def test_uses_smh_when_present(self):
        """Если SMH есть, market_alignment должен отражать его тренд."""
        td_target = _td(Ticker.NBIS)
        td_smh = _td(Ticker.SMH, price=200.0)
        m_target = _metrics(Ticker.NBIS, sma50_pct=0.0)
        m_smh = _metrics(Ticker.SMH, sma20_pct=15.0)  # сильно бычий SMH

        sig = LseHeuristicAgent().predict(
            Ticker.NBIS,
            [td_target, td_smh],
            [m_target, m_smh],
        )
        assert sig.market_alignment_score > 0

    def test_fallback_to_sma50_without_context(self):
        sig_bull = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(sma50_pct=18.0)])
        sig_bear = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(sma50_pct=-18.0)])
        assert sig_bull.market_alignment_score > 0
        assert sig_bear.market_alignment_score < 0


# ---------------------------------------------------------------------------
# bias formula (pystockinvest-совместимость)
# ---------------------------------------------------------------------------

class TestBiasFormula:
    def test_all_positive_scores_give_positive_bias(self):
        """При бычьих метриках bias > 0."""
        sig = LseHeuristicAgent().predict(
            Ticker.NBIS, [_td()],
            [_metrics(sma20_pct=8.0, sma50_pct=12.0, rsi=55.0, rel_vol=2.0)],
        )
        assert sig.bias > 0

    def test_all_negative_scores_give_negative_bias(self):
        """При медвежьих метриках bias < 0."""
        # Медвежий тикер: цена ниже SMA, RSI нейтральный, объём слабый
        candles_down = _candles(25, start=120.0, drift=-0.5)
        td = TickerData(Ticker.NBIS, 107.5, candles_down, candles_down[:48])
        sig = LseHeuristicAgent().predict(
            Ticker.NBIS, [td],
            [_metrics(sma20_pct=-8.0, sma50_pct=-12.0, rsi=50.0, rel_vol=0.5)],
        )
        assert sig.bias < 0

    def test_tradeability_increases_with_volume(self):
        lo = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(rel_vol=0.5)])
        hi = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(rel_vol=2.5)])
        assert hi.tradeability_score > lo.tradeability_score

    def test_confidence_increases_with_signal_clarity(self):
        """Сильный тренд (высокий |sma20_pct|) → выше confidence."""
        weak = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(sma20_pct=0.5)])
        strong = LseHeuristicAgent().predict(Ticker.NBIS, [_td()], [_metrics(sma20_pct=9.0)])
        assert strong.confidence > weak.confidence
