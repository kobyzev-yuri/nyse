"""Уровень 4: решение о режиме LLM по порогам."""

from __future__ import annotations

from .types import GateContext, LLMMode, ThresholdConfig

# Порог FULL = t1 * этот множитель; значение 2.0 получено из калибровки §5.3.
# При t1=0.12 (PROFILE_GAME5M): FULL если |bias| ≥ 0.24.
_FULL_BIAS_MULTIPLIER = 2.0


def decide_llm_mode(cfg: ThresholdConfig, ctx: GateContext) -> LLMMode:
    """
    Политика выбора режима LLM (калибруется тестами, см. docs/calibration.md):

    FULL  — скоро макро-событие календаря, или REGIME с высокой уверенностью,
            или черновой |bias| ≥ t1 * _FULL_BIAS_MULTIPLIER.
    LITE  — умеренный сигнал, или слишком много статей для полного промпта.
    SKIP  — спокойный фон без REGIME-сигнала (дорогой LLM не нужен).
    """
    if ctx.calendar_high_soon:
        return LLMMode.FULL

    if ctx.regime_present and ctx.regime_rule_confidence >= cfg.t2_regime_confidence:
        return LLMMode.FULL

    ab = abs(ctx.draft_bias)

    # Сильный черновой сигнал имеет приоритет над лимитом статей.
    if ab >= cfg.t1_abs_draft_bias * _FULL_BIAS_MULTIPLIER:
        return LLMMode.FULL

    # Спокойный фон без REGIME → пропускаем LLM.
    if ab < cfg.t1_abs_draft_bias and not ctx.regime_present:
        return LLMMode.SKIP

    # Умеренный сигнал: если статей слишком много — lite-промпт экономит токены.
    if ctx.article_count > cfg.max_articles_full_batch:
        return LLMMode.LITE

    return LLMMode.LITE
