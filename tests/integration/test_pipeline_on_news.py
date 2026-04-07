"""
Интеграция: pipeline (канал → draft → gate) на реальных заголовках Yahoo.
Приоритет: первичный GAME_5M тикер из TICKERS_FAST.
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_pipeline_end_to_end_from_yfinance(load_nyse_config, game5m_primary):
    pytest.importorskip("yfinance")
    from pipeline import (
        GateContext,
        ThresholdConfig,
        decide_llm_mode,
        draft_impulse,
        single_scalar_draft_bias,
    )
    from pipeline.draft import scored_from_news_articles
    from sources.news import Source

    ticker = game5m_primary
    articles = Source(max_per_ticker=15, lookback_hours=72).get_articles([ticker])
    if not articles:
        pytest.skip(f"Yahoo не вернул новостей для {ticker.value} за 72ч")

    # scored_from_news_articles нормализует cheap_sentiment=None → 0.0
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
        f"\n[{ticker.value}] articles={len(articles)}  "
        f"draft_bias={bias:.3f}  gate={mode.value}"
    )
    assert mode.value in ("skip", "lite", "full")


@pytest.mark.integration
def test_pipeline_on_all_game5m(load_nyse_config, game5m_tickers):
    """
    Новости + gate для всех GAME_5M тикеров в одном запросе.
    Проверяем что gate возвращает валидный режим для каждого.
    """
    pytest.importorskip("yfinance")
    from pipeline import (
        GateContext,
        ThresholdConfig,
        decide_llm_mode,
        draft_impulse,
        single_scalar_draft_bias,
    )
    from pipeline.draft import scored_from_news_articles
    from sources.news import Source

    all_articles = Source(max_per_ticker=10, lookback_hours=48).get_articles(game5m_tickers)
    if not all_articles:
        pytest.skip("Yahoo не вернул новостей ни для одного GAME_5M тикера")

    by_ticker: dict = {}
    for a in all_articles:
        by_ticker.setdefault(a.ticker, []).append(a)

    print()
    for ticker in game5m_tickers:
        arts = by_ticker.get(ticker, [])
        if not arts:
            print(f"  {ticker.value:6s} — нет новостей")
            continue

        scored = scored_from_news_articles(arts)
        d = draft_impulse(scored)
        bias = single_scalar_draft_bias(d)
        mode = decide_llm_mode(
            ThresholdConfig(),
            GateContext(
                draft_bias=bias,
                regime_present=d.regime_stress > 0.01,
                regime_rule_confidence=0.85 if d.regime_stress > 0.01 else 0.0,
                calendar_high_soon=False,
                article_count=len(arts),
            ),
        )
        assert mode.value in ("skip", "lite", "full")
        print(
            f"  {ticker.value:6s}  {len(arts):2d} статей  "
            f"bias={bias:+.3f}  gate={mode.value}"
        )
