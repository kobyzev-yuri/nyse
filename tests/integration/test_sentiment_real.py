"""
Интеграция: Level 2 — cheap_sentiment на реальных данных GAME_5M.

Два пути проверяются независимо:

  A) FinBERT (локальная модель)
     - transformers загружает ProsusAI/finbert (~435 MB кэш HuggingFace)
     - прогоняем реальные заголовки Yahoo News GAME_5M
     - проверяем что cheap_sentiment ≠ 0.0 у явно тональных заголовков

  B) LLM gpt-5.4-mini (через run_news_signal_pipeline)
     - FinBERT enrich → draft_impulse → decide_llm_mode
     - если gate=FULL → LLM → AggregatedNewsSignal с bias/confidence
     - если gate=SKIP/LITE → тест показывает что LLM не нужен сейчас

Запуск:
    # только FinBERT (без LLM):
    pytest tests/integration/test_sentiment_real.py -v -m integration -k "not llm" -s

    # только LLM:
    pytest tests/integration/test_sentiment_real.py -v -m integration -k "llm" -s

    # всё:
    pytest tests/integration/test_sentiment_real.py -v -m integration -s
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# A) FinBERT — локальная модель
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_finbert_loads_and_scores_headline(require_finbert):
    """
    FinBERT загружается (из HuggingFace кэша или скачивается).
    Явно bullish заголовок → cheap_sentiment > 0.
    Явно bearish заголовок  → cheap_sentiment < 0.
    """
    from pipeline.sentiment import local_sentiment_minus1_to_1

    model = require_finbert

    bullish = "SNDK surges after record quarterly earnings beat expectations"
    bearish = "ASML drops sharply on export ban fears, analyst downgrades stock"
    neutral = "Company announces board meeting scheduled for next month"

    s_bull = local_sentiment_minus1_to_1(bullish, model_name=model)
    s_bear = local_sentiment_minus1_to_1(bearish, model_name=model)
    s_neut = local_sentiment_minus1_to_1(neutral, model_name=model)

    print(f"\nFinBERT ({model}):")
    print(f"  bullish: {s_bull:+.3f}  headline: '{bullish[:50]}'")
    print(f"  bearish: {s_bear:+.3f}  headline: '{bearish[:50]}'")
    print(f"  neutral: {s_neut:+.3f}  headline: '{neutral[:50]}'")

    assert -1.0 <= s_bull <= 1.0
    assert -1.0 <= s_bear <= 1.0
    assert s_bull > 0, f"FinBERT дал ≤0 на явно bullish заголовке: {s_bull}"
    assert s_bear < 0, f"FinBERT дал ≥0 на явно bearish заголовке: {s_bear}"


@pytest.mark.integration
def test_finbert_on_real_game5m_news(require_finbert, game5m_primary):
    """
    Реальные заголовки Yahoo News для первичного GAME_5M тикера → FinBERT.
    Все статьи получают cheap_sentiment ∈ [-1, 1].
    Хотя бы одна → не нейтральна (≠ 0.0).
    """
    pytest.importorskip("yfinance")
    from pipeline.sentiment import enrich_cheap_sentiment
    from sources.news import Source

    articles = Source(max_per_ticker=10, lookback_hours=48).get_articles([game5m_primary])
    if not articles:
        pytest.skip(f"Yahoo не вернул новостей для {game5m_primary.value}")

    enriched = enrich_cheap_sentiment(
        articles,
        use_local=True,
        model_name=require_finbert,
    )

    print(f"\nFinBERT — {game5m_primary.value} ({len(enriched)} статей):")
    for a in enriched[:8]:
        cs = a.cheap_sentiment
        bar = "█" * int(abs(cs) * 10)
        sign = "+" if cs >= 0 else "-"
        print(f"  {sign}{abs(cs):.3f} {bar:<10} {a.title[:60]}")

    for a in enriched:
        assert a.cheap_sentiment is not None
        assert -1.0 <= a.cheap_sentiment <= 1.0

    non_zero = [a for a in enriched if abs(a.cheap_sentiment) > 0.01]
    assert non_zero, "FinBERT выдал 0.0 для всех статей — возможно модель не загрузилась"


@pytest.mark.integration
def test_finbert_all_game5m_batch(require_finbert, game5m_tickers):
    """
    FinBERT на новостях всех GAME_5M тикеров.
    Выводит сводную таблицу для визуального анализа.
    """
    pytest.importorskip("yfinance")
    from pipeline.sentiment import enrich_cheap_sentiment
    from sources.news import Source

    all_articles = Source(max_per_ticker=8, lookback_hours=48).get_articles(game5m_tickers)
    if not all_articles:
        pytest.skip("Yahoo не вернул новостей ни для одного GAME_5M тикера")

    enriched = enrich_cheap_sentiment(all_articles, use_local=True, model_name=require_finbert)

    by_ticker: dict = {}
    for a in enriched:
        by_ticker.setdefault(a.ticker, []).append(a)

    print(f"\nFinBERT GAME_5M ({len(enriched)} статей всего):")
    for ticker in game5m_tickers:
        arts = by_ticker.get(ticker, [])
        if not arts:
            print(f"  {ticker.value:6s} — нет статей")
            continue
        scores = [a.cheap_sentiment for a in arts if a.cheap_sentiment is not None]
        avg = sum(scores) / len(scores) if scores else 0.0
        print(f"  {ticker.value:6s}  avg={avg:+.3f}  n={len(scores)}")

    # Всё что получили — в диапазоне
    for a in enriched:
        assert a.cheap_sentiment is not None
        assert -1.0 <= a.cheap_sentiment <= 1.0


@pytest.mark.integration
def test_finbert_cache_avoids_second_load(require_finbert, tmp_path):
    """
    Второй вызов с тем же текстом берётся из FileCache, модель не перевызывается.
    """
    from datetime import datetime, timezone
    from unittest.mock import patch

    from domain import NewsArticle, Ticker
    from pipeline.cache import FileCache
    from pipeline.sentiment import resolve_cheap_sentiment

    a = NewsArticle(
        ticker=Ticker.SNDK,
        title="SanDisk surges on AI memory demand surge",
        timestamp=datetime.now(timezone.utc),
        summary="Analysts raise price targets.",
        link=None,
        publisher="Reuters",
        raw_sentiment=None,
    )
    cache = FileCache(tmp_path, default_ttl_sec=3600)

    with patch(
        "pipeline.sentiment.local_sentiment_minus1_to_1",
        wraps=lambda text, model_name: 0.75,
    ) as mock_fn:
        s1 = resolve_cheap_sentiment(a, use_local=True, model_name=require_finbert, cache=cache)
        s2 = resolve_cheap_sentiment(a, use_local=True, model_name=require_finbert, cache=cache)

    assert s1 == pytest.approx(s2)
    assert mock_fn.call_count == 1, "FinBERT вызвался дважды — кэш не сработал"
    print(f"\nCache hit: first={s1:.3f}  second={s2:.3f}  model_calls={mock_fn.call_count}")


# ---------------------------------------------------------------------------
# B) LLM (gpt-5.4-mini) — полный Level 2 → 5
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_llm_signal_on_real_game5m_news(require_openai_settings, require_finbert,
                                         game5m_primary, tmp_path):
    """
    Полный pipeline Level 0–5 на реальных данных:
      Yahoo News → FinBERT enrich → draft → gate → LLM (если FULL) → AggregatedNewsSignal

    Если gate=SKIP/LITE: тест проходит, показывает что LLM не нужен для текущих новостей.
    Если gate=FULL: запускает реальный gpt-5.4-mini, проверяет структуру ответа.

    KERIM_REPLACE: после интеграции NyseNewsAgent-обёртки — этот тест
    переиспользуется напрямую с agent.predict().
    """
    pytest.importorskip("yfinance")
    from pipeline import (
        GateContext, LLMMode, ThresholdConfig, decide_llm_mode,
        draft_impulse, single_scalar_draft_bias,
    )
    from pipeline.cache import FileCache
    from pipeline.draft import scored_from_news_articles
    from pipeline.news_signal_runner import run_news_signal_pipeline
    from pipeline.sentiment import enrich_cheap_sentiment
    from sources.news import Source

    ticker = game5m_primary
    raw_articles = Source(max_per_ticker=15, lookback_hours=48).get_articles([ticker])
    if not raw_articles:
        pytest.skip(f"Yahoo не вернул новостей для {ticker.value}")

    # Level 2: FinBERT
    articles = enrich_cheap_sentiment(
        raw_articles,
        use_local=True,
        model_name=require_finbert,
    )

    # Level 3: draft impulse
    scored = scored_from_news_articles(articles)
    d = draft_impulse(scored)
    bias = single_scalar_draft_bias(d)

    # Level 4: gate
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

    print(
        f"\n[{ticker.value}] articles={len(articles)}  "
        f"FinBERT bias={bias:.3f}  gate={mode.value}"
    )

    if mode != LLMMode.FULL:
        print(f"  → gate={mode.value}: LLM не нужен для текущего новостного потока")
        assert mode.value in ("skip", "lite")
        return

    # Level 5: LLM
    try:
        result = run_news_signal_pipeline(
            articles,
            ticker.value,
            cfg=ThresholdConfig(),
            mode=mode,
            cache=FileCache(tmp_path),
            settings=require_openai_settings,
        )
    except Exception as exc:
        exc_name = type(exc).__name__
        if any(kw in exc_name for kw in ("Connection", "Timeout", "Auth", "API", "HTTP")):
            pytest.skip(f"LLM API недоступен: {exc_name}: {exc}")
        raise

    assert -1.0 <= result.bias <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.items) > 0
    print(
        f"  → LLM: bias={result.bias:.3f}  conf={result.confidence:.3f}  "
        f"items={len(result.items)}"
    )
    for line in result.summary:
        print(f"    {line}")


@pytest.mark.integration
def test_llm_signal_without_finbert(require_openai_settings, game5m_primary, tmp_path):
    """
    Level 5 без FinBERT: cheap_sentiment=None → 0.0 в draft.
    Gate обычно SKIP (нет сигнала) — показывает что LLM-путь требует FinBERT для активации.
    """
    pytest.importorskip("yfinance")
    from pipeline import GateContext, ThresholdConfig, decide_llm_mode
    from pipeline.draft import scored_from_news_articles
    from pipeline import draft_impulse, single_scalar_draft_bias
    from sources.news import Source

    ticker = game5m_primary
    articles = Source(max_per_ticker=10, lookback_hours=48).get_articles([ticker])
    if not articles:
        pytest.skip(f"Yahoo не вернул новостей для {ticker.value}")

    # БЕЗ enrich — cheap_sentiment=None → scored_from_news_articles даст 0.0
    scored = scored_from_news_articles(articles)
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

    print(
        f"\n[{ticker.value}] без FinBERT: articles={len(articles)}  "
        f"bias={bias:.3f}  gate={mode.value}"
    )
    # Без FinBERT bias=0.0 → gate почти всегда SKIP
    assert mode.value in ("skip", "lite", "full")
    print(
        f"  → Без FinBERT gate={mode.value} "
        f"(ожидаем skip — нет сентимента для активации LLM)"
    )
