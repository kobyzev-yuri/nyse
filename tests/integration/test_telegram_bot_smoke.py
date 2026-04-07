"""
Интеграция: Telegram Bot API smoke-тест.

Что проверяет:
  1. TELEGRAM_BOT_TOKEN валиден → getMe возвращает имя бота
  2. Бот может отправить сообщение в chat_id (TELEGRAM_SIGNAL_CHAT_ID)
  3. Форматированный сигнал TechnicalSignal доставляется корректно

Запуск:
    pytest tests/integration/test_telegram_bot_smoke.py -v -m integration -s

Нужно в config.env:
    TELEGRAM_BOT_TOKEN=<токен от @BotFather>
    TELEGRAM_SIGNAL_CHAT_ID=<chat_id>
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import requests


_TG_API = "https://api.telegram.org/bot{token}/{method}"
_TIMEOUT = 15


def _tg(token: str, method: str, **kwargs) -> dict:
    """Вызов Telegram Bot API. Бросает RuntimeError при ошибке."""
    url = _TG_API.format(token=token, method=method)
    try:
        r = requests.post(url, json=kwargs, timeout=_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        pytest.skip(f"Telegram API недоступен: {exc}")
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data}")
    return data["result"]


# ---------------------------------------------------------------------------
# Тесты
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_telegram_get_me(require_telegram_token):
    """Токен валиден — getMe возвращает имя бота."""
    token = require_telegram_token
    bot = _tg(token, "getMe")

    assert "username" in bot
    assert bot["is_bot"] is True
    print(f"\nBot: @{bot['username']}  id={bot['id']}")


@pytest.mark.integration
def test_telegram_send_text_message(require_telegram_settings):
    """Простой текст доставляется в chat_id."""
    token, chat_id = require_telegram_settings
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    result = _tg(
        token, "sendMessage",
        chat_id=chat_id,
        text=f"🧪 nyse smoke test — {ts}",
    )

    assert result["message_id"] > 0
    assert result["chat"]["id"] == int(chat_id)
    print(f"\nmessage_id={result['message_id']}")


@pytest.mark.integration
def test_telegram_send_technical_signal_format(require_telegram_settings):
    """
    Форматированное сообщение с TechnicalSignal отправляется без ошибок.

    Симулирует вывод сигнала в бот-команде /signal NVDA.
    KERIM_REPLACE: после интеграции с Kerim-агентом — тот же формат, 
    только sig получен от KerimsAgent.predict() вместо LseHeuristicAgent.
    """
    token, chat_id = require_telegram_settings

    # Синтетический сигнал (не нужны реальные данные для проверки форматирования)
    sig_text = (
        "📊 *NVDA — Technical Signal* (baseline)\n"
        "\n"
        "bias `+0.31` (moderate bullish)\n"
        "confidence `0.71`  tradeability `0.63`\n"
        "\n"
        "• Trend score `+0.45`. RSI 58 — neutral zone.\n"
        "• Volatility regime `0.48` — calm, ATR=5.25\n"
        "• Momentum `+0.32`  Breakout `+0.55`\n"
        "\n"
        "_⚠️ baseline: LseHeuristicAgent (KERIM\\_REPLACE)_"
    )

    result = _tg(
        token, "sendMessage",
        chat_id=chat_id,
        text=sig_text,
        parse_mode="Markdown",
    )
    assert result["message_id"] > 0
    print(f"\nSignal message delivered: id={result['message_id']}")


@pytest.mark.integration
def test_telegram_send_real_game5m_signal(require_telegram_settings, game5m_tickers):
    """
    Полный цикл: реальные данные GAME_5M → LseHeuristicAgent → сигналы всех тикеров → Telegram.

    Требует сеть (yfinance + Finviz + Telegram).
    KERIM_REPLACE: тот же тест после замены на KerimsAgent — формат сообщения идентичен.
    """
    pytest.importorskip("yfinance")
    pytest.importorskip("finvizfinance")

    import config_loader
    token, chat_id = require_telegram_settings

    from domain import TickerData
    from pipeline.technical import LseHeuristicAgent
    from sources.candles import Source as CandleSource
    from sources.metrics import Source as MetricsSource

    ctx_tickers = config_loader.get_game5m_context_tickers()
    fetch = list(set(game5m_tickers + ctx_tickers))

    try:
        src = CandleSource(with_prepostmarket=False)
        daily  = src.get_daily_candles(fetch, days=30)
        hourly = src.get_hourly_candles(fetch, days=5)
        metrics_list = MetricsSource().get_metrics(fetch)
    except Exception as exc:
        pytest.skip(f"Источники данных недоступны: {exc}")

    ticker_data = [
        TickerData(
            ticker=t,
            current_price=daily[t][-1].close,
            daily_candles=daily[t],
            hourly_candles=hourly.get(t, []),
        )
        for t in fetch
        if t in daily and daily[t]
    ]
    metrics_by_ticker = {m.ticker: m for m in metrics_list}

    agent = LseHeuristicAgent()
    lines = []
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    for ticker in game5m_tickers:
        if ticker not in metrics_by_ticker:
            lines.append(f"⚠️ {ticker.value} — нет метрик")
            continue
        if not any(td.ticker == ticker for td in ticker_data):
            lines.append(f"⚠️ {ticker.value} — нет свечей")
            continue
        sig = agent.predict(ticker, ticker_data, metrics_list)
        icon = "🟢" if sig.bias > 0.05 else "🔴" if sig.bias < -0.05 else "⚪"
        price = sig.target_snapshot.data.current_price
        rsi   = sig.target_snapshot.metrics.rsi_14
        lines.append(
            f"{icon} *{ticker.value}* `${price:.2f}`  "
            f"bias `{sig.bias:+.3f}`  RSI `{rsi:.0f}`  conf `{sig.confidence:.2f}`"
        )

    if not lines:
        pytest.skip("Нет данных ни для одного GAME_5M тикера")

    text = f"📊 *GAME\\_5M signals* — {ts}\n\n" + "\n".join(lines)
    text += "\n\n_baseline: LseHeuristicAgent_"

    result = _tg(
        token, "sendMessage",
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
    )
    assert result["message_id"] > 0
    print(f"\nGAME_5M signals → Telegram: {len(lines)} tickers  msg_id={result['message_id']}")
