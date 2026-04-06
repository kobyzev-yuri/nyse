"""Тесты гейтинга LLM (калибровка порогов)."""

from __future__ import annotations

import pytest

from pipeline import GateContext, LLMMode, ThresholdConfig, decide_llm_mode


def test_gate_skip_calm(default_thresholds):
    ctx = GateContext(
        draft_bias=0.05,
        regime_present=False,
        regime_rule_confidence=0.0,
        calendar_high_soon=False,
        article_count=3,
    )
    assert decide_llm_mode(default_thresholds, ctx) == LLMMode.SKIP


def test_gate_full_calendar():
    cfg = ThresholdConfig()
    ctx = GateContext(
        draft_bias=0.01,
        regime_present=False,
        regime_rule_confidence=0.0,
        calendar_high_soon=True,
        article_count=2,
    )
    assert decide_llm_mode(cfg, ctx) == LLMMode.FULL


def test_gate_full_regime():
    cfg = ThresholdConfig()
    ctx = GateContext(
        draft_bias=0.1,
        regime_present=True,
        regime_rule_confidence=0.9,
        calendar_high_soon=False,
        article_count=2,
    )
    assert decide_llm_mode(cfg, ctx) == LLMMode.FULL


@pytest.mark.parametrize(
    "bias,mode",
    [
        (0.6, LLMMode.FULL),
        (0.3, LLMMode.LITE),
    ],
)
def test_gate_bias_branches(default_thresholds, bias, mode):
    ctx = GateContext(
        draft_bias=bias,
        regime_present=False,
        regime_rule_confidence=0.0,
        calendar_high_soon=False,
        article_count=4,
    )
    assert decide_llm_mode(default_thresholds, ctx) == mode


def test_gate_strong_bias_overrides_article_count():
    """Сильный bias >= T1*2 должен давать FULL даже если статей > N."""
    cfg = ThresholdConfig(
        t1_abs_draft_bias=0.25,
        max_articles_full_batch=15,
    )
    ctx = GateContext(
        draft_bias=0.55,  # >= T1*2 = 0.50
        regime_present=False,
        regime_rule_confidence=0.0,
        calendar_high_soon=False,
        article_count=30,  # > N=15
    )
    assert decide_llm_mode(cfg, ctx) == LLMMode.FULL


def test_gate_many_articles_moderate_bias_is_lite():
    """Умеренный bias при большом числе статей → LITE, не SKIP."""
    cfg = ThresholdConfig(
        t1_abs_draft_bias=0.25,
        max_articles_full_batch=15,
    )
    ctx = GateContext(
        draft_bias=0.35,  # T1 < bias < T1*2
        regime_present=False,
        regime_rule_confidence=0.0,
        calendar_high_soon=False,
        article_count=30,  # > N=15
    )
    assert decide_llm_mode(cfg, ctx) == LLMMode.LITE


def test_gate_calm_many_articles_is_skip():
    """Нейтральный фон (bias < T1) с большим числом статей → SKIP, не LITE."""
    cfg = ThresholdConfig(
        t1_abs_draft_bias=0.25,
        max_articles_full_batch=15,
    )
    ctx = GateContext(
        draft_bias=0.05,  # < T1
        regime_present=False,
        regime_rule_confidence=0.0,
        calendar_high_soon=False,
        article_count=50,
    )
    assert decide_llm_mode(cfg, ctx) == LLMMode.SKIP
