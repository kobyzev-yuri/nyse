"""
Уровень 5 (шаг 7): оркестратор pipeline — от статей до ``AggregatedNewsSignal``.

Склейка:
    articles → plan_llm_article_batch → build_signal_messages
             → chat_completion_text (с кэшем) → parse_news_signal_llm_json
             → llm_response_to_domain_signals → aggregate_news_signals
             → AggregatedNewsSignal

При ``mode=SKIP`` возвращает нейтральный агрегат (без вызова LLM).
При ``mode=LITE`` возвращает нейтральный агрегат (lite-дайджест — отдельно через ``run_lite_digest_cached``).

Запуск: ``python -m pipeline.news_signal_runner`` или ``python pipeline/news_signal_runner.py``.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.news_signal_runner", run_name="__main__")
    raise SystemExit(0)

from domain import AggregatedNewsSignal, NewsArticle

from datetime import datetime, timezone

from .cache import FileCache
from .llm_batch_plan import plan_llm_article_batch
from .llm_cache import cache_key_llm, default_llm_file_cache, get_or_set_llm_text
from .llm_client import chat_completion_text
from .news_signal_aggregator import aggregate_news_signals
from .news_signal_prompt import PROMPT_VERSION, build_signal_messages
from .news_signal_schema import llm_response_to_domain_signals, parse_news_signal_llm_json
from .types import LLMMode, ThresholdConfig


def run_news_signal_pipeline(
    articles: Sequence[NewsArticle],
    ticker: str,
    *,
    cfg: ThresholdConfig,
    mode: LLMMode,
    cache: Optional[FileCache] = None,
    settings=None,
    ttl_sec: Optional[int] = None,
    post: Optional[Callable] = None,
    now: Optional[datetime] = None,
) -> AggregatedNewsSignal:
    """
    Главная функция уровня 5.

    Parameters
    ----------
    articles : список статей уже прошедших уровни 0–4.
    ticker   : строка тикера (например ``"NVDA"``).
    cfg      : пороги ``ThresholdConfig`` (уже решено снаружи через ``decide_llm_mode``).
    mode     : ``LLMMode.SKIP / LITE / FULL`` — решение гейта уровня 4.
    cache    : ``FileCache`` для ответов LLM; ``None`` → ``default_llm_file_cache()``.
    settings : ``OpenAISettings``; ``None`` → ``config_loader.get_openai_settings()``.
    ttl_sec  : TTL кэша; ``None`` → ``config_loader.llm_cache_ttl_sec()``.
    post     : mock для ``requests.post`` (тесты без сети).
    """
    arts = list(articles)
    # now фиксируется один раз, чтобы кэш-ключ не менялся при повторных вызовах в одну сессию
    _now = now or datetime.now(timezone.utc)

    # SKIP / LITE → нейтральный агрегат без structured LLM
    if mode in (LLMMode.SKIP, LLMMode.LITE):
        return aggregate_news_signals([])

    # FULL: формируем батч
    plan = plan_llm_article_batch(LLMMode.FULL, arts, cfg=cfg)
    if not plan.indices_for_structured_signal:
        return aggregate_news_signals([])

    batch = [arts[i] for i in plan.indices_for_structured_signal]

    # Промпт (now фиксировано — стабильный кэш-ключ)
    messages = build_signal_messages(batch, ticker, now=_now)

    # Настройки / кэш / TTL
    import config_loader

    s = settings if settings is not None else config_loader.get_openai_settings()
    if s is None:
        raise RuntimeError("OpenAI settings missing (OPENAI_API_KEY)")

    c = cache if cache is not None else default_llm_file_cache()
    ttl = ttl_sec if ttl_sec is not None else config_loader.llm_cache_ttl_sec()
    key = cache_key_llm(messages, s.model, prompt_version=PROMPT_VERSION)

    # HTTP (с кэшем)
    _post_fn = post  # захватываем в замыкание

    def fetcher() -> str:
        kw: dict = {"settings": s}
        if _post_fn is not None:
            kw["post"] = _post_fn
        return chat_completion_text(messages, **kw)

    raw_text = get_or_set_llm_text(c, key, ttl, fetcher)

    # Парсинг + агрегация
    try:
        llm_response = parse_news_signal_llm_json(raw_text)
    except Exception as exc:
        raise ValueError(
            f"LLM returned unparseable JSON for {ticker}: {exc!r}\n---\n{raw_text[:500]}"
        ) from exc

    signals = llm_response_to_domain_signals(llm_response)
    return aggregate_news_signals(signals)


if __name__ == "__main__":
    print(
        "run_news_signal_pipeline — импортируйте из pipeline.\n"
        "Для smoke с реальным API: tests/integration/test_news_signal_runner_smoke.py"
    )
