"""Уровень 4: решение о режиме LLM по порогам."""

from __future__ import annotations

from .types import GateContext, LLMMode, ThresholdConfig


def decide_llm_mode(cfg: ThresholdConfig, ctx: GateContext) -> LLMMode:
    """
    Упрощённая политика (дальше калибруется тестами):
    - full: сильный черновой сигнал, высокий REGIME, скоро HIGH календарь, или много статей.
    - lite: умеренное отклонение.
    - skip: спокойный фон без REGIME.
    """
    if ctx.calendar_high_soon:
        return LLMMode.FULL

    if ctx.regime_present and ctx.regime_rule_confidence >= cfg.t2_regime_confidence:
        return LLMMode.FULL

    if ctx.article_count > cfg.max_articles_full_batch:
        return LLMMode.LITE

    ab = abs(ctx.draft_bias)
    if ab < cfg.t1_abs_draft_bias and not ctx.regime_present:
        return LLMMode.SKIP

    if ab >= cfg.t1_abs_draft_bias * 2.0:
        return LLMMode.FULL

    return LLMMode.LITE
