"""
Unit-тесты TradeBuilder и format_trade (без сети и без LLM).

Запуск:
    pytest tests/unit/test_trade_builder.py -v
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

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
    Position,
    PositionType,
    SignalBundle,
    TechnicalSignal,
    TechnicalSnapshot,
    Ticker,
    TickerData,
    TickerMetrics,
)
from pipeline import TradeBuilder, format_trade, neutral_calendar_signal
from pipeline.trade_builder import FusedBias


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
# FusedBias
# ---------------------------------------------------------------------------

def test_fuse_tech_only():
    builder = TradeBuilder()
    tech = _tech_signal(0.4)
    fused = builder.fuse_bias(tech, None)
    assert fused.value == pytest.approx(0.4)
    assert fused.confidence == pytest.approx(0.75)
    assert not fused.news_available
    assert fused.news_contrib == 0.0


def test_fuse_tech_and_news():
    builder = TradeBuilder()
    tech = _tech_signal(0.6, confidence=0.80)
    news = _news_signal(0.4, confidence=0.70)
    fused = builder.fuse_bias(tech, news)
    # 0.55*0.6 + 0.45*0.4 = 0.33 + 0.18 = 0.51
    assert fused.value == pytest.approx(0.51, abs=0.01)
    assert fused.news_available
    assert fused.news_contrib == pytest.approx(0.45 * 0.4, abs=0.001)


def test_fuse_opposite_signals_cancel():
    """Tech bullish, news bearish → слабый общий сигнал."""
    builder = TradeBuilder()
    fused = builder.fuse_bias(_tech_signal(0.5), _news_signal(-0.5))
    # 0.55*0.5 + 0.45*(-0.5) = 0.275 - 0.225 = 0.05
    assert abs(fused.value) < 0.10


def test_fuse_clips_to_minus_1_plus_1():
    builder = TradeBuilder()
    fused = builder.fuse_bias(_tech_signal(1.0), _news_signal(1.0))
    assert fused.value <= 1.0
    assert fused.value >= -1.0


# ---------------------------------------------------------------------------
# Position / Trade
# ---------------------------------------------------------------------------

def test_trade_long_position_levels():
    """LONG: TP > entry > SL, levels кратны ATR."""
    trade = TradeBuilder().build(_bundle(tech_bias=0.5, price=100.0, atr=5.0))
    assert trade.entry_type == PositionType.MARKET
    p = trade.position
    assert p.side == Direction.LONG
    assert p.entry == pytest.approx(100.0)
    assert p.take_profit == pytest.approx(100.0 + 2 * 5.0)   # TP = +2 ATR
    assert p.stop_loss   == pytest.approx(100.0 - 1 * 5.0)   # SL = -1 ATR
    assert p.take_profit > p.entry > p.stop_loss


def test_trade_short_position_levels():
    """SHORT: TP < entry < SL."""
    trade = TradeBuilder().build(_bundle(tech_bias=-0.5, price=200.0, atr=10.0))
    assert trade.entry_type == PositionType.MARKET
    p = trade.position
    assert p.side == Direction.SHORT
    assert p.take_profit == pytest.approx(200.0 - 2 * 10.0)
    assert p.stop_loss   == pytest.approx(200.0 + 1 * 10.0)
    assert p.take_profit < p.entry < p.stop_loss


def test_trade_no_position_weak_bias():
    """Слабый bias < MIN_ABS_BIAS (0.15) → PositionType.NONE."""
    trade = TradeBuilder().build(_bundle(tech_bias=0.05))
    assert trade.entry_type == PositionType.NONE
    assert trade.position is None


def test_trade_no_position_low_confidence():
    """Низкая confidence < MIN_CONFIDENCE (0.55) → NONE."""
    builder = TradeBuilder(min_confidence=0.80)
    trade = builder.build(_bundle(tech_bias=0.5))
    # default tech confidence=0.75 < 0.80 → NONE
    assert trade.entry_type == PositionType.NONE


def test_trade_news_improves_confidence():
    """С новостями confidence растёт и позволяет открыть позицию."""
    builder = TradeBuilder(min_confidence=0.75)
    # tech-only: conf=0.70 < 0.75 → NONE
    bundle_no_news = _bundle(tech_bias=0.4)
    bundle_no_news.technical_signal.confidence  # 0.75 default — let's make it lower
    tech = _tech_signal(0.4, confidence=0.65)
    news = _news_signal(0.4, confidence=0.90)
    bundle = SignalBundle(
        ticker=Ticker.SNDK,
        technical_signal=tech,
        news_signal=news,
        calendar_signal=neutral_calendar_signal(),
    )
    trade = builder.build(bundle)
    fused = builder.fuse_bias(tech, news)
    # conf = 0.55*0.65 + 0.45*0.90 = 0.3575 + 0.405 = 0.7625 >= 0.75
    assert fused.confidence >= 0.75
    assert trade.entry_type == PositionType.MARKET


def test_trade_summaries_populated():
    """Trade содержит непустые summary из tech и calendar."""
    trade = TradeBuilder().build(_bundle(tech_bias=0.4))
    assert trade.technical_summary
    assert trade.calendar_summary
    assert "нет" in " ".join(trade.news_summary).lower()  # tech-only → нет новостного сигнала


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
    assert "[SNDK]" in msg
    assert "LONG" in msg
    assert "Entry" in msg
    assert "$100" in msg


def test_format_trade_no_position():
    trade = TradeBuilder().build(_bundle(tech_bias=0.05))
    msg = format_trade(trade)
    assert "NO TRADE" in msg
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
    assert "News fusion contrib" in msg
    assert "tech(" in msg and "news(" in msg
