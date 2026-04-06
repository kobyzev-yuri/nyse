"""
Уровень 5 (шаг 5): агрегация ``list[NewsSignal]`` → ``AggregatedNewsSignal``.

Веса и логика **идентичны** ``pystockinvest/agent/news/signal.py`` (``_aggregate_signals``),
чтобы результат был совместим при слиянии репозиториев.

Запуск: ``python -m pipeline.news_signal_aggregator`` или ``python pipeline/news_signal_aggregator.py``.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.news_signal_aggregator", run_name="__main__")
    raise SystemExit(0)

from domain import (
    AggregatedNewsSignal,
    NewsImpact,
    NewsRelevance,
    NewsSignal,
    NewsTimeHorizon,
)

# Веса — тот же маппинг, что в Kerima (pystockinvest/agent/news/signal.py)
_RELEVANCE_WEIGHT: dict[NewsRelevance, float] = {
    NewsRelevance.MENTION: 0.4,
    NewsRelevance.RELATED: 0.7,
    NewsRelevance.PRIMARY: 1.0,
}

_IMPACT_WEIGHT: dict[NewsImpact, float] = {
    NewsImpact.LOW: 0.4,
    NewsImpact.MODERATE: 0.7,
    NewsImpact.HIGH: 1.0,
}

_HORIZON_WEIGHT: dict[NewsTimeHorizon, float] = {
    NewsTimeHorizon.INTRADAY: 0.8,
    NewsTimeHorizon.SHORT: 1.0,
    NewsTimeHorizon.MEDIUM: 0.6,
    NewsTimeHorizon.LONG: 0.3,
}


def aggregate_news_signals(signals: list[NewsSignal]) -> AggregatedNewsSignal:
    """
    Взвешенное среднее ``sentiment`` по весу ``relevance × impact × horizon × confidence``.

    Пустой список или нулевой суммарный вес → нейтральный агрегат (bias=0, confidence=0).
    """
    if not signals:
        return AggregatedNewsSignal(
            bias=0.0,
            confidence=0.0,
            summary=["No relevant news signals.", "News contribution is neutral."],
            items=[],
        )

    weighted_sum = 0.0
    weight_sum = 0.0
    confidence_sum = 0.0

    for s in signals:
        w = (
            _RELEVANCE_WEIGHT[s.relevance]
            * _IMPACT_WEIGHT[s.impact_strength]
            * _HORIZON_WEIGHT[s.time_horizon]
            * max(s.confidence, 0.05)
        )
        weighted_sum += s.sentiment * w
        confidence_sum += s.confidence * w
        weight_sum += w

    if weight_sum == 0.0:
        return AggregatedNewsSignal(
            bias=0.0,
            confidence=0.0,
            summary=[
                "No strong short-horizon news edge.",
                "News contribution is neutral.",
            ],
            items=signals,
        )

    bias = weighted_sum / weight_sum
    confidence = confidence_sum / weight_sum

    return AggregatedNewsSignal(
        bias=bias,
        confidence=confidence,
        summary=[
            f"Aggregated news bias is {bias:.2f} on a -1 to 1 scale.",
            f"News confidence is {confidence:.2f}.",
        ],
        items=signals,
    )


if __name__ == "__main__":
    from domain import NewsSurprise

    demo = [
        NewsSignal(
            sentiment=0.5,
            impact_strength=NewsImpact.HIGH,
            relevance=NewsRelevance.PRIMARY,
            surprise=NewsSurprise.SIGNIFICANT,
            time_horizon=NewsTimeHorizon.SHORT,
            confidence=0.8,
        ),
        NewsSignal(
            sentiment=-0.3,
            impact_strength=NewsImpact.MODERATE,
            relevance=NewsRelevance.RELATED,
            surprise=NewsSurprise.MINOR,
            time_horizon=NewsTimeHorizon.INTRADAY,
            confidence=0.5,
        ),
    ]
    agg = aggregate_news_signals(demo)
    print(f"bias={agg.bias:.4f}  confidence={agg.confidence:.4f}")
    print(agg.summary[0])
