"""Уровень 3: черновой импульс без LLM."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence, Tuple

from .types import DraftImpulse, NewsImpactChannel


@dataclass(frozen=True)
class ScoredArticle:
    """Одна статья с дешёвым сентиментом и каналом."""

    published_at: datetime
    cheap_sentiment: float
    channel: NewsImpactChannel


def _age_hours(now: datetime, t: datetime) -> float:
    return max(0.0, (now - t).total_seconds() / 3600.0)


def draft_impulse(
    articles: Sequence[ScoredArticle],
    *,
    now: datetime | None = None,
    half_life_hours: float = 12.0,
) -> DraftImpulse:
    """
    Взвешенные средние cheap_sentiment по каналам с экспоненциальным затуханием по времени.
    Вес: exp(-ln(2) * age / half_life).
    """
    now = now or datetime.now(timezone.utc)
    if not articles:
        return DraftImpulse()

    lam = math.log(2) / max(half_life_hours, 1e-6)

    def weighted_mean(
        pairs: Iterable[Tuple[float, float]],
    ) -> float:
        num = 0.0
        den = 0.0
        for w, x in pairs:
            num += w * x
            den += w
        return num / den if den > 0 else 0.0

    inc: List[Tuple[float, float]] = []
    reg: List[Tuple[float, float]] = []
    pol: List[Tuple[float, float]] = []
    wsum_inc = wsum_reg = wsum_pol = 0.0
    max_abs_reg = max_abs_pol = 0.0

    for a in articles:
        age = _age_hours(now, a.published_at)
        w = math.exp(-lam * age)
        pair = (w, a.cheap_sentiment)
        if a.channel == NewsImpactChannel.INCREMENTAL:
            inc.append(pair)
            wsum_inc += w
        elif a.channel == NewsImpactChannel.REGIME:
            reg.append(pair)
            wsum_reg += w
            max_abs_reg = max(max_abs_reg, abs(a.cheap_sentiment))
        else:
            pol.append(pair)
            wsum_pol += w
            max_abs_pol = max(max_abs_pol, abs(a.cheap_sentiment))

    return DraftImpulse(
        draft_bias_incremental=weighted_mean(inc),
        regime_stress=weighted_mean([(w, abs(x)) for w, x in reg]) if reg else 0.0,
        policy_stress=weighted_mean([(w, abs(x)) for w, x in pol]) if pol else 0.0,
        articles_incremental=len(inc),
        articles_regime=len(reg),
        articles_policy=len(pol),
        weight_sum_incremental=wsum_inc,
        weight_sum_regime=wsum_reg,
        weight_sum_policy=wsum_pol,
        max_abs_regime=max_abs_reg,
        max_abs_policy=max_abs_pol,
    )


def scored_from_news_articles(articles: Sequence["NewsArticle"]) -> List[ScoredArticle]:
    """
    Уровень 3: ``NewsArticle`` с уже заполненным ``cheap_sentiment`` (после этапа B)
    + классификация канала → ``ScoredArticle`` для ``draft_impulse``.
    Если ``cheap_sentiment`` ещё None — подставляется 0.0.
    """
    from domain import NewsArticle

    from .channels import classify_channel

    out: List[ScoredArticle] = []
    for a in articles:
        if not isinstance(a, NewsArticle):
            raise TypeError("expected NewsArticle")
        ch, _ = classify_channel(a.title, a.summary)
        cs = a.cheap_sentiment if a.cheap_sentiment is not None else 0.0
        out.append(
            ScoredArticle(
                published_at=a.timestamp,
                cheap_sentiment=cs,
                channel=ch,
            )
        )
    return out


def single_scalar_draft_bias(d: DraftImpulse) -> float:
    """Число для гейтинга: основной вклад incremental + мягкий штраф за stress."""
    return (
        d.draft_bias_incremental
        - 0.15 * d.regime_stress
        - 0.1 * d.policy_stress
    )
