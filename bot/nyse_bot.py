"""
NyseBot — Telegram-бот для nyse news+technical pipeline.

Команды:
    /start          — приветствие
    /help           — список команд
    /trade TICKER   — агрегат для входа: tech + news → Trade (HTML)
    /signal TICKER  — полный отчёт L0–L6 (как бывший /news_signal)
    /scan           — снапшот всех GAME_5M тикеров (техника)
    /news TICKER    — новости, геополитика, макро-календарь (без торгового пайплайна)
    /status         — статус рынка (NYSE open/closed)

Запуск:
    cd /path/to/nyse
    conda run -n py11 python scripts/run_bot.py

Structured LLM (как pystockinvest): ``NYSE_LLM_TECHNICAL=1`` — ``LlmTechnicalAgent``;
``NYSE_LLM_CALENDAR=1`` — ``CalendarLlmAgent`` (см. ``config_loader``).
По умолчанию техника — ``LseHeuristicAgent``, календарь — нейтральный сигнал без LLM.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

# Подключаем корень nyse в sys.path при прямом запуске из scripts/
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from telegram import Update
from telegram.constants import ParseMode
from telegram.error import TimedOut, NetworkError
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest

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


def _h(text: str) -> str:
    """HTML-экранирование для безопасной вставки динамического контента."""
    import html
    return html.escape(str(text))


# ---------------------------------------------------------------------------
# Общий хелпер загрузки рыночных данных
# Используется в _worker_scan и _worker_trade / _worker_signal.
# ---------------------------------------------------------------------------

def _load_calendar_events():
    """
    Экономический календарь (Investing.com API), тот же источник, что в pystockinvest ``sources.ecalendar``.
    При ошибке сети / парсинга возвращает пустой список.
    """
    try:
        from domain import Currency
        from sources.ecalendar import Source as CalendarSource

        return CalendarSource([Currency.GBP, Currency.JPY, Currency.EUR]).get_calendar()
    except Exception:
        log.warning("ecalendar: не удалось загрузить события", exc_info=True)
        return []


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

def _worker_scan() -> Tuple[str, str]:
    """
    Технический снапшот всех GAME_5M тикеров.

    Returns
    -------
    (short_text, html_content) — текст для чата и HTML-отчёт для reply_document.
    """
    from pipeline.technical import LseHeuristicAgent
    from pipeline import format_signal_table
    from pipeline.html_report import build_scan_html

    game5m  = config_loader.get_game5m_tickers()
    context = config_loader.get_game5m_context_tickers()
    fetch   = list(set(game5m + context))

    ticker_data, metrics_list = _load_market_data(fetch)
    if not ticker_data:
        return "yfinance не вернул данных.", ""

    # /scan — только быстрые эвристики (без LLM); /signal может использовать LlmTechnicalAgent.
    agent   = LseHeuristicAgent()
    td_list = list(ticker_data.values())

    pairs = []
    for t in game5m:
        if t not in ticker_data:
            continue
        sig = agent.predict(t, td_list, metrics_list)
        pairs.append((t.value, sig))

    if not pairs:
        return "Нет сигналов.", ""

    short = "📊 <b>GAME_5M — технический снапшот</b>\n\n" + f"<pre>{format_signal_table(pairs)}</pre>"
    html  = build_scan_html([(t, s) for t, s in pairs])
    return short, html


def _worker_trade(ticker_str: str) -> Tuple[str, str]:
    """
    Полный pipeline L0-L6 для одного тикера.

    Уровни:
        L0-L1  yfinance + Finviz → TickerData, TickerMetrics
        L2     LseHeuristicAgent или LlmTechnicalAgent (см. NYSE_LLM_TECHNICAL) → TechnicalSignal
        L3-L4  Новости (окно ``NYSE_NEWS_LOOKBACK_SIGNAL_HOURS``, дефолт 72 ч) → FinBERT → DraftImpulse → Gate
        L5     LLM новостей (если gate=FULL/LITE) → AggregatedNewsSignal
        L6     TradeBuilder (+ CalendarLlmAgent при NYSE_LLM_CALENDAR) → Trade

    Returns
    -------
    (short_text, html_content) — краткое сообщение в чат + HTML-отчёт для reply_document.
    """
    from datetime import datetime, timezone

    from domain import SignalBundle, TickerData  # noqa: F401 (TickerData нужен _load_market_data)
    from sources.news import Source as NewsSource
    from pipeline.calendar_llm_agent import CalendarLlmAgent
    from pipeline.technical import LlmTechnicalAgent, LseHeuristicAgent
    from pipeline.sentiment import enrich_cheap_sentiment
    from pipeline.draft import scored_from_news_articles
    from pipeline import (
        build_gate_context,
        draft_impulse, single_scalar_draft_bias,
        decide_llm_mode,
        TradeBuilder, neutral_calendar_signal,
        format_trade, run_news_signal_pipeline,
    )
    from pipeline.html_report import build_trade_html

    gate_cfg = config_loader.get_pipeline_gate_threshold()
    ticker = _make_ticker(ticker_str)

    game5m  = config_loader.get_game5m_tickers()
    context = config_loader.get_game5m_context_tickers()
    fetch   = list(set(game5m + context))

    ticker_data, metrics_list = _load_market_data(fetch)
    if ticker not in ticker_data:
        return f"Нет данных yfinance для {ticker_str.upper()}.", ""

    cal_events = _load_calendar_events()
    oai = config_loader.get_openai_settings()
    now = datetime.now(timezone.utc)

    # --- L2: технический сигнал (эвристика или structured LLM — NYSE_LLM_TECHNICAL=1) ---
    if oai and config_loader.use_llm_technical_signal():
        tech_agent = LlmTechnicalAgent(settings=oai)
        sig = tech_agent.predict(ticker, list(ticker_data.values()), metrics_list)
    else:
        tech_agent = LseHeuristicAgent()
        sig = tech_agent.predict(ticker, list(ticker_data.values()), metrics_list)

    # --- L3: загрузка новостей и cheap_sentiment (FinBERT / API / price_pattern_boost) ---
    lb = config_loader.news_lookback_hours_signal()
    articles = NewsSource(max_per_ticker=12, lookback_hours=lb).get_articles([ticker])
    articles = [a for a in articles if a.ticker == ticker]
    articles = enrich_cheap_sentiment(articles)

    # --- L3: черновой импульс по каналам (INCREMENTAL / REGIME / POLICY) ---
    scored = scored_from_news_articles(articles)
    di     = draft_impulse(scored)
    bias   = single_scalar_draft_bias(di)

    # --- L4: гейт — решаем нужен ли LLM новостей (календарь влияет на FULL) ---
    gate_ctx = build_gate_context(
        draft_bias=bias,
        regime_present=di.regime_stress > gate_cfg.regime_stress_min,
        regime_rule_confidence=0.85 if di.regime_stress > gate_cfg.regime_stress_min else 0.0,
        calendar_events=cal_events,
        article_count=len(articles),
        now=now,
    )
    mode = decide_llm_mode(gate_cfg, gate_ctx)

    # --- L5: LLM-агрегация новостей (только если gate=FULL или LITE) ---
    news_signal = None
    if mode.value in ("full", "lite"):
        if oai:
            news_signal = run_news_signal_pipeline(
                articles, ticker.value,
                cfg=gate_cfg,
                mode=mode,
                settings=oai,
            )

    # --- L6: календарь (нейтраль или structured LLM — NYSE_LLM_CALENDAR=1) ---
    if oai and config_loader.use_llm_calendar_signal() and cal_events:
        cal_agent = CalendarLlmAgent(
            settings=oai,
            batch_size=config_loader.calendar_llm_batch_size(),
        )
        calendar_signal = cal_agent.predict(ticker, cal_events)
    else:
        calendar_signal = neutral_calendar_signal()

    # --- L6: fusion → Trade ---
    bundle = SignalBundle(
        ticker=ticker,
        technical_signal=sig,
        news_signal=news_signal,
        calendar_signal=calendar_signal,
    )
    builder = TradeBuilder()
    trade   = builder.build(bundle)
    fused   = builder.fuse_bias(sig, news_signal, calendar_signal)

    short_text = format_trade(trade, fused=fused, include_details=True)
    html_content = build_trade_html(
        trade,
        fused=fused,
        articles=articles,
        calendar_events=cal_events,
        calendar_high_soon=gate_ctx.calendar_high_soon,
        calendar_report_time=now,
        headlines_lookback_hours=lb,
    )
    return short_text, html_content


def _worker_news(ticker_str: str) -> Tuple[str, str]:
    """
    Новости + геополитика (каналы) и макро-календарь; без L2–L6 торгового пайплайна.

    cheap_sentiment [-1, 1]:  > +0.05 → ▲,  < -0.05 → ▼,  иначе → ■
    Канал: INC (incremental) / REG (regime-macro) / POL (policy/rates).

    Returns
    -------
    (short_text, html_content) — краткий список в чате + полный HTML-отчёт.
    """
    from datetime import datetime, timezone

    from sources.news import Source as NewsSource
    from pipeline.sentiment import enrich_cheap_sentiment
    from pipeline.telegram_format import format_news_list
    from pipeline.calendar_context import calendar_high_soon
    from pipeline.html_report import build_news_html

    ticker   = _make_ticker(ticker_str)
    lb = config_loader.news_lookback_hours_news_cmd()
    articles = NewsSource(max_per_ticker=10, lookback_hours=lb).get_articles([ticker])
    articles = [a for a in articles if a.ticker == ticker]
    if not articles:
        return f"Новостей для <b>{_h(ticker_str.upper())}</b> не найдено.", ""

    articles = enrich_cheap_sentiment(articles)
    short_text   = format_news_list(ticker_str.upper(), articles, lookback_hours=lb)

    now = datetime.now(timezone.utc)
    cal_events: list = []
    cal_err = None
    try:
        from domain import Currency
        from sources.ecalendar import Source as CalendarSource

        cal_events = list(CalendarSource([Currency.GBP, Currency.JPY, Currency.EUR]).get_calendar())
    except Exception as exc:
        cal_err = f"{type(exc).__name__}: {exc}"[:400]

    gch = calendar_high_soon(cal_events, now=now)
    html_content = build_news_html(
        ticker_str.upper(),
        articles,
        lookback_hours=lb,
        calendar_events=cal_events,
        calendar_high_soon=gch,
        calendar_report_time=now,
        calendar_load_error=cal_err,
    )
    return short_text, html_content


def _worker_signal(ticker_str: str) -> Tuple[str, str]:
    """
    Команда /signal: полный прогон pipeline L0–L6 → подробный HTML (техника, fusion, статьи, гейт, LLM, trade).

    В чат — кратко; весь разбор — в HTML-документе (секции ①–⑦).
    """
    from pipeline.debug_runner import run_debug_pipeline
    from pipeline.html_report import build_debug_report_html

    ticker = _make_ticker(ticker_str)

    game5m  = config_loader.get_game5m_tickers()
    context = config_loader.get_game5m_context_tickers()
    fetch   = list(set(game5m + context))

    ticker_data, metrics_list = _load_market_data(fetch)
    if ticker not in ticker_data:
        return f"Нет данных yfinance для {ticker_str.upper()}.", ""

    oai = config_loader.get_openai_settings()
    trace = run_debug_pipeline(
        ticker,
        ticker_data,
        metrics_list,
        settings=oai,
    )

    html_content = build_debug_report_html(trace)

    p = trace.trade.position
    if p is not None:
        side = "▲ LONG" if p.side.value == "long" else "▼ SHORT"
        short = (
            f"📡 <b>Полный сигнал: {_h(ticker_str.upper())}</b>\n"
            f"{side}  Entry ${p.entry:,.2f} · TP {(p.take_profit-p.entry)/p.entry*100:+.1f}%"
            f" · SL {(p.stop_loss-p.entry)/p.entry*100:+.1f}%\n"
            f"Fused {trace.fused.value:+.3f} · Gate <b>{trace.llm_mode.upper()}</b>\n"
            f"📎 Детальный отчёт — в документе"
        )
    else:
        short = (
            f"📡 <b>Полный сигнал: {_h(ticker_str.upper())}</b>\n"
            f"NO TRADE · Fused {trace.fused.value:+.3f} · Gate <b>{trace.llm_mode.upper()}</b>\n"
            f"📎 Детальный отчёт — в документе"
        )

    return short, html_content


def _worker_status() -> str:
    """Статус торговой сессии NYSE/NASDAQ + текущее время ET."""
    from datetime import datetime, timezone, timedelta

    # EDT (UTC-4) действует апрель–октябрь; зимой EST (UTC-5).
    # Для учёта перехода на зимнее время используй zoneinfo.ZoneInfo("America/New_York").
    ET     = timezone(timedelta(hours=-4))
    now_et = datetime.now(ET)
    hour   = now_et.hour
    minute = now_et.minute

    time_str = now_et.strftime("%H:%M ET  ·  %a %d %b %Y")

    if now_et.weekday() >= 5:
        status = "🔴 <b>Закрыто</b> — выходной"
        detail = "Торги пн–пт, 09:30–16:00 ET"
    elif (hour, minute) >= (9, 30) and (hour, minute) < (16, 0):
        mins_left = (16 * 60) - (hour * 60 + minute)
        status = f"🟢 <b>Основная сессия</b> — закроется через {mins_left} мин"
        detail = "NYSE/NASDAQ regular hours · 09:30–16:00 ET"
    elif (hour, minute) < (4, 0):
        status = "🔴 <b>Закрыто</b> — ночь"
        detail = "Премаркет начнётся в 04:00 ET"
    elif (hour, minute) < (9, 30):
        mins_to_open = (9 * 60 + 30) - (hour * 60 + minute)
        status = f"🟡 <b>Премаркет</b> — основная сессия через {mins_to_open} мин"
        detail = "Ограниченная ликвидность · 04:00–09:30 ET"
    else:
        mins_since = (hour * 60 + minute) - (16 * 60)
        status = f"🟠 <b>Постмаркет</b> — {mins_since} мин после закрытия"
        detail = "Ограниченная ликвидность · 16:00–20:00 ET"

    return (
        f"🏛 <b>NYSE/NASDAQ — торговая сессия</b>\n\n"
        f"{status}\n"
        f"<i>{detail}</i>\n\n"
        f"<code>{time_str}</code>"
    )


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------

async def _run_in_thread(func, *args):
    """Запускает синхронную функцию в thread executor, не блокируя event loop."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(func, *args))


async def _send_thinking(update: Update) -> None:
    try:
        await update.message.reply_text("⏳ Считаю…")
    except Exception:
        pass  # не критично — просто не покажем "считаю"


async def _reply(update: Update, text: str) -> None:
    """Отправляет HTML-сообщение; длинные разбивает на части по 4000 символов."""
    MAX    = 4000
    chunks = [text[i:i + MAX] for i in range(0, len(text), MAX)] if len(text) > MAX else [text]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def _reply_error(update: Update, text: str) -> None:
    """Сообщение об ошибке plain text — спецсимволы в трейсбеке не ломают парсер."""
    await update.message.reply_text(text)


async def _reply_document(update: Update, html_content: str, filename: str) -> None:
    """
    Отправляет HTML-контент как документ (открывается в браузере).
    Молча пропускает если html_content пустой.
    """
    if not html_content:
        return
    try:
        buf = BytesIO(html_content.encode("utf-8"))
        await update.message.reply_document(
            document=buf,
            filename=filename,
            caption="📎 Откройте файл в браузере для удобного просмотра",
        )
    except Exception as exc:
        log.warning("Не удалось отправить HTML-файл %s: %s", filename, exc)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 <b>NYSE Signal Bot</b>\n\n"
        "Анализирует рынок: технический анализ + новостной пайплайн.\n\n"
        "Используй /help для списка команд."
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 <b>Команды бота</b>\n\n"

        "💼 /trade <code>TICKER</code>\n"
        "Решение для входа: техника + новости + fusion → Entry/TP/SL (агрегат).\n"
        "В чате — краткое резюме; HTML — в документе.\n"
        "<i>Пример: /trade SNDK</i>\n\n"

        "📡 /signal <code>TICKER</code>\n"
        "Полный отчёт по пайплайну L0–L6: tech, fusion, статьи, DraftImpulse, Gate, LLM, trade.\n"
        "<i>Пример: /signal SNDK</i> (раньше команда называлась <code>/news_signal</code>)\n\n"

        "📊 /scan\n"
        "Снапшот всех GAME_5M тикеров: цена, bias, RSI (~10 сек, без LLM).\n"
        "HTML-таблица — в документе.\n\n"

        "📰 /news <code>TICKER</code>\n"
        "Новости и геополитика (INC/REG/POL) + макро-календарь; без торгового пайплайна.\n"
        "▲ позитив  ■ нейтраль  ▼ негатив · окно ч: NYSE_NEWS_LOOKBACK_NEWS_HOURS\n"
        "<i>Пример: /news MU</i>\n\n"

        "🏛 /status\n"
        "Статус торговой сессии NYSE/NASDAQ и текущее время ET.\n\n"

        "──────────────────\n"
        "<b>Тикеры GAME_5M:</b> SNDK, NBIS, ASML, MU, LITE, CIEN\n"
        "<b>Контекст:</b> SMH, QQQ (не торгуются, используются для market alignment)\n\n"
        "<b>Pipeline:</b>\n"
        "  L2 FinBERT → L3 DraftImpulse → L4 Gate → L5 LLM → L6 Trade"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_thinking(update)
    try:
        from datetime import datetime
        short, html = await _run_in_thread(_worker_scan)
        await _reply(update, short)
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
        await _reply_document(update, html, f"scan_{ts}.html")
    except Exception as exc:
        log.exception("scan error")
        await _reply_error(update, f"❌ Ошибка: {exc}")


async def cmd_trade(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Укажи тикер: <code>/trade SNDK</code>", parse_mode=ParseMode.HTML)
        return
    ticker_str = args[0].upper()
    await _send_thinking(update)
    try:
        from datetime import datetime
        short, html = await _run_in_thread(_worker_trade, ticker_str)
        await _reply(update, short)
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
        await _reply_document(update, html, f"trade_{ticker_str}_{ts}.html")
    except ValueError as exc:
        await _reply_error(update, f"❌ {exc}")
    except Exception as exc:
        log.exception("trade error for %s", ticker_str)
        await _reply_error(update, f"❌ Ошибка: {exc}")


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Укажи тикер: <code>/signal SNDK</code>", parse_mode=ParseMode.HTML)
        return
    ticker_str = args[0].upper()
    await _send_thinking(update)
    try:
        from datetime import datetime
        short, html = await _run_in_thread(_worker_signal, ticker_str)
        await _reply(update, short)
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
        await _reply_document(update, html, f"signal_{ticker_str}_{ts}.html")
    except ValueError as exc:
        await _reply_error(update, f"❌ {exc}")
    except Exception as exc:
        log.exception("signal error for %s", ticker_str)
        await _reply_error(update, f"❌ Ошибка: {exc}")


async def cmd_news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if not args:
        await update.message.reply_text("Укажи тикер: <code>/news MU</code>", parse_mode=ParseMode.HTML)
        return
    ticker_str = args[0].upper()
    await _send_thinking(update)
    try:
        from datetime import datetime
        short, html = await _run_in_thread(_worker_news, ticker_str)
        await _reply(update, short)
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
        await _reply_document(update, html, f"news_{ticker_str}_{ts}.html")
    except ValueError as exc:
        await _reply_error(update, f"❌ {exc}")
    except Exception as exc:
        log.exception("news error for %s", ticker_str)
        await _reply_error(update, f"❌ Ошибка: {exc}")


async def cmd_news_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Совместимость: то же, что /signal."""
    await cmd_signal(update, context)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        result = await _run_in_thread(_worker_status)
        await _reply(update, result)
    except Exception as exc:
        await _reply_error(update, f"❌ Ошибка: {exc}")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирует сетевые ошибки без краша бота."""
    err = context.error
    if isinstance(err, (TimedOut, NetworkError)):
        log.warning("Telegram network error (transient): %s", err)
    else:
        log.exception("Unhandled error: %s", err)


def build_application(token: str, proxy: Optional[str] = None) -> Application:
    """Собирает PTB Application с хендлерами команд и опциональным прокси."""
    # Увеличиваем таймауты для работы через SOCKS5 прокси
    request = HTTPXRequest(
        proxy=proxy,
        read_timeout=30,
        write_timeout=30,
        connect_timeout=15,
        pool_timeout=10,
    )
    get_updates_request = HTTPXRequest(
        proxy=proxy,
        read_timeout=40,   # long-polling держит соединение ~30 сек
        write_timeout=30,
        connect_timeout=15,
        pool_timeout=10,
    )
    if proxy:
        log.info("Telegram proxy: %s", proxy)

    builder = (
        Application.builder()
        .token(token)
        .request(request)
        .get_updates_request(get_updates_request)
    )
    app = builder.build()
    app.add_handler(CommandHandler("start",       cmd_start))
    app.add_handler(CommandHandler("help",        cmd_help))
    app.add_handler(CommandHandler("scan",        cmd_scan))
    app.add_handler(CommandHandler("trade",       cmd_trade))
    app.add_handler(CommandHandler("signal",      cmd_signal))
    app.add_handler(CommandHandler("news",        cmd_news))
    app.add_handler(CommandHandler("news_signal", cmd_news_signal))
    app.add_handler(CommandHandler("status",      cmd_status))
    app.add_error_handler(error_handler)
    return app
