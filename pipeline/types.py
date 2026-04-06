"""Типы для конвейера новостей (уровни 1–4 без LLM)."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


class NewsImpactChannel(enum.StrEnum):
    INCREMENTAL = "incremental"
    REGIME = "regime"
    POLICY_RATES = "policy_rates"


class LLMMode(enum.StrEnum):
    SKIP = "skip"
    LITE = "lite"
    FULL = "full"


@dataclass(frozen=True)
class ThresholdConfig:
    """Пороги для гейтинга LLM; подбираются тестами и офлайн-калибровкой."""

    t1_abs_draft_bias: float = 0.25
    """Ниже этого |draft_bias| при отсутствии REGIME можно skip full LLM."""

    t2_regime_confidence: float = 0.5
    """Выше этого rule-confidence по REGIME — тянуть full (или lite)."""

    max_articles_full_batch: int = 15
    """Больше статей — сужать батч (lite) до топ-K."""


@dataclass(frozen=True)
class GateContext:
    draft_bias: float
    regime_present: bool
    regime_rule_confidence: float
    calendar_high_soon: bool
    article_count: int


@dataclass(frozen=True)
class DraftImpulse:
    """Черновой импульс по каналам (уровень 3)."""

    draft_bias_incremental: float
    regime_stress: float
    policy_stress: float
