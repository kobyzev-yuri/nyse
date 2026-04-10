"""
DTO уровня 5 — зеркало ``pystockinvest/agent/news/dto.py``.

Имена и поля совпадают с pystockinvest (`agent/news`); отличие только в импорте enum’ов
из ``domain`` (в pystockinvest — ``agent.models``).

Использование:
  - **вход**: ``NewsSignalAgentInput`` → ``model_dump_json`` в user-промпт;
  - **выход**: ``NewsSignalLLMResponse`` / ``NewsSignalLLMItem`` — для ``with_structured_output``.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from domain import NewsImpact, NewsRelevance, NewsSurprise, NewsTimeHorizon


class NewsArticleInput(BaseModel):
    """Как ``NewsArticleInput`` в pystockinvest ``agent/news/dto.py``."""

    article_index: int = Field(ge=1, description="1-based index of the article")
    title: str = Field(
        min_length=1,
        description="Headline of the article.",
    )
    summary: Optional[str] = Field(
        default=None,
        description="Short article summary or excerpt. Null if unavailable.",
    )
    timestamp: datetime = Field(
        description="Publication time of the article in UTC.",
    )
    source: Optional[str] = Field(
        default=None,
        description="Publisher or source name if available.",
    )


class NewsSignalAgentInput(BaseModel):
    """Как ``NewsSignalAgentInput`` в pystockinvest ``agent/news/dto.py``."""

    target_ticker: str = Field(
        min_length=1,
        description="Ticker for which the article impact must be estimated.",
    )
    current_time: datetime = Field(description="Current UTC time at inference.")
    articles: List[NewsArticleInput] = Field(
        description="Articles to analyze independently, in input order."
    )


class NewsSignalLLMItem(BaseModel):
    """
    Один элемент ответа LLM.
    В pystockinvest класс называется ``NewsSignal`` внутри ``dto.py``;
    здесь имя ``NewsSignalLLMItem``, чтобы не конфликтовать с ``domain.NewsSignal``.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    article_index: int = Field(ge=1, description="1-based index in the prompt list.")
    sentiment: float = Field(
        ge=-1.0,
        le=1.0,
        description=(
            "Expected direction/strength of price impact on the target ticker (−1 bearish … +1 bullish); "
            "not raw article tone if the ticker is peripheral."
        ),
    )
    impact_strength: NewsImpact = Field(
        description="Expected magnitude of move given the sign of sentiment (low/moderate/high)."
    )
    relevance: NewsRelevance = Field(
        description="How central the target ticker is to the story; feeds aggregation weight."
    )
    surprise: NewsSurprise = Field(
        description="Surprise vs expectations; stored for UI/trace, not used in bias weight formula."
    )
    time_horizon: NewsTimeHorizon = Field(
        description="When the effect mainly materializes; feeds aggregation weight (shorter horizons weighted higher)."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Certainty in this per-article signal; feeds aggregation weight (floored at 0.05).",
    )


class NewsSignalLLMResponse(BaseModel):
    """
    Корневой ответ LLM: ``{"items": [...]}``.
    Как ``NewsSignalResponse`` в pystockinvest ``agent/news/dto.py``.
    """

    model_config = ConfigDict(extra="forbid")

    items: List[NewsSignalLLMItem] = Field(
        min_length=1,
        description="Exactly one signal per input article, in the same order as provided.",
    )

    @model_validator(mode="after")
    def validate_signals_order(self) -> NewsSignalLLMResponse:
        expected_indexes = list(range(1, len(self.items) + 1))
        actual_indexes = [signal.article_index for signal in self.items]
        if actual_indexes != expected_indexes:
            raise ValueError(
                "signals must preserve input order and contain sequential "
                f"article_index values starting from 1: expected {expected_indexes}, "
                f"got {actual_indexes}"
            )
        return self
