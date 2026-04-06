"""Парсинг JSON ответа LLM → NewsSignalLLMResponse (уровень 5)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from domain import NewsImpact, NewsRelevance, NewsSignal, NewsSurprise, NewsTimeHorizon
from pipeline.news_signal_schema import (
    NewsSignalLLMResponse,
    llm_response_to_domain_signals,
    parse_news_signal_llm_json,
    strip_json_fence,
)


def test_strip_json_fence():
    raw = "```json\n{\"items\": []}\n```"
    assert '"items"' in strip_json_fence(raw)


def test_parse_valid_minimal():
    payload = {
        "items": [
            {
                "article_index": 1,
                "sentiment": 0.1,
                "impact_strength": "moderate",
                "relevance": "primary",
                "surprise": "none",
                "time_horizon": "1-3d",
                "confidence": 0.5,
            }
        ]
    }
    text = json.dumps(payload)
    parsed = parse_news_signal_llm_json(text)
    assert len(parsed.items) == 1
    assert parsed.items[0].impact_strength == NewsImpact.MODERATE


def test_parse_with_markdown_fence():
    inner = json.dumps(
        {
            "items": [
                {
                    "article_index": 1,
                    "sentiment": 0.0,
                    "impact_strength": "low",
                    "relevance": "mention",
                    "surprise": "minor",
                    "time_horizon": "intraday",
                    "confidence": 0.5,
                }
            ]
        }
    )
    parsed = parse_news_signal_llm_json(f"```json\n{inner}\n```")
    assert parsed.items[0].time_horizon == NewsTimeHorizon.INTRADAY


def test_wrong_article_index_order_raises():
    bad = json.dumps(
        {
            "items": [
                {
                    "article_index": 2,
                    "sentiment": 0.0,
                    "impact_strength": "low",
                    "relevance": "mention",
                    "surprise": "minor",
                    "time_horizon": "intraday",
                    "confidence": 0.5,
                }
            ]
        }
    )
    with pytest.raises(ValueError, match="article_index"):
        parse_news_signal_llm_json(bad)


def test_two_items_must_be_1_and_2():
    ok = json.dumps(
        {
            "items": [
                {
                    "article_index": 1,
                    "sentiment": -0.5,
                    "impact_strength": "high",
                    "relevance": "related",
                    "surprise": "significant",
                    "time_horizon": "intraday",
                    "confidence": 0.5,
                },
                {
                    "article_index": 2,
                    "sentiment": 0.5,
                    "impact_strength": "high",
                    "relevance": "related",
                    "surprise": "significant",
                    "time_horizon": "intraday",
                    "confidence": 0.5,
                },
            ]
        }
    )
    parsed = parse_news_signal_llm_json(ok)
    assert len(parsed.items) == 2


def test_empty_items_invalid():
    with pytest.raises(ValidationError):
        parse_news_signal_llm_json(json.dumps({"items": []}))


def test_invalid_json():
    with pytest.raises(json.JSONDecodeError):
        parse_news_signal_llm_json("not json")


def test_llm_response_to_domain():
    r = NewsSignalLLMResponse(
        items=[
            {
                "article_index": 1,
                "sentiment": 0.2,
                "impact_strength": NewsImpact.MODERATE,
                "relevance": NewsRelevance.PRIMARY,
                "surprise": NewsSurprise.MINOR,
                "time_horizon": NewsTimeHorizon.SHORT,
                "confidence": 0.8,
            }
        ]
    )
    out = llm_response_to_domain_signals(r)
    assert len(out) == 1
    assert isinstance(out[0], NewsSignal)
    assert out[0].sentiment == pytest.approx(0.2)
