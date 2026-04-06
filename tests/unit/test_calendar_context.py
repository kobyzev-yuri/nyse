"""
Юнит-тесты: этап C — ``calendar_high_soon`` и ``build_gate_context`` (без сети).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from domain import CalendarEvent, CalendarEventImportance, Currency


def _evt(
    *,
    at: datetime,
    importance: CalendarEventImportance = CalendarEventImportance.HIGH,
) -> CalendarEvent:
    return CalendarEvent(
        name="CPI",
        category="macro",
        time=at,
        country="US",
        currency=Currency.USD,
        importance=importance,
        actual=None,
        forecast=None,
        previous=None,
    )


def test_calendar_high_soon_true_when_event_in_30_minutes():
    """HIGH через 30 мин попадает в окно по умолчанию (до +120 мин)."""
    from pipeline.calendar_context import calendar_high_soon

    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ev = _evt(at=now + timedelta(minutes=30))
    assert calendar_high_soon([ev], now=now, minutes_before=120, minutes_after=60) is True


def test_calendar_high_soon_false_when_event_too_far():
    """HIGH через 3 ч не попадает при окне +120 мин вперёд."""
    from pipeline.calendar_context import calendar_high_soon

    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ev = _evt(at=now + timedelta(hours=3))
    assert calendar_high_soon([ev], now=now, minutes_before=120, minutes_after=60) is False


def test_calendar_high_soon_true_shortly_after_release():
    """Событие 45 мин назад — ещё в окне ``after`` (60 мин по умолчанию в тесте)."""
    from pipeline.calendar_context import calendar_high_soon

    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ev = _evt(at=now - timedelta(minutes=45))
    assert calendar_high_soon([ev], now=now, minutes_before=120, minutes_after=60) is True


def test_calendar_high_soon_ignores_moderate():
    """MODERATE не поднимает флаг."""
    from pipeline.calendar_context import calendar_high_soon

    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ev = _evt(at=now + timedelta(minutes=10), importance=CalendarEventImportance.MODERATE)
    assert calendar_high_soon([ev], now=now, minutes_before=120, minutes_after=60) is False


def test_calendar_high_soon_empty_events():
    from pipeline.calendar_context import calendar_high_soon

    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert calendar_high_soon([], now=now) is False


def test_build_gate_context_sets_calendar_flag():
    """``build_gate_context`` прокидывает вычисленный флаг в ``GateContext``."""
    from pipeline import build_gate_context

    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ev = _evt(at=now + timedelta(minutes=15))
    ctx = build_gate_context(
        draft_bias=0.1,
        regime_present=False,
        regime_rule_confidence=0.0,
        calendar_events=[ev],
        article_count=5,
        now=now,
        minutes_before=120,
        minutes_after=60,
    )
    assert ctx.calendar_high_soon is True
    assert ctx.article_count == 5


def test_build_gate_context_calendar_false_triggers_skip_path():
    """С календарём «тихо» гейт не форсирует FULL (проверка связки с ``decide_llm_mode``)."""
    from pipeline import ThresholdConfig, build_gate_context, decide_llm_mode

    now = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    ev = _evt(at=now + timedelta(days=7))
    ctx = build_gate_context(
        draft_bias=0.05,
        regime_present=False,
        regime_rule_confidence=0.0,
        calendar_events=[ev],
        article_count=3,
        now=now,
        minutes_before=120,
        minutes_after=60,
    )
    assert ctx.calendar_high_soon is False
    assert decide_llm_mode(ThresholdConfig(), ctx).value == "skip"


if __name__ == "__main__":
    raise SystemExit(
        pytest.main([__file__, "-v", "--tb=short", "-rA"])
    )
