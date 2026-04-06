"""
Тесты чернового импульса (``draft_impulse``, ``scored_from_news_articles``).

Запуск из корня nyse::

    python -m pytest tests/unit/test_draft.py -v

Или: ``python tests/unit/test_draft.py`` (в конце вызывается pytest).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain import NewsArticle, Ticker

from pipeline import (
    NewsImpactChannel,
    ScoredArticle,
    draft_impulse,
    scored_from_news_articles,
    single_scalar_draft_bias,
)


def test_draft_empty():
    d = draft_impulse([])
    assert d.draft_bias_incremental == 0.0
    assert single_scalar_draft_bias(d) == 0.0


def test_draft_incremental_only(utc_now: datetime):
    t0 = utc_now - timedelta(hours=1)
    articles = [
        ScoredArticle(t0, 0.5, NewsImpactChannel.INCREMENTAL),
        ScoredArticle(t0, -0.2, NewsImpactChannel.INCREMENTAL),
    ]
    d = draft_impulse(articles, now=utc_now, half_life_hours=24.0)
    assert -0.2 < d.draft_bias_incremental < 0.5
    assert d.regime_stress == 0.0
    assert d.articles_incremental == 2
    assert d.articles_regime == 0
    assert d.weight_sum_incremental > 0.0


def test_scored_from_news_articles_uses_cheap_sentiment(utc_now: datetime):
    """После этапа B: ``cheap_sentiment`` попадает в ``ScoredArticle``."""
    a = NewsArticle(
        ticker=Ticker.NVDA,
        title="NVDA beats estimates",
        timestamp=utc_now,
        summary=None,
        link=None,
        publisher=None,
        cheap_sentiment=0.3,
    )
    scored = scored_from_news_articles([a])
    assert len(scored) == 1
    assert scored[0].cheap_sentiment == pytest.approx(0.3)
    assert scored[0].channel == NewsImpactChannel.INCREMENTAL


def test_draft_regime_separate(utc_now: datetime):
    t0 = utc_now - timedelta(hours=2)
    articles = [
        ScoredArticle(t0, 0.1, NewsImpactChannel.INCREMENTAL),
        ScoredArticle(t0, 0.9, NewsImpactChannel.REGIME),
    ]
    d = draft_impulse(articles, now=utc_now)
    assert d.regime_stress > 0.0
    assert d.articles_incremental == 1
    assert d.articles_regime == 1
    assert d.max_abs_regime == pytest.approx(0.9)


def test_draft_incremental_only_channel_regime_does_not_mix_into_incremental_bias(
    utc_now: datetime,
):
    """
    Этап D / §5.4: REGIME не входит в среднее по INCREMENTAL — только в regime_stress.
    """
    t0 = utc_now - timedelta(hours=1)
    articles = [
        ScoredArticle(t0, 0.8, NewsImpactChannel.REGIME),
        ScoredArticle(t0, -0.7, NewsImpactChannel.REGIME),
    ]
    d = draft_impulse(articles, now=utc_now)
    assert d.draft_bias_incremental == pytest.approx(0.0)
    assert d.articles_incremental == 0
    assert d.articles_regime == 2
    assert d.regime_stress > 0.0


def test_draft_policy_max_abs_and_counts(utc_now: datetime):
    t0 = utc_now - timedelta(hours=1)
    articles = [
        ScoredArticle(t0, 0.2, NewsImpactChannel.POLICY_RATES),
        ScoredArticle(t0, -0.5, NewsImpactChannel.POLICY_RATES),
    ]
    d = draft_impulse(articles, now=utc_now)
    assert d.articles_policy == 2
    assert d.articles_incremental == 0
    assert d.max_abs_policy == pytest.approx(0.5)
    assert d.policy_stress > 0.0


if __name__ == "__main__":
    raise SystemExit(
        pytest.main(
            [
                __file__,
                "-v",
                "--tb=short",
                "-rA",
            ]
        )
    )
