"""
Юнит-тесты модуля ``pipeline.ingest`` (уровень 0: слияние списков новостей, дедуп, окно времени).

Запуск с понятным отчётом из корня репозитория nyse::

    python -m pytest tests/unit/test_ingest.py -v --tb=short

Или этот файл напрямую (в конце вызывается pytest с ``-v``).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain import NewsArticle, Ticker


def _art(
    *,
    title: str,
    ts: datetime,
    link: str | None = None,
    provider: str | None = "p",
    sentiment: float | None = None,
    ticker: Ticker = Ticker.NVDA,
) -> NewsArticle:
    """Собирает минимальный ``NewsArticle`` для тестов (без сети)."""
    return NewsArticle(
        ticker=ticker,
        title=title,
        timestamp=ts,
        summary=None,
        link=link,
        publisher=None,
        provider_id=provider,
        raw_sentiment=sentiment,
    )


def test_merge_unites_independent_batches_without_dedup():
    """
    Функционал: склейка нескольких источников (несколько итерируемых батчей) в один список.

    Проверяем: две статьи с разными заголовками и временем не считаются дубликатами;
    порядок сортировки — по убыванию времени (свежая «A» выше «B»).

    Ожидаемый результат: 2 статьи, порядок заголовков [A, B].
    """
    from pipeline.ingest import merge_news_articles

    now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    a1 = _art(title="A", ts=now - timedelta(hours=1))
    a2 = _art(title="B", ts=now - timedelta(hours=2))
    out = merge_news_articles([a1], [a2], lookback_hours=24, reference_time=now)
    assert len(out) == 2, f"ожидали 2 статьи после склейки батчей, получили {len(out)}"
    assert [x.title for x in out] == ["A", "B"], (
        "ожидали сортировку по убыванию времени: сначала A (новее), затем B"
    )


def test_merge_dedupes_same_story_canonical_url():
    """
    Функционал: дедупликация по одной и той же новости с разного вида URL.

    Проверяем: разный регистр схемы/хоста, порядок query-параметров, фрагмент ``#`` —
    после канонизации это один URL; остаётся одна запись.

    Ожидаемый результат: 1 статья — более поздняя по времени (yfinance), т.к. она новее на 5 мин.
    """
    from pipeline.ingest import merge_news_articles

    now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    ts = now - timedelta(hours=1)
    x = _art(
        title="Same story",
        ts=ts,
        link="HTTPS://Example.COM/path/?b=2&a=1#frag",
        provider="newsapi",
    )
    y = _art(
        title="Same story alt title",
        ts=ts + timedelta(minutes=5),
        link="https://example.com/path?a=1&b=2",
        provider="yfinance",
    )
    out = merge_news_articles([x], [y], lookback_hours=24, reference_time=now)
    assert len(out) == 1, f"ожидали 1 статью после дедупа по URL, получили {len(out)}"
    assert out[0].timestamp == y.timestamp, "должна остаться более новая по timestamp копия"
    assert out[0].provider_id == "yfinance", "должна остаться запись от более нового времени"


def test_merge_when_timestamps_equal_prefers_article_with_raw_sentiment():
    """
    Функционал: разрешение коллизии при одинаковом дедуп-ключе и одинаковом времени.

    Проверяем: две записи с тем же каноническим URL и одним timestamp; у одной есть
    ``raw_sentiment``, у другой нет — выбираем ту, где заполнен sentiment.

    Ожидаемый результат: одна статья с ``raw_sentiment == 0.5``.
    """
    from pipeline.ingest import merge_news_articles

    now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    ts = now - timedelta(hours=1)
    x = _art(title="T", ts=ts, link="https://x.com/a", provider="a", sentiment=None)
    y = _art(title="T", ts=ts, link="https://x.com/a/", provider="b", sentiment=0.5)
    out = merge_news_articles([x], [y], lookback_hours=24, reference_time=now)
    assert len(out) == 1, f"ожидали одну запись после дедупа, получили {len(out)}"
    assert out[0].raw_sentiment == pytest.approx(0.5), (
        "при равном времени должна остаться запись с заполненным raw_sentiment"
    )


def test_merge_dedupes_articles_without_link_same_hour_title_and_provider():
    """
    Функционал: дедуп без URL (составной ключ: провайдер, тикер, нормализованный заголовок, час UTC).

    Проверяем: одинаковый смысл заголовка с лишними пробелами и регистром — один ключ.

    Ожидаемый результат: одна статья.
    """
    from pipeline.ingest import merge_news_articles

    now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    ts = now - timedelta(hours=2)
    x = _art(title="Headline", ts=ts, link=None, provider="rss")
    y = _art(title="  headline  ", ts=ts, link=None, provider="rss")
    out = merge_news_articles([x], [y], lookback_hours=24, reference_time=now)
    assert len(out) == 1, (
        f"ожидали дедуп по noguid-ключу при одном часе и одном провайдере, получили {len(out)}"
    )


def test_merge_drops_articles_outside_lookback_window():
    """
    Функционал: отсечение по окну ``lookback_hours`` относительно ``reference_time``.

    Проверяем: статья «свежая» внутри 72 ч остаётся; «старая» (100 ч назад) отбрасывается.

    Ожидаемый результат: одна статья с заголовком «F».
    """
    from pipeline.ingest import merge_news_articles

    now = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    fresh = _art(title="F", ts=now - timedelta(hours=1))
    stale = _art(title="S", ts=now - timedelta(hours=100))
    out = merge_news_articles([fresh, stale], lookback_hours=72, reference_time=now)
    assert len(out) == 1, f"ожидали только статьи внутри окна 72 ч, получили {len(out)}"
    assert out[0].title == "F", "должна остаться только свежая статья"


def test_with_normalized_link_canonical_form():
    """
    Функционал: вспомогательная функция ``with_normalized_link`` — приведение ссылки к канону.

    Проверяем: хост в другом регистре, порядок query-параметров — предсказуемая строка URL.

    Ожидаемый результат: канонический URL с нижним регистром хоста и отсортированным query.
    """
    from pipeline.ingest import with_normalized_link

    a = _art(
        title="T",
        ts=datetime.now(timezone.utc),
        link="https://EXAMPLE.com/PATH/?z=1&y=2",
    )
    b = with_normalized_link(a)
    assert b.link == "https://example.com/PATH?y=2&z=1", (
        f"ожидали канонический URL, получили {b.link!r}"
    )


if __name__ == "__main__":
    # Чтобы «Run Python File» в IDE не давал пустой вывод — вызываем pytest явно.
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
