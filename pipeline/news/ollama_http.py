"""Минимальный POST /api/chat к Ollama (stdlib, без langchain)."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


def strip_json_fence(raw: str) -> str:
    s = raw.strip()
    if not s.startswith("```"):
        return s
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def ollama_chat(
    model: str,
    messages: list[dict[str, str]],
    *,
    base_url: str = "http://127.0.0.1:11434",
    timeout_sec: float = 180.0,
    json_mode: bool = True,
) -> str:
    url = base_url.rstrip("/") + "/api/chat"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if json_mode:
        body["format"] = "json"

    ka = (os.environ.get("OLLAMA_KEEP_ALIVE") or "").strip()
    if ka:
        if ka.lstrip("-").isdigit():
            body["keep_alive"] = int(ka)
        else:
            body["keep_alive"] = ka

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Ollama HTTP {e.code}: {e.read().decode('utf-8', errors='replace')}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama connection failed: {e}") from e

    msg = payload.get("message") or {}
    content = msg.get("content")
    if not isinstance(content, str):
        raise RuntimeError(f"Unexpected Ollama response: {payload!r}")
    return content
