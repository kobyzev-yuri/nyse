"""Конвейер новостей: каналы, черновой импульс, гейты LLM, файловый кэш."""

from .cache import FileCache
from .news_cache import (
    cache_key_draft_aggregate,
    cache_key_raw_news,
    default_news_file_cache,
    deserialize_news_article,
    get_or_set_articles,
    get_or_set_draft_impulse,
    serialize_news_article,
)
from .channels import classify_channel, story_type_ru
from .draft import MultiTickerGateSession, ScoredArticle, draft_impulse, scored_from_news_articles, single_scalar_draft_bias
from .calendar_context import build_gate_context, calendar_high_soon
from .gates import decide_llm_mode
from .ingest import merge_news_articles, with_normalized_link
from .trade_builder import FusedBias, TradeBuilder, W_CAL, W_NEWS, W_TECH, neutral_calendar_signal
from .telegram_format import format_trade, format_technical_signal, format_signal_table, format_news_list
from .sentiment import (
    article_text,
    enrich_cheap_sentiment,
    enrich_with_default_cache,
    local_sentiment_minus1_to_1,
    resolve_cheap_sentiment,
)
from .types import (
    DraftImpulse,
    GateContext,
    LLMMode,
    NewsImpactChannel,
    PROFILE_CONTEXT,
    PROFILE_GAME5M,
    ThresholdConfig,
)

__all__ = [
    "FileCache",
    "cache_key_raw_news",
    "cache_key_draft_aggregate",
    "serialize_news_article",
    "deserialize_news_article",
    "get_or_set_articles",
    "get_or_set_draft_impulse",
    "default_news_file_cache",
    "merge_news_articles",
    "with_normalized_link",
    "article_text",
    "resolve_cheap_sentiment",
    "local_sentiment_minus1_to_1",
    "enrich_cheap_sentiment",
    "enrich_with_default_cache",
    "calendar_high_soon",
    "build_gate_context",
    "classify_channel",
    "story_type_ru",
    "MultiTickerGateSession",
    "ScoredArticle",
    "scored_from_news_articles",
    "draft_impulse",
    "single_scalar_draft_bias",
    "decide_llm_mode",
    "FusedBias",
    "TradeBuilder",
    "W_TECH",
    "W_NEWS",
    "W_CAL",
    "neutral_calendar_signal",
    "format_trade",
    "format_technical_signal",
    "format_signal_table",
    "format_news_list",
    "DraftImpulse",
    "GateContext",
    "LLMMode",
    "NewsImpactChannel",
    "PROFILE_CONTEXT",
    "PROFILE_GAME5M",
    "ThresholdConfig",
    "aggregate_news_signals",
    "build_signal_messages",
    "PROMPT_VERSION",
    "run_news_signal_pipeline",
    "NewsSignalLLMItem",
    "NewsSignalLLMResponse",
    "parse_news_signal_llm_json",
    "strip_json_fence",
    "llm_response_to_domain_signals",
    "LlmArticlePlan",
    "plan_llm_article_batch",
    "chat_completion_text",
    "cache_key_llm",
    "get_or_set_llm_text",
    "default_llm_file_cache",
    "build_digest_messages",
    "run_lite_digest_cached",
    "run_calendar_signal_pipeline",
    "run_technical_signal_pipeline",
    "CalendarLlmAgent",
]


def __getattr__(name: str):
    """
    LLM и схемы уровня 5 подгружаются лениво, чтобы ``python -m pipeline.<module>`` не получал
    предупреждение runpy о модуле, уже попавшем в sys.modules при ``import pipeline``.
    """
    if name == "chat_completion_text":
        from .llm_client import chat_completion_text

        return chat_completion_text
    if name in ("cache_key_llm", "default_llm_file_cache", "get_or_set_llm_text"):
        from . import llm_cache as _lc

        return getattr(_lc, name)
    if name in ("build_digest_messages", "run_lite_digest_cached"):
        from . import llm_digest as _ld

        return getattr(_ld, name)
    if name in (
        "NewsSignalLLMItem",
        "NewsSignalLLMResponse",
        "parse_news_signal_llm_json",
        "strip_json_fence",
        "llm_response_to_domain_signals",
    ):
        from . import news_signal_schema as _ns

        return getattr(_ns, name)
    if name in ("LlmArticlePlan", "plan_llm_article_batch"):
        from . import llm_batch_plan as _bp

        return getattr(_bp, name)
    if name == "aggregate_news_signals":
        from .news_signal_aggregator import aggregate_news_signals

        return aggregate_news_signals
    if name in ("build_signal_messages", "PROMPT_VERSION"):
        from . import news_signal_prompt as _nsp

        return getattr(_nsp, name)
    if name == "run_news_signal_pipeline":
        from .news_signal_runner import run_news_signal_pipeline

        return run_news_signal_pipeline
    if name == "run_calendar_signal_pipeline":
        from .calendar_signal_runner import run_calendar_signal_pipeline

        return run_calendar_signal_pipeline
    if name == "run_technical_signal_pipeline":
        from .technical_signal_runner import run_technical_signal_pipeline

        return run_technical_signal_pipeline
    if name == "CalendarLlmAgent":
        from .calendar_llm_agent import CalendarLlmAgent

        return CalendarLlmAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return list(__all__)
