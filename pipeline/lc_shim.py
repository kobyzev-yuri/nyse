"""
Сообщения для ``invoke`` — ``langchain_core.messages`` или лёгкий shim (тесты без langchain).

Реальный прод: установлены ``langchain_core`` / ``langchain_openai``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

try:
    from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore[attr-defined]
except ImportError:

    def SystemMessage(*, content: str, **kwargs: Any) -> Any:
        return SimpleNamespace(content=content)

    def HumanMessage(*, content: str, **kwargs: Any) -> Any:
        return SimpleNamespace(content=content)
