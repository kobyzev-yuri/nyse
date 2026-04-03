import logging
from typing import List, Optional

from finvizfinance.quote import finvizfinance

from .models import Ticker, TickerMetrics
from .symbols import finviz_symbol

logger = logging.getLogger(__name__)


class Source:
    def get_metrics(self, tickers: List[Ticker]) -> List[TickerMetrics]:
        logger.info("Loading metrics: tickers=%s", [t.value for t in tickers])
        return [self._fetch_ticker(ticker) for ticker in tickers]

    def _fetch_ticker(self, ticker: Ticker) -> TickerMetrics:
        stock = finvizfinance(finviz_symbol(ticker))
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
