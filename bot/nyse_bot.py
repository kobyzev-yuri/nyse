"""
NyseBot — Telegram-бот для nyse news+technical pipeline.

Команды:
    /start          — приветствие
    /help           — список команд
    /signal TICKER  — полный сигнал: tech + news → Trade
    /scan           — снапшот всех GAME_5M тикеров (техника)
    /news TICKER    — последние заголовки + FinBERT
    /status         — статус рынка (NYSE open/closed)

Запуск:
    cd /media/cnn/home/cnn/lse/nyse
    conda run -n py11 python scripts/run_bot.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
from functools import partial
from pathlib import Path
from typing import Optional

# Подключаем корень nyse в sys.path при прямом запуске
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

import config_loader

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GAME_5M тикеры (загружаются один раз при старте)
# ---------------------------------------------------------------------------

DAILY_DAYS  = 30
HOURLY_DAYS = 5


def _make_ticker(raw: str):
    """Строка → domain.Ticker; ValueError если не распознан."""
    from domain import Ticker
    try:
        return Ticker(raw.upper())
    except ValueError:
        raise ValueError(f"Неизвестный тикер: {raw.upper()}")


# ---------------------------------------------------------------------------
# Синхронные воркеры (запускаются в executor)
# ---------------------------------------------------------------------------

def _worker_scan() -> str:
    """Технический снапшот всех GAME_5M тикеров → строка для Telegram."""
    from domain import TickerData
    from sources.candles import Source as CandleSource
    from sources.metrics import Source as MetricsSource
    from pipeline.technical import LseHeuristicAgent
    from pipeline import format_signal_table

    game5m  = config_loader.get_game5m_tickers()
    context = config_loader.get_game5m_context_tickers()
    fetch   = list(set(game5m + context))

    src    = CandleSource(with_prepostmarket=False)
    daily  = src.get_daily_candles(fetch,  days=DAILY_DAYS)
    hourly = src.get_hourly_candles(fetch, days=HOURLY_DAYS)

    ticker_data: dict = {}
    for t in fetch:
        d = daily.get(t, [])
        if not d:
            continue
        ticker_data[t] = TickerData(
            ticker=t,
            current_price=d[-1].close,
            daily_candles=d,
            hourly_candles=hourly.get(t, []),
        )
    if not ticker_data:
        return "yfinance не вернул данных."

    try:
        metrics_list = MetricsSource().get_metrics(list(ticker_data.keys()))
    except Exception:
        metrics_list = []

    agent    = LseHeuristicAgent()
    td_list  = list(ticker_data.values())
    m_list   = list(metrics_list) if metrics_list else []

    pairs = []
    for t in game5m:
        if t not in ticker_data:
            continue
        sig = agent.predict(t, td_list, m_list)
        pairs.append((t.value, sig))

    if not pairs:
        return "Нет сигналов."

    header = "📊 *GAME\\_5M — технический снапшот*\n\n"
    return header + f"```\n{format_signal_table(pairs)}\n```"


def _worker_signal(ticker_str: str) -> str:
    """Полный pipeline L0-L6 для одного тикера → сообщение для Telegram."""
    from domain import Direction, SignalBundle, PositionType, TickerData
    from sources.candles import Source as CandleSource
    from sources.metrics import Source as MetricsSource
    from sources.news import Source as NewsSource
    from pipeline.technical import LseHeuristicAgent
    from pipeline.sentiment import enrich_cheap_sentiment
    from pipeline.draft import scored_from_news_articles
    from pipeline import (
        draft_impulse, single_scalar_draft_bias,
        GateContext, decide_llm_mode, PROFILE_GAME5M,
        TradeBuilder, neutral_calendar_signal,
        format_trade, run_news_signal_pipeline,
    )
    from pipeline.trade_builder import FusedBias

    ticker = _make_ticker(ticker_str)

    game5m  = config_loader.get_game5m_tickers()
    context = config_loader.get_game5m_context_tickers()
    fetch   = list(set(game5m + context))

    # --- Данные ---
    src    = CandleSource(with_prepostmarket=False)
    daily  = src.get_daily_candles(fetch,  days=DAILY_DAYS)
    hourly = src.get_hourly_candles(fetch, days=HOURLY_DAYS)

    ticker_data: dict = {}
    for t in fetch:
        d = daily.get(t, [])
        if not d:
            continue
        ticker_data[t] = TickerData(
            ticker=t,
            current_price=d[-1].close,
            daily_candles=d,
            hourly_candles=hourly.get(t, []),
        )
    if ticker not in ticker_data:
        return f"Нет данных yfinance для {ticker_str.upper()}."

    try:
        metrics_list = MetricsSource().get_metrics(list(ticker_data.keys()))
    except Exception:
        metrics_list = []

    # --- Технический сигнал ---
    agent = LseHeuristicAgent()
    sig   = agent.predict(ticker, list(ticker_data.values()), list(metrics_list))

    # --- Новостной pipeline ---
    articles = NewsSource(max_per_ticker=12, lookback_hours=72).get_articles([ticker])
    articles = [a for a in articles if a.ticker == ticker]
    articles = enrich_cheap_sentiment(articles)

    scored  = scored_from_news_articles(articles)
    di      = draft_impulse(scored)
    bias    = single_scalar_draft_bias(di)

    gate_ctx = GateContext(
        draft_bias=bias,
        regime_present=di.regime_stress > PROFILE_GAME5M.regime_stress_min,
        regime_rule_confidence=0.85 if di.regime_stress > PROFILE_GAME5M.regime_stress_min else 0.0,
        calendar_high_soon=False,
        article_count=len(articles),
    )
    mode = decide_llm_mode(PROFILE_GAME5M, gate_ctx)

    news_signal = None
    if mode.value in ("full", "lite"):
        oai = config_loader.get_openai_settings()
        if oai:
            news_signal = run_news_signal_pipeline(
                articles, ticker.value,
                cfg=PROFILE_GAME5M,
                mode=mode,
                settings=oai,
            )

    # --- Trade ---
    bundle = SignalBundle(
        ticker=ticker,
        technical_signal=sig,
        news_signal=news_signal,
        calendar_signal=neutral_calendar_signal(),
    )
    builder = TradeBuilder()
    trade   = builder.build(bundle)
    fused   = builder.fuse_bias(sig, news_signal)

    return format_trade(trade, fused=fused, include_details=True)


def _worker_news(ticker_str: str) -> str:
    """Последние заголовки + FinBERT для тикера → сообщение для Telegram."""
    from sources.news import Source as NewsSource
    from pipeline.sentiment import enrich_cheap_sentiment
    from pipeline import classify_channel

    ticker = _make_ticker(ticker_str)
    articles = NewsSource(max_per_ticker=10, lookback_hours=48).get_articles([ticker])
    articles = [a for a in articles if a.ticker == ticker]
    if not articles:
        return f"Новостей для {ticker_str.upper()} не найдено."

    articles = enrich_cheap_sentiment(articles)

    lines = [f"📰 *{ticker_str.upper()} — последние новости*\n"]
    for a in articles[:10]:
        score = a.cheap_sentiment or 0.0
        ch    = classify_channel(a.title, getattr(a, "summary", None))[0].value[:3].upper()
        bar   = "▲" if score > 0.05 else ("▼" if score < -0.05 else "■")
        title = _escape_md(a.title[:80])
        lines.append(f"{bar} [{ch}] {title}")
        lines.append(f"   score={score:+.2f}")

    return "\n".join(lines)


def _worker_status() -> str:
    """Статус NYSE (open/closed) + текущее время ET."""
    from datetime import datetime, timezone, timedelta

    ET = timezone(timedelta(hours=-4))  # EDT
    now_et = datetime.now(ET)
    weekday = now_et.weekday()         # 0=Mon, 6=Sun
    hour    = now_et.hour
    minute  = now_et.minute

    is_weekend = weekday >= 5
    time_str = now_et.strftime("%H:%M ET, %a %b %d")

    if is_weekend:
        status = "🔴 Закрыто (выходной)"
    elif (hour, minute) >= (9, 30) and (hour, minute) < (16, 0):
        status = "🟢 Открыто"
    elif (hour, minute) < (9, 30):
        mins_to_open = (9 * 60 + 30) - (hour * 60 + minute)
        status = f"🟡 Предрынок (откроется через {mins_to_open} мин)"
    else:
        status = "🔴 Закрыто (постмаркет)"

    return f"🏛 *NYSE статус*\n{status}\n{time_str}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _escape_md(text: str) -> str:
    """Экранирует символы, ломающие Telegram Markdown v1 (* _ [ ] `)."""
    if not text:
        return ""
    s = str(text)
    for c in ("\\", "_", "*", "[", "]", "`"):
        s = s.replace(c, "\\" + c)
    return s


async def _run_in_thread(func, *args):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args))


async def _send_thinking(update: Update) -> None:
    await update.message.reply_text("⏳ Считаю…")


async def _reply(update: Update, text: str) -> None:
    """Отправляет сообщение; если слишком длинное — разбивает на части."""
    MAX = 4000
    chunks = [text[i:i + MAX] for i in range(0, len(text), MAX)] if len(text) > MAX else [text]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)


async def _reply_error(update: Update, text: str) -> None:
    """Ошибка plain text — без Markdown (спецсимволы не ломают сообщение)."""
    await update.message.reply_text(text)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *NYSE Signal Bot*\n\n"
        "Анализирует рынок: технический анализ + новостной пайплайн.\n\n"
        "Используй /help для списка команд."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *Команды*\n\n"
        "/signal `TICKER` — полный сигнал (tech + news → Trade)\n"
        "   _Пример:_ `/signal SNDK`\n\n"
        "/scan — снапшот всех GAME\\_5M тикеров (техника)\n\n"
        "/news `TICKER` — последние заголовки + FinBERT\n"
        "   _Пример:_ `/news MU`\n\n"
        "/status — статус NYSE (открыто / закрыто)\n\n"
        "/help — это сообщение\n\n"
        "──────────────────\n"
        "GAME\\_5M тикеры: SNDK, NBIS, ASML, MU, LITE, CIEN\n"
        "Технический агент: LseHeuristicAgent\n"
        "Новостной pipeline: FinBERT → Gate → LLM (если нужно)"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_thinking(update)
    try:
        result = await _run_in_thread(_worker_scan)
        await _reply(update, result)
    except Exception as exc:
        log.exception("scan error")
        await _reply_error(update, f"❌ Ошибка: {exc}")


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Укажи тикер: `/signal SNDK`", parse_mode=ParseMode.MARKDOWN)
        return
    ticker_str = args[0].upper()
    await _send_thinking(update)
    try:
        result = await _run_in_thread(_worker_signal, ticker_str)
        await _reply(update, result)
    except ValueError as exc:
        await _reply_error(update, f"❌ {exc}")
    except Exception as exc:
        log.exception("signal error for %s", ticker_str)
        await _reply_error(update, f"❌ Ошибка: {exc}")


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Укажи тикер: `/news MU`", parse_mode=ParseMode.MARKDOWN)
        return
    ticker_str = args[0].upper()
    await _send_thinking(update)
    try:
        result = await _run_in_thread(_worker_news, ticker_str)
        await _reply(update, result)
    except ValueError as exc:
        await _reply_error(update, f"❌ {exc}")
    except Exception as exc:
        log.exception("news error for %s", ticker_str)
        await _reply_error(update, f"❌ Ошибка: {exc}")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = await _run_in_thread(_worker_status)
        await _reply(update, result)
    except Exception as exc:
        await _reply_error(update, f"❌ Ошибка: {exc}")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def build_application(token: str, proxy: Optional[str] = None) -> Application:
    builder = Application.builder().token(token)
    if proxy:
        builder = builder.proxy(proxy).get_updates_proxy(proxy)
        log.info("Telegram proxy: %s", proxy)
    app = builder.build()
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("scan",   cmd_scan))
    app.add_handler(CommandHandler("signal", cmd_signal))
    app.add_handler(CommandHandler("news",   cmd_news))
    app.add_handler(CommandHandler("status", cmd_status))
    return app
