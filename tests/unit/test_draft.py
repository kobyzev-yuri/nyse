"""Тесты чернового импульса."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pipeline import NewsImpactChannel, ScoredArticle, draft_impulse, single_scalar_draft_bias


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


def test_draft_regime_separate(utc_now: datetime):
    t0 = utc_now - timedelta(hours=2)
    articles = [
        ScoredArticle(t0, 0.1, NewsImpactChannel.INCREMENTAL),
        ScoredArticle(t0, 0.9, NewsImpactChannel.REGIME),
    ]
    d = draft_impulse(articles, now=utc_now)
    assert d.regime_stress > 0.0
