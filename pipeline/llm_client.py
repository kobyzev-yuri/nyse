"""
Этап F: OpenAI-совместимый POST /chat/completions (HTTP через requests).

В юнит-тестах сеть не нужна: передайте ``post=...`` (mock) или замокайте ``requests.post``.

Импорт: ``from pipeline.llm_client import chat_completion_text`` (из корня nyse).
Запуск файла напрямую: ``python -m pipeline.llm_client``.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path
from typing import Any, Callable, Optional

import requests

if __name__ == "__main__" and __package__ is None:
    _root = Path(__file__).resolve().parent.parent
    if str(_root) not in sys.path:
        sys.path.insert(0, str(_root))
    runpy.run_module("pipeline.llm_client", run_name="__main__")
    raise SystemExit(0)


def chat_completion_text(
    messages: list[dict[str, str]],
    *,
    settings: Any = None,
    temperature: Optional[float] = None,
    timeout_sec: Optional[int] = None,
    post: Callable[..., Any] = requests.post,
) -> str:
    """
    Возвращает ``choices[0].message.content`` из JSON-ответа API.

    ``settings``: экземпляр ``OpenAISettings`` или ``None`` (тогда ``get_openai_settings()``).
    """
    import config_loader

    s = settings if settings is not None else config_loader.get_openai_settings()
    if s is None:
        raise RuntimeError("OpenAI settings missing (OPENAI_API_KEY)")
    url = f"{s.base_url.rstrip('/')}/chat/completions"
    temp = float(s.temperature) if temperature is None else float(temperature)
    to = int(s.timeout_sec) if timeout_sec is None else int(timeout_sec)
    body: dict[str, Any] = {
        "model": s.model,
        "messages": messages,
        "temperature": temp,
    }
    headers = {
        "Authorization": f"Bearer {s.api_key}",
        "Content-Type": "application/json",
    }
    r = post(url, headers=headers, json=body, timeout=to)
    if r.status_code != 200:
        raise RuntimeError(f"chat completion HTTP {r.status_code}: {r.text[:500]}")
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("chat completion: empty choices")
    msg = choices[0].get("message") or {}
    content = msg.get("content")
    if content is None:
        raise RuntimeError("chat completion: missing content")
    return content if isinstance(content, str) else str(content)


if __name__ == "__main__":
    print("chat_completion_text — импортируйте из pipeline или вызывайте с ключом в окружении.")
