"""
Уровень 5 (шаг 6): промпт для structured LLM signal.

Тексты **SYSTEM_PROMPT** и **USER_PROMPT_TEMPLATE** совпадают с
``pystockinvest/agent/news/signal.py`` (байт-в-байт для system; user — тот же шаблон + JSON payload).

Схема ответа задаётся ``with_structured_output(NewsSignalLLMResponse)`` в
``news_signal_runner.py``, а не перечислением полей в промпте.

Payload JSON — как ``NewsSignalAgentInput`` в pystockinvest (target_ticker, current_time, articles[]).

Запуск: ``python -m pipeline.news_signal_prompt`` или ``python pipeline/news_signal_prompt.py``.
"""

from __future__ import annotations

import runpy
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.news_signal_prompt", run_name="__main__")
    raise SystemExit(0)

from domain import NewsArticle

from .news_dto import NewsArticleInput, NewsSignalAgentInput

# Дословно из pystockinvest/agent/news/signal.py
SYSTEM_PROMPT = """
You are a financial news analyst for stock prediction.
For each article, estimate the expected effect on the target ticker.

Your output should help determine the likely direction, strength, and duration of the target ticker's price move.
Be conservative when relevance is weak.
Return only the structured output.
""".strip()


USER_PROMPT_TEMPLATE = """
Analyze each article independently for its likely effect on the target ticker.
Analyze in context of short-term price move (over next 1-3 days).
Return exactly one signal per article, in the same order as provided.

Input:
{payload}
""".strip()

# Инкремент при любом изменении SYSTEM/USER выше — сбрасывает LLM-кэш
PROMPT_VERSION = "v3"


def build_signal_messages(
    articles: Sequence[NewsArticle],
    ticker: str,
    *,
    now: datetime | None = None,
) -> list[dict[str, str]]:
    """
    Список из двух сообщений (system + user) для вызова LLM (LangChain ``BaseChatModel``).

    ``articles`` — уже отобранный батч (индексы 1..n);
    ``ticker``   — строка тикера, например ``"NVDA"``.
    """
    if not articles:
        raise ValueError("articles must not be empty")
    ts = now or datetime.now(timezone.utc)
    batch_input = NewsSignalAgentInput(
        target_ticker=ticker,
        current_time=ts,
        articles=[
            NewsArticleInput(
                article_index=i + 1,
                title=a.title.strip(),
                summary=a.summary.strip() if a.summary else None,
                timestamp=a.timestamp,
                source=a.publisher or a.provider_id,
            )
            for i, a in enumerate(articles)
        ],
    )
    user_content = USER_PROMPT_TEMPLATE.format(
        payload=batch_input.model_dump_json(indent=2),
    )
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
