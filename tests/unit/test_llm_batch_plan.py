"""План батча по LLMMode (уровень 5, шаг 3)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain import NewsArticle, Ticker
from pipeline import LLMMode, ThresholdConfig, plan_llm_article_batch


def _article(title: str, cheap: float | None) -> NewsArticle:
    return NewsArticle(
        ticker=Ticker.NVDA,
        title=title,
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        summary=None,
        link=None,
        publisher=None,
        cheap_sentiment=cheap,
    )


def test_skip_empty():
    cfg = ThresholdConfig()
    a = [_article("a", 0.5)]
    p = plan_llm_article_batch(LLMMode.SKIP, a, cfg=cfg)
    assert p.indices_for_structured_signal == ()
    assert p.titles_for_lite_digest == ()


def test_lite_titles_only():
    cfg = ThresholdConfig()
    arts = [_article("t1", 0.1), _article("t2", -0.2)]
    p = plan_llm_article_batch(LLMMode.LITE, arts, cfg=cfg, max_titles_digest=10)
    assert p.indices_for_structured_signal == ()
    assert p.titles_for_lite_digest == ("t1", "t2")


def test_lite_respects_max_titles():
    cfg = ThresholdConfig()
    arts = [_article(f"h{i}", 0.0) for i in range(5)]
    p = plan_llm_article_batch(LLMMode.LITE, arts, cfg=cfg, max_titles_digest=2)
    assert p.titles_for_lite_digest == ("h0", "h1")


def test_full_all_when_under_cap():
    cfg = ThresholdConfig(max_articles_full_batch=10)
    arts = [_article("x", 0.1), _article("y", -0.2)]
    p = plan_llm_article_batch(LLMMode.FULL, arts, cfg=cfg)
    assert p.indices_for_structured_signal == (0, 1)


def test_full_top_k_when_over_cap():
    cfg = ThresholdConfig(max_articles_full_batch=10)
    arts = [_article("x", 0.1), _article("y", -0.2)]
    cfg2 = ThresholdConfig(max_articles_full_batch=1)
    p = plan_llm_article_batch(LLMMode.FULL, arts, cfg=cfg2)
    assert p.indices_for_structured_signal == (1,)


def test_full_many_articles_ranked():
    cfg = ThresholdConfig(max_articles_full_batch=3)
    arts = [
        _article("a", 0.1),
        _article("b", 0.9),
        _article("c", -0.5),
        _article("d", 0.0),
    ]
    p = plan_llm_article_batch(LLMMode.FULL, arts, cfg=cfg)
    assert p.indices_for_structured_signal == (0, 1, 2)


def test_full_tie_breaker_lower_index():
    cfg = ThresholdConfig(max_articles_full_batch=1)
    arts = [_article("a", 0.5), _article("b", 0.5)]
    p = plan_llm_article_batch(LLMMode.FULL, arts, cfg=cfg)
    assert p.indices_for_structured_signal == (0,)
