#!/usr/bin/env python3
"""
Экспорт новостей NYSE в JSONL (для импорта в LSE knowledge_base).

Зачем:
  - NYSE умеет собирать новости из большего числа источников;
  - LSE держит каноническую PostgreSQL knowledge_base;
  - этот скрипт создаёт файл JSONL, который затем импортируется в LSE через
    lse/scripts/import_news_jsonl_to_kb.py.

Формат JSONL (1 строка = 1 статья):
  ts, symbol, exchange, source, title, summary, url, external_id, raw_payload
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _add_repo_root_to_syspath() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _dt_iso(dt: object) -> str:
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


def _safe_str(x: Any, max_len: int = 2000) -> str:
    s = ("" if x is None else str(x)).strip()
    return s[:max_len]


def main() -> None:
    ap = argparse.ArgumentParser(description="Export merged news to JSONL for LSE import")
    ap.add_argument("--tickers", default="", help="Comma-separated tickers (default: from config/env in sources.news)")
    ap.add_argument("--lookback-hours", type=int, default=48, help="Lookback window")
    ap.add_argument("--max-per-ticker", type=int, default=40, help="Cap per ticker before export")
    ap.add_argument("--exchange", default="NYSE", help="Exchange label")
    ap.add_argument("--out", required=True, help="Output JSONL path")
    ap.add_argument("--pretty", action="store_true", help="Pretty JSON (still one line per record if false)")
    args = ap.parse_args()

    _add_repo_root_to_syspath()

    import config_loader
    from domain import Ticker
    from sources.news import Source as NewsSource

    config_loader.load_config_env()

    tickers_raw = (args.tickers or "").strip()
    if tickers_raw:
        tickers = [Ticker(t.strip().upper()) for t in tickers_raw.split(",") if t.strip()]
    else:
        # fallback: use same universe as bot/pipeline (config-driven)
        try:
            tl = config_loader.get_tickers_list()
            tickers = [Ticker(t.strip().upper()) for t in tl if t.strip()]
        except Exception:
            tickers = []
    if not tickers:
        print("No tickers provided and config tickers empty.", file=sys.stderr)
        sys.exit(2)

    src = NewsSource(max_per_ticker=max(1, int(args.max_per_ticker)), lookback_hours=max(1, int(args.lookback_hours)))
    articles = src.get_articles(tickers)

    out_path = Path(args.out).expanduser()
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path
    out_path.parent.mkdir(parents=True, exist_ok=True)

    n = 0
    with out_path.open("w", encoding="utf-8") as f:
        for a in articles:
            rec: Dict[str, Any] = {
                "ts": _dt_iso(getattr(a, "timestamp", None)),
                "symbol": getattr(getattr(a, "ticker", None), "value", None),
                "exchange": str(args.exchange or "NYSE").strip().upper(),
                "source": _safe_str(getattr(a, "publisher", None) or "NYSE"),
                "title": _safe_str(getattr(a, "title", None), 2000),
                "summary": _safe_str(getattr(a, "summary", None), 4000),
                "url": _safe_str(getattr(a, "link", None), 2000),
                "external_id": _safe_str(getattr(a, "provider_id", None), 512),
                "raw_payload": {
                    "raw_sentiment": getattr(a, "raw_sentiment", None),
                    "cheap_sentiment": getattr(a, "cheap_sentiment", None),
                    "publisher": getattr(a, "publisher", None),
                },
            }
            # Remove empty external_id so LSE importer generates deterministic one
            if not rec["external_id"]:
                rec.pop("external_id", None)
            s = json.dumps(rec, ensure_ascii=False, indent=2 if args.pretty else None)
            if args.pretty:
                # pretty still must be single JSON per line in JSONL: strip newlines
                s = " ".join(s.splitlines())
            f.write(s + "\n")
            n += 1

    print(json.dumps({"ok": True, "out": str(out_path), "records": n}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

