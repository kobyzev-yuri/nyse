#!/usr/bin/env python
"""
Калибровка порогов гейта (G): реальные новости Yahoo → pipeline 0–4 → LLMMode.

Запуск из корня nyse:
    conda run -n py11 python scripts/calibrate_gate.py
    conda run -n py11 python scripts/calibrate_gate.py --tickers NVDA MU MSFT --days 7 --t1 0.20

Вывод: таблица с окнами, key-метриками и решением гейта; итоговые счётчики skip/lite/full.
Скопируй результат в docs/calibration.md (§3 Журнал прогонов).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config_loader
from domain import Ticker

config_loader.load_config_env()


def _tickers_from_args(names: list[str]) -> list[Ticker]:
    out = []
    for n in names:
        try:
            out.append(Ticker(n))
        except ValueError:
            try:
                out.append(Ticker[n])
            except KeyError:
                print(f"[warn] Неизвестный тикер: {n!r} — пропущен")
    return out or [Ticker.NVDA, Ticker.MU, Ticker.MSFT]


def run(
    tickers: list[Ticker],
    lookback_days: int,
    t1: float,
    t2: float,
    max_n: int,
    half_life_hours: float,
) -> None:
    from pipeline import (
        GateContext,
        LLMMode,
        ThresholdConfig,
        classify_channel,
        decide_llm_mode,
        draft_impulse,
        enrich_cheap_sentiment,
        single_scalar_draft_bias,
        ScoredArticle,
    )
    from sources.news import Source

    cfg = ThresholdConfig(
        t1_abs_draft_bias=t1,
        t2_regime_confidence=t2,
        max_articles_full_batch=max_n,
    )
    now = datetime.now(timezone.utc)

    rows: list[dict] = []

    for ticker in tickers:
        print(f"\n=== {ticker.value} (последние {lookback_days}д) ===")
        try:
            articles = Source(
                max_per_ticker=50,
                lookback_hours=int(lookback_days * 24),
            ).get_articles([ticker])
        except Exception as e:
            print(f"  [error] Yahoo: {e}")
            continue

        if not articles:
            print("  нет статей")
            continue

        # уровень 2: cheap_sentiment через VADER / HuggingFace
        try:
            articles = enrich_cheap_sentiment(articles)
        except Exception as e:
            print(f"  [warn] sentiment enrich: {e}")

        scored = []
        for a in articles:
            ch, conf = classify_channel(a.title, a.summary)
            cs = a.cheap_sentiment or 0.0
            scored.append(
                ScoredArticle(
                    published_at=a.timestamp,
                    cheap_sentiment=cs,
                    channel=ch,
                )
            )

        d = draft_impulse(scored, now=now, half_life_hours=half_life_hours)
        bias = single_scalar_draft_bias(d)

        regime_present = d.regime_stress > cfg.regime_stress_min
        ctx = GateContext(
            draft_bias=bias,
            regime_present=regime_present,
            regime_rule_confidence=0.85 if regime_present else 0.0,
            calendar_high_soon=False,
            article_count=len(articles),
        )
        mode = decide_llm_mode(cfg, ctx)

        # канал-распределение статей
        n_inc = sum(1 for s in scored if s.channel.value == "incremental")
        n_reg = sum(1 for s in scored if s.channel.value == "regime")
        n_pol = sum(1 for s in scored if s.channel.value == "policy_rates")

        print(
            f"  статей: {len(articles):3d}  "
            f"INC={n_inc} REG={n_reg} POL={n_pol}  "
            f"bias={bias:+.3f}  regime_stress={d.regime_stress:.3f}  "
            f"→ {mode.value.upper()}"
        )

        # несколько заголовков для ориентации
        for a in articles[:3]:
            ch, _ = classify_channel(a.title, a.summary)
            print(f"    [{ch.value[:3].upper()}] {a.title[:90]}")

        rows.append(
            {
                "ticker": ticker.value,
                "n": len(articles),
                "inc": n_inc,
                "reg": n_reg,
                "pol": n_pol,
                "bias": round(bias, 3),
                "regime_stress": round(d.regime_stress, 3),
                "mode": mode.value,
            }
        )

    # --- итог ---
    print("\n" + "=" * 60)
    print(f"Конфиг: T1={t1}  T2={t2}  N={max_n}  half_life={half_life_hours}h")
    print(
        f"Итого: "
        f"FULL={sum(1 for r in rows if r['mode']=='full')}  "
        f"LITE={sum(1 for r in rows if r['mode']=='lite')}  "
        f"SKIP={sum(1 for r in rows if r['mode']=='skip')}"
    )
    print("=" * 60)
    print(
        "\n>>> Запиши в docs/calibration.md (§3) — метрики и свою разметку "
        "(skip/full — ожидалось?)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Калибровка гейта nyse pipeline")
    parser.add_argument(
        "--tickers",
        nargs="+",
        default=["NVDA", "MU", "MSFT", "META"],
        help="Тикеры (default: NVDA MU MSFT META)",
    )
    parser.add_argument("--days", type=int, default=3, help="Окно в днях (default: 3)")
    parser.add_argument(
        "--profile",
        choices=("game5m", "context", "default"),
        default="default",
        help="Готовый профиль порогов: game5m / context / default (из ThresholdConfig)",
    )
    parser.add_argument("--t1", type=float, default=None, help="Порог T1 (default: из профиля)")
    parser.add_argument("--t2", type=float, default=None, help="Порог T2 (default: из ThresholdConfig)")
    parser.add_argument(
        "--max-n", type=int, default=None, help="max_articles_full_batch N (default: из ThresholdConfig)"
    )
    parser.add_argument(
        "--half-life",
        type=float,
        default=12.0,
        help="Полупериод затухания, часов (default: 12)",
    )
    args = parser.parse_args()

    from pipeline.types import PROFILE_CONTEXT, PROFILE_GAME5M, ThresholdConfig as _TC
    _profile_map = {"game5m": PROFILE_GAME5M, "context": PROFILE_CONTEXT, "default": _TC()}
    _base = _profile_map[args.profile]
    run(
        tickers=_tickers_from_args(args.tickers),
        lookback_days=args.days,
        t1=args.t1 if args.t1 is not None else _base.t1_abs_draft_bias,
        t2=args.t2 if args.t2 is not None else _base.t2_regime_confidence,
        max_n=args.max_n if args.max_n is not None else _base.max_articles_full_batch,
        half_life_hours=args.half_life,
    )


if __name__ == "__main__":
    main()
