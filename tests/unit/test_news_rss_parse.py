"""Юнит: parse_rss_xml без сети."""

from __future__ import annotations

from sources.news_rss import parse_rss_xml


def test_parse_rss2_minimal():
    xml = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<item>
<title>Hello World</title>
<link>https://example.com/a</link>
<pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
<description>Summary text</description>
</item>
</channel></rss>"""
    rows = parse_rss_xml(xml)
    assert len(rows) == 1
    assert rows[0]["title"] == "Hello World"
    assert rows[0]["link"] == "https://example.com/a"
    assert rows[0]["summary"] == "Summary text"
    assert rows[0]["published"] is not None


def test_parse_atom_entry_with_namespace():
    xml = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
<entry>
<title>Atom title</title>
<link href="https://example.com/b"/>
<updated>2024-06-15T10:00:00Z</updated>
<summary>Atom sum</summary>
</entry>
</feed>"""
    rows = parse_rss_xml(xml)
    assert len(rows) == 1
    assert rows[0]["title"] == "Atom title"
    assert rows[0]["link"] == "https://example.com/b"
    assert rows[0]["summary"] == "Atom sum"
