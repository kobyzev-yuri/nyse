"""
Уровень 5 (шаг 2): Pydantic-схема ответа LLM как в pystockinvest `agent/news/dto.py`.

Парсинг сырой строки (JSON, опционально в markdown-огороде ```json) → валидация → ``domain.NewsSignal``.

Запуск из корня nyse: ``python -m pipeline.news_signal_schema`` или ``python pipeline/news_signal_schema.py``.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.news_signal_schema", run_name="__main__")
    raise SystemExit(0)

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain import (
    NewsImpact,
    NewsRelevance,
    NewsSignal,
    NewsSurprise,
    NewsTimeHorizon,
)


class NewsSignalLLMItem(BaseModel):
    """Один элемент ответа; поля как у pydantic `NewsSignal` в pystockinvest."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    article_index: int = Field(ge=1, description="1-based index in the prompt list.")
    sentiment: float = Field(ge=-1.0, le=1.0)
    impact_strength: NewsImpact
    relevance: NewsRelevance
    surprise: NewsSurprise
    time_horizon: NewsTimeHorizon
    confidence: float = Field(ge=0.0, le=1.0)


class NewsSignalLLMResponse(BaseModel):
    """Корневой объект: ``{"items": [...]}`` — как ``NewsSignalResponse`` в Kerima."""

    model_config = ConfigDict(extra="forbid")

    items: list[NewsSignalLLMItem] = Field(
        min_length=1,
        description="One signal per article, article_index 1..n in order.",
    )

    @model_validator(mode="after")
    def _sequential_indexes(self) -> NewsSignalLLMResponse:
        expected = list(range(1, len(self.items) + 1))
        actual = [x.article_index for x in self.items]
        if actual != expected:
            raise ValueError(
                "items must have article_index 1..n in order, "
                f"expected {expected}, got {actual}"
            )
        return self


def strip_json_fence(raw: str) -> str:
    """Убирает обёртку ```json ... ``` если модель её вернула."""
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def parse_news_signal_llm_json(raw: str) -> NewsSignalLLMResponse:
    """Разбор и валидация JSON строки → ``NewsSignalLLMResponse``."""
    text = strip_json_fence(raw)
    data: Any = json.loads(text)
    if isinstance(data, dict) and "items" in data:
        return NewsSignalLLMResponse.model_validate(data)
    raise ValueError("JSON must be an object with an 'items' array")


def llm_response_to_domain_signals(response: NewsSignalLLMResponse) -> list[NewsSignal]:
    """Снимает ``article_index``; порядок списка = порядок статей в промпте."""
    return [
        NewsSignal(
            sentiment=item.sentiment,
            impact_strength=item.impact_strength,
            relevance=item.relevance,
            surprise=item.surprise,
            time_horizon=item.time_horizon,
            confidence=item.confidence,
        )
        for item in response.items
    ]


if __name__ == "__main__":
    sample = {
        "items": [
            {
                "article_index": 1,
                "sentiment": 0.0,
                "impact_strength": "low",
                "relevance": "mention",
                "surprise": "none",
                "time_horizon": "intraday",
                "confidence": 0.5,
            }
        ]
    }
    parsed = parse_news_signal_llm_json(json.dumps(sample))
    dom = llm_response_to_domain_signals(parsed)
    print("items:", len(parsed.items), "→ domain NewsSignal:", dom[0])
