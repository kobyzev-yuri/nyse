"""
Уровень 5 (шаг 7): оркестратор pipeline — от статей до ``AggregatedNewsSignal``.

Паттерн вызова LLM идентичен pystockinvest/agent/news/signal.py::

    structured_llm = llm.with_structured_output(NewsSignalLLMResponse)
    response = structured_llm.invoke([SystemMessage(...), HumanMessage(...)])

Кэш сохраняет ``response.model_dump_json()`` → при попадании восстанавливает через
``NewsSignalLLMResponse.model_validate_json(cached)``.

При ``mode=SKIP / LITE`` возвращает нейтральный агрегат без вызова LLM.
"""

from __future__ import annotations

import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence, cast

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.news_signal_runner", run_name="__main__")
    raise SystemExit(0)

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from domain import AggregatedNewsSignal, NewsArticle

from .cache import FileCache
from .llm_batch_plan import plan_llm_article_batch
from .llm_cache import cache_key_llm, default_llm_file_cache, get_or_set_llm_text
from .llm_factory import get_chat_model
from .news_signal_aggregator import aggregate_news_signals
from .news_signal_prompt import PROMPT_VERSION, build_signal_messages
from .news_signal_schema import NewsSignalLLMResponse, llm_response_to_domain_signals
from .types import LLMMode, ThresholdConfig

if TYPE_CHECKING:
    from config_loader import OpenAISettings


def run_news_signal_pipeline(
    articles: Sequence[NewsArticle],
    ticker: str,
    *,
    cfg: ThresholdConfig,
    mode: LLMMode,
    cache: Optional[FileCache] = None,
    settings: Optional["OpenAISettings"] = None,
    ttl_sec: Optional[int] = None,
    llm: Optional[BaseChatModel] = None,
    now: Optional[datetime] = None,
) -> AggregatedNewsSignal:
    """
    Главная функция уровня 5.

    Parameters
    ----------
    articles : список статей уже прошедших уровни 0–4.
    ticker   : строка тикера (например ``"NVDA"``).
    cfg      : пороги ``ThresholdConfig``.
    mode     : ``LLMMode.SKIP / LITE / FULL`` — решение гейта уровня 4.
    cache    : ``FileCache`` для ответов LLM; ``None`` → ``default_llm_file_cache()``.
    settings : ``OpenAISettings``; ``None`` → ``config_loader.get_openai_settings()``.
    ttl_sec  : TTL кэша; ``None`` → ``config_loader.llm_cache_ttl_sec()``.
    llm      : готовый ``BaseChatModel``; ``None`` → ``get_chat_model(settings)``.
               Передайте в тестах: ``FakeChatModel()`` или ``MagicMock(spec=BaseChatModel)``.
    """
    arts = list(articles)
    _now = now or datetime.now(timezone.utc)

    # SKIP / LITE → нейтральный агрегат без structured LLM
    if mode in (LLMMode.SKIP, LLMMode.LITE):
        return aggregate_news_signals([])

    # FULL: формируем батч
    plan = plan_llm_article_batch(LLMMode.FULL, arts, cfg=cfg)
    if not plan.indices_for_structured_signal:
        return aggregate_news_signals([])

    batch = [arts[i] for i in plan.indices_for_structured_signal]

    # Промпт в виде dict (для cache_key_llm) + LangChain-объекты для invoke
    msg_dicts = build_signal_messages(batch, ticker, now=_now)
    lc_messages = [
        SystemMessage(content=msg_dicts[0]["content"]),
        HumanMessage(content=msg_dicts[1]["content"]),
    ]

    import config_loader

    s = settings if settings is not None else config_loader.get_openai_settings()
    if s is None:
        raise RuntimeError("OpenAI settings missing (OPENAI_API_KEY)")

    _llm = llm if llm is not None else get_chat_model(s)
    structured_llm = _llm.with_structured_output(NewsSignalLLMResponse)

    c = cache if cache is not None else default_llm_file_cache()
    ttl = ttl_sec if ttl_sec is not None else config_loader.llm_cache_ttl_sec()
    key = cache_key_llm(msg_dicts, s.model, prompt_version=PROMPT_VERSION)

    def fetcher() -> str:
        response = cast(NewsSignalLLMResponse, structured_llm.invoke(lc_messages))
        return response.model_dump_json()

    raw_json = get_or_set_llm_text(c, key, ttl, fetcher)

    try:
        llm_response = NewsSignalLLMResponse.model_validate_json(raw_json)
    except Exception as exc:
        raise ValueError(
            f"Cached/returned LLM JSON invalid for {ticker}: {exc!r}\n---\n{raw_json[:500]}"
        ) from exc

    signals = llm_response_to_domain_signals(llm_response)
    return aggregate_news_signals(signals)


if __name__ == "__main__":
    print(
        "run_news_signal_pipeline — импортируйте из pipeline.\n"
        "Для smoke с реальным API: tests/integration/test_news_signal_runner_smoke.py"
    )
