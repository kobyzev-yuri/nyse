"""
Юнит-тесты: pipeline.sentiment (уровень 2: cheap_sentiment).

Локальные transformers **не** требуются: используются mock/patch.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from domain import NewsArticle, Ticker


def _article(
    *,
    raw: float | None = None,
    title: str = "T",
    summary: str | None = None,
) -> NewsArticle:
    return NewsArticle(
        ticker=Ticker.NVDA,
        title=title,
        timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        summary=summary,
        link=None,
        publisher=None,
        provider_id="test",
        raw_sentiment=raw,
        cheap_sentiment=None,
    )


def test_resolve_prefers_raw_sentiment_from_api():
    """
    Функционал: при наличии ``raw_sentiment`` у провайдера локальная модель не вызывается.

    Ожидание: ``cheap_sentiment`` совпадает с обрезанным raw (см. clip −1…1).
    """
    from pipeline.sentiment import resolve_cheap_sentiment

    a = _article(raw=0.7)
    with patch("pipeline.news.sentiment.local_sentiment_minus1_to_1") as mock_local:
        s = resolve_cheap_sentiment(a, use_local=True)
        mock_local.assert_not_called()
    assert s == pytest.approx(0.7)


def test_resolve_clip_raw_sentiment_outside_range():
    """Границы: значения API обрезаются в [−1, 1]."""
    from pipeline.sentiment import resolve_cheap_sentiment

    assert resolve_cheap_sentiment(_article(raw=2.0)) == pytest.approx(1.0)
    assert resolve_cheap_sentiment(_article(raw=-9.0)) == pytest.approx(-1.0)


def test_resolve_calls_local_when_no_raw_and_use_local_true():
    """
    Без ``raw_sentiment`` и с ``use_local=True`` вызывается локальная оценка
    (мок вместо загрузки FinBERT).
    """
    from pipeline.sentiment import resolve_cheap_sentiment

    a = _article(raw=None, title="NVDA up", summary="beat")
    with patch(
        "pipeline.news.sentiment.local_sentiment_minus1_to_1",
        return_value=0.4,
    ) as mock_local:
        s = resolve_cheap_sentiment(a, use_local=True, model_name="ProsusAI/finbert")
        mock_local.assert_called_once()
    assert s == pytest.approx(0.4)


def test_resolve_neutral_when_no_raw_and_use_local_false():
    """Без API и без локальной модели — нейтраль 0.0."""
    from pipeline.sentiment import resolve_cheap_sentiment

    a = _article(raw=None, title="x", summary="y")
    s = resolve_cheap_sentiment(a, use_local=False)
    assert s == pytest.approx(0.0)


def test_article_text_joins_title_and_summary():
    """Вспомогательная функция склеивает заголовок и summary."""
    from pipeline.sentiment import article_text

    a = _article(title="A", summary="B")
    assert "A" in article_text(a) and "B" in article_text(a)


def test_enrich_cheap_sentiment_sets_field_on_all():
    """``enrich_cheap_sentiment`` возвращает новые объекты с заполненным полем."""
    from pipeline.sentiment import enrich_cheap_sentiment

    a = _article(raw=0.2)
    b = _article(raw=None, title="only title")
    with patch("pipeline.news.sentiment.resolve_cheap_sentiment") as mock_r:
        mock_r.side_effect = [0.2, 0.0]
        out = enrich_cheap_sentiment([a, b], use_local=False)
    assert mock_r.call_count == 2
    assert out[0].cheap_sentiment == pytest.approx(0.2)
    assert out[1].cheap_sentiment == pytest.approx(0.0)
    assert a.cheap_sentiment is None


def test_file_cache_avoids_second_local_call(tmp_path):
    """При переданном FileCache второй запрос с тем же текстом идёт из кэша."""
    from pipeline.cache import FileCache
    from pipeline.sentiment import resolve_cheap_sentiment

    fc = FileCache(tmp_path, default_ttl_sec=3600)
    a = _article(raw=None, title="Same", summary="body")
    with patch(
        "pipeline.news.sentiment.local_sentiment_minus1_to_1",
        return_value=0.5,
    ) as mock_local:
        s1 = resolve_cheap_sentiment(a, use_local=True, model_name="m", cache=fc)
        s2 = resolve_cheap_sentiment(a, use_local=True, model_name="m", cache=fc)
    assert s1 == s2 == pytest.approx(0.5)
    assert mock_local.call_count == 1


# ---------------------------------------------------------------------------
# price_pattern_boost
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title, expected",
    [
        ("Nebius Stock Jumped 15% on Its Meta Deal", 0.8),
        ("SanDisk Gains 3% as AI Tailwinds Drive Memory Sector Higher", 0.4),
        ("Micron surges 20% after earnings beat", 1.0),
        ("ASML Stock Sinks 7% on Export Curb News", -0.6),
        ("Company drops 2.5% after guidance cut", -0.4),
        ("Stock plunges 25% on fraud allegations", -1.0),
        ("Apple rose 1% in early trading", 0.2),
        ("Markets rally on Fed news", None),           # нет числа → None
        ("Stock up big today", None),                  # нет % → None
        ("Quarterly earnings released", None),
    ],
)
def test_price_pattern_boost(title, expected):
    from pipeline.sentiment import price_pattern_boost

    result = price_pattern_boost(title)
    if expected is None:
        assert result is None
    else:
        assert result == pytest.approx(expected)


def test_price_boost_applied_as_floor_over_finbert():
    """Если FinBERT дал 0.0, но паттерн нашёл +0.8 — результат +0.8."""
    from pipeline.sentiment import resolve_cheap_sentiment

    a = _article(
        raw=None,
        title="Nebius Stock Jumped 15% on Its Meta Deal. Is This the Next CoreWeave?",
    )
    with patch("pipeline.news.sentiment.local_sentiment_minus1_to_1", return_value=0.0):
        s = resolve_cheap_sentiment(a, use_local=True, model_name="m")
    assert s == pytest.approx(0.8)


def test_price_boost_does_not_override_stronger_finbert():
    """Если FinBERT дал 0.95 (сильный позитив), паттерн с +0.4 не перезаписывает."""
    from pipeline.sentiment import resolve_cheap_sentiment

    a = _article(raw=None, title="Stock gains 3% after blowout quarter")
    with patch("pipeline.news.sentiment.local_sentiment_minus1_to_1", return_value=0.95):
        s = resolve_cheap_sentiment(a, use_local=True, model_name="m")
    assert s == pytest.approx(0.95)


def test_price_boost_negative_floor():
    """Если FinBERT дал −0.1 но паттерн −0.6 (sinks 7%) — результат −0.6."""
    from pipeline.sentiment import resolve_cheap_sentiment

    a = _article(raw=None, title="ASML Stock Sinks 7% on Export Curb News")
    with patch("pipeline.news.sentiment.local_sentiment_minus1_to_1", return_value=-0.1):
        s = resolve_cheap_sentiment(a, use_local=True, model_name="m")
    assert s == pytest.approx(-0.6)


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
