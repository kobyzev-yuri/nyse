"""Оркестратор run_news_signal_pipeline (уровень 5, шаг 7) — без сети."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from config_loader import OpenAISettings
from domain import NewsArticle, Ticker
from pipeline import LLMMode, ThresholdConfig
from pipeline.news_signal_runner import run_news_signal_pipeline


_SETTINGS = OpenAISettings(
    api_key="test-key",
    base_url="https://example.com/v1",
    model="gpt-test",
    temperature=0.0,
    timeout_sec=10,
)


def _art(title: str, sentiment: float = 0.0) -> NewsArticle:
    return NewsArticle(
        ticker=Ticker.NVDA,
        title=title,
        timestamp=datetime(2026, 4, 6, 10, 0, 0, tzinfo=timezone.utc),
        summary=None,
        link=None,
        publisher=None,
        cheap_sentiment=sentiment,
    )


def _mock_post(response_json: dict):
    """Возвращает mock ``requests.post``, который отдаёт нужный JSON."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(response_json)}}]
    }
    return MagicMock(return_value=resp)


def _llm_items(n: int) -> dict:
    return {
        "items": [
            {
                "article_index": i + 1,
                "sentiment": 0.4,
                "impact_strength": "moderate",
                "relevance": "primary",
                "surprise": "minor",
                "time_horizon": "1-3d",
                "confidence": 0.8,
            }
            for i in range(n)
        ]
    }


# --- SKIP / LITE возвращают нейтральный агрегат без HTTP ---

def test_skip_returns_neutral_no_http(tmp_path):
    from pipeline.cache import FileCache

    arts = [_art("h", 0.5)]
    result = run_news_signal_pipeline(
        arts,
        "NVDA",
        cfg=ThresholdConfig(),
        mode=LLMMode.SKIP,
        cache=FileCache(tmp_path),
        settings=_SETTINGS,
    )
    assert result.bias == pytest.approx(0.0)
    assert result.items == []


def test_lite_returns_neutral_no_http(tmp_path):
    from pipeline.cache import FileCache

    arts = [_art("h", 0.5)]
    result = run_news_signal_pipeline(
        arts,
        "NVDA",
        cfg=ThresholdConfig(),
        mode=LLMMode.LITE,
        cache=FileCache(tmp_path),
        settings=_SETTINGS,
    )
    assert result.bias == pytest.approx(0.0)


# --- FULL: один HTTP вызов, парсинг, агрегация ---

def test_full_one_article_calls_http_once(tmp_path):
    from pipeline.cache import FileCache

    arts = [_art("NVDA beats Q1", 0.6)]
    post = _mock_post(_llm_items(1))
    result = run_news_signal_pipeline(
        arts,
        "NVDA",
        cfg=ThresholdConfig(),
        mode=LLMMode.FULL,
        cache=FileCache(tmp_path),
        settings=_SETTINGS,
        post=post,
    )
    post.assert_called_once()
    assert result.bias == pytest.approx(0.4)  # один сигнал sentiment=0.4
    assert len(result.items) == 1


def test_full_caches_response_second_call_no_http(tmp_path):
    from pipeline.cache import FileCache

    arts = [_art("headline", 0.3)]
    post = _mock_post(_llm_items(1))
    cache = FileCache(tmp_path)

    fixed_now = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
    run_news_signal_pipeline(
        arts, "NVDA", cfg=ThresholdConfig(), mode=LLMMode.FULL,
        cache=cache, settings=_SETTINGS, post=post, now=fixed_now,
    )
    run_news_signal_pipeline(
        arts, "NVDA", cfg=ThresholdConfig(), mode=LLMMode.FULL,
        cache=cache, settings=_SETTINGS, post=post, now=fixed_now,
    )
    assert post.call_count == 1  # второй раз из кэша


def test_full_batch_respects_max_articles(tmp_path):
    from pipeline.cache import FileCache

    # cfg.max_articles_full_batch=2, 5 статей → только 2 идут в LLM
    cfg = ThresholdConfig(max_articles_full_batch=2)
    arts = [_art(f"h{i}", float(i) * 0.1) for i in range(5)]
    post = _mock_post(_llm_items(2))  # LLM вернёт 2 сигнала
    result = run_news_signal_pipeline(
        arts, "NVDA", cfg=cfg, mode=LLMMode.FULL,
        cache=FileCache(tmp_path), settings=_SETTINGS, post=post,
    )
    assert len(result.items) == 2


def test_full_bad_json_raises_value_error(tmp_path):
    from pipeline.cache import FileCache

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "not-json"}}]
    }
    post = MagicMock(return_value=resp)

    with pytest.raises(ValueError, match="unparseable JSON"):
        run_news_signal_pipeline(
            [_art("h")], "NVDA",
            cfg=ThresholdConfig(), mode=LLMMode.FULL,
            cache=FileCache(tmp_path), settings=_SETTINGS,
            post=post,
        )


def test_empty_articles_full_returns_neutral(tmp_path):
    from pipeline.cache import FileCache

    result = run_news_signal_pipeline(
        [], "NVDA",
        cfg=ThresholdConfig(), mode=LLMMode.FULL,
        cache=FileCache(tmp_path), settings=_SETTINGS,
    )
    assert result.bias == pytest.approx(0.0)
