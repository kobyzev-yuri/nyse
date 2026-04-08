"""Уровень 1: грубая классификация NewsImpactChannel по тексту (без LLM).

Терминология (чтобы не путать с календарём и с «политикой» в бытовом смысле):

- **INCREMENTAL (INC)** — идосинкразия: эмитент, отрасль, earnings, компания. Не гео и не ЦБ.
- **REGIME (REG)** — геополитика и «режим» рынка: войны, санкции, Ближний Восток, энергия/нефть
  как макро-риск. Это **не** экономический календарь (CPI, заседания — см. ниже).
- **POLICY_RATES (POL)** — **монетарная** политика: Fed, ECB, BoE, ставки, QE/QT.
  Заголовки про выборы/Конгресс без Fed часто попадают в INC, если нет ключевых слов POL.

Отдельно от каналов: **макро-календарь** (блок ③b, ``calendar_high_soon``) — запланированные
релизы (CPI, NFP, …) из ecalendar; к REG-статьям **не относится**.

Приоритет правил: REG > POL > INC (см. ``classify_channel``).
"""

from __future__ import annotations

import re
from typing import Optional

from .types import NewsImpactChannel

# Минимальные словари; расширяются по результатам тестов и калибровки.
# REGIME — не только «война», но и перемирие/геозона: иначе заголовки вида
# «Persian Gulf Ceasefire…» остаются в INCREMENTAL и regime_stress=0.
# Сырьевой/энерго-макро (Brent, WTI, OPEC): частый канал «режима рынка» без слова «war»;
# иначе заголовки в духе «Oil prices plunge on ceasefire» не ловятся, если нет совпадения
# по Ирану/нефти в других паттернах (редкий edge).
_REGIME_PATTERNS = [
    re.compile(
        r"\b(?:war|sanction|sanctions|embargo|invasion|military|nato|missile)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:ceasefire|truce|armistice|geopolitical|terror|hostilities|"
        r"iran|israeli?|ukraine|gaza|taiwan|north korea)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:persian gulf|middle east|strait of hormuz|red sea)\b",
        re.I,
    ),
    # Энергия / нефть как макро-риск (не путать с POLICY: там Fed/ECB/ставки).
    re.compile(
        r"\b(?:brent(?:\s+crude)?|wti|west texas intermediate|crude\s+oil|"
        r"oil\s+prices?|opec|energy\s+prices?)\b",
        re.I,
    ),
    re.compile(r"\b(?:геополит|санкци|война|конфликт|перемири)\b", re.I),
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


def story_type_ru(ch: NewsImpactChannel) -> str:
    """
    Краткая подпись для колонки «Сюжет» в отчётах.

    «Политика» в смысле выборов/конгресса сюда **не выводится отдельно** — без слов Fed/ставок
    такие статьи обычно INC. POL — только монетарная политика (ставки, ЦБ).
    REG — не путать с календарём макро-релизов (это другой блок пайплайна).
    """
    if ch == NewsImpactChannel.REGIME:
        return "гео·энерго·режим"
    if ch == NewsImpactChannel.POLICY_RATES:
        return "ЦБ·ставки (монетарная)"
    return "эмитент·отрасль"
