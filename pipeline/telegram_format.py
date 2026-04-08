"""
Форматирование Trade/TechnicalSignal в HTML-сообщения для Telegram.

Все функции возвращают HTML-строки для parse_mode="HTML".
Динамический контент экранируется через html.escape().

Telegram поддерживает: <b>, <i>, <code>, <pre>, <a href=...>.

Использование::

    from pipeline.telegram_format import format_trade, format_signal_table
    text = format_trade(trade, fused=fused)
    await message.reply_text(text, parse_mode="HTML")
"""

from __future__ import annotations

import html
from typing import Optional

from domain import Direction, PositionType, TechnicalSignal, Trade

from .trade_builder import FusedBias, W_CAL, W_NEWS, W_TECH

# Стрелки и эмодзи направлений
_SIDE_EMOJI = {Direction.LONG: "📈", Direction.SHORT: "📉"}
_SIDE_LABEL = {Direction.LONG: "LONG",  Direction.SHORT: "SHORT"}


def _bias_arrow(b: float) -> str:
    return "▲" if b > 0.05 else ("▼" if b < -0.05 else "─")


def _h(text: str) -> str:
    """HTML-экранирование динамического контента."""
    return html.escape(str(text))


def format_trade(
    trade: Trade,
    *,
    fused: Optional[FusedBias] = None,
    include_details: bool = True,
) -> str:
    """
    Полное HTML-сообщение о торговом сигнале.

    Пример (рендер):

        📈 SNDK — LONG   conf 77%
        ──────────────────────────
        Entry   $708.46
        TP      $821.06   +15.9%
        SL      $652.16   -7.9%
        ──────────────────────────
        Tech (55%) / News (30%) / Cal (15%) — как в pystockinvest
        Fused:  tech_contrib + news_contrib + cal_contrib = final_bias
        ──────────────────────────
        Technical bias +0.26 (moderate bullish)...
        Aggregated news bias is 0.44...
    """
    ticker_val = trade.ticker.value if hasattr(trade.ticker, "value") else str(trade.ticker)
    lines: list[str] = []

    # --- Заголовок ---
    if trade.position is not None:
        p    = trade.position
        emo  = _SIDE_EMOJI.get(p.side, "")
        side = _SIDE_LABEL.get(p.side, str(p.side))
        conf_pct = int(p.confidence * 100)
        lines.append(f"{emo} <b>{_h(ticker_val)} — {side}</b>   conf {conf_pct}%")
    elif trade.entry_type == PositionType.NONE:
        lines.append(f"⬜ <b>{_h(ticker_val)}</b>   нет сигнала")
    else:
        lines.append(f"<b>{_h(ticker_val)}</b>   {_h(trade.entry_type.value)}")

    lines.append("─" * 28)

    # --- Уровни входа/TP/SL ---
    if trade.position is not None:
        p = trade.position
        tp_pct = (p.take_profit - p.entry) / p.entry * 100 if p.entry else 0
        sl_pct = (p.stop_loss  - p.entry) / p.entry * 100 if p.entry else 0
        lines.append(f"<code>Entry  ${p.entry:>10,.2f}</code>")
        lines.append(
            f"<code>TP     ${p.take_profit:>10,.2f}</code>   "
            f"<i>{tp_pct:+.1f}%</i>"
        )
        lines.append(
            f"<code>SL     ${p.stop_loss:>10,.2f}</code>   "
            f"<i>{sl_pct:+.1f}%</i>"
        )
        lines.append("─" * 28)

    if include_details:
        # --- Числовые параметры ---
        tech_sig = None
        try:
            tech_sig = trade  # для атрибутов ниже используем summary
        except Exception:
            pass

        # Fusion breakdown (веса как в pystockinvest: 55% / 30% / 15%)
        if fused is not None:
            arrow = _bias_arrow(fused.value)
            tech_raw = fused.tech_contrib / W_TECH if W_TECH else 0.0
            news_raw = fused.news_contrib / W_NEWS if W_NEWS else 0.0
            cal_raw = fused.cal_contrib / W_CAL if W_CAL else 0.0
            lines.append(
                f"<b>Tech</b> ({int(W_TECH * 100)}%):  "
                f"bias {tech_raw:+.2f} {arrow}"
            )
            if fused.news_available:
                lines.append(
                    f"<b>News</b> ({int(W_NEWS * 100)}%):  "
                    f"bias {news_raw:+.2f} · contrib {fused.news_contrib:+.3f}"
                )
            else:
                lines.append(
                    f"<b>News</b> ({int(W_NEWS * 100)}%):  "
                    f"<i>(нет LLM-агрегата)</i> · contrib {fused.news_contrib:+.3f}"
                )
            lines.append(
                f"<b>Cal</b> ({int(W_CAL * 100)}%):  "
                f"bias {cal_raw:+.2f} · contrib {fused.cal_contrib:+.3f}"
            )
            lines.append(
                f"<b>Fused:</b>  "
                f"{fused.tech_contrib:+.3f} + {fused.news_contrib:+.3f} + {fused.cal_contrib:+.3f} = "
                f"<b>{fused.value:+.3f}</b>"
            )
            lines.append("─" * 28)

        # --- Summary строки ---
        for line in trade.technical_summary[:2]:
            lines.append(f"<i>{_h(line)}</i>")

        news_lines = list(trade.news_summary)
        for line in news_lines[:2]:
            lines.append(f"<i>{_h(line)}</i>")

    return "\n".join(lines)


def format_technical_signal(ticker_value: str, sig: TechnicalSignal) -> str:
    """
    Однострочный технический снапшот — для отладки/мониторинга.

    Пример:
        [SNDK]  bias +0.21 ▲  conf 70%  RSI 57  $704.76
    """
    price   = sig.target_snapshot.data.current_price
    rsi     = sig.target_snapshot.metrics.rsi_14
    arrow   = _bias_arrow(sig.bias)
    conf_pct = int(sig.confidence * 100)
    return (
        f"[{_h(ticker_value)}]  "
        f"bias {sig.bias:+.2f} {arrow}  "
        f"conf {conf_pct}%  "
        f"RSI {rsi:.0f}  "
        f"${price:,.2f}"
    )


def format_signal_table(signals: list[tuple[str, TechnicalSignal]]) -> str:
    """
    Компактная таблица технических сигналов (plain text — для вставки в <pre>).

    Пример:
        SNDK   $  704.76  +0.21 ▲  70%  RSI 57
        NBIS   $  116.79  +0.45 ▲  81%  RSI 57
        ASML   $1,297.46  -0.36 ▼  78%  RSI 44
    """
    lines = []
    for ticker_val, sig in signals:
        price   = sig.target_snapshot.data.current_price
        rsi     = sig.target_snapshot.metrics.rsi_14
        arrow   = "▲" if sig.bias > 0.05 else ("▼" if sig.bias < -0.05 else "─")
        conf_pct = int(sig.confidence * 100)
        lines.append(
            f"{ticker_val:6s}  ${price:>9,.2f}  "
            f"{sig.bias:+.2f} {arrow}  "
            f"{conf_pct:>2d}%  "
            f"RSI {rsi:.0f}"
        )
    return "\n".join(lines)


def format_news_list(
    ticker_val: str,
    articles: list,
    *,
    lookback_hours: int = 48,
) -> str:
    """
    HTML-список статей с cheap_sentiment и каналом.

    Parameters
    ----------
    articles : список NewsArticle с заполненным cheap_sentiment и методом title/summary.
    lookback_hours : подпись окна (как при загрузке новостей).
    """
    from pipeline.channels import classify_channel, story_type_ru

    lines = [f"📰 <b>{_h(ticker_val)} — новости ({lookback_hours} ч)</b>\n"]
    for a in articles[:10]:
        score = a.cheap_sentiment or 0.0
        ch, _ = classify_channel(a.title, getattr(a, "summary", None))
        ch_s  = ch.value[:3].upper()
        story = story_type_ru(ch)
        prov  = getattr(a, "provider_id", None) or "?"
        bar   = "▲" if score > 0.05 else ("▼" if score < -0.05 else "■")
        ch_tag = f"<code>{ch_s}</code>"
        st_tag = f"<code>{_h(story)}</code>"
        pv_tag = f"<code>{_h(str(prov))}</code>"
        score_str = f"<i>{score:+.2f}</i>"
        title = _h(a.title[:80])
        lines.append(f"{bar} {ch_tag} {st_tag} {pv_tag} {title}")
        lines.append(f"    {score_str}")

    return "\n".join(lines)
