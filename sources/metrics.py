import logging
from typing import List, Optional

from finvizfinance.quote import finvizfinance

from .models import Ticker, TickerMetrics

logger = logging.getLogger(__name__)


class Source:
    def get_metrics(self, tickers: List[Ticker]) -> List[TickerMetrics]:
        logger.info("Loading metrics: tickers=%s", [t.value for t in tickers])
        return [self._fetch_ticker(ticker) for ticker in tickers]

    def _fetch_ticker(self, ticker: Ticker) -> TickerMetrics:
        stock = finvizfinance(parse_ticker(ticker))
        data = stock.ticker_fundament()

        pp = self._parse_percent
        pf = self._parse_float

        return TickerMetrics(
            ticker=ticker,
            perf_week=pp(data.get("Perf Week")),
            rsi_14=pf(data.get("RSI (14)")),
            sma20_pct=pp(data.get("SMA20")),
            sma50_pct=pp(data.get("SMA50")),
            atr=pf(data.get("ATR (14)")),
            relative_volume=pf(data.get("Rel Volume")),
            beta=pf(data.get("Beta")),
        )

    @staticmethod
    def _parse_percent(value: Optional[str]) -> float:
        if value is None or value.strip() in ("", "-"):
            raise ValueError("Missing percent value")

        return float(value.replace("%", ""))

    @staticmethod
    def _parse_float(value: Optional[str]) -> float:
        if value is None or value.strip() in ("", "-"):
            raise ValueError("Missing float value")

        return float(value)


def parse_ticker(ticker: Ticker) -> str:
    if ticker == Ticker.SNDK:
        return "SNDK"
    elif ticker == Ticker.QQQ:
        return "QQQ"
    elif ticker == Ticker.SMH:
        return "SMH"
    elif ticker == Ticker.MU:
        return "MU"
    elif ticker == Ticker.NVDA:
        return "NVDA"
    elif ticker == Ticker.TLT:
        return "TLT"
    elif ticker == Ticker.VIX:
        return "VIXY"
    elif ticker == Ticker.BNO:
        return "BNO"
    elif ticker == Ticker.MSFT:
        return "MSFT"
    elif ticker == Ticker.META:
        return "META"
    elif ticker == Ticker.AMZN:
        return "AMZN"
    elif ticker == Ticker.ASML:
        return "ASML"
    elif ticker == Ticker.LITE:
        return "LITE"
    elif ticker == Ticker.CIEN:
        return "CIEN"
    elif ticker == Ticker.NBIS:
        return "NBIS"
    elif ticker == Ticker.ORCL:
        return "ORCL"
