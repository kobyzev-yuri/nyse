"""Кластеризация REG по смыслу (TF-IDF / опционально OpenAI) для draft_impulse."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from domain import NewsArticle, Ticker
from pipeline.regime_cluster import RegimeClusterMeta, apply_regime_cluster_for_draft


def _art(
    title: str,
    *,
    cheap: float,
    hours_ago: float = 0,
    summary: str = "",
) -> NewsArticle:
    now = datetime(2026, 4, 8, 14, 0, 0, tzinfo=timezone.utc)
    ts = now - timedelta(hours=hours_ago)
    return NewsArticle(
        ticker=Ticker.SNDK,
        title=title,
        timestamp=ts,
        summary=summary or "iran ceasefire middle east crude oil markets",
        link="https://example.com/x",
        publisher="t",
        cheap_sentiment=cheap,
    )


def test_regime_cluster_merges_near_duplicate_geo_themes():
    """Две REG-статьи с идентичным title+summary схлопываются в один кластер (TF-IDF cos=1)."""
    inc = _art("Sandisk NAND pricing update for investors", cheap=0.4, summary="company flash")
    shared = "iran ceasefire persian gulf oil micron memory sector"
    title = "Middle East ceasefire moves oil and semiconductor names"
    r1 = _art(title, cheap=0.1, hours_ago=2, summary=shared)
    r2 = _art(title, cheap=-0.3, hours_ago=1, summary=shared)
    now = datetime(2026, 4, 8, 14, 0, 0, tzinfo=timezone.utc)
    merged, meta = apply_regime_cluster_for_draft(
        [inc, r1, r2],
        now=now,
        enabled=True,
        similarity_threshold=0.88,
        embed_backend="tfidf",
    )
    assert isinstance(meta, RegimeClusterMeta)
    assert meta.n_reg_in == 2
    assert meta.n_reg_out == 1
    assert meta.n_clusters == 1
    assert len(merged) == 2  # INC + 1 REG rep


def test_regime_cluster_disabled_passes_through():
    a = _art("Iran war risk and oil surge", cheap=0.2, summary="brent crude opec")
    b = _art("Gaza tensions and energy prices move", cheap=-0.1, summary="middle east oil")
    now = datetime(2026, 4, 8, 14, 0, 0, tzinfo=timezone.utc)
    merged, meta = apply_regime_cluster_for_draft(
        [a, b], now=now, enabled=False
    )
    assert meta is None
    assert len(merged) == 2


def test_regime_cluster_single_reg_no_meta():
    only = _art("Oil OPEC cut Brent futures", cheap=0.5)
    now = datetime(2026, 4, 8, 14, 0, 0, tzinfo=timezone.utc)
    merged, meta = apply_regime_cluster_for_draft([only], now=now, enabled=True)
    assert meta is None
    assert len(merged) == 1
