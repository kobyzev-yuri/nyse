"""
Unit-тесты TradeBuilder (логика как в pystockinvest/agent/trade.py) и format_trade.

Запуск:
    pytest tests/unit/test_trade_builder.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain import (
    AggregatedNewsSignal,
    Candle,
    Direction,
    NewsSignal,
    NewsTimeHorizon,
    NewsImpact,
    NewsRelevance,
    NewsSurprise,
    PositionType,
    SignalBundle,
    TechnicalSignal,
    TechnicalSnapshot,
    Ticker,
    TickerData,
    TickerMetrics,
)
from pipeline import TradeBuilder, format_trade, neutral_calendar_signal
from pipeline.trade_builder import W_CAL, W_NEWS, W_TECH


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------


def _candle(close: float) -> Candle:
    return Candle(time=datetime.now(timezone.utc), open=close, high=close, low=close, close=close, volume=1_000_000.0)


def _ticker_data(price: float = 100.0) -> TickerData:
    return TickerData(
        ticker=Ticker.SNDK,
        current_price=price,
        daily_candles=[_candle(price)],
        hourly_candles=[],
    )


def _metrics(rsi: float = 50.0, atr: float = 5.0) -> TickerMetrics:
    return TickerMetrics(
        ticker=Ticker.SNDK,
        perf_week=1.0,
        rsi_14=rsi,
        sma20_pct=3.0,
        sma50_pct=5.0,
        atr=atr,
        relative_volume=1.2,
        beta=1.1,
    )


def _tech_signal(bias: float, confidence: float = 0.75, price: float = 100.0, atr: float = 5.0) -> TechnicalSignal:
    snap = TechnicalSnapshot(data=_ticker_data(price), metrics=_metrics(atr=atr))
    return TechnicalSignal(
        bias=bias,
        trend_score=bias,
        momentum_score=bias * 0.5,
        mean_reversion_score=0.0,
        breakout_score=0.0,
        volatility_regime=0.3,
        relative_strength_score=0.1,
        market_alignment_score=0.1,
        exhaustion_score=0.1,
        support_resistance_pressure=0.0,
        tradeability_score=0.7,
        confidence=confidence,
        target_snapshot=snap,
        summary=[f"Tech bias {bias:+.2f}. RSI 50."],
    )


def _news_signal(bias: float, confidence: float = 0.75, n: int = 5) -> AggregatedNewsSignal:
    item = NewsSignal(
        sentiment=bias,
        impact_strength=NewsImpact.MODERATE,
        relevance=NewsRelevance.PRIMARY,
        surprise=NewsSurprise.MINOR,
        time_horizon=NewsTimeHorizon.INTRADAY,
        confidence=confidence,
    )
    return AggregatedNewsSignal(
        bias=bias,
        confidence=confidence,
        summary=[f"News bias {bias:+.2f}, {n} items."],
        items=[item] * n,
    )


def _bundle(
    tech_bias: float = 0.4,
    news_bias: float | None = None,
    price: float = 100.0,
    atr: float = 5.0,
) -> SignalBundle:
    tech = _tech_signal(tech_bias, price=price, atr=atr)
    news = _news_signal(news_bias) if news_bias is not None else None
    return SignalBundle(
        ticker=Ticker.SNDK,
        technical_signal=tech,
        news_signal=news,
        calendar_signal=neutral_calendar_signal(),
    )


# ---------------------------------------------------------------------------
# FusedBias (55% / 30% / 15% как в pystockinvest)
# ---------------------------------------------------------------------------


def test_fuse_tech_only():
    builder = TradeBuilder()
    tech = _tech_signal(0.4)
    fused = builder.fuse_bias(tech, None, neutral_calendar_signal())
    # 0.55 * 0.4 + 0 + 0.15 * 0 = 0.22
    assert fused.value == pytest.approx(W_TECH * 0.4)
    assert fused.cal_contrib == pytest.approx(0.0)
    assert not fused.news_available
    assert fused.news_contrib == 0.0
    # agreement_bonus = 0.22*0.15; raw = 0.5*0.75 + 0.2*0.5 + bonus
    assert fused.confidence == pytest.approx(0.508, abs=0.001)


def test_fuse_tech_and_news():
    builder = TradeBuilder()
    tech = _tech_signal(0.6, confidence=0.80)
    news = _news_signal(0.4, confidence=0.70)
    fused = builder.fuse_bias(tech, news)
    assert fused.value == pytest.approx(W_TECH * 0.6 + W_NEWS * 0.4)
    assert fused.news_available
    assert fused.news_contrib == pytest.approx(W_NEWS * 0.4, abs=0.001)


def test_fuse_opposite_signals():
    builder = TradeBuilder()
    fused = builder.fuse_bias(_tech_signal(0.5), _news_signal(-0.5))
    assert fused.value == pytest.approx(W_TECH * 0.5 + W_NEWS * (-0.5))


def test_fuse_clips_to_minus_1_plus_1():
    builder = TradeBuilder()
    fused = builder.fuse_bias(_tech_signal(1.0), _news_signal(1.0))
    assert fused.value <= 1.0
    assert fused.value >= -1.0


# ---------------------------------------------------------------------------
# Position / Trade (как pystockinvest: LIMIT по умолчанию, TP/SL от volatility_regime)
# ---------------------------------------------------------------------------


def test_trade_long_limit_levels():
    """LONG: LIMIT-вход, TP/SL от ATR и volatility_regime."""
    trade = TradeBuilder().build(_bundle(tech_bias=0.5, price=100.0, atr=5.0))
    assert trade.entry_type == PositionType.LIMIT
    p = trade.position
    assert p is not None
    assert p.side == Direction.LONG
    entry = 100.0 - 0.25 * 5.0
    assert p.entry == pytest.approx(entry, abs=0.001)
    stop_mult = 1.0 + 0.4 * 0.3
    tp_mult = 1.8 + 0.5 * (1.0 - 0.3)
    assert p.stop_loss == pytest.approx(entry - stop_mult * 5.0, abs=0.001)
    assert p.take_profit == pytest.approx(entry + tp_mult * 5.0, abs=0.001)
    assert p.take_profit > p.entry > p.stop_loss


def test_trade_short_limit_levels():
    """SHORT: LIMIT-вход, TP ниже entry, SL выше."""
    trade = TradeBuilder().build(_bundle(tech_bias=-0.5, price=200.0, atr=10.0))
    assert trade.entry_type == PositionType.LIMIT
    p = trade.position
    assert p is not None
    assert p.side == Direction.SHORT
    entry = 200.0 + 0.25 * 10.0
    assert p.entry == pytest.approx(entry, abs=0.001)
    stop_mult = 1.0 + 0.4 * 0.3
    tp_mult = 1.8 + 0.5 * (1.0 - 0.3)
    assert p.take_profit == pytest.approx(entry - tp_mult * 10.0, abs=0.001)
    assert p.stop_loss == pytest.approx(entry + stop_mult * 10.0, abs=0.001)
    assert p.take_profit < p.entry < p.stop_loss


def test_trade_no_position_weak_final_bias():
    """|final_bias| ≤ 0.20 → нет позиции (как в pystockinvest)."""
    trade = TradeBuilder().build(_bundle(tech_bias=0.05))
    assert trade.entry_type == PositionType.NONE
    assert trade.position is None


def test_trade_no_position_low_tradeability():
    """tradeability_score < 0.40 → нет позиции."""
    tech = _tech_signal(0.5)
    tech.tradeability_score = 0.35
    bundle = SignalBundle(
        ticker=Ticker.SNDK,
        technical_signal=tech,
        news_signal=None,
        calendar_signal=neutral_calendar_signal(),
    )
    trade = TradeBuilder().build(bundle)
    assert trade.position is None
    assert trade.entry_type == PositionType.NONE


def test_trade_market_when_breakout_and_urgent_news():
    """MARKET при breakout_preferred и |news.bias| > 0.4."""
    tech = _tech_signal(0.5)
    tech.breakout_score = 0.8
    tech.mean_reversion_score = 0.1
    tech.exhaustion_score = 0.5
    news = _news_signal(0.5)
    bundle = SignalBundle(
        ticker=Ticker.SNDK,
        technical_signal=tech,
        news_signal=news,
        calendar_signal=neutral_calendar_signal(),
    )
    trade = TradeBuilder().build(bundle)
    assert trade.entry_type == PositionType.MARKET
    assert trade.position is not None
    assert trade.position.entry == pytest.approx(100.0, abs=0.0001)


def test_trade_summaries_populated():
    trade = TradeBuilder().build(_bundle(tech_bias=0.4))
    assert trade.technical_summary
    assert trade.calendar_summary


def test_trade_ticker_preserved():
    trade = TradeBuilder().build(_bundle(tech_bias=0.4))
    assert trade.ticker == Ticker.SNDK


# ---------------------------------------------------------------------------
# format_trade
# ---------------------------------------------------------------------------


def test_format_trade_long():
    trade = TradeBuilder().build(_bundle(tech_bias=0.4, price=100.0))
    fused = TradeBuilder().fuse_bias(_tech_signal(0.4, price=100.0), None)
    msg = format_trade(trade, fused=fused)
    assert "[SNDK]" in msg or "SNDK" in msg
    assert "LONG" in msg
    assert "Entry" in msg
    assert "Cal" in msg or "Fused" in msg


def test_format_trade_no_position():
    trade = TradeBuilder().build(_bundle(tech_bias=0.05))
    msg = format_trade(trade)
    assert "NO TRADE" in msg or "нет сигнала" in msg
    assert "SNDK" in msg


def test_format_trade_with_news():
    tech = _tech_signal(0.4, price=500.0, atr=20.0)
    news = _news_signal(0.5)
    bundle = SignalBundle(
        ticker=Ticker.SNDK,
        technical_signal=tech,
        news_signal=news,
        calendar_signal=neutral_calendar_signal(),
    )
    builder = TradeBuilder()
    trade = builder.build(bundle)
    fused = builder.fuse_bias(tech, news)
    msg = format_trade(trade, fused=fused)
    assert "Fused" in msg
    assert "News" in msg
