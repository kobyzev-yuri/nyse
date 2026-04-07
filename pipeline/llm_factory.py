"""
Фабрика LangChain BaseChatModel.

Единственное место, где создаётся ChatOpenAI — по аналогии с
pystockinvest/cmd/telegram_bot.py::

    llm = ChatOpenAI(model=..., temperature=0, api_key=..., base_url=...)

Используется в news_signal_runner.py (with_structured_output) и
llm_digest.py (plain invoke).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from langchain_core.language_models.chat_models import BaseChatModel

if TYPE_CHECKING:
    from config_loader import OpenAISettings


def get_chat_model(settings: Optional["OpenAISettings"] = None) -> BaseChatModel:
    """
    Возвращает ``ChatOpenAI`` из настроек конфига.

    Parameters
    ----------
    settings : ``OpenAISettings`` или ``None`` → ``config_loader.get_openai_settings()``.

    Raises
    ------
    RuntimeError
        Если ключи API не заданы.
    """
    import config_loader
    from langchain_openai import ChatOpenAI
    from pydantic import SecretStr

    s = settings if settings is not None else config_loader.get_openai_settings()
    if s is None:
        raise RuntimeError("OpenAI settings missing — задайте OPENAI_API_KEY в config.env")

    return ChatOpenAI(
        model=s.model,
        temperature=float(s.temperature),
        api_key=SecretStr(s.api_key),
        base_url=s.base_url.rstrip("/"),
        timeout=int(s.timeout_sec),
    )
