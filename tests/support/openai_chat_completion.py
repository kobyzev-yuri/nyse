"""
Низкоуровневый HTTP-клиент к OpenAI-совместимому ``/chat/completions``.

Используется в юнит-тестах с моком ``requests.post``. Продакшен-пайплайн и бот
работают через ``pipeline.llm_factory.get_chat_model()`` (LangChain).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import requests


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
