"""
Уровень 5 (шаг 6): промпт для structured LLM signal.

``build_signal_messages`` возвращает список сообщений для ``chat_completion_text``.
Формат payload совместим с ``pystockinvest/agent/news/dto.py``:
  - системный промпт идентичен Kerima (``SYSTEM_PROMPT``);
  - user-payload — JSON ``NewsSignalAgentInput`` (target_ticker, current_time, articles[]);
  - от модели ожидается JSON ``{"items": [...]}`` → ``parse_news_signal_llm_json``.

JSON-схема (поля items[i]):
    article_index  : int   1-based, по порядку входного списка
    sentiment      : float -1..1
    impact_strength: "low" | "moderate" | "high"
    relevance      : "mention" | "related" | "primary"
    surprise       : "none" | "minor" | "significant" | "major"
    time_horizon   : "intraday" | "1-3d" | "3-7d" | "long"
    confidence     : float 0..1

Запуск: ``python -m pipeline.news_signal_prompt`` или ``python pipeline/news_signal_prompt.py``.
"""

from __future__ import annotations

import json
import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.news_signal_prompt", run_name="__main__")
    raise SystemExit(0)

from domain import NewsArticle

SYSTEM_PROMPT = (
    "You are a financial news analyst for stock prediction.\n"
    "For each article, estimate the expected effect on the target ticker.\n"
    "\n"
    "Your output should help determine the likely direction, strength, and duration "
    "of the target ticker's price move.\n"
    "Be conservative when relevance is weak.\n"
    "Return only valid JSON matching the schema — no markdown, no extra keys."
)

_USER_PREFIX = (
    "Analyze each article independently for its likely effect on the target ticker.\n"
    "Analyze in context of short-term price move (over next 1-3 days).\n"
    "Return exactly one signal per article, in the same order as provided.\n"
    "\n"
    'Reply with a JSON object {"items": [...]} where each element has:\n'
    '  article_index (int, 1-based), sentiment (float -1..1),\n'
    '  impact_strength ("low"|"moderate"|"high"), relevance ("mention"|"related"|"primary"),\n'
    '  surprise ("none"|"minor"|"significant"|"major"),\n'
    '  time_horizon ("intraday"|"1-3d"|"3-7d"|"long"), confidence (float 0..1).\n'
    "\n"
    "Input:\n"
)

PROMPT_VERSION = "v1"


def _article_to_dict(idx: int, a: NewsArticle) -> dict:
    return {
        "article_index": idx,
        "title": a.title.strip(),
        "summary": a.summary.strip() if a.summary else None,
        "timestamp": a.timestamp.isoformat(),
        "source": a.publisher or a.provider_id,
    }


def build_signal_messages(
    articles: Sequence[NewsArticle],
    ticker: str,
    *,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """
    Список из двух сообщений (system + user) для ``chat_completion_text``.

    ``articles`` — уже отобранный батч (индексы 1..n);
    ``ticker``   — строка тикера, например ``"NVDA"``.
    """
    if not articles:
        raise ValueError("articles must not be empty")
    ts = (now or datetime.now(timezone.utc)).isoformat()
    payload = {
        "target_ticker": ticker,
        "current_time": ts,
        "articles": [_article_to_dict(i + 1, a) for i, a in enumerate(articles)],
    }
    user_content = _USER_PREFIX + json.dumps(payload, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


if __name__ == "__main__":
    from datetime import timezone

    from domain import Ticker

    sample = NewsArticle(
        ticker=Ticker.NVDA,
        title="NVIDIA announces record quarterly revenue",
        timestamp=datetime(2026, 4, 6, 9, 0, 0, tzinfo=timezone.utc),
        summary="NVIDIA reports Q1 revenue of $44 billion, beating estimates.",
        link=None,
        publisher="Reuters",
    )
    msgs = build_signal_messages([sample], "NVDA")
    print("=== system ===")
    print(msgs[0]["content"])
    print("\n=== user (first 600 chars) ===")
    print(msgs[1]["content"][:600])
