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

    t1_abs_draft_bias: float = 0.20
    """Ниже этого |draft_bias| при отсутствии REGIME можно skip full LLM.
    Откалибровано 2026-04-06 на 7 тикерах × 7 дней; снижено с 0.25 → 0.20
    чтобы ловить умеренно значимые сигналы (e.g. ASML экспортные ограничения).
    """

    t2_regime_confidence: float = 0.5
    """Выше этого rule-confidence по REGIME — тянуть full (или lite)."""

    max_articles_full_batch: int = 15
    """Больше статей — сужать батч (lite) до топ-K."""

    regime_stress_min: float = 0.05
    """Минимальный regime_stress для признания REGIME-присутствия в GateContext.
    Откалибровано 2026-04-06: порог 0.01 давал ложный FULL для ORCL
    из-за одной нерелевантной REG-статьи.
    """


PROFILE_GAME5M = ThresholdConfig(
    t1_abs_draft_bias=0.12,
    t2_regime_confidence=0.5,
    max_articles_full_batch=12,
    regime_stress_min=0.05,
)
"""Профиль для интрадей GAME_5M тикеров (SNDK, NBIS, MU, LITE, CIEN, ASML).
Пониженный T1; N поднят с 8 → 12 (2026-04-08): после слияния Yahoo+др. источников
до ``max_per_ticker`` статей в окне ветка ``article_count > N`` не должна ложно
тянуть LITE только из-за лимита 8 при фактическом потолке 12.
Откалибровано 2026-04-06, уточнено 2026-04-08.
"""

PROFILE_CONTEXT = ThresholdConfig(
    t1_abs_draft_bias=0.20,
    t2_regime_confidence=0.5,
    max_articles_full_batch=15,
    regime_stress_min=0.05,
)
"""Профиль для контекстных тикеров (MSFT, META, AMZN, NVDA и др.).
Стандартный T1 и N для крупных тикеров с 40–50 статей/день.
Откалибровано 2026-04-06.
"""


@dataclass(frozen=True)
class GateContext:
    draft_bias: float
    regime_present: bool
    regime_rule_confidence: float
    calendar_high_soon: bool
    article_count: int


@dataclass(frozen=True)
class DraftImpulse:
    """
    Черновой импульс по каналам (уровень 3, этап D).

    Средние по каналам **не смешиваются**: ``draft_bias_incremental`` только из
    ``INCREMENTAL``; ``regime_stress`` / ``policy_stress`` — из своих каналов (|sentiment|, вес).

    Дополнительно: число статей и сумма весов затухания по каналу; максимум |sentiment|
    в REGIME/POLICY (для пиков «стресса», см. §5.4).
    """

    draft_bias_incremental: float = 0.0
    regime_stress: float = 0.0
    policy_stress: float = 0.0
    articles_incremental: int = 0
    articles_regime: int = 0
    articles_policy: int = 0
    weight_sum_incremental: float = 0.0
    weight_sum_regime: float = 0.0
    weight_sum_policy: float = 0.0
    max_abs_regime: float = 0.0
    max_abs_policy: float = 0.0
