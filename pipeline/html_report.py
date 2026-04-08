"""
HTML-отчёты для Telegram reply_document.

Паттерн аналогичен lse/services/telegram_bot.py::_build_recommend5m_compact_html:
  1. Бот отправляет краткое текстовое сообщение в чат.
  2. Следом отправляет HTML-файл (BytesIO) — открывается в браузере.

Функции возвращают строку HTML (UTF-8).
"""

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import List, Optional

from pipeline.trade_builder import W_CAL, W_NEWS, W_TECH

_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0d1117;
    color: #e6edf3;
    margin: 0;
    padding: 16px;
}
h1 { font-size: 1.3em; margin: 0 0 4px; }
h2 { font-size: 1em; color: #8b949e; margin: 16px 0 6px; border-bottom: 1px solid #30363d; padding-bottom: 4px; }
.meta { color: #8b949e; font-size: 0.85em; margin-bottom: 16px; }
table { border-collapse: collapse; width: 100%; margin-bottom: 8px; }
th { background: #161b22; color: #8b949e; font-size: 0.8em; text-align: left; padding: 6px 10px; }
td { padding: 6px 10px; border-bottom: 1px solid #21262d; font-size: 0.9em; }
tr:hover td { background: #161b22; }
.long  { color: #3fb950; font-weight: bold; }
.short { color: #f85149; font-weight: bold; }
.none  { color: #8b949e; }
.pos   { color: #3fb950; }
.neg   { color: #f85149; }
.neu   { color: #8b949e; }
.tag   { background: #21262d; border-radius: 4px; padding: 1px 6px; font-size: 0.8em; }
.score { font-size: 0.85em; font-family: monospace; }
.summary { color: #c9d1d9; font-size: 0.9em; line-height: 1.5; }
.analysis-box h2 { color: #58a6ff; font-size: 1.05em; margin-top: 0; }
.analysis-box p { margin: 0 0 10px 0; line-height: 1.55; color: #c9d1d9; font-size: 0.9em; }
.analysis-box p:last-child { margin-bottom: 0; }
"""


def _h(text: str) -> str:
    return html.escape(str(text))


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _wrap(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>"
        '<html lang="ru"><head><meta charset="utf-8">'
        f"<title>{_h(title)}</title>"
        f"<style>{_CSS}</style></head><body>"
        f"{body}"
        "</body></html>"
    )


def _debug_auto_analysis_html(t) -> str:
    """
    Краткий автоматический разбор для debug-отчёта (тот же контекст, что таблицы;
    без LLM — только эвристики по числам trace).
    """
    fused = t.fused
    tech = t.tech_signal
    mode_val = getattr(t.llm_mode, "value", str(t.llm_mode)).lower()
    paras: list[str] = []

    if t.trade.position is None:
        _fv = fused.value
        _fcls = "pos" if _fv > 0 else ("neg" if _fv < 0 else "neu")
        paras.append(
            "<strong>Почему NO TRADE:</strong> итоговый fused bias "
            f'<span class="score {_fcls}">{_fv:+.3f}</span>, confidence {fused.confidence:.2f}. '
            "Позиция не строится при слабом сигнале / низкой tradeability / фильтрах TradeBuilder "
            "(см. блок ①)."
        )
    else:
        paras.append(
            "См. блок ①: сформирована позиция (Entry / TP / SL) при прохождении порогов."
        )

    ac = abs(fused.tech_contrib)
    an = abs(fused.news_contrib)
    al = abs(fused.cal_contrib)
    if an >= ac and an >= al and fused.news_available:
        dom = "новости (LLM-агрегат)"
    elif al >= ac and al >= an:
        dom = "календарь"
    else:
        dom = "техника (эвристика)"
    paras.append(
        f"<strong>Fusion:</strong> по модулю вклада доминирует «{dom}» "
        f"(tech {fused.tech_contrib:+.3f} · news {fused.news_contrib:+.3f} · cal {fused.cal_contrib:+.3f})."
    )
    if not fused.news_available:
        paras.append(
            "Новостной вклад в fusion без LLM: вес news фактически на нейтральном агрегате "
            "(см. «News LLM: нет агрегата» выше)."
        )

    if tech.trend_score < -0.15 and tech.bias > 0.05:
        paras.append(
            "<strong>Техника:</strong> отрицательный trend_score при слегка бычьем суммарном bias — "
            "рассогласование «направление SMA vs импульс/пробой»; интерпретировать осторожно."
        )
    elif tech.trend_score > 0.15 and tech.bias < -0.05:
        paras.append(
            "<strong>Техника:</strong> положительный trend_score при слегка медвежьем bias — "
            "смешанная картина."
        )

    paras.append(
        f"<strong>Гейт L4 ({mode_val.upper()}):</strong> {_h(t.gate_reason)}"
    )
    if mode_val == "skip" and len(t.articles) > t.profile.max_articles_full_batch:
        paras.append(
            "Ветка «тихий рынок» (<code>|draft_bias| &lt; t1</code> без REGIME) в "
            "<code>decide_llm_mode</code> выполняется <em>раньше</em> проверки числа статей — "
            f"поэтому при {len(t.articles)} статей news-LLM всё равно может не вызываться."
        )

    ab = abs(t.draft_bias)
    t1 = t.profile.t1_abs_draft_bias
    if mode_val == "skip" and ab >= t1 * 0.65 and ab < t1:
        paras.append(
            f"<strong>Калибровка:</strong> |draft_bias|={ab:.3f} близко к t1={t1:.3f}. "
            "Чтобы чаще получать FULL/LITE при таком фоне, можно снизить "
            "<code>NYSE_GATE_T1</code> (см. <code>docs/calibration.md</code>)."
        )

    body = "".join(f"<p>{p}</p>" for p in paras)
    return (
        '<div id="b0" class="analysis-box" style="margin-bottom:20px;padding:12px 14px;'
        'background:#161b22;border-radius:6px;border-left:4px solid #58a6ff">'
        "<h2>Краткий разбор</h2>"
        f"{body}"
        '<p style="color:#8b949e;font-size:0.8em;margin-top:10px;margin-bottom:0">'
        "Автоматический текст по числам отчёта; не заменяет разбор трейдера."
        "</p>"
        "</div>"
    )


def _debug_calendar_macro_html(t) -> str:
    """
    Макро-события из того же источника, что и гейт (ecalendar).
    Объясняет, почему во fusion Calendar может быть 0 при наличии строк в таблице.
    """
    from datetime import timezone

    import config_loader
    from domain import CalendarEventImportance

    def _utc(dt):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    config_loader.load_config_env()
    mb = config_loader.calendar_high_before_minutes()
    ma = config_loader.calendar_high_after_minutes()
    now = _utc(t.generated_at)

    err = getattr(t, "calendar_load_error", None)
    evs = list(getattr(t, "calendar_events", None) or [])

    intro = (
        "Источник: Investing.com, макро по валютам <strong>GBP / JPY / EUR</strong> "
        "(не даты отчётов по тикеру). "
        f"Гейт помечает <code>calendar_high_soon</code>, только если есть "
        f'<span class="tag">HIGH</span> в окне <strong>−{ma}…+{mb}</strong> минут от времени отчёта (UTC). '
        "Во fusion вклад Calendar при выключенном <code>NYSE_LLM_CALENDAR</code> — нейтральный сигнал (bias 0); "
        "это не «пропуск» таблицы ниже."
    )

    head = (
        '<div id="bcal"><h2>③b Макро-календарь</h2>'
        f'<p class="meta">{intro}</p>'
    )

    if err:
        return head + f'<p class="neg">Ошибка загрузки: {_h(err)}</p></div>'

    if not evs:
        return (
            head
            + "<p>В выборке <strong>0</strong> событий — пустой ответ API или нет релизов в отдаваемом окне.</p>"
            + "</div>"
        )

    rows = []
    for e in sorted(evs, key=lambda x: _utc(x.time))[:100]:
        delta_min = (_utc(e.time) - now).total_seconds() / 60.0
        in_win = (
            e.importance == CalendarEventImportance.HIGH
            and -ma <= delta_min <= mb
        )
        mark = '<span class="pos">★ окно</span>' if in_win else "—"
        cur = getattr(e.currency, "value", str(e.currency))
        rows.append(
            "<tr>"
            f"<td>{_utc(e.time).strftime('%Y-%m-%d %H:%M')}</td>"
            f"<td>{_h((e.name or '')[:120])}</td>"
            f"<td>{_h(e.importance.value)}</td>"
            f"<td>{_h(cur)}</td>"
            f'<td class="score">{delta_min:+.0f}</td>'
            f"<td>{mark}</td>"
            "</tr>"
        )

    gch = t.gate_ctx.calendar_high_soon
    tbl = (
        f"<p>Всего в сырье: <strong>{len(evs)}</strong> (показано до 100 по времени).</p>"
        "<table><thead><tr>"
        "<th>Время UTC</th><th>Событие</th><th>Важн.</th><th>Валюта</th>"
        "<th>Δ мин</th><th>Окно гейта</th>"
        "</tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        f'<p class="meta">На момент отчёта <code>calendar_high_soon={gch}</code> (блок ⑥). '
        "Если все события <em>moderate</em> или вне окна — флаг остаётся False.</p>"
        "</div>"
    )
    return head + tbl


# ---------------------------------------------------------------------------
# /signal — полный торговый сигнал
# ---------------------------------------------------------------------------

def build_signal_html(
    trade,
    *,
    fused=None,
    articles: Optional[List] = None,
) -> str:
    """
    HTML-отчёт для /signal TICKER.

    Разделы:
      1. Заголовок: тикер, направление, Entry/TP/SL
      2. Fusion breakdown: Tech / News / Fused
      3. Technical summary
      4. News headlines с cheap_sentiment (если переданы articles)
    """
    from domain import Direction, PositionType
    from pipeline.channels import classify_channel

    ticker_val = trade.ticker.value if hasattr(trade.ticker, "value") else str(trade.ticker)

    # --- Заголовок ---
    if trade.position is not None:
        p    = trade.position
        side_class = "long" if p.side == Direction.LONG else "short"
        side_label = "▲ LONG" if p.side == Direction.LONG else "▼ SHORT"
        tp_pct = (p.take_profit - p.entry) / p.entry * 100 if p.entry else 0
        sl_pct = (p.stop_loss  - p.entry) / p.entry * 100 if p.entry else 0
        header = (
            f'<h1><span class="{side_class}">{side_label}</span> {_h(ticker_val)}</h1>'
            f'<p class="meta">{_now_str()} · confidence {int(p.confidence*100)}%</p>'
            f"<table><thead><tr><th>Уровень</th><th>Цена</th><th>%</th></tr></thead><tbody>"
            f"<tr><td>Entry</td><td>${p.entry:,.2f}</td><td>—</td></tr>"
            f'<tr><td>TP</td><td>${p.take_profit:,.2f}</td><td class="pos">{tp_pct:+.1f}%</td></tr>'
            f'<tr><td>SL</td><td>${p.stop_loss:,.2f}</td><td class="neg">{sl_pct:+.1f}%</td></tr>'
            f"</tbody></table>"
        )
    else:
        header = (
            f'<h1><span class="none">— NO TRADE</span> {_h(ticker_val)}</h1>'
            f'<p class="meta">{_now_str()} · ниже порога confidence/bias</p>'
        )

    # --- Fusion (веса как в pystockinvest: 55% / 30% / 15%) ---
    fusion_html = ""
    if fused is not None:
        fusion_html = "<h2>Fusion</h2><table><thead><tr><th>Агент</th><th>Вес</th><th>Bias</th><th>Contrib</th></tr></thead><tbody>"
        tech_raw = fused.tech_contrib / W_TECH
        news_raw = fused.news_contrib / W_NEWS if W_NEWS else 0.0
        cal_raw = fused.cal_contrib / W_CAL if W_CAL else 0.0
        fusion_html += (
            f"<tr><td>Tech (LseHeuristicAgent)</td><td>{int(W_TECH * 100)}%</td>"
            f'<td class="{"pos" if tech_raw > 0 else "neg"}">{tech_raw:+.3f}</td>'
            f'<td class="{"pos" if fused.tech_contrib > 0 else "neg"}">{fused.tech_contrib:+.3f}</td></tr>'
            f"<tr><td>News (LLM)</td><td>{int(W_NEWS * 100)}%</td>"
            f'<td class="{"pos" if news_raw > 0 else "neg"}">{news_raw:+.3f}</td>'
            f'<td class="{"pos" if fused.news_contrib > 0 else "neg"}">{fused.news_contrib:+.3f}</td></tr>'
            f"<tr><td>Calendar</td><td>{int(W_CAL * 100)}%</td>"
            f'<td class="{"pos" if cal_raw > 0 else "neg"}">{cal_raw:+.3f}</td>'
            f'<td class="{"pos" if fused.cal_contrib > 0 else "neg"}">{fused.cal_contrib:+.3f}</td></tr>'
            f"<tr><td><strong>Fused</strong></td><td>100%</td><td>—</td>"
            f'<td class="{"pos" if fused.value > 0 else "neg"}"><strong>{fused.value:+.3f}</strong></td></tr>'
        )
        fusion_html += "</tbody></table>"

    # --- Tech summary ---
    tech_html = ""
    if trade.technical_summary:
        tech_html = "<h2>Технический анализ</h2>"
        for line in trade.technical_summary:
            tech_html += f'<p class="summary">{_h(line)}</p>'

    # --- News summary (LLM) ---
    news_llm_html = ""
    news_lines = [l for l in trade.news_summary if "fusion contrib" not in l]
    if news_lines:
        news_llm_html = "<h2>Новостной сигнал (LLM)</h2>"
        for line in news_lines:
            news_llm_html += f'<p class="summary">{_h(line)}</p>'

    # --- Headlines таблица ---
    headlines_html = ""
    if articles:
        headlines_html = (
            "<h2>Заголовки (48 ч)</h2>"
            "<table><thead><tr>"
            "<th>#</th><th>Канал</th><th>Заголовок</th><th>Score</th>"
            "</tr></thead><tbody>"
        )
        for i, a in enumerate(articles, 1):
            score = a.cheap_sentiment or 0.0
            ch, _ = classify_channel(a.title, getattr(a, "summary", None))
            ch_val = ch.value[:3].upper()
            score_class = "pos" if score > 0.05 else ("neg" if score < -0.05 else "neu")
            bar = "▲" if score > 0.05 else ("▼" if score < -0.05 else "■")
            summary = getattr(a, "summary", "") or ""
            title_full = _h(a.title)
            if summary:
                title_full += f'<br><small style="color:#8b949e">{_h(summary[:120])}</small>'
            headlines_html += (
                f"<tr>"
                f"<td>{i}</td>"
                f'<td><span class="tag">{_h(ch_val)}</span></td>'
                f"<td>{title_full}</td>"
                f'<td class="score {score_class}">{bar} {score:+.2f}</td>'
                f"</tr>"
            )
        headlines_html += "</tbody></table>"

    body = header + fusion_html + tech_html + news_llm_html + headlines_html
    return _wrap(f"{ticker_val} Signal", body)


# ---------------------------------------------------------------------------
# /news — список заголовков
# ---------------------------------------------------------------------------

def build_news_html(ticker_val: str, articles: List) -> str:
    """
    HTML-отчёт для /news TICKER.
    Полная таблица заголовков с сентиментом, каналом и summary.
    """
    from pipeline.channels import classify_channel

    rows = ""
    for i, a in enumerate(articles, 1):
        score = a.cheap_sentiment or 0.0
        ch, conf = classify_channel(a.title, getattr(a, "summary", None))
        ch_val = ch.value[:3].upper()
        score_class = "pos" if score > 0.05 else ("neg" if score < -0.05 else "neu")
        bar = "▲" if score > 0.05 else ("▼" if score < -0.05 else "■")
        summary = getattr(a, "summary", "") or ""
        ts = getattr(a, "timestamp", None)
        ts_str = ts.strftime("%m-%d %H:%M") if ts else "—"
        title_cell = _h(a.title)
        if summary:
            title_cell += f'<br><small style="color:#8b949e">{_h(summary[:150])}</small>'
        rows += (
            f"<tr>"
            f"<td>{i}</td>"
            f'<td><span class="tag">{_h(ch_val)}</span></td>'
            f"<td>{title_cell}</td>"
            f'<td class="score {score_class}">{bar} {score:+.2f}</td>'
            f"<td>{ts_str}</td>"
            f"</tr>"
        )

    body = (
        f"<h1>📰 {_h(ticker_val)} — новости</h1>"
        f'<p class="meta">{_now_str()} · {len(articles)} статей за 48 ч</p>'
        "<table><thead><tr>"
        "<th>#</th><th>Канал</th><th>Заголовок</th><th>Score</th><th>Время</th>"
        "</tr></thead><tbody>"
        f"{rows}"
        "</tbody></table>"
        "<p style='color:#8b949e;font-size:0.8em;margin-top:16px'>"
        "INC = корп. новость · REG = макро/режим · POL = ставки/политика<br>"
        "Score: FinBERT/API/price_pattern_boost [-1..+1]"
        "</p>"
    )
    return _wrap(f"{ticker_val} News", body)


# ---------------------------------------------------------------------------
# /scan — таблица тикеров
# ---------------------------------------------------------------------------

def build_scan_html(signals: list) -> str:
    """HTML-отчёт для /scan: таблица всех GAME_5M тикеров."""
    from domain import Direction

    rows = ""
    for ticker_val, sig in signals:
        price    = sig.target_snapshot.data.current_price
        rsi      = sig.target_snapshot.metrics.rsi_14
        atr      = sig.target_snapshot.metrics.atr
        conf_pct = int(sig.confidence * 100)
        arrow    = "▲" if sig.bias > 0.05 else ("▼" if sig.bias < -0.05 else "─")
        bias_cls = "pos" if sig.bias > 0.05 else ("neg" if sig.bias < -0.05 else "neu")
        rsi_cls  = "neg" if rsi > 70 else ("pos" if rsi < 30 else "neu")
        rows += (
            f"<tr>"
            f"<td><strong>{_h(ticker_val)}</strong></td>"
            f"<td>${price:,.2f}</td>"
            f'<td class="score {bias_cls}">{arrow} {sig.bias:+.2f}</td>'
            f"<td>{conf_pct}%</td>"
            f'<td class="score {rsi_cls}">{rsi:.0f}</td>'
            f"<td>{atr:.2f}</td>"
            f"</tr>"
        )

    body = (
        f"<h1>📊 GAME_5M — технический снапшот</h1>"
        f'<p class="meta">{_now_str()}</p>'
        "<table><thead><tr>"
        "<th>Тикер</th><th>Цена</th><th>Bias</th><th>Conf</th><th>RSI</th><th>ATR</th>"
        "</tr></thead><tbody>"
        f"{rows}"
        "</tbody></table>"
    )
    return _wrap("GAME_5M Scan", body)


# ---------------------------------------------------------------------------
# /news_signal — полный debug-отчёт по PipelineDebugTrace
# ---------------------------------------------------------------------------

def build_debug_report_html(trace) -> str:  # trace: PipelineDebugTrace
    """
    Полный HTML-отчёт для /news_signal TICKER.

    Секции (сверху вниз):
      0. Краткий разбор (автотекст по числам trace)
      1. Trade Signal (Entry/TP/SL или NO TRADE)
      2. Fusion breakdown (tech/news contributions)
      3. Technical Signal (все score-поля)
      3b. Макро-календарь (сырьё ecalendar + окно гейта)
      4. L3 — Статьи с cheap_sentiment + канал
      5. L3 — DraftImpulse (per-channel stats)
      6. L4 — Gate decision (context + LLMMode + reason)
      7. L5 — AggregatedNewsSignal + per-item (если LLM запускался)
    """
    from domain import Direction

    t = trace  # короткий псевдоним
    ticker_val = t.ticker
    ts = t.generated_at.strftime("%Y-%m-%d %H:%M UTC")

    # -----------------------------------------------------------------------
    # Блок 1: Trade Signal (Kerim-style)
    # -----------------------------------------------------------------------
    trade = t.trade
    fused = t.fused
    p = trade.position

    if p is not None:
        side_cls = "long" if p.side == Direction.LONG else "short"
        side_lbl = "▲ LONG" if p.side == Direction.LONG else "▼ SHORT"
        tp_pct   = (p.take_profit - p.entry) / p.entry * 100
        sl_pct   = (p.stop_loss  - p.entry) / p.entry * 100
        b1 = (
            f'<h1><span class="{side_cls}">{side_lbl}</span>  {_h(ticker_val)}</h1>'
            f'<p class="meta">{ts} · price ${t.current_price:,.2f}</p>'
            "<table><thead><tr><th>Level</th><th>Price</th><th>%</th><th>Conf</th></tr></thead><tbody>"
            f"<tr><td><b>Entry</b></td><td><b>${p.entry:,.2f}</b></td><td>—</td>"
            f"<td rowspan=3>{int(p.confidence*100)}%</td></tr>"
            f'<tr><td>Take Profit</td><td>${p.take_profit:,.2f}</td><td class="pos">{tp_pct:+.1f}%</td></tr>'
            f'<tr><td>Stop Loss</td><td>${p.stop_loss:,.2f}</td><td class="neg">{sl_pct:+.1f}%</td></tr>'
            "</tbody></table>"
        )
    else:
        b1 = (
            f'<h1><span class="none">— NO TRADE</span>  {_h(ticker_val)}</h1>'
            f'<p class="meta">{ts} · price ${t.current_price:,.2f} · '
            f"нет позиции (tradeability / |final_bias| / уровни)</p>"
        )

    # -----------------------------------------------------------------------
    # Блок 2: Fusion Breakdown (веса как в pystockinvest: 55% / 30% / 15%)
    # -----------------------------------------------------------------------
    def _fcls(v: float) -> str:
        return "pos" if v > 0 else ("neg" if v < 0 else "neu")

    tech_raw = fused.tech_contrib / W_TECH
    news_raw = fused.news_contrib / W_NEWS if W_NEWS else 0.0
    cal_raw = fused.cal_contrib / W_CAL if W_CAL else 0.0
    news_note = "" if fused.news_available else '<p class="meta">News LLM: нет агрегата (gate SKIP)</p>'
    cal_fusion_note = (
        '<p class="meta">Calendar во fusion: при выключенном <code>NYSE_LLM_CALENDAR</code> '
        'в сделку идёт нейтральный календарный сигнал (bias 0). Список макро-событий — '
        '<a href="#bcal" style="color:#58a6ff">③b Макро-календарь</a>.</p>'
    )
    b2 = (
        "<h2>② Fusion Breakdown</h2>"
        "<table><thead><tr><th>Агент</th><th>Вес</th><th>Raw bias</th>"
        "<th>Contribution</th></tr></thead><tbody>"
        f"<tr><td>LseHeuristicAgent (tech)</td><td>{int(W_TECH * 100)}%</td>"
        f'<td class="score {_fcls(tech_raw)}">{tech_raw:+.4f}</td>'
        f'<td class="score {_fcls(fused.tech_contrib)}">{fused.tech_contrib:+.4f}</td></tr>'
        f"<tr><td>NewsSignalAgent (LLM)</td><td>{int(W_NEWS * 100)}%</td>"
        f'<td class="score {_fcls(news_raw)}">{news_raw:+.4f}</td>'
        f'<td class="score {_fcls(fused.news_contrib)}">{fused.news_contrib:+.4f}</td></tr>'
        f"<tr><td>Calendar</td><td>{int(W_CAL * 100)}%</td>"
        f'<td class="score {_fcls(cal_raw)}">{cal_raw:+.4f}</td>'
        f'<td class="score {_fcls(fused.cal_contrib)}">{fused.cal_contrib:+.4f}</td></tr>'
        f"<tr><td><strong>Fused</strong></td><td>100%</td><td>—</td>"
        f'<td class="score {_fcls(fused.value)}"><strong>{fused.value:+.4f}</strong>'
        f" conf={fused.confidence:.2f}</td></tr>"
        "</tbody></table>"
        f"{news_note}{cal_fusion_note}"
    )

    # -----------------------------------------------------------------------
    # Блок 3: Technical Signal (все score-поля)
    # -----------------------------------------------------------------------
    tech = t.tech_signal
    m    = t.metrics

    def _srow(label: str, val: float, rng: str = "[-1,1]", note: str = "") -> str:
        bar_w = int(abs(val) * 80)
        bar_c = "#3fb950" if val > 0 else "#f85149"
        bar_html = (
            f'<div style="display:inline-block;width:{bar_w}px;height:10px;'
            f'background:{bar_c};vertical-align:middle;border-radius:2px"></div>'
        )
        cls = _fcls(val)
        note_html = f' <small style="color:#8b949e">{_h(note)}</small>' if note else ""
        return (
            f"<tr><td>{_h(label)}</td>"
            f'<td class="score {cls}">{val:+.4f}</td>'
            f"<td>{rng}</td>"
            f"<td>{bar_html}</td>"
            f"<td>{note_html}</td></tr>"
        )

    b3 = (
        "<h2>③ Technical Signal (L2 — LseHeuristicAgent)</h2>"
        f'<p class="meta">Candles: daily={t.daily_candles_count}d · '
        f"hourly={t.hourly_candles_count}h · "
        f"RSI={m.rsi_14:.1f} · ATR={m.atr:.2f} · "
        f"perf_1w={m.perf_week:+.2f}% · β={m.beta:.2f}</p>"
        "<table><thead><tr><th>Score</th><th>Value</th><th>Range</th>"
        "<th>Bar</th><th>Note</th></tr></thead><tbody>"
        + _srow("bias", tech.bias, "[-1,1]", "взвешенная сумма")
        + _srow("trend_score", tech.trend_score, "[-1,1]", "SMA direction")
        + _srow("momentum_score", tech.momentum_score, "[-1,1]", "price acceleration")
        + _srow("breakout_score", tech.breakout_score, "[-1,1]", "range breakout pressure")
        + _srow("relative_strength_score", tech.relative_strength_score, "[-1,1]", "vs SMH/QQQ")
        + _srow("market_alignment_score", tech.market_alignment_score, "[-1,1]", "broad market context")
        + _srow("support_resistance_pressure", tech.support_resistance_pressure, "[-1,1]", "20d range position")
        + _srow("mean_reversion_score", tech.mean_reversion_score, "[-1,1]", "reversion expectation")
        + _srow("volatility_regime", tech.volatility_regime, "[0,1]", "0=calm 1=high vol")
        + _srow("exhaustion_score", tech.exhaustion_score, "[0,1]", "0=fresh 1=exhausted")
        + _srow("tradeability_score", tech.tradeability_score, "[0,1]", "setup quality")
        + _srow("confidence", tech.confidence, "[0,1]", "agent confidence")
        + "</tbody></table>"
        + "<p>" + " · ".join(_h(s) for s in tech.summary) + "</p>"
    )

    # -----------------------------------------------------------------------
    # Блок 4: Raw articles + cheap_sentiment
    # -----------------------------------------------------------------------
    def _sent_cls(v: float) -> str:
        return "pos" if v > 0.05 else ("neg" if v < -0.05 else "neu")

    def _sent_bar(v: float) -> str:
        return "▲" if v > 0.05 else ("▼" if v < -0.05 else "■")

    art_rows = ""
    for i, (a, ch) in enumerate(zip(t.articles, t.article_channels), 1):
        sc = a.cheap_sentiment or 0.0
        ts_a = a.timestamp.strftime("%m-%d %H:%M") if a.timestamp else "—"
        in_llm = "✓" if a in t.llm_batch_articles else ""
        summ = _h((a.summary or "")[:120])
        prov = getattr(a, "provider_id", None) or "—"
        art_rows += (
            f"<tr>"
            f"<td>{i}</td>"
            f'<td><span class="tag">{_h(ch[:3].upper())}</span></td>'
            f'<td><span class="tag">{_h(str(prov))}</span></td>'
            f"<td>{_h(a.title)}"
            + (f"<br><small style='color:#8b949e'>{summ}</small>" if summ else "")
            + f"</td>"
            f'<td class="score {_sent_cls(sc)}">{_sent_bar(sc)} {sc:+.2f}</td>'
            f"<td>{ts_a}</td>"
            f"<td style='text-align:center;color:#3fb950'>{in_llm}</td>"
            f"</tr>"
        )

    b4 = (
        f"<h2>④ L3 — Статьи + cheap_sentiment ({len(t.articles)} статей, "
        f"lookback {t.profile.max_articles_full_batch*6}h)</h2>"
        "<table><thead><tr>"
        "<th>#</th><th>Канал</th><th>Источник</th><th>Заголовок / Summary</th>"
        "<th>Score</th><th>Время</th><th>→LLM</th>"
        "</tr></thead><tbody>"
        + art_rows
        + "</tbody></table>"
        "<p style='color:#8b949e;font-size:0.8em'>"
        "INC=incremental корп. · REG=regime макро · POL=policy ставки · "
        "✓ = вошла в LLM-батч</p>"
    )

    # -----------------------------------------------------------------------
    # Блок 5: DraftImpulse
    # -----------------------------------------------------------------------
    di = t.draft_impulse

    def _di_row(channel: str, arts: int, wsum: float, score: float, max_abs: float) -> str:
        cls = _fcls(score) if channel == "INC" else ("neg" if score > 0.05 else "neu")
        return (
            f"<tr><td>{channel}</td><td>{arts}</td>"
            f"<td>{wsum:.3f}</td>"
            f'<td class="score {_fcls(score)}">{score:+.4f}</td>'
            f"<td>{max_abs:.3f}</td></tr>"
        )

    b5 = (
        "<h2>⑤ L3 — DraftImpulse (per-channel weighted mean)</h2>"
        "<table><thead><tr>"
        "<th>Channel</th><th>Articles</th><th>Weight Σ</th>"
        "<th>Score</th><th>max|sent|</th>"
        "</tr></thead><tbody>"
        + _di_row("INC (draft_bias)", di.articles_incremental, di.weight_sum_incremental,
                  di.draft_bias_incremental, 0.0)
        + _di_row("REG (regime_stress)", di.articles_regime, di.weight_sum_regime,
                  di.regime_stress, di.max_abs_regime)
        + _di_row("POL (policy_stress)", di.articles_policy, di.weight_sum_policy,
                  di.policy_stress, di.max_abs_policy)
        + "</tbody></table>"
        f'<p class="meta"><b>draft_bias = {t.draft_bias:+.4f}</b> '
        f"(single_scalar_draft_bias: INC bias, boosted by |REG|+|POL| если стресс высокий)</p>"
    )

    # -----------------------------------------------------------------------
    # Блок 6: Gate Decision
    # -----------------------------------------------------------------------
    ctx = t.gate_ctx
    mode_cls = "pos" if t.llm_mode == "full" else ("neu" if t.llm_mode == "lite" else "neg")
    b6 = (
        "<h2>⑥ L4 — Gate Decision</h2>"
        "<table><thead><tr><th>Параметр</th><th>Значение</th><th>Порог</th></tr></thead><tbody>"
        f"<tr><td>draft_bias</td>"
        f'<td class="score {_fcls(ctx.draft_bias)}">{ctx.draft_bias:+.4f}</td>'
        f"<td>t1={t.profile.t1_abs_draft_bias:.3f}  "
        f"t1×2={t.profile.t1_abs_draft_bias*2.0:.3f}</td></tr>"
        f"<tr><td>regime_present</td>"
        f'<td class="{"pos" if ctx.regime_present else "neu"}">{ctx.regime_present}</td>'
        f"<td>regime_stress_min={t.profile.regime_stress_min:.3f}</td></tr>"
        f"<tr><td>regime_rule_confidence</td><td>{ctx.regime_rule_confidence:.2f}</td>"
        f"<td>t2={t.profile.t2_regime_confidence:.2f}</td></tr>"
        f"<tr><td>article_count</td><td>{ctx.article_count}</td>"
        f"<td>max_full={t.profile.max_articles_full_batch}</td></tr>"
        f"<tr><td>calendar_high_soon</td><td>{ctx.calendar_high_soon}</td><td>—</td></tr>"
        "</tbody></table>"
        f'<p><b>→ LLMMode: <span class="score {mode_cls}">{t.llm_mode.upper()}</span></b>'
        f"  <i style='color:#8b949e'>{_h(t.gate_reason)}</i></p>"
        + (
            f"<p>LLM batch: {len(t.llm_batch_articles)} из {len(t.articles)} статей "
            f"(индексы топ-{t.profile.max_articles_full_batch} по весу)</p>"
            if t.llm_batch_articles else ""
        )
    )

    # -----------------------------------------------------------------------
    # Блок 7: AggregatedNewsSignal + per-item LLM
    # -----------------------------------------------------------------------
    ns = t.news_signal
    if ns is not None and ns.items:
        item_rows = ""
        for i, (item, a) in enumerate(zip(ns.items, t.llm_batch_articles), 1):
            sc = item.sentiment
            item_rows += (
                f"<tr>"
                f"<td>{i}</td>"
                f"<td>{_h(a.title[:70])}</td>"
                f'<td class="score {_fcls(sc)}">{_sent_bar(sc)} {sc:+.2f}</td>'
                f"<td>{_h(item.impact_strength.value)}</td>"
                f"<td>{_h(item.relevance.value)}</td>"
                f"<td>{_h(item.surprise.value)}</td>"
                f"<td>{_h(item.time_horizon.value)}</td>"
                f"<td>{item.confidence:.2f}</td>"
                "</tr>"
            )
        llm_table = (
            "<h3>Per-article LLM signals</h3>"
            "<table><thead><tr>"
            "<th>#</th><th>Заголовок</th><th>Sentiment</th>"
            "<th>Impact</th><th>Relevance</th><th>Surprise</th>"
            "<th>Horizon</th><th>Conf</th>"
            "</tr></thead><tbody>"
            + item_rows
            + "</tbody></table>"
        )
        b7 = (
            "<h2>⑦ L5 — AggregatedNewsSignal (LLM)</h2>"
            "<table><thead><tr><th>Поле</th><th>Значение</th></tr></thead><tbody>"
            f'<tr><td>bias</td><td class="score {_fcls(ns.bias)}">{ns.bias:+.4f}</td></tr>'
            f"<tr><td>confidence</td><td>{ns.confidence:.4f}</td></tr>"
            f"<tr><td>items analyzed</td><td>{len(ns.items)}</td></tr>"
            + "".join(f"<tr><td>summary</td><td>{_h(s)}</td></tr>" for s in ns.summary)
            + "</tbody></table>"
            + llm_table
        )
    elif ns is not None:
        b7 = (
            "<h2>⑦ L5 — AggregatedNewsSignal (LLM)</h2>"
            f'<p>Mode={t.llm_mode.upper()} → neutral aggregate: bias=0.0, conf=0.0</p>'
        )
    else:
        b7 = "<h2>⑦ L5 — LLM</h2><p>SKIP — LLM не запускался.</p>"

    # -----------------------------------------------------------------------
    # Навигация + сборка
    # -----------------------------------------------------------------------
    b0 = _debug_auto_analysis_html(t)
    bcal = _debug_calendar_macro_html(t)
    nav = (
        '<nav style="margin-bottom:20px;padding:10px;background:#161b22;'
        'border-radius:6px;font-size:0.85em">'
        "<b>Перейти к:</b> "
        '<a href="#b0" style="color:#58a6ff">Краткий разбор</a> · '
        '<a href="#b1" style="color:#58a6ff">① Trade</a> · '
        '<a href="#b2" style="color:#58a6ff">② Fusion</a> · '
        '<a href="#b3" style="color:#58a6ff">③ Technical</a> · '
        '<a href="#bcal" style="color:#58a6ff">③b Cal</a> · '
        '<a href="#b4" style="color:#58a6ff">④ Articles</a> · '
        '<a href="#b5" style="color:#58a6ff">⑤ DraftImpulse</a> · '
        '<a href="#b6" style="color:#58a6ff">⑥ Gate</a> · '
        '<a href="#b7" style="color:#58a6ff">⑦ LLM Signal</a>'
        "</nav>"
    )

    def _anchor(bid: str, content: str) -> str:
        return f'<div id="{bid}">{content}</div>'

    body = (
        nav
        + b0
        + _anchor("b1", b1)
        + _anchor("b2", b2)
        + _anchor("b3", b3)
        + bcal
        + _anchor("b4", b4)
        + _anchor("b5", b5)
        + _anchor("b6", b6)
        + _anchor("b7", b7)
        + f'<p style="color:#8b949e;font-size:0.75em;margin-top:32px">'
        f"Профиль: t1={t.profile.t1_abs_draft_bias} · "
        f"t2={t.profile.t2_regime_confidence} · "
        f"max_full={t.profile.max_articles_full_batch} · "
        f"regime_min={t.profile.regime_stress_min}</p>"
    )

    return _wrap(f"{ticker_val} Debug Pipeline", body)
