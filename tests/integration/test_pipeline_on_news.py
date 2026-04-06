"""Интеграция: pipeline (канал → draft → scalar) на реальных заголовках Yahoo."""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_pipeline_end_to_end_from_yfinance(load_nyse_config):
    pytest.importorskip("yfinance")
    from domain import Ticker
    from pipeline import (
        ScoredArticle,
        classify_channel,
        decide_llm_mode,
        draft_impulse,
        GateContext,
        single_scalar_draft_bias,
        ThresholdConfig,
    )
    from sources.news import Source

    articles = Source(max_per_ticker=15, lookback_hours=72).get_articles([Ticker.NVDA])
    if not articles:
        pytest.skip("Yahoo не вернул новостей за окно (временно или лимит)")

    scored: list[ScoredArticle] = []
    for a in articles:
        ch, _ = classify_channel(a.title, a.summary)
        cheap = 0.0
        scored.append(
            ScoredArticle(
                published_at=a.timestamp,
                cheap_sentiment=cheap,
                channel=ch,
            )
        )

    d = draft_impulse(scored)
    bias = single_scalar_draft_bias(d)
    mode = decide_llm_mode(
        ThresholdConfig(),
        GateContext(
            draft_bias=bias,
            regime_present=d.regime_stress > 0.01,
            regime_rule_confidence=0.85 if d.regime_stress > 0.01 else 0.0,
            calendar_high_soon=False,
            article_count=len(articles),
        ),
    )
    assert mode.value in ("skip", "lite", "full")
