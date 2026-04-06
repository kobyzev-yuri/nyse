"""
Интеграция: run_news_signal_pipeline → реальный API → AggregatedNewsSignal.

Нужен OPENAI_API_KEY. Без сети → pytest.skip.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests

from domain import NewsArticle, Ticker
from pipeline import LLMMode, ThresholdConfig
from pipeline.news_signal_runner import run_news_signal_pipeline


@pytest.mark.integration
def test_news_signal_pipeline_smoke(require_openai_settings, tmp_path):
    from pipeline.cache import FileCache

    articles = [
        NewsArticle(
            ticker=Ticker.NVDA,
            title="NVIDIA reports record quarterly revenue, beats analyst expectations",
            timestamp=datetime(2026, 4, 6, 9, 0, 0, tzinfo=timezone.utc),
            summary="NVIDIA Q1 revenue reached $44 billion, driven by AI chip demand.",
            link=None,
            publisher="Reuters",
            cheap_sentiment=0.6,
        ),
        NewsArticle(
            ticker=Ticker.NVDA,
            title="US government considers new restrictions on AI chip exports",
            timestamp=datetime(2026, 4, 6, 8, 0, 0, tzinfo=timezone.utc),
            summary="Washington may impose new limits on high-end chip exports to several countries.",
            link=None,
            publisher="Bloomberg",
            cheap_sentiment=-0.5,
        ),
    ]

    try:
        result = run_news_signal_pipeline(
            articles,
            "NVDA",
            cfg=ThresholdConfig(),
            mode=LLMMode.FULL,
            cache=FileCache(tmp_path),
            settings=require_openai_settings,
        )
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        pytest.skip(f"Сеть до API недоступна: {type(e).__name__}")

    assert -1.0 <= result.bias <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.items) == 2
    assert len(result.summary) >= 1
    print(f"\nbias={result.bias:.3f}  confidence={result.confidence:.3f}")
    print(result.summary[0])
