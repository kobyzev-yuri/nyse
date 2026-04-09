"""
Уровень 5 (шаг 2): разбор JSON ответа LLM → доменные ``NewsSignal``.

Модели входа/выхода — в ``pipeline/news_dto.py`` (как ``pystockinvest/agent/news/dto.py``).
Здесь: парсинг сырой строки, strip markdown fence, маппинг в ``domain.NewsSignal``.

Запуск из корня nyse: ``python -m pipeline.news_signal_schema`` или ``python pipeline/news_signal_schema.py``.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.news_signal_schema", run_name="__main__")
    raise SystemExit(0)

import json
import re
from typing import Any

from domain import NewsSignal

from .news_dto import NewsSignalLLMResponse

# Обратная совместимость импортов
from .news_dto import NewsArticleInput, NewsSignalAgentInput, NewsSignalLLMItem  # noqa: F401


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
