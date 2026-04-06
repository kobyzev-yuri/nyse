"""Парсинг RSS 2.0 / Atom-совместимых лент → NewsArticle."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from xml.etree import ElementTree as ET

import requests

from domain import NewsArticle, Ticker

logger = logging.getLogger(__name__)


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def parse_rss_xml(xml_text: str) -> List[dict]:
    """
    Извлекает элементы item/entry без сети.
    Возвращает dict: title, link, summary, published (datetime | None).
    """
    root = ET.fromstring(xml_text)
    out: List[dict] = []
    for el in root.iter():
        if _local_tag(el.tag) not in ("item", "entry"):
            continue
        title = _child_text(el, ("title",))
        link = _child_text(el, ("link",)) or _link_from_atom(el)
        summary = _child_text(el, ("description", "summary", "content"))
        pub_raw = _child_text(el, ("pubDate", "published", "updated"))
        published = _parse_pub_date(pub_raw)
        if title:
            out.append(
                {
                    "title": title.strip(),
                    "link": link.strip() if link else None,
                    "summary": summary.strip() if summary else None,
                    "published": published,
                }
            )
    return out


def _child_text(parent: ET.Element, names: tuple[str, ...]) -> Optional[str]:
    for child in parent:
        if _local_tag(child.tag) in names:
            t = (child.text or "").strip()
            if t:
                return t
    return None


def _link_from_atom(entry: ET.Element) -> Optional[str]:
    for child in entry:
        if _local_tag(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href
    return None


def _parse_pub_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    s = raw.strip()
    try:
        if len(s) >= 10 and s[4] == "-" and s[7] == "-":
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(s)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


class Source:
    def __init__(
        self,
        feed_url: str,
        *,
        ticker: Ticker = Ticker.GENERAL,
        lookback_hours: int = 48,
        max_items: int = 80,
        timeout_sec: int = 30,
    ):
        self.feed_url = feed_url
        self.ticker = ticker
        self.lookback_hours = lookback_hours
        self.max_items = max(1, max_items)
        self.timeout_sec = timeout_sec

    def get_articles(self, tickers: List[Ticker]) -> List[NewsArticle]:
        """tickers игнорируются; тикер задаётся в конструкторе (по умолчанию GENERAL)."""
        del tickers
        r = requests.get(self.feed_url, timeout=self.timeout_sec)
        r.raise_for_status()
        rows = parse_rss_xml(r.text)[: self.max_items]
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        articles: List[NewsArticle] = []
        for row in rows:
            ts = row.get("published") or datetime.now(timezone.utc)
            if ts < cutoff:
                continue
            articles.append(
                NewsArticle(
                    ticker=self.ticker,
                    title=row["title"],
                    summary=row.get("summary"),
                    timestamp=ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
                    link=row.get("link"),
                    publisher=None,
                    provider_id="rss",
                )
            )
        logger.info("RSS loaded articles: count=%d url=%s", len(articles), self.feed_url)
        return sorted(articles, key=lambda a: a.timestamp, reverse=True)
