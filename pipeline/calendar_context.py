"""
Этап C: календарь макро → флаг ``calendar_high_soon`` для ``GateContext``.

Используются только события с ``CalendarEventImportance.HIGH``.
Окно: время события в интервале
``[now - after_minutes, now + before_minutes]`` (в минутах относительно ``now``), UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Sequence

from .types import GateContext

if TYPE_CHECKING:
    from domain import CalendarEvent


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def calendar_high_soon(
    events: Sequence["CalendarEvent"],
    *,
    now: datetime | None = None,
    minutes_before: int | None = None,
    minutes_after: int | None = None,
) -> bool:
    """
    ``True``, если есть хотя бы одно HIGH-событие с временем в окне
    «скоро / только что»: от ``-minutes_after`` до ``+minutes_before`` минут от ``now``.

    ``minutes_before`` / ``minutes_after``: по умолчанию из ``config_loader`` (env
    ``NYSE_CALENDAR_HIGH_BEFORE_MIN``, ``NYSE_CALENDAR_HIGH_AFTER_MIN``).
    """
    import config_loader

    from domain import CalendarEventImportance

    if not events:
        return False

    now = now or datetime.now(timezone.utc)
    now = _utc(now)
    mb = (
        minutes_before
        if minutes_before is not None
        else config_loader.calendar_high_before_minutes()
    )
    ma = (
        minutes_after
        if minutes_after is not None
        else config_loader.calendar_high_after_minutes()
    )

    for e in events:
        if e.importance != CalendarEventImportance.HIGH:
            continue
        t = _utc(e.time)
        delta_min = (t - now).total_seconds() / 60.0
        if -ma <= delta_min <= mb:
            return True
    return False


def build_gate_context(
    *,
    draft_bias: float,
    regime_present: bool,
    regime_rule_confidence: float,
    calendar_events: Sequence["CalendarEvent"],
    article_count: int,
    now: datetime | None = None,
    minutes_before: int | None = None,
    minutes_after: int | None = None,
) -> GateContext:
    """Собирает ``GateContext`` с вычисленным ``calendar_high_soon``."""
    ch = calendar_high_soon(
        calendar_events,
        now=now,
        minutes_before=minutes_before,
        minutes_after=minutes_after,
    )
    return GateContext(
        draft_bias=draft_bias,
        regime_present=regime_present,
        regime_rule_confidence=regime_rule_confidence,
        calendar_high_soon=ch,
        article_count=article_count,
    )
