"""Агрегатор NewsSignal → AggregatedNewsSignal (уровень 5, шаг 5)."""

from __future__ import annotations

import pytest

from domain import (
    AggregatedNewsSignal,
    NewsImpact,
    NewsRelevance,
    NewsSignal,
    NewsSurprise,
    NewsTimeHorizon,
)
from pipeline.news_signal_aggregator import aggregate_news_signals


def _sig(
    sentiment: float,
    impact: NewsImpact = NewsImpact.MODERATE,
    relevance: NewsRelevance = NewsRelevance.PRIMARY,
    surprise: NewsSurprise = NewsSurprise.NONE,
    horizon: NewsTimeHorizon = NewsTimeHorizon.SHORT,
    confidence: float = 1.0,
) -> NewsSignal:
    return NewsSignal(
        sentiment=sentiment,
        impact_strength=impact,
        relevance=relevance,
        surprise=surprise,
        time_horizon=horizon,
        confidence=confidence,
    )


def test_empty_signals_returns_neutral():
    r = aggregate_news_signals([])
    assert r.bias == pytest.approx(0.0)
    assert r.confidence == pytest.approx(0.0)
    assert r.items == []
    assert any("neutral" in s.lower() for s in r.summary)


def test_single_signal_bias_equals_sentiment():
    """Один сигнал: bias = sentiment (вес нормируется на себя)."""
    r = aggregate_news_signals([_sig(0.5)])
    assert r.bias == pytest.approx(0.5)


def test_two_opposite_equal_weight_cancel():
    """Два одинаковых по весу, противоположных sentiment → bias ≈ 0."""
    r = aggregate_news_signals([_sig(0.5), _sig(-0.5)])
    assert r.bias == pytest.approx(0.0, abs=1e-9)


def test_higher_relevance_has_more_weight():
    """PRIMARY тянет сильнее, чем MENTION при одинаковом sentiment."""
    primary = _sig(0.8, relevance=NewsRelevance.PRIMARY, confidence=1.0)
    mention = _sig(-1.0, relevance=NewsRelevance.MENTION, confidence=1.0)
    r = aggregate_news_signals([primary, mention])
    assert r.bias > 0.0


def test_higher_impact_has_more_weight():
    """HIGH impact тянет сильнее LOW при одинаковой relevance/horizon."""
    strong = _sig(1.0, impact=NewsImpact.HIGH, confidence=1.0)
    weak = _sig(-1.0, impact=NewsImpact.LOW, confidence=1.0)
    r = aggregate_news_signals([strong, weak])
    assert r.bias > 0.0


def test_lower_confidence_clamps_to_minimum():
    """confidence=0 → используется пол 0.05, не нуль."""
    r = aggregate_news_signals([_sig(0.5, confidence=0.0)])
    assert r.bias == pytest.approx(0.5)


def test_short_horizon_outweighs_long():
    """SHORT (1.0) доминирует над LONG (0.3) при прочих равных."""
    short = _sig(0.9, horizon=NewsTimeHorizon.SHORT, confidence=1.0)
    long_ = _sig(-1.0, horizon=NewsTimeHorizon.LONG, confidence=1.0)
    r = aggregate_news_signals([short, long_])
    assert r.bias > 0.0


def test_result_items_reference():
    """items в AggregatedNewsSignal — тот же список объектов."""
    sigs = [_sig(0.1), _sig(-0.1)]
    r = aggregate_news_signals(sigs)
    assert r.items is sigs


def test_bias_in_valid_range_for_mixed():
    """bias должен быть в [−1, 1] для любых входных данных."""
    sigs = [
        _sig(1.0, impact=NewsImpact.HIGH, relevance=NewsRelevance.PRIMARY),
        _sig(-1.0, impact=NewsImpact.HIGH, relevance=NewsRelevance.PRIMARY),
        _sig(0.7, impact=NewsImpact.MODERATE, relevance=NewsRelevance.RELATED),
    ]
    r = aggregate_news_signals(sigs)
    assert -1.0 <= r.bias <= 1.0


def test_known_values_match_pystockinvest_formula():
    """
    Ручная проверка формулы (один сигнал):
        w = relevance(PRIMARY=1.0) * impact(HIGH=1.0) * horizon(SHORT=1.0) * confidence(0.8)
          = 1.0 * 1.0 * 1.0 * 0.8 = 0.8
        bias  = (0.5 * 0.8) / 0.8 = 0.5
        conf  = (0.8 * 0.8) / 0.8 = 0.8
    """
    sig = NewsSignal(
        sentiment=0.5,
        impact_strength=NewsImpact.HIGH,
        relevance=NewsRelevance.PRIMARY,
        surprise=NewsSurprise.NONE,
        time_horizon=NewsTimeHorizon.SHORT,
        confidence=0.8,
    )
    r = aggregate_news_signals([sig])
    assert r.bias == pytest.approx(0.5)
    assert r.confidence == pytest.approx(0.8)
    assert isinstance(r, AggregatedNewsSignal)
