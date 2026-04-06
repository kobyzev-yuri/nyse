"""Промпт build_signal_messages (уровень 5, шаг 6)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from domain import NewsArticle, Ticker
from pipeline.news_signal_prompt import PROMPT_VERSION, build_signal_messages


def _art(title: str, summary: str | None = None, publisher: str | None = None) -> NewsArticle:
    return NewsArticle(
        ticker=Ticker.NVDA,
        title=title,
        timestamp=datetime(2026, 4, 6, 10, 0, 0, tzinfo=timezone.utc),
        summary=summary,
        link=None,
        publisher=publisher,
    )


def test_returns_two_messages():
    msgs = build_signal_messages([_art("headline")], "NVDA")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"


def test_system_prompt_contains_key_instructions():
    msgs = build_signal_messages([_art("h")], "NVDA")
    sys_text = msgs[0]["content"]
    assert "financial news analyst" in sys_text
    assert "conservative" in sys_text
    assert "JSON" in sys_text or "json" in sys_text.lower()


def test_user_payload_is_valid_json_containing_articles():
    now = datetime(2026, 4, 6, 12, 0, 0, tzinfo=timezone.utc)
    msgs = build_signal_messages([_art("NVDA beats earnings")], "NVDA", now=now)
    user = msgs[1]["content"]
    # payload блок начинается после "Input:\n"
    idx = user.index("Input:\n") + len("Input:\n")
    payload = json.loads(user[idx:])
    assert payload["target_ticker"] == "NVDA"
    assert len(payload["articles"]) == 1
    assert payload["articles"][0]["article_index"] == 1
    assert payload["articles"][0]["title"] == "NVDA beats earnings"


def test_article_indexes_are_sequential():
    arts = [_art(f"headline {i}") for i in range(3)]
    msgs = build_signal_messages(arts, "NVDA")
    user = msgs[1]["content"]
    idx = user.index("Input:\n") + len("Input:\n")
    payload = json.loads(user[idx:])
    indexes = [a["article_index"] for a in payload["articles"]]
    assert indexes == [1, 2, 3]


def test_ticker_in_payload():
    msgs = build_signal_messages([_art("h")], "MU")
    user = msgs[1]["content"]
    idx = user.index("Input:\n") + len("Input:\n")
    payload = json.loads(user[idx:])
    assert payload["target_ticker"] == "MU"


def test_summary_included_when_present():
    msgs = build_signal_messages([_art("h", summary="short desc")], "NVDA")
    assert "short desc" in msgs[1]["content"]


def test_summary_none_when_absent():
    msgs = build_signal_messages([_art("h", summary=None)], "NVDA")
    user = msgs[1]["content"]
    idx = user.index("Input:\n") + len("Input:\n")
    payload = json.loads(user[idx:])
    assert payload["articles"][0]["summary"] is None


def test_publisher_goes_to_source_field():
    msgs = build_signal_messages([_art("h", publisher="Reuters")], "NVDA")
    user = msgs[1]["content"]
    idx = user.index("Input:\n") + len("Input:\n")
    payload = json.loads(user[idx:])
    assert payload["articles"][0]["source"] == "Reuters"


def test_empty_articles_raises():
    with pytest.raises(ValueError):
        build_signal_messages([], "NVDA")


def test_prompt_version_is_string():
    assert isinstance(PROMPT_VERSION, str) and len(PROMPT_VERSION) >= 1
