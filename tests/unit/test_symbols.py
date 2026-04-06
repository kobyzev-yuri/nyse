"""Юнит-тесты: sources.symbols (без сети)."""

from __future__ import annotations

import pytest


def test_yfinance_symbol_matches_ticker_value():
    from domain import Ticker
    from sources.symbols import yfinance_symbol

    assert yfinance_symbol(Ticker.NVDA) == "NVDA"
    assert yfinance_symbol(Ticker.VIX) == "^VIX"


def test_finviz_symbol_vix_maps_to_vixy():
    from domain import Ticker
    from sources.symbols import finviz_symbol

    assert finviz_symbol(Ticker.NVDA) == "NVDA"
    assert finviz_symbol(Ticker.VIX) == "VIXY"


def test_tickers_from_environ_empty_uses_default(monkeypatch):
    from domain import Ticker
    from sources.symbols import tickers_from_environ

    monkeypatch.delenv("NYSE_TICKERS", raising=False)
    out = tickers_from_environ(default=[Ticker.NVDA])
    assert out == [Ticker.NVDA]


def test_tickers_from_environ_parses_list(monkeypatch):
    from domain import Ticker
    from sources.symbols import tickers_from_environ

    monkeypatch.setenv("NYSE_TICKERS", "NVDA, MU")
    out = tickers_from_environ()
    assert out == [Ticker.NVDA, Ticker.MU]


def test_tickers_from_environ_unknown_raises(monkeypatch):
    from sources.symbols import tickers_from_environ

    monkeypatch.setenv("NYSE_TICKERS", "NOT_A_REAL_TICKER_XYZ")
    with pytest.raises(ValueError, match="Unknown ticker"):
        tickers_from_environ()
