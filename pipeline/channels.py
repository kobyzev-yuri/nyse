"""Уровень 1: грубая классификация NewsImpactChannel по тексту (без LLM)."""

from __future__ import annotations

import re
from typing import Optional

from .types import NewsImpactChannel

# Минимальные словари; расширяются по результатам тестов и калибровки.
_REGIME_PATTERNS = [
    re.compile(
        r"\b(?:war|sanction|sanctions|embargo|invasion|military|nato|missile)\b",
        re.I,
    ),
    re.compile(r"\b(?:геополит|санкци|война|конфликт)\b", re.I),
]
_POLICY_PATTERNS = [
    re.compile(
        r"\b(?:fed|fomc|federal reserve|ecb|boe|rate hike|rate cut|interest rate|bps|qe|qt)\b",
        re.I,
    ),
    re.compile(r"\b(?:ставк|центральн\w+ банк|базовая ставка)\b", re.I),
]


def classify_channel(
    title: str,
    summary: Optional[str] = None,
) -> tuple[NewsImpactChannel, float]:
    """
    Возвращает канал и грубую уверенность правила 0..1.
    Приоритет: REGIME > POLICY_RATES > INCREMENTAL.
    """
    text = f"{title} {summary or ''}".strip()
    if not text:
        return NewsImpactChannel.INCREMENTAL, 1.0

    for rx in _REGIME_PATTERNS:
        if rx.search(text):
            return NewsImpactChannel.REGIME, 0.85

    for rx in _POLICY_PATTERNS:
        if rx.search(text):
            return NewsImpactChannel.POLICY_RATES, 0.8

    return NewsImpactChannel.INCREMENTAL, 1.0
