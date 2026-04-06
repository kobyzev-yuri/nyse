"""Тесты классификации NewsImpactChannel."""

from __future__ import annotations

import pytest

from pipeline import NewsImpactChannel, classify_channel


@pytest.mark.parametrize(
    "title,summary,expected",
    [
        ("Fed signals pause in rate hikes", None, NewsImpactChannel.POLICY_RATES),
        ("Oil jumps on new sanctions package", None, NewsImpactChannel.REGIME),
        ("NVDA beats earnings estimates", None, NewsImpactChannel.INCREMENTAL),
    ],
)
def test_classify_channel_keywords(title, summary, expected):
    ch, conf = classify_channel(title, summary)
    assert ch == expected
    assert 0.0 < conf <= 1.0
