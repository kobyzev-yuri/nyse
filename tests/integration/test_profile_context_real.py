"""
Интеграция: PROFILE_CONTEXT тикеры (ORCL, MSFT, NVDA, META, AMZN) — FinBERT + gate.

Ключевые отличия от PROFILE_GAME5M:
  - t1=0.20 (vs 0.12), full_at=0.40 (vs 0.24)
  - max_articles_full_batch=15 (vs 12 в PROFILE_GAME5M)
  - Крупные тикеры получают 10-50 статей/день

Что проверяет:
  1. FinBERT + PROFILE_CONTEXT на live данных — gate decision для каждого тикера
  2. REGIME-детекция: показывает REGIME-статьи (война, санкции) и их влияние
  3. Диагностика FinBERT на заголовках с ambiguous sentiment (Goldman, "Buy the dip")
  4. Сравнение gate PROFILE_CONTEXT vs PROFILE_GAME5M для общих тикеров

Запуск:
    pytest tests/integration/test_profile_context_real.py -v -m integration -s
"""

from __future__ import annotations

import pytest

CONTEXT_TICKERS_VALUES = ["ORCL", "MSFT", "NVDA", "META", "AMZN"]


@pytest.fixture(scope="module")
def context_ticker_list():
    from domain import Ticker
    return [Ticker(v) for v in CONTEXT_TICKERS_VALUES]


@pytest.fixture(scope="module")
def enriched_context(context_ticker_list, require_finbert):
    """Yahoo News → FinBERT → enriched articles для PROFILE_CONTEXT тикеров."""
    pytest.importorskip("yfinance")
    from pipeline.sentiment import enrich_cheap_sentiment
    from sources.news import Source

    raw = Source(max_per_ticker=12, lookback_hours=48).get_articles(context_ticker_list)
    if not raw:
        pytest.skip("Yahoo не вернул новостей ни для одного PROFILE_CONTEXT тикера")

    enriched = enrich_cheap_sentiment(raw, use_local=True, model_name=require_finbert)
    by_ticker = {}
    for a in enriched:
        by_ticker.setdefault(a.ticker, []).append(a)
    return by_ticker


# ---------------------------------------------------------------------------
# Gate decisions
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_profile_context_gate_decisions(enriched_context, context_ticker_list):
    """
    PROFILE_CONTEXT gate для всех тикеров.
    Выводит таблицу: avg sentiment, regime_stress, gate decision.
    """
    from pipeline import GateContext, decide_llm_mode, draft_impulse, single_scalar_draft_bias
    from pipeline.draft import scored_from_news_articles
    from pipeline.types import PROFILE_CONTEXT

    cfg = PROFILE_CONTEXT
    print(
        f"\nPROFILE_CONTEXT  t1={cfg.t1_abs_draft_bias}  "
        f"full_at={cfg.t1_abs_draft_bias * 2:.2f}  "
        f"max_batch={cfg.max_articles_full_batch}"
    )
    print(f"{'Тикер':6s}  {'n':>3}  {'avg':>7}  {'reg_str':>7}  {'bias':>7}  {'gate':>6}")
    print("-" * 55)

    results = {}
    for ticker in context_ticker_list:
        arts = enriched_context.get(ticker, [])
        if not arts:
            print(f"{ticker.value:6s}  — нет статей")
            continue

        scored = scored_from_news_articles(arts)
        d = draft_impulse(scored)
        bias = single_scalar_draft_bias(d)
        ctx = GateContext(
            draft_bias=bias,
            regime_present=d.regime_stress > cfg.regime_stress_min,
            regime_rule_confidence=0.85 if d.regime_stress > cfg.regime_stress_min else 0.0,
            calendar_high_soon=False,
            article_count=len(arts),
        )
        mode = decide_llm_mode(cfg, ctx)
        scores = [a.cheap_sentiment for a in arts if a.cheap_sentiment is not None]
        avg = sum(scores) / len(scores) if scores else 0.0
        regime_flag = " ⚠REGIME" if ctx.regime_present else ""

        print(
            f"{ticker.value:6s}  {len(arts):>3}  {avg:>+.3f}  "
            f"{d.regime_stress:>+.3f}  {bias:>+.3f}  {mode.value:>6}{regime_flag}"
        )
        results[ticker] = (mode, d, bias, avg)

    assert results, "Нет данных ни для одного тикера"
    for ticker, (mode, d, bias, avg) in results.items():
        assert mode.value in ("skip", "lite", "full")


# ---------------------------------------------------------------------------
# REGIME-артефакты: показывает реальные REGIME-статьи
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_regime_articles_inspection(enriched_context, context_ticker_list):
    """
    Выводит все REGIME-статьи по PROFILE_CONTEXT тикерам.

    Ключевая проверка: одна macro-статья может триггерить REGIME у нескольких тикеров
    (например статья о "Iran war" появляется у MSFT, META, AMZN через summary).
    Это НОРМАЛЬНО — classify_channel правильно видит "war" в summary.
    Но FinBERT может неправильно оценить bullish заголовок если summary негативный.
    """
    from pipeline.channels import classify_channel
    from pipeline.types import NewsImpactChannel

    regime_found: dict = {}
    for ticker in context_ticker_list:
        arts = enriched_context.get(ticker, [])
        for a in arts:
            ch, _ = classify_channel(a.title, a.summary)
            if ch == NewsImpactChannel.REGIME:
                regime_found.setdefault(ticker, []).append(a)

    print("\n=== REGIME-статьи ===")
    all_regime_titles = set()
    for ticker, arts in regime_found.items():
        for a in arts:
            duplicate = "♻ ДУБЛИКАТ" if a.title in all_regime_titles else ""
            all_regime_titles.add(a.title)
            print(
                f"  {ticker.value:6s}  cs={a.cheap_sentiment:+.3f}  "
                f"{duplicate}  {a.title[:65]}"
            )
            if a.summary:
                snippet = a.summary[:120].replace('\n', ' ')
                print(f"         summary: {snippet}...")

    # Если нет REGIME статей — всё спокойно
    if not regime_found:
        print("  (нет REGIME статей — рынок спокоен по геополитике)")


# ---------------------------------------------------------------------------
# FinBERT диагностика на ambiguous заголовках
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_finbert_ambiguous_headlines(require_finbert):
    """
    Диагностика FinBERT на заголовках с неоднозначным сентиментом.

    Проблема: "Goldman Sachs Says It's Time to Buy Tech Stocks" получает cs=-0.927
    потому что summary содержит "Iran war", "worst performance" — FinBERT читает
    ВЕСЬ текст (title + summary), а не только заголовок.

    Это ОЖИДАЕМОЕ поведение — article_text() склеивает title + summary.
    Тест показывает расхождение заголовок-only vs title+summary.
    """
    from datetime import datetime, timezone
    from domain import NewsArticle, Ticker
    from pipeline.sentiment import resolve_cheap_sentiment, article_text

    def make_article(title, summary=None):
        return NewsArticle(
            ticker=Ticker.MSFT,
            title=title,
            timestamp=datetime.now(timezone.utc),
            summary=summary,
            link=None,
            publisher=None,
            raw_sentiment=None,
        )

    cases = [
        (
            "Goldman Sachs Says It's Time to Buy Tech Stocks",
            None,
            "title-only: ожидаем позитив",
        ),
        (
            "Goldman Sachs Says It's Time to Buy Tech Stocks",
            "Big Tech stocks have taken a battering lately — but investors should buy the dip "
            "as the Iran war drags on. Tech in 2026 has posted one of its worst performances.",
            "title+bearish_summary: FinBERT видит 'war', 'worst', 'battering' → негатив",
        ),
        (
            "Nvidia Stock Drops as Iran War Heats Up",
            None,
            "war в title → bearish",
        ),
        (
            "Samsung Beats High Estimates After AI Chip Sales Defy War Fears",
            None,
            "war в title но beats → FinBERT должен дать позитив",
        ),
    ]

    print(f"\nFinBERT ({require_finbert}) диагностика ambiguous заголовков:")
    for title, summary, comment in cases:
        a = make_article(title, summary)
        cs = resolve_cheap_sentiment(a, use_local=True, model_name=require_finbert)
        text_used = article_text(a)
        print(f"\n  cs={cs:+.3f}  [{comment}]")
        print(f"  text → '{text_used[:100]}'")

    # Проверяем самый важный случай: title-only Goldman = нейтральный (не -0.9)
    a_title_only = make_article("Goldman Sachs Says It's Time to Buy Tech Stocks")
    cs_title = resolve_cheap_sentiment(a_title_only, use_local=True, model_name=require_finbert)
    # С title-only FinBERT не должен давать сильный негатив на bullish заголовке
    # (с summary он будет негативным — это ОК)
    assert cs_title > -0.5, (
        f"FinBERT дал {cs_title:.3f} на title-only bullish заголовке. "
        "Возможно модель неправильно интерпретирует 'It\\'s Time to Buy'?"
    )


# ---------------------------------------------------------------------------
# Сравнение профилей
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_multi_ticker_session_dedup_live(enriched_context, context_ticker_list):
    """
    MultiTickerGateSession на live данных: MSFT, META, AMZN — один Goldman/IranWar дубликат.

    Сравниваем gate-решения:
      - без сессии (old): все три → full via REGIME (3x LLM вызова)
      - с сессией (new):  MSFT → full; META и AMZN — REGIME понижен до INCREMENTAL
        → gate пересчитывается по bias без REGIME-пути

    Количество ожидаемых LLM вызовов снижается.
    """
    from pipeline import GateContext, MultiTickerGateSession, decide_llm_mode, draft_impulse, single_scalar_draft_bias
    from pipeline.types import PROFILE_CONTEXT

    cfg = PROFILE_CONTEXT
    mag7 = [t for t in context_ticker_list if t.value in ("MSFT", "META", "AMZN")]
    if not any(enriched_context.get(t) for t in mag7):
        pytest.skip("Нет live данных для MSFT/META/AMZN")

    def gate_from_draft(arts, cfg):
        from pipeline.draft import scored_from_news_articles as _s
        scored = _s(arts)
        d = draft_impulse(scored)
        bias = single_scalar_draft_bias(d)
        ctx = GateContext(
            draft_bias=bias,
            regime_present=d.regime_stress > cfg.regime_stress_min,
            regime_rule_confidence=0.85 if d.regime_stress > cfg.regime_stress_min else 0.0,
            calendar_high_soon=False,
            article_count=len(arts),
        )
        return decide_llm_mode(cfg, ctx).value, d.regime_stress

    # Без сессии (старое поведение)
    old_modes = {}
    for t in mag7:
        arts = enriched_context.get(t, [])
        if arts:
            mode, rs = gate_from_draft(arts, cfg)
            old_modes[t.value] = (mode, rs)

    # С сессией (новое поведение)
    session = MultiTickerGateSession()
    new_modes = {}
    for t in mag7:
        arts = enriched_context.get(t, [])
        if not arts:
            continue
        scored = session.scored(arts)
        d = draft_impulse(scored)
        bias = single_scalar_draft_bias(d)
        ctx = GateContext(
            draft_bias=bias,
            regime_present=d.regime_stress > cfg.regime_stress_min,
            regime_rule_confidence=0.85 if d.regime_stress > cfg.regime_stress_min else 0.0,
            calendar_high_soon=False,
            article_count=len(arts),
        )
        mode = decide_llm_mode(cfg, ctx).value
        new_modes[t.value] = (mode, d.regime_stress)

    print(f"\n{'Тикер':6s}  {'без сессии':>15}  {'с сессией':>15}  {'деdup?':>6}")
    print("-" * 55)
    saved = 0
    for ticker in [t.value for t in mag7]:
        old = old_modes.get(ticker)
        new = new_modes.get(ticker)
        if not old or not new:
            continue
        old_mode, old_rs = old
        new_mode, new_rs = new
        dedup = "✓" if new_rs < old_rs else ""
        if dedup:
            saved += 1
        print(
            f"{ticker:6s}  regime={old_rs:.3f} {old_mode:>5}  "
            f"regime={new_rs:.3f} {new_mode:>5}  {dedup}"
        )
    print(f"\nLLM вызовов сэкономлено (FULL→не-FULL): ~{saved}")
    print(f"Уникальных REGIME-статей в сессии: {session.seen_regime_count}")

    assert new_modes, "Нет результатов"
    # Первый тикер в сессии должен получить REGIME если было ⚠REGIME у хотя бы одного
    first_ticker = [t.value for t in mag7 if enriched_context.get(t)][0]
    old_first_mode = old_modes.get(first_ticker, (None,))[0]
    new_first_mode = new_modes.get(first_ticker, (None,))[0]
    assert new_first_mode == old_first_mode, (
        f"Первый тикер {first_ticker} должен сохранять gate-решение"
    )


@pytest.mark.integration
def test_profile_comparison_nvda(enriched_context):
    """
    NVDA: сравниваем gate при PROFILE_CONTEXT vs PROFILE_GAME5M.
    Показывает почему крупные тикеры нужен более высокий порог.
    """
    from domain import Ticker
    from pipeline import GateContext, decide_llm_mode, draft_impulse, single_scalar_draft_bias
    from pipeline.draft import scored_from_news_articles
    from pipeline.types import PROFILE_CONTEXT, PROFILE_GAME5M

    ticker = Ticker.NVDA
    arts = enriched_context.get(ticker, [])
    if not arts:
        pytest.skip(f"Нет данных для {ticker.value}")

    scored = scored_from_news_articles(arts)
    d = draft_impulse(scored)
    bias = single_scalar_draft_bias(d)

    def gate_for_profile(cfg):
        ctx = GateContext(
            draft_bias=bias,
            regime_present=d.regime_stress > cfg.regime_stress_min,
            regime_rule_confidence=0.85 if d.regime_stress > cfg.regime_stress_min else 0.0,
            calendar_high_soon=False,
            article_count=len(arts),
        )
        return decide_llm_mode(cfg, ctx).value

    mode_ctx  = gate_for_profile(PROFILE_CONTEXT)
    mode_g5m  = gate_for_profile(PROFILE_GAME5M)

    print(
        f"\n[{ticker.value}]  bias={bias:+.3f}  reg_stress={d.regime_stress:.3f}"
        f"\n  PROFILE_CONTEXT (t1={PROFILE_CONTEXT.t1_abs_draft_bias}, full_at={PROFILE_CONTEXT.t1_abs_draft_bias*2:.2f}): {mode_ctx}"
        f"\n  PROFILE_GAME5M  (t1={PROFILE_GAME5M.t1_abs_draft_bias},  full_at={PROFILE_GAME5M.t1_abs_draft_bias*2:.2f}): {mode_g5m}"
    )
    assert mode_ctx in ("skip", "lite", "full")
    assert mode_g5m in ("skip", "lite", "full")
