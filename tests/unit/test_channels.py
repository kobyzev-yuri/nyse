"""Тесты классификации NewsImpactChannel."""

from __future__ import annotations

import pytest

from pipeline import NewsImpactChannel, classify_channel, story_type_ru


@pytest.mark.parametrize(
    "title,summary,expected",
    [
        ("Fed signals pause in rate hikes", None, NewsImpactChannel.POLICY_RATES),
        ("Oil jumps on new sanctions package", None, NewsImpactChannel.REGIME),
        (
            "Persian Gulf Ceasefire Looses Bulls on Wall Street Pre-Bell",
            None,
            NewsImpactChannel.REGIME,
        ),
        ("US and Iran agree to two-week ceasefire", None, NewsImpactChannel.REGIME),
        ("Brent crude jumps 4% on supply disruption fears", None, NewsImpactChannel.REGIME),
        ("WTI and Brent slide as traders take profits", None, NewsImpactChannel.REGIME),
        ("NVDA beats earnings estimates", None, NewsImpactChannel.INCREMENTAL),
    ],
)
def test_classify_channel_keywords(title, summary, expected):
    ch, conf = classify_channel(title, summary)
    assert ch == expected
    assert 0.0 < conf <= 1.0


def test_story_type_ru_labels():
    assert story_type_ru(NewsImpactChannel.INCREMENTAL) == "эмитент·отрасль"
    assert story_type_ru(NewsImpactChannel.REGIME) == "гео·энерго·режим"
    assert story_type_ru(NewsImpactChannel.POLICY_RATES) == "ЦБ·ставки (монетарная)"
