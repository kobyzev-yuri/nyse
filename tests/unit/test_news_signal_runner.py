"""Оркестратор run_news_signal_pipeline (уровень 5) — без сети.

Паттерн мока соответствует pystockinvest: передаём ``llm=`` (BaseChatModel),
а не ``post=``. Structured output мокируется через with_structured_output().invoke().
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from config_loader import OpenAISettings
from domain import NewsArticle, Ticker
from pipeline import LLMMode, ThresholdConfig
from pipeline.news_signal_runner import run_news_signal_pipeline
from pipeline.news_signal_schema import NewsSignalLLMResponse


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


def _mock_llm(items_dict: dict):
    """
    Возвращает (mock_llm, mock_structured) где:
    - mock_llm.with_structured_output(...) → mock_structured
    - mock_structured.invoke(...) → NewsSignalLLMResponse(items_dict)
    """
    response = NewsSignalLLMResponse.model_validate(items_dict)
    structured = MagicMock()
    structured.invoke.return_value = response
    llm = MagicMock()
    llm.with_structured_output.return_value = structured
    return llm, structured


# --- SKIP / LITE → нейтральный агрегат без вызова LLM ---

def test_skip_returns_neutral_no_llm(tmp_path):
    from pipeline.cache import FileCache

    llm, structured = _mock_llm(_llm_items(1))
    result = run_news_signal_pipeline(
        [_art("h", 0.5)], "NVDA",
        cfg=ThresholdConfig(), mode=LLMMode.SKIP,
        cache=FileCache(tmp_path), settings=_SETTINGS, llm=llm,
    )
    assert result.bias == pytest.approx(0.0)
    assert result.items == []
    structured.invoke.assert_not_called()


def test_lite_returns_neutral_no_llm(tmp_path):
    from pipeline.cache import FileCache

    llm, structured = _mock_llm(_llm_items(1))
    result = run_news_signal_pipeline(
        [_art("h", 0.5)], "NVDA",
        cfg=ThresholdConfig(), mode=LLMMode.LITE,
        cache=FileCache(tmp_path), settings=_SETTINGS, llm=llm,
    )
    assert result.bias == pytest.approx(0.0)
    structured.invoke.assert_not_called()


# --- FULL: один вызов LLM, парсинг, агрегация ---

def test_full_one_article_calls_llm_once(tmp_path):
    from pipeline.cache import FileCache

    llm, structured = _mock_llm(_llm_items(1))
    result = run_news_signal_pipeline(
        [_art("NVDA beats Q1", 0.6)], "NVDA",
        cfg=ThresholdConfig(), mode=LLMMode.FULL,
        cache=FileCache(tmp_path), settings=_SETTINGS, llm=llm,
    )
    structured.invoke.assert_called_once()
    assert result.bias == pytest.approx(0.4)
    assert len(result.items) == 1


def test_full_caches_response_second_call_no_llm(tmp_path):
    from pipeline.cache import FileCache

    llm, structured = _mock_llm(_llm_items(1))
    cache = FileCache(tmp_path)
    fixed_now = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)

    run_news_signal_pipeline(
        [_art("headline", 0.3)], "NVDA",
        cfg=ThresholdConfig(), mode=LLMMode.FULL,
        cache=cache, settings=_SETTINGS, llm=llm, now=fixed_now,
    )
    run_news_signal_pipeline(
        [_art("headline", 0.3)], "NVDA",
        cfg=ThresholdConfig(), mode=LLMMode.FULL,
        cache=cache, settings=_SETTINGS, llm=llm, now=fixed_now,
    )
    assert structured.invoke.call_count == 1  # второй раз из кэша


def test_full_batch_respects_max_articles(tmp_path):
    from pipeline.cache import FileCache

    # cfg.max_articles_full_batch=2, 5 статей → только 2 идут в LLM
    cfg = ThresholdConfig(max_articles_full_batch=2)
    arts = [_art(f"h{i}", float(i) * 0.1) for i in range(5)]
    llm, structured = _mock_llm(_llm_items(2))
    result = run_news_signal_pipeline(
        arts, "NVDA", cfg=cfg, mode=LLMMode.FULL,
        cache=FileCache(tmp_path), settings=_SETTINGS, llm=llm,
    )
    assert len(result.items) == 2


def test_full_bad_cached_json_raises_value_error(tmp_path):
    from pipeline.cache import FileCache

    llm, _ = _mock_llm(_llm_items(1))
    # Симулируем повреждённый кэш: get_or_set_llm_text возвращает невалидный JSON
    with patch(
        "pipeline.news.news_signal_runner.get_or_set_llm_text",
        return_value="not-valid-json",
    ):
        with pytest.raises(ValueError, match="invalid"):
            run_news_signal_pipeline(
                [_art("h")], "NVDA",
                cfg=ThresholdConfig(), mode=LLMMode.FULL,
                cache=FileCache(tmp_path), settings=_SETTINGS, llm=llm,
            )


def test_empty_articles_full_returns_neutral(tmp_path):
    from pipeline.cache import FileCache

    result = run_news_signal_pipeline(
        [], "NVDA",
        cfg=ThresholdConfig(), mode=LLMMode.FULL,
        cache=FileCache(tmp_path), settings=_SETTINGS,
    )
    assert result.bias == pytest.approx(0.0)


def test_with_structured_output_called_with_schema(tmp_path):
    """with_structured_output вызывается именно с NewsSignalLLMResponse."""
    from pipeline.cache import FileCache

    llm, _ = _mock_llm(_llm_items(1))
    run_news_signal_pipeline(
        [_art("h", 0.5)], "NVDA",
        cfg=ThresholdConfig(), mode=LLMMode.FULL,
        cache=FileCache(tmp_path), settings=_SETTINGS, llm=llm,
    )
    llm.with_structured_output.assert_called_once_with(NewsSignalLLMResponse)
