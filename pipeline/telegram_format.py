"""
Форматирование Trade/TechnicalSignal в сообщения для Telegram.

Все функции возвращают plain-text строки (без Markdown/HTML разметки Telegram,
чтобы избежать escape-проблем при специальных символах в summary).

Использование::

    from pipeline.telegram_format import format_trade, format_technical_signal
    text = format_trade(trade, fused_bias=fused)
    send_to_telegram(text, token=..., chat_id=...)
"""

from __future__ import annotations

from typing import Optional

from domain import Direction, PositionType, TechnicalSignal, Trade

from .trade_builder import FusedBias

# Символы направления (plain-text, без emoji по умолчанию)
_SIDE_ARROW = {Direction.LONG: "▲ LONG", Direction.SHORT: "▼ SHORT"}


def format_trade(
    trade: Trade,
    *,
    fused: Optional[FusedBias] = None,
    include_details: bool = True,
) -> str:
    """
    Полное сообщение о торговом сигнале.

    Пример:

        ════════════════════════
        [SNDK]  ▲ LONG  conf=0.76
        Entry  $717.80
        TP     $830.40  (+15.7%)
        SL     $661.50  (-7.8%)
        ────────────────────────
        Tech:  bias=+0.35  trend▲  RSI 57  vol calm (ATR=56.30)
        News:  bias=+0.42  8 items  conf=0.77
        Fused: tech(+0.19) + news(+0.19) = +0.38
        ════════════════════════
    """
    lines: list[str] = []
    sep_thick = "=" * 26
    sep_thin  = "-" * 26

    lines.append(sep_thick)

    ticker_val = trade.ticker.value if hasattr(trade.ticker, "value") else str(trade.ticker)

    # --- Заголовок ---
    if trade.position is not None:
        side_str = _SIDE_ARROW.get(trade.position.side, str(trade.position.side))
        lines.append(f"[{ticker_val}]  {side_str}  conf={trade.position.confidence:.2f}")
    elif trade.entry_type == PositionType.NONE:
        lines.append(f"[{ticker_val}]  — NO TRADE (confidence/bias below threshold)")
    else:
        lines.append(f"[{ticker_val}]  {trade.entry_type.value}")

    # --- Уровни ---
    if trade.position is not None:
        p = trade.position
        lines.append(sep_thin)
        lines.append(f"Entry  ${p.entry:,.2f}")
        if p.entry > 0:
            tp_pct = (p.take_profit - p.entry) / p.entry * 100
            sl_pct = (p.stop_loss  - p.entry) / p.entry * 100
            lines.append(f"TP     ${p.take_profit:,.2f}  ({tp_pct:+.1f}%)")
            lines.append(f"SL     ${p.stop_loss:,.2f}  ({sl_pct:+.1f}%)")

    if include_details:
        lines.append(sep_thin)

        # Tech summary (первые 2 строки)
        tech_lines = trade.technical_summary[:2]
        if tech_lines:
            lines.append(f"Tech:  {tech_lines[0]}")
            for tl in tech_lines[1:]:
                lines.append(f"       {tl}")

        # News summary (последняя строка = fusion contrib)
        if trade.news_summary:
            news_main = trade.news_summary[0]
            lines.append(f"News:  {news_main}")
            # Последняя строка содержит "News fusion contrib: ..."
            if len(trade.news_summary) > 1:
                lines.append(f"       {trade.news_summary[-1]}")

        # Fused breakdown
        if fused is not None:
            if fused.news_available:
                lines.append(
                    f"Fused: tech({fused.tech_contrib:+.3f}) + "
                    f"news({fused.news_contrib:+.3f}) = {fused.value:+.3f}"
                )
            else:
                lines.append(
                    f"Fused: tech-only  bias={fused.value:+.3f}  (no news signal)"
                )

    lines.append(sep_thick)
    return "\n".join(lines)


def format_technical_signal(
    ticker_value: str,
    sig: TechnicalSignal,
) -> str:
    """
    Короткий технический снапшот — без news, для отладки/мониторинга.

    Пример:

        [SNDK] Tech bias=+0.35 ▲  conf=0.78  RSI 57  ATR 56.30
    """
    price = sig.target_snapshot.data.current_price
    atr   = sig.target_snapshot.metrics.atr
    rsi   = sig.target_snapshot.metrics.rsi_14
    arrow = "▲" if sig.bias > 0.05 else ("▼" if sig.bias < -0.05 else "─")
    return (
        f"[{ticker_value}] Tech bias={sig.bias:+.2f} {arrow}  "
        f"conf={sig.confidence:.2f}  "
        f"RSI {rsi:.0f}  ATR {atr:.2f}  "
        f"price ${price:,.2f}"
    )


def format_signal_table(signals: list[tuple[str, TechnicalSignal]]) -> str:
    """
    Таблица технических сигналов по нескольким тикерам.

    Пример:
        SNDK   $717.80  bias=+0.35 ▲  conf=0.78  RSI 57
        NBIS   $116.14  bias=+0.39 ▲  conf=0.79  RSI 56
        ASML  $1297.36  bias=-0.35 ▼  conf=0.81  RSI 43
    """
    lines = []
    for ticker_val, sig in signals:
        price = sig.target_snapshot.data.current_price
        rsi   = sig.target_snapshot.metrics.rsi_14
        arrow = "▲" if sig.bias > 0.05 else ("▼" if sig.bias < -0.05 else "─")
        lines.append(
            f"{ticker_val:6s}  ${price:>8,.2f}  "
            f"bias={sig.bias:+.2f} {arrow}  "
            f"conf={sig.confidence:.2f}  "
            f"RSI {rsi:.0f}"
        )
    return "\n".join(lines)
