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
    MultiTickerGateSession,
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


def _make_article(ticker, title, summary=None, sentiment=0.0, hours_ago=1):
    from datetime import timedelta

    return NewsArticle(
        ticker=ticker,
        title=title,
        timestamp=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
        summary=summary,
        link=None,
        publisher=None,
        cheap_sentiment=sentiment,
    )


# ---------------------------------------------------------------------------
# Дедупликация REGIME macro-статей
# ---------------------------------------------------------------------------


def test_seen_regime_titles_deduplication(utc_now: datetime):
    """
    Одна REGIME-статья (war) у двух тикеров:
    - первый тикер → ch=REGIME, title добавляется в seen_regime_titles
    - второй тикер → та же статья понижается до INCREMENTAL
    """
    war_title = "Nvidia Stock Drops as Iran War Heats Up"
    war_summary = "Shares fell after Iran escalation news."

    a_msft = _make_article(Ticker.MSFT, war_title, war_summary, sentiment=-0.9)
    a_nvda = _make_article(Ticker.NVDA, war_title, war_summary, sentiment=-0.9)

    seen: set[str] = set()

    scored_msft = scored_from_news_articles([a_msft], seen_regime_titles=seen)
    scored_nvda = scored_from_news_articles([a_nvda], seen_regime_titles=seen)

    assert scored_msft[0].channel == NewsImpactChannel.REGIME, "первый тикер — REGIME"
    assert scored_nvda[0].channel == NewsImpactChannel.INCREMENTAL, "дубликат → INCREMENTAL"
    assert war_title in seen
    assert len(seen) == 1


def test_seen_regime_titles_none_is_independent(utc_now: datetime):
    """Без seen_regime_titles оба тикера получают REGIME независимо (старое поведение)."""
    war_title = "Nvidia Stock Drops as Iran War Heats Up"

    a1 = _make_article(Ticker.MSFT, war_title, sentiment=-0.9)
    a2 = _make_article(Ticker.NVDA, war_title, sentiment=-0.9)

    s1 = scored_from_news_articles([a1])  # seen_regime_titles=None
    s2 = scored_from_news_articles([a2])

    assert s1[0].channel == NewsImpactChannel.REGIME
    assert s2[0].channel == NewsImpactChannel.REGIME


def test_multi_ticker_gate_session_dedup(utc_now: datetime):
    """
    MultiTickerGateSession: тот же war заголовок у MSFT, META, AMZN —
    только MSFT получает reg_stress > 0; META и AMZN — 0.
    """
    war_title = "Goldman Sachs on Iran War Impact on Big Tech"

    articles_msft = [_make_article(Ticker.MSFT, war_title, sentiment=-0.9)]
    articles_meta = [_make_article(Ticker.META, war_title, sentiment=-0.9)]
    articles_amzn = [_make_article(Ticker.AMZN, war_title, sentiment=-0.9)]

    session = MultiTickerGateSession()

    d_msft = draft_impulse(session.scored(articles_msft), now=utc_now)
    d_meta = draft_impulse(session.scored(articles_meta), now=utc_now)
    d_amzn = draft_impulse(session.scored(articles_amzn), now=utc_now)

    assert d_msft.regime_stress > 0.0, "первый тикер в сессии — REGIME"
    assert d_meta.regime_stress == pytest.approx(0.0), "META дубликат → no regime_stress"
    assert d_amzn.regime_stress == pytest.approx(0.0), "AMZN дубликат → no regime_stress"
    assert session.seen_regime_count == 1


def test_multi_ticker_session_unique_regime_articles(utc_now: datetime):
    """
    Разные REGIME-статьи у разных тикеров — оба получают reg_stress.
    """
    a_nvda = _make_article(Ticker.NVDA, "Nvidia drops as Iran War escalates", sentiment=-0.9)
    a_asml = _make_article(Ticker.ASML, "ASML faces new sanctions from US", sentiment=-0.8)

    session = MultiTickerGateSession()

    d_nvda = draft_impulse(session.scored([a_nvda]), now=utc_now)
    d_asml = draft_impulse(session.scored([a_asml]), now=utc_now)

    assert d_nvda.regime_stress > 0.0
    assert d_asml.regime_stress > 0.0
    assert session.seen_regime_count == 2


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
