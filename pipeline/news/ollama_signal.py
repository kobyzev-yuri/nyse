"""
Structured news signal (уровень 5) через Ollama /api/chat + JSON.

Тот же промпт ``build_signal_messages``, что и OpenAI-путь, плюс текстовая инструкция
схемы ответа (аналог tradenews ``OLLAMA_JSON_SUFFIX``): Ollama не использует
``with_structured_output`` из LangChain.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, Sequence

from domain import NewsArticle

from ..cache import FileCache
from ..llm_batch_plan import plan_llm_article_batch
from ..llm_cache import cache_key_llm, default_llm_file_cache, get_or_set_llm_text
from ..types import LLMMode, ThresholdConfig
from .news_signal_aggregator import aggregate_news_signals
from .news_signal_prompt import PROMPT_VERSION, build_signal_messages
from .news_signal_schema import NewsSignalLLMResponse, llm_response_to_domain_signals
from .ollama_http import ollama_chat, strip_json_fence


def _coerce_ollama_items_to_pydantic_ranges(data: object) -> object:
    """
    Ollama иногда выдаёт sentiment вне [-1,1] или confidence вне [0,1].
    Поджимаем до границ NewsSignalLLMItem до model_validate.
    """
    if not isinstance(data, dict):
        return data
    items = data.get("items")
    if not isinstance(items, list):
        return data
    out_items: list[object] = []
    for it in items:
        if not isinstance(it, dict):
            out_items.append(it)
            continue
        row = dict(it)
        if "sentiment" in row:
            try:
                s = float(row["sentiment"])
                row["sentiment"] = max(-1.0, min(1.0, s))
            except (TypeError, ValueError):
                pass
        if "confidence" in row:
            try:
                c = float(row["confidence"])
                row["confidence"] = max(0.0, min(1.0, c))
            except (TypeError, ValueError):
                pass
        out_items.append(row)
    merged = dict(data)
    merged["items"] = out_items
    return merged


# Согласовано с tradenews/tradenews/prompt_news_signal.py (поля = NewsSignalLLMItem)
_OLLAMA_JSON_SUFFIX = """
When returning JSON (no markdown fences), use exactly this shape. Field values must match the allowed strings below (lowercase).

{
  "items": [
    {
      "article_index": 1,
      "sentiment": 0.0,
      "impact_strength": "low" | "moderate" | "high",
      "relevance": "mention" | "related" | "primary",
      "surprise": "none" | "minor" | "significant" | "major",
      "time_horizon": "intraday" | "1-3d" | "3-7d" | "long",
      "confidence": 0.0
    }
  ]
}

Rules:
- One object per input article; article_index must be 1..n in order matching the input articles.
- sentiment: float in [-1, 1] for expected effect on the target ticker price.
- confidence: float in [0, 1].
- Use only the literal strings shown for enums (e.g. time_horizon "1-3d" exactly).
""".strip()


def run_news_signal_pipeline_ollama(
    articles: Sequence[NewsArticle],
    ticker: str,
    *,
    cfg: ThresholdConfig,
    mode: LLMMode,
    ollama_model: str,
    ollama_host: str = "http://127.0.0.1:11434",
    cache: Optional[FileCache] = None,
    ttl_sec: Optional[int] = None,
    now: Optional[datetime] = None,
    timeout_sec: float = 180.0,
) -> AggregatedNewsSignal:
    arts = list(articles)
    _now = now or datetime.now(timezone.utc)

    if mode in (LLMMode.SKIP, LLMMode.LITE):
        return aggregate_news_signals([])

    plan = plan_llm_article_batch(LLMMode.FULL, arts, cfg=cfg)
    if not plan.indices_for_structured_signal:
        return aggregate_news_signals([])

    batch = [arts[i] for i in plan.indices_for_structured_signal]

    msg_dicts = build_signal_messages(batch, ticker, now=_now)
    if len(msg_dicts) != 2:
        raise RuntimeError("build_signal_messages must return [system, user]")
    user_extended = msg_dicts[1]["content"] + "\n\n" + _OLLAMA_JSON_SUFFIX
    msg_dicts_ollama = [
        msg_dicts[0],
        {"role": "user", "content": user_extended},
    ]

    import config_loader

    c = cache if cache is not None else default_llm_file_cache()
    ttl = ttl_sec if ttl_sec is not None else config_loader.llm_cache_ttl_sec()
    cache_model = f"ollama:{ollama_model}"
    key = cache_key_llm(msg_dicts_ollama, cache_model, prompt_version=PROMPT_VERSION)

    def fetcher() -> str:
        raw = ollama_chat(
            ollama_model,
            msg_dicts_ollama,
            base_url=ollama_host,
            timeout_sec=timeout_sec,
            json_mode=True,
        )
        text = strip_json_fence(raw)
        parsed = json.loads(text)
        parsed = _coerce_ollama_items_to_pydantic_ranges(parsed)
        return json.dumps(parsed, ensure_ascii=False)

    raw_json = get_or_set_llm_text(c, key, ttl, fetcher)
    # Поджим границ и для записей кэша, сделанных до coerce в fetcher.
    parsed = json.loads(raw_json)
    parsed = _coerce_ollama_items_to_pydantic_ranges(parsed)
    raw_json = json.dumps(parsed, ensure_ascii=False)

    try:
        llm_response = NewsSignalLLMResponse.model_validate_json(raw_json)
    except Exception as exc:
        raise ValueError(
            f"Ollama JSON invalid for {ticker} ({ollama_model}): {exc!r}\n---\n{raw_json[:800]}"
        ) from exc

    signals = llm_response_to_domain_signals(llm_response)
    return aggregate_news_signals(signals)
