"""Конвейер новостей: каналы, черновой импульс, гейты LLM, файловый кэш."""

from .cache import FileCache
from .channels import classify_channel
from .draft import ScoredArticle, draft_impulse, single_scalar_draft_bias
from .gates import decide_llm_mode
from .types import (
    DraftImpulse,
    GateContext,
    LLMMode,
    NewsImpactChannel,
    ThresholdConfig,
)

__all__ = [
    "FileCache",
    "classify_channel",
    "ScoredArticle",
    "draft_impulse",
    "single_scalar_draft_bias",
    "decide_llm_mode",
    "DraftImpulse",
    "GateContext",
    "LLMMode",
    "NewsImpactChannel",
    "ThresholdConfig",
]
