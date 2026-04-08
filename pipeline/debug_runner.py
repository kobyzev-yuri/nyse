"""
Debug-режим пайплайна: прогоняет все уровни L0–L6 и сохраняет промежуточные
результаты в ``PipelineDebugTrace`` для HTML-отчёта (/news_signal команда бота).

Не предназначен для продакшена — только для отладки и калибровки.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional, Sequence

from domain import (
    AggregatedNewsSignal,
    NewsArticle,
    SignalBundle,
    TechnicalSignal,
    Ticker,
    TickerData,
    TickerMetrics,
    Trade,
)
from pipeline.channels import classify_channel
from pipeline.draft import ScoredArticle, draft_impulse, scored_from_news_articles
from pipeline.draft import single_scalar_draft_bias
from pipeline.gates import decide_llm_mode
from pipeline.llm_batch_plan import plan_llm_article_batch
import config_loader as _cfg_mod

from pipeline.calendar_llm_agent import CalendarLlmAgent
from pipeline.trade_builder import neutral_calendar_signal
from pipeline.news_signal_runner import run_news_signal_pipeline
from pipeline.sentiment import enrich_cheap_sentiment
from pipeline.trade_builder import FusedBias, TradeBuilder
from pipeline.types import (
    DraftImpulse,
    GateContext,
    LLMMode,
    PROFILE_GAME5M,
    ThresholdConfig,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Результат одного прогона (все промежуточные данные)
# ---------------------------------------------------------------------------

@dataclass
class PipelineDebugTrace:
    """Полный снимок всех уровней пайплайна для одного тикера."""

    ticker: str
    generated_at: datetime
    profile: ThresholdConfig

    # --- L0-L1: рыночные данные ---
    current_price: float
    daily_candles_count: int
    hourly_candles_count: int

    # --- L2: технический агент ---
    tech_signal: TechnicalSignal
    metrics: TickerMetrics

    # --- L3a: сырые статьи с cheap_sentiment ---
    articles: List[NewsArticle]            # обогащены enrich_cheap_sentiment

    # --- L3b: ScoredArticle + channel (для draft_impulse) ---
    scored: List[ScoredArticle]
    article_channels: List[str]            # channel per article (параллельно articles)

    # --- L3c: DraftImpulse ---
    draft_impulse: DraftImpulse
    draft_bias: float

    # --- L4: Gate ---
    gate_ctx: GateContext
    llm_mode: LLMMode
    gate_reason: str                       # человеко-читаемая причина

    # --- L5: LLM (если mode != SKIP) ---
    llm_batch_articles: List[NewsArticle]  # какие статьи ушли в LLM
    news_signal: Optional[AggregatedNewsSignal]

    # --- L6: fusion + Trade ---
    fused: FusedBias
    trade: Trade


# ---------------------------------------------------------------------------
# Причина решения Gate (для отображения в HTML)
# ---------------------------------------------------------------------------

def _gate_reason(cfg: ThresholdConfig, ctx: GateContext, mode: LLMMode) -> str:
    if ctx.calendar_high_soon:
        return "FULL: calendar high-impact event imminent"
    if ctx.regime_present and ctx.regime_rule_confidence >= cfg.t2_regime_confidence:
        return (
            f"FULL: REGIME present (conf={ctx.regime_rule_confidence:.2f} ≥ "
            f"t2={cfg.t2_regime_confidence:.2f})"
        )
    ab = abs(ctx.draft_bias)
    if ab >= cfg.t1_abs_draft_bias * 2.0:
        return (
            f"FULL: |draft_bias|={ab:.3f} ≥ t1×2={cfg.t1_abs_draft_bias * 2.0:.3f}"
        )
    if ab < cfg.t1_abs_draft_bias and not ctx.regime_present:
        return (
            f"SKIP: |draft_bias|={ab:.3f} < t1={cfg.t1_abs_draft_bias:.3f}, "
            "no REGIME → LLM дорог, пропускаем"
        )
    if ctx.article_count > cfg.max_articles_full_batch:
        return (
            f"LITE: moderate bias, article_count={ctx.article_count} > "
            f"max_full={cfg.max_articles_full_batch}"
        )
    return f"LITE: moderate bias={ab:.3f} (t1={cfg.t1_abs_draft_bias:.3f})"


# ---------------------------------------------------------------------------
# Главная функция
# ---------------------------------------------------------------------------

def run_debug_pipeline(
    ticker: Ticker,
    ticker_data_map: dict,       # Dict[Ticker, TickerData]
    metrics_list: list,          # List[TickerMetrics]
    *,
    profile: ThresholdConfig = PROFILE_GAME5M,
    lookback_hours: int = 72,
    max_articles: int = 12,
    settings=None,
) -> PipelineDebugTrace:
    """
    Прогоняет L0–L6 с захватом промежуточных данных.

    Parameters
    ----------
    ticker          : целевой тикер.
    ticker_data_map : Dict[Ticker, TickerData] (уже загружены).
    metrics_list    : List[TickerMetrics] (уже загружены).
    profile         : пороги; по умолчанию PROFILE_GAME5M.
    settings        : OpenAISettings; None → config_loader.
    """
    import config_loader
    from sources.news import Source as NewsSource
    from pipeline.calendar_context import build_gate_context
    from pipeline.technical import LlmTechnicalAgent, LseHeuristicAgent

    now = datetime.now(timezone.utc)
    ticker_val = ticker.value

    td: TickerData = ticker_data_map[ticker]
    metrics_map = {m.ticker: m for m in metrics_list}
    m: TickerMetrics = metrics_map[ticker]

    # --- L2: технический сигнал ---
    s_oai = settings if settings is not None else config_loader.get_openai_settings()
    if s_oai and _cfg_mod.use_llm_technical_signal():
        tech = LlmTechnicalAgent(settings=s_oai).predict(
            ticker, list(ticker_data_map.values()), metrics_list
        )
    else:
        tech = LseHeuristicAgent().predict(ticker, list(ticker_data_map.values()), metrics_list)

    # --- L3a: статьи + cheap_sentiment ---
    raw_articles = NewsSource(
        max_per_ticker=max_articles,
        lookback_hours=lookback_hours,
    ).get_articles([ticker])
    articles = [a for a in raw_articles if a.ticker == ticker]
    articles = list(enrich_cheap_sentiment(articles))

    # --- L3b: канал для каждой статьи (для таблицы в HTML) ---
    article_channels: List[str] = []
    for a in articles:
        ch, _ = classify_channel(a.title, a.summary)
        article_channels.append(ch.value)

    # --- L3c: scored + DraftImpulse ---
    scored = list(scored_from_news_articles(articles))
    di = draft_impulse(scored, now=now)
    bias = single_scalar_draft_bias(di)

    # --- L4: Gate (календарь HIGH в окне → FULL) ---
    cal_events: list = []
    try:
        from domain import Currency
        from sources.ecalendar import Source as CalendarSource

        cal_events = CalendarSource([Currency.GBP, Currency.JPY, Currency.EUR]).get_calendar()
    except Exception:
        pass

    gate_ctx = build_gate_context(
        draft_bias=bias,
        regime_present=di.regime_stress > profile.regime_stress_min,
        regime_rule_confidence=0.85 if di.regime_stress > profile.regime_stress_min else 0.0,
        calendar_events=cal_events,
        article_count=len(articles),
        now=now,
    )
    mode = decide_llm_mode(profile, gate_ctx)
    reason = _gate_reason(profile, gate_ctx, mode)

    # --- L5: LLM batch plan + news signal ---
    llm_batch: List[NewsArticle] = []
    if mode.value == "full":
        plan = plan_llm_article_batch(LLMMode.FULL, articles, cfg=profile)
        llm_batch = [articles[i] for i in plan.indices_for_structured_signal]

    s = settings if settings is not None else config_loader.get_openai_settings()
    news_signal: Optional[AggregatedNewsSignal] = None
    if mode.value in ("full", "lite") and s is not None:
        news_signal = run_news_signal_pipeline(
            articles, ticker_val,
            cfg=profile,
            mode=mode,
            settings=s,
        )

    if s is not None and _cfg_mod.use_llm_calendar_signal() and cal_events:
        calendar_signal = CalendarLlmAgent(
            settings=s,
            batch_size=_cfg_mod.calendar_llm_batch_size(),
        ).predict(ticker, cal_events)
    else:
        calendar_signal = neutral_calendar_signal()

    # --- L6: Trade ---
    bundle = SignalBundle(
        ticker=ticker,
        technical_signal=tech,
        news_signal=news_signal,
        calendar_signal=calendar_signal,
    )
    builder = TradeBuilder()
    trade = builder.build(bundle)
    fused = builder.fuse_bias(tech, news_signal, calendar_signal)

    return PipelineDebugTrace(
        ticker=ticker_val,
        generated_at=now,
        profile=profile,
        current_price=td.current_price,
        daily_candles_count=len(td.daily_candles),
        hourly_candles_count=len(td.hourly_candles),
        tech_signal=tech,
        metrics=m,
        articles=articles,
        scored=scored,
        article_channels=article_channels,
        draft_impulse=di,
        draft_bias=bias,
        gate_ctx=gate_ctx,
        llm_mode=mode,
        gate_reason=reason,
        llm_batch_articles=llm_batch,
        news_signal=news_signal,
        fused=fused,
        trade=trade,
    )
