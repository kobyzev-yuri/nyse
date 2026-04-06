"""
Уровень 5 (шаг 3): по ``LLMMode`` и списку статей — что отдавать в structured LLM vs lite-дайджест.

Без HTTP; только политика индексов и заголовков (юнит-тестируемо).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from domain import NewsArticle

from .types import LLMMode, ThresholdConfig


@dataclass(frozen=True)
class LlmArticlePlan:
    """План вызовов: skip = ничего; lite = дайджест по заголовкам; full = индексы для signal."""

    mode: LLMMode
    indices_for_structured_signal: tuple[int, ...]
    """Индексы в ``articles`` (0-based) для полного structured signal (уровень 5)."""
    titles_for_lite_digest: tuple[str, ...]
    """Заголовки для ``run_lite_digest_cached`` / микро-режима при LITE."""


def _rank_indices_by_abs_sentiment(articles: Sequence[NewsArticle], cap: int) -> tuple[int, ...]:
    if cap <= 0 or not articles:
        return ()
    scored = [(i, abs(a.cheap_sentiment or 0.0)) for i, a in enumerate(articles)]
    scored.sort(key=lambda t: (-t[1], t[0]))
    top = [i for i, _ in scored[:cap]]
    return tuple(sorted(top))


def plan_llm_article_batch(
    mode: LLMMode,
    articles: Sequence[NewsArticle],
    *,
    cfg: ThresholdConfig,
    max_titles_digest: int = 20,
) -> LlmArticlePlan:
    """
    - **SKIP:** не звать structured LLM; дайджест пустой (экономия токенов).
    - **LITE:** structured signal не планируем; дайджест по заголовкам (обрезка ``max_titles_digest``).
    - **FULL:** structured signal на всех статьях, если их ≤ ``max_articles_full_batch``; иначе топ-K
      по ``|cheap_sentiment|`` (при равенстве — меньший индекс), затем индексы отсортированы по времени.
    """
    arts = list(articles)
    if mode == LLMMode.SKIP:
        return LlmArticlePlan(
            mode=mode,
            indices_for_structured_signal=(),
            titles_for_lite_digest=(),
        )
    if mode == LLMMode.LITE:
        titles = tuple(a.title for a in arts[:max_titles_digest])
        return LlmArticlePlan(
            mode=mode,
            indices_for_structured_signal=(),
            titles_for_lite_digest=titles,
        )
    # FULL
    cap = cfg.max_articles_full_batch
    if len(arts) <= cap:
        idx = tuple(range(len(arts)))
    else:
        idx = _rank_indices_by_abs_sentiment(arts, cap)
    return LlmArticlePlan(
        mode=mode,
        indices_for_structured_signal=idx,
        titles_for_lite_digest=(),
    )
