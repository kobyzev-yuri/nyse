"""
Уровень 5: DTO `NewsSignal` / `AggregatedNewsSignal` в `domain` (совместимость с pystockinvest).

Значения enum и имена полей держим в синхроне с `pystockinvest/agent/models.py`.
"""

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


@pytest.mark.parametrize(
    "enum_cls, value",
    [
        (NewsTimeHorizon.INTRADAY, "intraday"),
        (NewsTimeHorizon.SHORT, "1-3d"),
        (NewsTimeHorizon.MEDIUM, "3-7d"),
        (NewsTimeHorizon.LONG, "long"),
    ],
)
def test_news_time_horizon_values(enum_cls, value):
    assert enum_cls.value == value


@pytest.mark.parametrize(
    "enum_cls, value",
    [
        (NewsSurprise.NONE, "none"),
        (NewsSurprise.MINOR, "minor"),
        (NewsSurprise.SIGNIFICANT, "significant"),
        (NewsSurprise.MAJOR, "major"),
    ],
)
def test_news_surprise_values(enum_cls, value):
    assert enum_cls.value == value


@pytest.mark.parametrize(
    "enum_cls, value",
    [
        (NewsImpact.LOW, "low"),
        (NewsImpact.MODERATE, "moderate"),
        (NewsImpact.HIGH, "high"),
    ],
)
def test_news_impact_values(enum_cls, value):
    assert enum_cls.value == value


@pytest.mark.parametrize(
    "enum_cls, value",
    [
        (NewsRelevance.MENTION, "mention"),
        (NewsRelevance.RELATED, "related"),
        (NewsRelevance.PRIMARY, "primary"),
    ],
)
def test_news_relevance_values(enum_cls, value):
    assert enum_cls.value == value


def test_news_signal_and_aggregate_roundtrip_fields():
    sig = NewsSignal(
        sentiment=0.2,
        impact_strength=NewsImpact.MODERATE,
        relevance=NewsRelevance.PRIMARY,
        surprise=NewsSurprise.MINOR,
        time_horizon=NewsTimeHorizon.SHORT,
        confidence=0.75,
    )
    agg = AggregatedNewsSignal(
        bias=0.15,
        confidence=0.6,
        summary=["line one", "line two"],
        items=[sig],
    )
    assert agg.items[0] is sig
    assert agg.bias == pytest.approx(0.15)
    assert len(agg.summary) == 2


def test_empty_aggregate_items():
    agg = AggregatedNewsSignal(
        bias=0.0,
        confidence=0.0,
        summary=["neutral"],
        items=[],
    )
    assert agg.items == []
