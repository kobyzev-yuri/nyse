"""Общие хелперы для новостных адаптеров."""

from __future__ import annotations

from domain import Ticker


def symbol_for_provider(t: Ticker) -> str:
    """Символ для NewsAPI/Marketaux (без префикса ^)."""
    v = t.value
    return v[1:] if v.startswith("^") else v
