"""
Интеграция Level 6: полный цикл от рыночных данных до Trade и Telegram.

    yfinance + Finviz  → LseHeuristicAgent → TechnicalSignal
    Yahoo News + FinBERT              → AggregatedNewsSignal  (gate permitting)
                                         ↓
                                   TradeBuilder.build()
                                         ↓
                                      Trade
                                         ↓
                                  format_trade() → Telegram

Приоритет: GAME_5M тикеры (SNDK, NBIS, ASML, MU, LITE, CIEN).

Запуск:
    # Только технический сигнал (без LLM):
    pytest tests/integration/test_trade_pipeline_real.py -v -m integration -s -k "not llm"

    # Полный цикл (LLM нужен OPENAI_API_KEY):
    pytest tests/integration/test_trade_pipeline_real.py -v -m integration -s

KERIM_REPLACE: заменить LseHeuristicAgent на KerimsAgent — остальной pipeline без изменений.
"""

from __future__ import annotations

import pytest

DAILY_DAYS  = 30
HOURLY_DAYS = 5


# ---------------------------------------------------------------------------
# Shared fixtures (scope=module)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def context_tickers():
    import config_loader
    return config_loader.get_game5m_context_tickers()


@pytest.fixture(scope="module")
def all_candles(game5m_tickers, context_tickers):
    """Dict[Ticker, TickerData] для GAME_5M + контекст. Идентично test_technical_agent_real_data."""
    pytest.importorskip("yfinance")
    from domain import TickerData
    from sources.candles import Source as CandleSource

    fetch = list(set(list(game5m_tickers) + list(context_tickers)))
    src   = CandleSource(with_prepostmarket=False)
    daily  = src.get_daily_candles(fetch,  days=DAILY_DAYS)   # Dict[Ticker, List[Candle]]
    hourly = src.get_hourly_candles(fetch, days=HOURLY_DAYS)  # Dict[Ticker, List[Candle]]

    result: dict = {}
    for t in fetch:
        d = daily.get(t, [])
        if not d:
            continue
        result[t] = TickerData(
            ticker=t,
            current_price=d[-1].close,
            daily_candles=d,
            hourly_candles=hourly.get(t, []),
        )
    if not any(t in result for t in game5m_tickers):
        pytest.skip("yfinance не вернул ни одного GAME_5M тикера")
    return result


@pytest.fixture(scope="module")
def all_metrics(game5m_tickers, context_tickers):
    pytest.importorskip("finvizfinance")
    from sources.metrics import Source as MetricsSource

    fetch = list(set(list(game5m_tickers) + list(context_tickers)))
    try:
        metrics = MetricsSource().get_metrics(fetch)
    except Exception as exc:
        pytest.skip(f"Finviz недоступен: {exc}")
    return {m.ticker: m for m in metrics}


@pytest.fixture(scope="module")
def tech_signals(game5m_tickers, all_candles, all_metrics):
    """TechnicalSignal для каждого GAME_5M тикера."""
    from pipeline.technical import LseHeuristicAgent

    agent            = LseHeuristicAgent()
    ticker_data_list = list(all_candles.values())
    metrics_list     = list(all_metrics.values())
    signals: dict    = {}

    for ticker in game5m_tickers:
        td = all_candles.get(ticker)
        if td is None or not td.daily_candles:
            continue
        signals[ticker] = agent.predict(ticker, ticker_data_list, metrics_list)
    return signals


# ---------------------------------------------------------------------------
# Тест 1: технический сигнал + TradeBuilder (без LLM)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_trade_tech_only(game5m_tickers, tech_signals):
    """
    TradeBuilder с news_signal=None (tech-only fusion).
    Проверяет: Position корректна, TP > Entry > SL (LONG), форматирование.
    """
    from domain import Direction, PositionType, SignalBundle
    from pipeline import TradeBuilder, format_trade, neutral_calendar_signal
    from pipeline.trade_builder import FusedBias

    builder = TradeBuilder()
    cal = neutral_calendar_signal()

    print(f"\n{'Тикер':6s}  {'bias':>6}  {'conf':>5}  {'side':>5}  {'entry':>8}  "
          f"{'TP':>8}  {'SL':>8}  {'type':>6}")
    print("-" * 65)

    results = {}
    for ticker in game5m_tickers:
        sig = tech_signals.get(ticker)
        if sig is None:
            continue

        bundle = SignalBundle(
            ticker=ticker,
            technical_signal=sig,
            news_signal=None,
            calendar_signal=cal,
        )
        trade = builder.build(bundle)
        fused = builder.fuse_bias(sig, None)
        results[ticker] = (trade, fused)

        price = sig.target_snapshot.data.current_price
        side_str = trade.position.side.value if trade.position else "none"
        tp_str = f"${trade.position.take_profit:,.0f}" if trade.position else "—"
        sl_str = f"${trade.position.stop_loss:,.0f}"  if trade.position else "—"
        print(
            f"{ticker.value:6s}  {sig.bias:>+.3f}  {sig.confidence:.3f}  "
            f"{side_str:>5}  ${price:>7,.0f}  {tp_str:>8}  {sl_str:>8}  "
            f"{trade.entry_type.value:>6}"
        )

    assert results, "Нет результатов"

    # Для каждого тикера с открытой позицией проверяем уровни
    for ticker, (trade, fused) in results.items():
        if trade.position is None:
            assert trade.entry_type == PositionType.NONE
            continue
        p = trade.position
        assert trade.entry_type == PositionType.MARKET
        if p.side == Direction.LONG:
            assert p.take_profit > p.entry > p.stop_loss, (
                f"{ticker.value}: LONG TP>{p.take_profit} Entry>{p.entry} > SL>{p.stop_loss}"
            )
        else:
            assert p.take_profit < p.entry < p.stop_loss, (
                f"{ticker.value}: SHORT TP<{p.take_profit} Entry<{p.entry} < SL<{p.stop_loss}"
            )
        assert 0 < p.confidence <= 1.0

    # Показываем сообщение для primary тикера
    primary_ticker = game5m_tickers[0]
    if primary_ticker in results:
        trade, fused = results[primary_ticker]
        msg = format_trade(trade, fused=fused)
        print(f"\n--- Telegram message [{primary_ticker.value}] ---\n{msg}")


# ---------------------------------------------------------------------------
# Тест 2: таблица технических сигналов → Telegram
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_format_signal_table(game5m_tickers, tech_signals):
    """format_signal_table → строка для Telegram (мониторинг снапшота)."""
    from pipeline import format_signal_table

    pairs = [
        (t.value, tech_signals[t])
        for t in game5m_tickers
        if t in tech_signals
    ]
    assert pairs, "Нет сигналов для таблицы"

    table = format_signal_table(pairs)
    print(f"\n--- Signal Table ---\n{table}")

    assert len(table.splitlines()) == len(pairs)
    for t_val, _ in pairs:
        assert t_val in table


# ---------------------------------------------------------------------------
# Тест 3: полный цикл tech + news → Trade → Telegram (требует OPENAI_API_KEY)
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_trade_full_pipeline_with_news(
    game5m_primary, tech_signals, require_finbert, require_telegram_settings
):
    """
    Полный цикл Level 0–6 + Telegram:
      FinBERT → draft → gate(PROFILE_GAME5M) → LLM(если FULL) → AggregatedNewsSignal
      → TradeBuilder → Trade → format_trade → sendMessage

    Если gate=SKIP/LITE, news_signal=None, trade строится на tech-only.
    """
    pytest.importorskip("yfinance")

    ticker = game5m_primary
    sig = tech_signals.get(ticker)
    if sig is None:
        pytest.skip(f"Нет TechnicalSignal для {ticker.value}")

    # --- News pipeline ---
    import config_loader
    from sources.news import Source as NewsSource
    from pipeline.sentiment import enrich_cheap_sentiment
    from pipeline.draft import scored_from_news_articles
    from pipeline import (
        draft_impulse, single_scalar_draft_bias,
        GateContext, decide_llm_mode, PROFILE_GAME5M,
    )
    from pipeline.news_signal_runner import run_news_signal_pipeline
    from pipeline.news_signal_aggregator import aggregate_news_signals
    from pipeline.llm_factory import get_chat_model

    articles = NewsSource(max_per_ticker=12, lookback_hours=48).get_articles([ticker])
    enriched = enrich_cheap_sentiment(articles, use_local=True, model_name=require_finbert)

    scored  = scored_from_news_articles(enriched)
    draft   = draft_impulse(scored)
    bias    = single_scalar_draft_bias(draft)

    ctx = GateContext(
        draft_bias=bias,
        regime_present=draft.regime_stress > PROFILE_GAME5M.regime_stress_min,
        regime_rule_confidence=0.85 if draft.regime_stress > PROFILE_GAME5M.regime_stress_min else 0.0,
        calendar_high_soon=False,
        article_count=len(enriched),
    )
    mode = decide_llm_mode(PROFILE_GAME5M, ctx)
    print(f"\n[{ticker.value}] articles={len(enriched)}  bias={bias:+.3f}  gate={mode.value}")

    news_signal = None
    if mode.value == "full":
        llm     = get_chat_model()
        signals = run_news_signal_pipeline(enriched, llm=llm, ticker=ticker)
        if signals:
            news_signal = aggregate_news_signals(signals)
            print(f"  → AggregatedNewsSignal: bias={news_signal.bias:+.3f}  "
                  f"conf={news_signal.confidence:.2f}  items={len(news_signal.items)}")
    else:
        print(f"  → gate={mode.value}: LLM пропущен, news_signal=None")

    # --- Trade builder ---
    from domain import SignalBundle
    from pipeline import TradeBuilder, format_trade, neutral_calendar_signal

    bundle = SignalBundle(
        ticker=ticker,
        technical_signal=sig,
        news_signal=news_signal,
        calendar_signal=neutral_calendar_signal(),
    )
    builder  = TradeBuilder()
    trade    = builder.build(bundle)
    fused    = builder.fuse_bias(sig, news_signal)
    msg      = format_trade(trade, fused=fused)

    print(f"\n{'='*26}\n{msg}")

    # --- Отправка в Telegram ---
    import requests
    token, chat_id = require_telegram_settings
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": msg},
        timeout=15,
    )
    assert resp.status_code == 200, f"Telegram: {resp.text}"
    print(f"  → Telegram OK (message_id={resp.json()['result']['message_id']})")

    # Базовые assertions
    assert trade.ticker == ticker
    assert trade.entry_type.value in ("market", "none")
    if trade.position:
        p = trade.position
        assert 0 < p.confidence <= 1.0
        assert p.entry > 0
