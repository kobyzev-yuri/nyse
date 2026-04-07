"""
Интеграция: run_news_signal_pipeline → реальный API → AggregatedNewsSignal.

Нужен OPENAI_API_KEY + сеть. Без них → pytest.skip.

Паттерн: НЕ передаём ``llm=`` вручную — runner сам строит ChatOpenAI через
``get_chat_model(settings)`` (как pystockinvest делает в cmd/telegram_bot.py).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

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
    except Exception as exc:
        # Пропускаем при любой сетевой / авторизационной ошибке LangChain/httpx
        exc_name = type(exc).__name__
        if any(kw in exc_name for kw in ("Connection", "Timeout", "Auth", "API", "HTTP")):
            pytest.skip(f"API/сеть недоступна: {exc_name}: {exc}")
        raise

    assert -1.0 <= result.bias <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.items) == 2
    assert len(result.summary) >= 1
    print(f"\nbias={result.bias:.3f}  confidence={result.confidence:.3f}")
    print(result.summary[0])


@pytest.mark.integration
def test_news_signal_pipeline_real_yahoo_news(require_openai_settings, tmp_path):
    """
    Полный цикл: реальные новости Yahoo → LLM → AggregatedNewsSignal.

    Шаги:
      1. sources.news.Source → реальные статьи NVDA (≤ 10)
      2. decide_llm_mode → если SKIP/LITE → skip теста
      3. run_news_signal_pipeline → FULL с реальным LLM-вызовом
      4. Проверка диапазонов bias / confidence

    KERIM_REPLACE: тот же тест применим к NyseNewsAgent-обёртке после интеграции
    с pystockinvest, замена run_news_signal_pipeline на agent.predict() прозрачна.
    """
    pytest.importorskip("yfinance")
    from domain import Ticker
    from pipeline import (
        GateContext,
        ScoredArticle,
        ThresholdConfig,
        classify_channel,
        decide_llm_mode,
        draft_impulse,
        single_scalar_draft_bias,
    )
    from pipeline.cache import FileCache
    from sources.news import Source

    articles = Source(max_per_ticker=10, lookback_hours=48).get_articles([Ticker.NVDA])
    if not articles:
        pytest.skip("Yahoo не вернул новостей")

    # Определяем режим гейта
    scored = [
        ScoredArticle(
            published_at=a.timestamp,
            cheap_sentiment=getattr(a, "cheap_sentiment", 0.0),
            channel=classify_channel(a.title, a.summary)[0],
        )
        for a in articles
    ]
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

    if mode != LLMMode.FULL:
        pytest.skip(f"Гейт выбрал {mode.value} — LLM не нужен для этого набора новостей")

    try:
        result = run_news_signal_pipeline(
            articles,
            "NVDA",
            cfg=ThresholdConfig(),
            mode=mode,
            cache=FileCache(tmp_path),
            settings=require_openai_settings,
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        if any(kw in exc_name for kw in ("Connection", "Timeout", "Auth", "API", "HTTP")):
            pytest.skip(f"API/сеть недоступна: {exc_name}: {exc}")
        raise

    assert -1.0 <= result.bias <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.items) <= len(articles)  # batch может быть меньше
    print(
        f"\n[NVDA real] articles={len(articles)}  bias={result.bias:.3f}  "
        f"conf={result.confidence:.3f}  gate={mode.value}"
    )
    for line in result.summary:
        print(" ", line)
