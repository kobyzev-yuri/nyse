"""
Интеграция: LseHeuristicAgent на РЕАЛЬНЫХ данных — GAME_5M тикеры (yfinance + Finviz).

Приоритет: тикеры из TICKERS_FAST (config.env): SNDK, NBIS, ASML, MU, LITE, CIEN.
Контекст для market_alignment: QQQ, SMH.

Что проверяет:
  1. sources.candles.Source  → реальные daily + hourly свечи с yfinance
  2. sources.metrics.Source  → реальные метрики с Finviz (RSI, SMA, ATR …)
  3. LseHeuristicAgent.predict() → TechnicalSignal с корректными диапазонами
  4. Все score-поля, bias, confidence лежат в допустимых диапазонах
  5. summary содержит числовые значения bias и RSI

Запуск:
    pytest tests/integration/test_technical_agent_real_data.py -v -m integration -s

Тот же сценарий для ``LlmTechnicalAgent`` (``NYSE_LLM_TECHNICAL=1``): тот же контракт
    ``predict(ticker, ticker_data, metrics)`` → ``TechnicalSignal``.
"""

from __future__ import annotations

import pytest


DAILY_DAYS = 30
HOURLY_DAYS = 5


# ---------------------------------------------------------------------------
# Shared fixtures (scope=module → один запрос на модуль)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def context_tickers():
    """QQQ + SMH для market_alignment_score."""
    import config_loader
    return config_loader.get_game5m_context_tickers()


@pytest.fixture(scope="module")
def all_candles(game5m_tickers, context_tickers):
    """
    Dict[Ticker, (daily_candles, hourly_candles)] для GAME_5M + контекст.
    Один батч-запрос к yfinance на весь модуль.
    """
    pytest.importorskip("yfinance")
    from domain import TickerData
    from sources.candles import Source as CandleSource

    fetch = list(set(game5m_tickers + context_tickers))
    src = CandleSource(with_prepostmarket=False)
    daily  = src.get_daily_candles(fetch, days=DAILY_DAYS)
    hourly = src.get_hourly_candles(fetch, days=HOURLY_DAYS)

    result = {}
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
        pytest.skip("yfinance не вернул ни одного тикера GAME_5M")

    return result  # Dict[Ticker, TickerData]


@pytest.fixture(scope="module")
def all_metrics(game5m_tickers, context_tickers):
    """
    Dict[Ticker, TickerMetrics] для GAME_5M + контекст.
    Один батч-запрос к Finviz на весь модуль.
    """
    pytest.importorskip("finvizfinance")
    from sources.metrics import Source as MetricsSource

    fetch = list(set(game5m_tickers + context_tickers))
    try:
        metrics = MetricsSource().get_metrics(fetch)
    except Exception as exc:
        pytest.skip(f"Finviz недоступен: {exc}")
    return {m.ticker: m for m in metrics}


# ---------------------------------------------------------------------------
# Параметризованные тесты по всем GAME_5M тикерам
# ---------------------------------------------------------------------------

def _game5m_ids(tickers):
    return [t.value for t in tickers]


@pytest.mark.integration
def test_all_game5m_signal_ranges(all_candles, all_metrics, game5m_tickers):
    """
    Для каждого тикера GAME_5M: TechnicalSignal в допустимых диапазонах.
    Результаты печатаются для визуального анализа.
    """
    from pipeline.technical import LseHeuristicAgent

    agent = LseHeuristicAgent()
    ticker_data_list = list(all_candles.values())
    metrics_list = list(all_metrics.values())

    print()
    missing = []
    for ticker in game5m_tickers:
        if ticker not in all_candles:
            missing.append(ticker.value)
            print(f"  {ticker.value:6s} — нет свечей, пропускаем")
            continue
        if ticker not in all_metrics:
            missing.append(ticker.value)
            print(f"  {ticker.value:6s} — нет Finviz-метрик, пропускаем")
            continue

        sig = agent.predict(ticker, ticker_data_list, metrics_list)

        for field in ("bias", "trend_score", "momentum_score", "mean_reversion_score",
                      "breakout_score", "market_alignment_score",
                      "support_resistance_pressure", "relative_strength_score"):
            val = getattr(sig, field)
            assert -1.0 <= val <= 1.0, f"{ticker.value} {field}={val} out of [-1,1]"

        for field in ("volatility_regime", "exhaustion_score",
                      "tradeability_score", "confidence"):
            val = getattr(sig, field)
            assert 0.0 <= val <= 1.0, f"{ticker.value} {field}={val} out of [0,1]"

        rsi = sig.target_snapshot.metrics.rsi_14
        price = sig.target_snapshot.data.current_price
        direction = "▲" if sig.bias > 0.05 else "▼" if sig.bias < -0.05 else "─"
        print(
            f"  {ticker.value:6s}  ${price:7.2f}  "
            f"bias {sig.bias:+.3f} {direction}  "
            f"conf {sig.confidence:.2f}  "
            f"RSI {rsi:.0f}  "
            f"ATR {sig.target_snapshot.metrics.atr:.2f}"
        )

    if len(missing) == len(game5m_tickers):
        pytest.fail("Нет данных ни для одного GAME_5M тикера")


@pytest.mark.integration
def test_game5m_primary_snapshot(all_candles, all_metrics, game5m_primary):
    """
    Первичный тикер (SNDK/первый в TICKERS_FAST): snapshot ссылается на реальные данные.
    """
    from pipeline.technical import LseHeuristicAgent

    ticker = game5m_primary
    if ticker not in all_candles or ticker not in all_metrics:
        pytest.skip(f"Нет данных для {ticker.value}")

    agent = LseHeuristicAgent()
    sig = agent.predict(
        ticker,
        list(all_candles.values()),
        list(all_metrics.values()),
    )

    assert sig.target_snapshot.data.ticker == ticker
    assert sig.target_snapshot.metrics.ticker == ticker
    assert sig.target_snapshot.data.current_price > 0
    assert sig.target_snapshot.metrics.rsi_14 > 0
    assert len(sig.target_snapshot.data.daily_candles) >= 5
    assert any(char.isdigit() for char in " ".join(sig.summary))

    print(f"\n[{ticker.value}]", " | ".join(sig.summary))


@pytest.mark.integration
def test_game5m_summary_format(all_candles, all_metrics, game5m_primary):
    """summary содержит bias и RSI для первичного тикера."""
    from pipeline.technical import LseHeuristicAgent

    ticker = game5m_primary
    if ticker not in all_candles or ticker not in all_metrics:
        pytest.skip(f"Нет данных для {ticker.value}")

    sig = LseHeuristicAgent().predict(
        ticker, list(all_candles.values()), list(all_metrics.values())
    )
    full = " ".join(sig.summary).lower()
    assert "bias" in full
    assert "rsi" in full


@pytest.mark.integration
def test_context_improves_market_alignment(all_candles, all_metrics,
                                            game5m_primary, context_tickers):
    """
    При наличии QQQ/SMH market_alignment_score не равен sma50_pct/20 fallback.
    """
    from pipeline.technical import LseHeuristicAgent

    ticker = game5m_primary
    if ticker not in all_candles or ticker not in all_metrics:
        pytest.skip(f"Нет данных для {ticker.value}")

    has_ctx = any(t in all_metrics for t in context_tickers)
    if not has_ctx:
        pytest.skip("Нет контекстных тикеров QQQ/SMH в Finviz")

    sig = LseHeuristicAgent().predict(
        ticker, list(all_candles.values()), list(all_metrics.values())
    )

    fallback = all_metrics[ticker].sma50_pct / 20.0
    # При наличии QQQ/SMH значение должно отличаться от sma50 fallback
    assert sig.market_alignment_score != pytest.approx(fallback, abs=0.01), \
        "market_alignment_score совпал с sma50 fallback — контекстные тикеры не учтены"
