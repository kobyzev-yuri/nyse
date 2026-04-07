"""
Интеграция: LseHeuristicAgent на РЕАЛЬНЫХ данных (yfinance + Finviz).

Что проверяет:
  1. sources.candles.Source → реальные daily + hourly свечи с yfinance
  2. sources.metrics.Source → реальные метрики с Finviz (RSI, SMA, ATR ...)
  3. LseHeuristicAgent.predict() → TechnicalSignal с корректными диапазонами
  4. Все score-поля, bias и confidence лежат в [-1, 1] / [0, 1]
  5. summary содержит числовые значения bias и RSI

Запуск:
    pytest tests/integration/test_technical_agent_real_data.py -v -m integration

KERIM_REPLACE: тот же тест будет валидировать агент Kerima после замены:
    agent = KerimsAgent(llm=get_chat_model())
    sig = agent.predict(ticker, ticker_data, metrics)
  Контракт выхода (TechnicalSignal) идентичен — тест переиспользуем без изменений.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TICKERS_UNDER_TEST = ["NVDA"]   # минимальный набор; добавить NBIS / MU при необходимости
DAILY_DAYS = 30                  # свечей достаточно для vol_20d
HOURLY_DAYS = 5


@pytest.fixture(scope="module")
def real_ticker_data():
    """Реальные свечи с yfinance (30d daily + 5d hourly)."""
    pytest.importorskip("yfinance")
    from domain import Ticker, TickerData
    from sources.candles import Source as CandleSource

    src = CandleSource(with_prepostmarket=False)
    tickers = [Ticker.NVDA, Ticker.QQQ, Ticker.SMH]  # контекст нужен для market_alignment

    daily  = src.get_daily_candles(tickers, days=DAILY_DAYS)
    hourly = src.get_hourly_candles(tickers, days=HOURLY_DAYS)

    result = {}
    for t in tickers:
        d = daily.get(t, [])
        h = hourly.get(t, [])
        if not d:
            continue
        result[t] = TickerData(
            ticker=t,
            current_price=d[-1].close,
            daily_candles=d,
            hourly_candles=h,
        )

    if Ticker.NVDA not in result:
        pytest.skip("yfinance не вернул свечи для NVDA")

    return result


@pytest.fixture(scope="module")
def real_metrics():
    """Реальные метрики с Finviz (RSI, SMA, ATR, RelVol, Beta)."""
    pytest.importorskip("finvizfinance")
    from domain import Ticker
    from sources.metrics import Source as MetricsSource

    tickers = [Ticker.NVDA, Ticker.QQQ, Ticker.SMH]
    try:
        return {m.ticker: m for m in MetricsSource().get_metrics(tickers)}
    except Exception as exc:
        pytest.skip(f"Finviz недоступен: {exc}")


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_lse_agent_output_ranges(real_ticker_data, real_metrics):
    """Все поля TechnicalSignal лежат в допустимых диапазонах."""
    from domain import Ticker
    from pipeline.technical import LseHeuristicAgent

    ticker = Ticker.NVDA
    if ticker not in real_metrics:
        pytest.skip("Нет Finviz-метрик для NVDA")

    agent = LseHeuristicAgent()
    sig = agent.predict(
        ticker,
        ticker_data=list(real_ticker_data.values()),
        metrics=list(real_metrics.values()),
    )

    # диапазоны [-1, 1]
    for field in (
        "bias", "trend_score", "momentum_score", "mean_reversion_score",
        "breakout_score", "market_alignment_score", "support_resistance_pressure",
        "relative_strength_score",
    ):
        val = getattr(sig, field)
        assert -1.0 <= val <= 1.0, f"{field}={val} out of [-1, 1]"

    # диапазоны [0, 1]
    for field in (
        "volatility_regime", "exhaustion_score",
        "tradeability_score", "confidence",
    ):
        val = getattr(sig, field)
        assert 0.0 <= val <= 1.0, f"{field}={val} out of [0, 1]"

    print(
        f"\n[NVDA] bias={sig.bias:+.3f}  conf={sig.confidence:.3f}  "
        f"tradeability={sig.tradeability_score:.3f}"
    )
    for line in sig.summary:
        print(" ", line)


@pytest.mark.integration
def test_lse_agent_snapshot_references_real_data(real_ticker_data, real_metrics):
    """target_snapshot ссылается на реальный TickerData/TickerMetrics."""
    from domain import Ticker
    from pipeline.technical import LseHeuristicAgent

    ticker = Ticker.NVDA
    if ticker not in real_metrics:
        pytest.skip("Нет Finviz-метрик для NVDA")

    agent = LseHeuristicAgent()
    sig = agent.predict(
        ticker,
        ticker_data=list(real_ticker_data.values()),
        metrics=list(real_metrics.values()),
    )

    assert sig.target_snapshot.data.ticker == ticker
    assert sig.target_snapshot.metrics.ticker == ticker
    assert sig.target_snapshot.data.current_price > 0
    assert sig.target_snapshot.metrics.rsi_14 > 0
    assert len(sig.target_snapshot.data.daily_candles) >= 10


@pytest.mark.integration
def test_lse_agent_summary_contains_real_numbers(real_ticker_data, real_metrics):
    """summary содержит актуальные числовые значения (RSI, bias)."""
    from domain import Ticker
    from pipeline.technical import LseHeuristicAgent

    ticker = Ticker.NVDA
    if ticker not in real_metrics:
        pytest.skip("Нет Finviz-метрик для NVDA")

    agent = LseHeuristicAgent()
    sig = agent.predict(
        ticker,
        ticker_data=list(real_ticker_data.values()),
        metrics=list(real_metrics.values()),
    )

    full_summary = " ".join(sig.summary)
    # summary должен упоминать bias и RSI числом
    assert "bias" in full_summary.lower()
    assert "rsi" in full_summary.lower()
    assert any(char.isdigit() for char in full_summary)


@pytest.mark.integration
def test_lse_agent_with_context_tickers(real_ticker_data, real_metrics):
    """С QQQ/SMH в контексте market_alignment_score должен быть ненулевым."""
    from domain import Ticker
    from pipeline.technical import LseHeuristicAgent

    ticker = Ticker.NVDA
    has_context = Ticker.QQQ in real_metrics or Ticker.SMH in real_metrics
    if not has_context:
        pytest.skip("Нет контекстных тикеров QQQ/SMH в Finviz")

    agent = LseHeuristicAgent()
    sig = agent.predict(
        ticker,
        ticker_data=list(real_ticker_data.values()),
        metrics=list(real_metrics.values()),
    )

    # market_alignment должен быть рассчитан по QQQ/SMH, а не по sma50_pct тикера
    # Проверяем только что он не является точно равным sma50_pct/20 (т.е. использован контекст)
    fallback_val = real_metrics[ticker].sma50_pct / 20.0
    # Если есть QQQ или SMH, ожидаем что значение отличается от fallback
    if Ticker.QQQ in real_ticker_data and Ticker.QQQ in real_metrics:
        assert sig.market_alignment_score != pytest.approx(fallback_val, abs=0.01), \
            "market_alignment_score unexpectedly equals sma50 fallback despite QQQ context"
