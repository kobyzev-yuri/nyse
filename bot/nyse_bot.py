"""
NyseBot — Telegram-бот для nyse news+technical pipeline.

Команды:
    /start          — приветствие
    /help           — список команд
    /signal TICKER  — полный сигнал: tech + news → Trade
    /scan           — снапшот всех GAME_5M тикеров (техника)
    /news TICKER    — заголовки + FinBERT-сентимент
    /status         — статус рынка (NYSE open/closed)

Запуск:
    cd /media/cnn/home/cnn/lse/nyse
    conda run -n py11 python scripts/run_bot.py

KERIM_REPLACE: в _worker_scan и _worker_signal заменить LseHeuristicAgent
на KerimsAgent — одна строка, интерфейс predict() идентичен.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from functools import partial
from pathlib import Path
from typing import List, Optional, Tuple

# Подключаем корень nyse в sys.path при прямом запуске из scripts/
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

import config_loader

log = logging.getLogger(__name__)

# Горизонт загрузки свечей (используется в обоих воркерах)
DAILY_DAYS  = 30
HOURLY_DAYS = 5


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _make_ticker(raw: str):
    """Строка → domain.Ticker; ValueError если тикер не в перечне."""
    from domain import Ticker
    try:
        return Ticker(raw.upper())
    except ValueError:
        raise ValueError(f"Неизвестный тикер: {raw.upper()}")


def _escape_md(text: str) -> str:
    """Экранирует символы Telegram Markdown v1: * _ [ ] `"""
    if not text:
        return ""
    s = str(text)
    for c in ("\\", "_", "*", "[", "]", "`"):
        s = s.replace(c, "\\" + c)
    return s


# ---------------------------------------------------------------------------
# Общий хелпер загрузки рыночных данных
# Используется в _worker_scan и _worker_signal.
# ---------------------------------------------------------------------------

def _load_market_data(fetch: list) -> Tuple[dict, list]:
    """
    Загружает свечи (yfinance) и метрики (Finviz) для списка тикеров.

    Parameters
    ----------
    fetch : список Ticker для загрузки (GAME_5M + контекст).

    Returns
    -------
    ticker_data : Dict[Ticker, TickerData] — только тикеры с данными.
    metrics_list : List[TickerMetrics] — пустой список если Finviz недоступен.
    """
    from domain import TickerData
    from sources.candles import Source as CandleSource
    from sources.metrics import Source as MetricsSource

    src    = CandleSource(with_prepostmarket=False)
    daily  = src.get_daily_candles(fetch, days=DAILY_DAYS)
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

    try:
        metrics_list = list(MetricsSource().get_metrics(list(ticker_data.keys())))
    except Exception:
        # Finviz может быть недоступен — агент работает без метрик (degrade gracefully)
        metrics_list = []

    return ticker_data, metrics_list


# ---------------------------------------------------------------------------
# Синхронные воркеры (запускаются в thread executor чтобы не блокировать loop)
# ---------------------------------------------------------------------------

def _worker_scan() -> str:
    """
    Технический снапшот всех GAME_5M тикеров → строка для Telegram.

    Использует LseHeuristicAgent для всех тикеров и форматирует таблицу.
    """
    from pipeline.technical import LseHeuristicAgent
    from pipeline import format_signal_table

    game5m  = config_loader.get_game5m_tickers()
    context = config_loader.get_game5m_context_tickers()
    fetch   = list(set(game5m + context))

    ticker_data, metrics_list = _load_market_data(fetch)
    if not ticker_data:
        return "yfinance не вернул данных."

    # KERIM_REPLACE: заменить LseHeuristicAgent на KerimsAgent:
    #   from pystockinvest.agent.market.agent import Agent as KerimsAgent
    #   from pipeline.llm_factory import get_chat_model
    #   agent = KerimsAgent(llm=get_chat_model())
    #   Интерфейс predict(ticker, ticker_data, metrics) → TechnicalSignal идентичен.
    agent   = LseHeuristicAgent()
    td_list = list(ticker_data.values())

    pairs = []
    for t in game5m:
        if t not in ticker_data:
            continue
        sig = agent.predict(t, td_list, metrics_list)
        pairs.append((t.value, sig))

    if not pairs:
        return "Нет сигналов."

    header = "📊 *GAME\\_5M — технический снапшот*\n\n"
    return header + f"```\n{format_signal_table(pairs)}\n```"


def _worker_signal(ticker_str: str) -> str:
    """
    Полный pipeline L0-L6 для одного тикера → сообщение для Telegram.

    Уровни:
        L0-L1  yfinance + Finviz → TickerData, TickerMetrics
        L2     LseHeuristicAgent → TechnicalSignal
        L3-L4  Yahoo News → FinBERT → DraftImpulse → Gate (SKIP/LITE/FULL)
        L5     LLM (если gate=FULL/LITE) → AggregatedNewsSignal
        L6     TradeBuilder → Trade → format_trade
    """
    from domain import SignalBundle, TickerData  # noqa: F401 (TickerData нужен _load_market_data)
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

    ticker = _make_ticker(ticker_str)

    game5m  = config_loader.get_game5m_tickers()
    context = config_loader.get_game5m_context_tickers()
    fetch   = list(set(game5m + context))

    ticker_data, metrics_list = _load_market_data(fetch)
    if ticker not in ticker_data:
        return f"Нет данных yfinance для {ticker_str.upper()}."

    # --- L2: технический сигнал ---
    # KERIM_REPLACE: заменить LseHeuristicAgent на KerimsAgent:
    #   from pystockinvest.agent.market.agent import Agent as KerimsAgent
    #   from pipeline.llm_factory import get_chat_model
    #   agent = KerimsAgent(llm=get_chat_model())
    agent = LseHeuristicAgent()
    sig   = agent.predict(ticker, list(ticker_data.values()), metrics_list)

    # --- L3: загрузка новостей и cheap_sentiment (FinBERT / API / price_pattern_boost) ---
    articles = NewsSource(max_per_ticker=12, lookback_hours=72).get_articles([ticker])
    articles = [a for a in articles if a.ticker == ticker]
    articles = enrich_cheap_sentiment(articles)

    # --- L3: черновой импульс по каналам (INCREMENTAL / REGIME / POLICY) ---
    scored = scored_from_news_articles(articles)
    di     = draft_impulse(scored)
    bias   = single_scalar_draft_bias(di)

    # --- L4: гейт — решаем нужен ли LLM ---
    gate_ctx = GateContext(
        draft_bias=bias,
        regime_present=di.regime_stress > PROFILE_GAME5M.regime_stress_min,
        regime_rule_confidence=0.85 if di.regime_stress > PROFILE_GAME5M.regime_stress_min else 0.0,
        calendar_high_soon=False,  # CalendarAgent — заглушка (KERIM_REPLACE: neutral_calendar_signal)
        article_count=len(articles),
    )
    mode = decide_llm_mode(PROFILE_GAME5M, gate_ctx)

    # --- L5: LLM-агрегация новостей (только если gate=FULL или LITE) ---
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

    # --- L6: fusion → Trade ---
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
    """
    Заголовки за 48 ч + cheap_sentiment (FinBERT / API / price_pattern_boost)
    для тикера → сообщение для Telegram.

    cheap_sentiment: число [-1, 1]:
        > +0.05  → ▲ позитив
        < -0.05  → ▼ негатив
        иначе    → ■ нейтраль
    Канал: INC (incremental) / REG (regime-macro) / POL (policy/rates).
    """
    from sources.news import Source as NewsSource
    from pipeline.sentiment import enrich_cheap_sentiment
    from pipeline import classify_channel

    ticker   = _make_ticker(ticker_str)
    articles = NewsSource(max_per_ticker=10, lookback_hours=48).get_articles([ticker])
    articles = [a for a in articles if a.ticker == ticker]
    if not articles:
        return f"Новостей для {ticker_str.upper()} не найдено."

    articles = enrich_cheap_sentiment(articles)

    lines = [f"📰 *{ticker_str.upper()} — новости (48 ч)*\n"]
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

    # EDT (UTC-4) действует апрель–октябрь; зимой EST (UTC-5).
    # Для учёта перехода на зимнее время используй zoneinfo.ZoneInfo("America/New_York").
    ET     = timezone(timedelta(hours=-4))
    now_et = datetime.now(ET)
    hour   = now_et.hour
    minute = now_et.minute

    time_str = now_et.strftime("%H:%M ET, %a %b %d")

    if now_et.weekday() >= 5:
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
# Async helpers
# ---------------------------------------------------------------------------

async def _run_in_thread(func, *args):
    """Запускает синхронную функцию в thread executor, не блокируя event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args))


async def _send_thinking(update: Update) -> None:
    await update.message.reply_text("⏳ Считаю…")


async def _reply(update: Update, text: str) -> None:
    """Отправляет сообщение с Markdown; длинные разбивает на части по 4000 символов."""
    MAX    = 4000
    chunks = [text[i:i + MAX] for i in range(0, len(text), MAX)] if len(text) > MAX else [text]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)


async def _reply_error(update: Update, text: str) -> None:
    """Сообщение об ошибке plain text — спецсимволы в трейсбеке не ломают парсер."""
    await update.message.reply_text(text)


# ---------------------------------------------------------------------------
# Command handlers
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
        "/news `TICKER` — заголовки + FinBERT за 48 ч\n"
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
    """Собирает PTB Application с хендлерами команд и опциональным прокси."""
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
