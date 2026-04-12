"""
CLI: выделенный новостной пайплайн (как команда /news в Telegram-боте),
но с выходом в **JSON** (никакого HTML / Telegram-разметки).

Пример:
    conda run -n py11 python scripts/run_news_pipeline.py MU --pretty > out.json

Что делает:
  - грузит новости (lookback 48h, cap 10 как в /news)
  - enrich_cheap_sentiment (FinBERT / API / price_pattern)
  - DraftImpulse (INC/REG/POL) + single_scalar_draft_bias
  - Gate (decide_llm_mode)
  - (опционально) structured LLM-агрегат (run_news_signal_pipeline)

Выход:
  - JSON-объект с calendar/geopolitics/articles/draft/gate/(optional) aggregated_llm

Реализация новостей в коде: ``pipeline/news/`` (корень ``pipeline/*.py`` — shim-реэкспорты).
См. также: ``docs/news_pipeline_cli.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class _JsonOnlyStdout:
    """Перенаправляет весь мусор в stderr, оставляя stdout только под JSON."""

    def __init__(self, real_stdout, real_stderr) -> None:
        self._out = real_stdout
        self._err = real_stderr

    def write(self, s: str) -> int:
        # JSON пишет main() напрямую в sys.stdout.write(...) одним куском.
        # Всё остальное (progress bars, предупреждения библиотек) отправляем в stderr.
        return self._err.write(s)

    def flush(self) -> None:
        return self._err.flush()

    def isatty(self) -> bool:
        # FinBERT/transformers/tqdm проверяют sys.stdout.isatty()
        return False

    def fileno(self) -> int:
        return self._out.fileno()

    @property
    def encoding(self) -> str:
        enc = getattr(self._out, "encoding", None)
        return enc if isinstance(enc, str) and enc else "utf-8"


def _add_repo_root_to_syspath() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="run_news_pipeline",
        description="Run NYSE news pipeline (same logic as Telegram /news), JSON to stdout.",
        epilog=(
            "Docs: docs/news_pipeline_cli.md · Code: pipeline/news/ · "
            "Requires config.env in repo root (or env vars) for API keys / calendar."
        ),
    )
    p.add_argument("ticker", help="Ticker, e.g. MU")
    p.add_argument(
        "--lookback-hours",
        type=int,
        default=48,
        help="News lookback window in hours (default: 48, as /news).",
    )
    p.add_argument(
        "--max-per-ticker",
        type=int,
        default=10,
        help="Max news articles per ticker (default: 10, as /news).",
    )
    p.add_argument(
        "--profile",
        choices=["game5m", "context"],
        default="game5m",
        help="Gate thresholds profile (default: game5m).",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable structured LLM even if OPENAI_API_KEY is set.",
    )
    p.add_argument(
        "--ollama-model",
        default="",
        metavar="NAME",
        help=(
            "Use Ollama for structured news signal (e.g. llama3.2:3b) instead of OpenAI. "
            "Requires ollama serve; OLLAMA_HOST optional. Implies LLM path when gate allows."
        ),
    )
    p.add_argument(
        "--ollama-host",
        default="",
        help="Ollama base URL (default: OLLAMA_HOST or http://127.0.0.1:11434).",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    p.add_argument(
        "--json-out",
        default="",
        help="Write JSON to this path (optional). Default: stdout.",
    )
    return p.parse_args(argv)


def _dt_iso(dt: object) -> Optional[str]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


def run(
    ticker_str: str,
    *,
    lookback_hours: int,
    max_per_ticker: int,
    profile: str,
    no_llm: bool,
    ollama_model: str = "",
    ollama_host: str = "",
) -> dict:
    import os

    import config_loader
    from sources.news import Source as NewsSource
    from pipeline.sentiment import enrich_cheap_sentiment
    from pipeline.draft import scored_from_news_articles, draft_impulse, single_scalar_draft_bias
    from pipeline.debug_runner import _gate_reason
    from pipeline import build_gate_context, decide_llm_mode, PROFILE_CONTEXT, PROFILE_GAME5M, run_news_signal_pipeline
    from pipeline.llm_batch_plan import plan_llm_article_batch
    from pipeline.types import LLMMode
    from domain import Ticker
    from pipeline.types import NewsImpactChannel

    config_loader.load_config_env()

    ticker_val = ticker_str.strip().upper()
    if not ticker_val:
        raise ValueError("Ticker is empty")

    cfg = PROFILE_GAME5M if profile == "game5m" else PROFILE_CONTEXT

    ticker = Ticker(ticker_val)
    now = datetime.now(timezone.utc)
    # Экономический календарь (Investing.com JSON), тот же источник, что в боте.
    # Важно: не импортируем bot/nyse_bot.py, чтобы не требовать python-telegram-bot в окружении CLI.
    cal_events: list = []
    calendar_load_error: str | None = None
    try:
        from domain import Currency
        from sources.ecalendar import Source as CalendarSource

        cal_events = list(CalendarSource([Currency.GBP, Currency.JPY, Currency.EUR]).get_calendar())
    except Exception as exc:
        calendar_load_error = f"{type(exc).__name__}: {exc}"

    def _cal_event_dict(e: object) -> dict:
        from domain import CalendarEvent

        if not isinstance(e, CalendarEvent):
            return {"error": "not_a_calendar_event"}
        t = e.time
        if isinstance(t, datetime):
            tu = t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)
            delta_min = (tu - now).total_seconds() / 60.0
        else:
            tu, delta_min = None, None
        cur = getattr(e.currency, "value", str(e.currency))
        return {
            "name": e.name,
            "time_utc": _dt_iso(tu) if tu is not None else None,
            "importance": e.importance.value,
            "currency": cur,
            "country": e.country,
            "category": e.category,
            "delta_minutes_from_now": None if delta_min is None else round(delta_min, 1),
        }

    articles = NewsSource(max_per_ticker=max_per_ticker, lookback_hours=lookback_hours).get_articles([ticker])
    articles = [a for a in articles if a.ticker == ticker]
    if not articles:
        calendar_events_json = [_cal_event_dict(e) for e in cal_events[:100]]
        return {
            "ticker": ticker_val,
            "lookback_hours": lookback_hours,
            "max_per_ticker": max_per_ticker,
            "profile": profile,
            "now_utc": _dt_iso(now),
            "error": "no_articles",
            "llm": {"backend": None, "model": None, "ollama_host": None},
            "calendar": {
                "source": "investing.com (sources.ecalendar, GBP/JPY/EUR)",
                "event_count": len(cal_events),
                "events_preview": calendar_events_json,
                "load_error": calendar_load_error,
            },
            "geopolitics": {
                "regime_articles": [],
                "policy_articles": [],
                "counts": {"regime": 0, "policy_rates": 0},
            },
            "articles": [],
        }

    articles = enrich_cheap_sentiment(articles)

    scored = scored_from_news_articles(articles)
    di = draft_impulse(scored, now=now)
    bias = single_scalar_draft_bias(di)

    regime_present = di.regime_stress > cfg.regime_stress_min
    gate_ctx = build_gate_context(
        draft_bias=bias,
        regime_present=regime_present,
        regime_rule_confidence=0.85 if regime_present else 0.0,
        calendar_events=cal_events,
        article_count=len(articles),
        now=now,
    )
    mode = decide_llm_mode(cfg, gate_ctx)
    gate_reason = _gate_reason(cfg, gate_ctx, mode)

    llm_batch_articles: list = []
    if mode == LLMMode.FULL:
        plan = plan_llm_article_batch(LLMMode.FULL, articles, cfg=cfg)
        llm_batch_articles = [articles[i] for i in plan.indices_for_structured_signal]

    ollama_model_str = (ollama_model or "").strip()
    ollama_host_str = (ollama_host or "").strip().rstrip("/") or (
        (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").strip().rstrip("/")
    )

    oai = None if no_llm else config_loader.get_openai_settings()
    news_signal = None
    llm_backend: str | None = None
    llm_model_id: str | None = None

    if not no_llm and mode in (LLMMode.FULL, LLMMode.LITE):
        if ollama_model_str:
            from pipeline.news.ollama_signal import run_news_signal_pipeline_ollama

            news_signal = run_news_signal_pipeline_ollama(
                articles,
                ticker.value,
                cfg=cfg,
                mode=mode,
                ollama_model=ollama_model_str,
                ollama_host=ollama_host_str,
            )
            llm_backend = "ollama"
            llm_model_id = ollama_model_str
        elif oai is not None:
            news_signal = run_news_signal_pipeline(
                articles,
                ticker.value,
                cfg=cfg,
                mode=mode,
                settings=oai,
            )
            llm_backend = "openai"
            llm_model_id = oai.model

    def _channel_to_str(ch: object) -> str:
        if isinstance(ch, NewsImpactChannel):
            return ch.value
        return str(ch)

    articles_json: list[dict] = []
    for a in articles:
        # Канал новостей живёт не в domain.NewsArticle, а вычисляется на уровне 3 (draft.scored_from_news_articles).
        ch, ch_conf = None, None
        try:
            from pipeline.channels import classify_channel

            ch, ch_conf = classify_channel(getattr(a, "title", ""), getattr(a, "summary", None))
        except Exception:
            ch, ch_conf = None, None

        articles_json.append(
            {
                "ticker": getattr(a.ticker, "value", str(a.ticker)),
                "provider_id": getattr(a, "provider_id", None),
                "title": getattr(a, "title", None),
                "summary": getattr(a, "summary", None),
                "url": getattr(a, "link", None),
                "published_at_utc": _dt_iso(getattr(a, "timestamp", None)),
                "channel": _channel_to_str(ch) if ch is not None else None,
                "channel_rule_confidence": ch_conf,
                "cheap_sentiment": getattr(a, "cheap_sentiment", None),
                "raw_sentiment": getattr(a, "raw_sentiment", None),
            }
        )

    llm_batch_titles = [
        {
            "title": getattr(a, "title", None),
            "published_at_utc": _dt_iso(getattr(a, "timestamp", None)),
            "provider_id": getattr(a, "provider_id", None),
        }
        for a in llm_batch_articles
    ]

    regime_articles = [a for a in articles_json if a.get("channel") == "regime"]
    policy_articles = [a for a in articles_json if a.get("channel") == "policy_rates"]
    calendar_events_json = [_cal_event_dict(e) for e in cal_events[:100]]

    out: dict = {
        "ticker": ticker_val,
        "lookback_hours": lookback_hours,
        "max_per_ticker": max_per_ticker,
        "profile": profile,
        "now_utc": _dt_iso(now),
        "calendar": {
            "source": "investing.com (sources.ecalendar, GBP/JPY/EUR)",
            "event_count": len(cal_events),
            "events_preview": calendar_events_json,
            "load_error": calendar_load_error,
        },
        "geopolitics": {
            "regime_articles": regime_articles,
            "policy_articles": policy_articles,
            "counts": {
                "regime": len(regime_articles),
                "policy_rates": len(policy_articles),
            },
        },
        "articles": articles_json,
        "draft_impulse": {
            "draft_bias_incremental": di.draft_bias_incremental,
            "regime_stress": di.regime_stress,
            "policy_stress": di.policy_stress,
            "articles_incremental": di.articles_incremental,
            "articles_regime": di.articles_regime,
            "articles_policy": di.articles_policy,
            "weight_sum_incremental": di.weight_sum_incremental,
            "weight_sum_regime": di.weight_sum_regime,
            "weight_sum_policy": di.weight_sum_policy,
            "max_abs_regime": di.max_abs_regime,
            "max_abs_policy": di.max_abs_policy,
        },
        "single_scalar_draft_bias": bias,
        "gate": {
            "llm_mode": mode.value,
            "reason": gate_reason,
            "calendar_high_soon": gate_ctx.calendar_high_soon,
            "regime_present": gate_ctx.regime_present,
            "regime_rule_confidence": gate_ctx.regime_rule_confidence,
            "article_count": gate_ctx.article_count,
        },
        "llm_batch": {
            "count": len(llm_batch_titles),
            "articles": llm_batch_titles,
        },
        "llm": {
            "backend": llm_backend,
            "model": llm_model_id,
            "ollama_host": ollama_host_str if ollama_model_str else None,
        },
        "aggregated_news_signal": None,
    }

    if news_signal is not None:
        out["aggregated_news_signal"] = {
            "bias": news_signal.bias,
            "confidence": news_signal.confidence,
            "summary": list(news_signal.summary),
            "items": [
                {
                    "sentiment": i.sentiment,
                    "impact_strength": i.impact_strength.value,
                    "relevance": i.relevance.value,
                    "surprise": i.surprise.value,
                    "time_horizon": i.time_horizon.value,
                    "confidence": i.confidence,
                    "title": getattr(i, "title", None),
                }
                for i in list(news_signal.items)
            ],
        }

    return out


def main(argv: Optional[list[str]] = None) -> int:
    _add_repo_root_to_syspath()
    args = _parse_args(list(argv) if argv is not None else sys.argv[1:])

    # Стараемся гарантировать: stdout содержит только JSON (удобно для пайпов).
    # Всё, что печатают зависимости (FinBERT/AlphaVantage/и т.д.) — уйдёт в stderr.
    sys.stdout = _JsonOnlyStdout(sys.__stdout__, sys.__stderr__)

    payload = run(
        args.ticker,
        lookback_hours=args.lookback_hours,
        max_per_ticker=args.max_per_ticker,
        profile=args.profile,
        no_llm=bool(args.no_llm),
        ollama_model=str(args.ollama_model or ""),
        ollama_host=str(args.ollama_host or ""),
    )

    s = json.dumps(payload, ensure_ascii=False, indent=2 if args.pretty else None)

    if args.json_out:
        out_path = Path(args.json_out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(s + "\n", encoding="utf-8")
    else:
        sys.__stdout__.write(s + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

