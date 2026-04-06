"""Тесты файлового кэша."""

from __future__ import annotations

import time

import pytest

from pipeline import FileCache


def test_cache_roundtrip(tmp_cache_dir):
    c = FileCache(tmp_cache_dir, default_ttl_sec=60)
    c.set("k1", {"a": 1})
    assert c.get("k1") == {"a": 1}


def test_cache_expires(tmp_cache_dir):
    c = FileCache(tmp_cache_dir, default_ttl_sec=1)
    c.set("k2", "x", ttl_sec=1)
    assert c.get("k2") == "x"
    time.sleep(1.2)
    assert c.get("k2") is None
