import logging
import warnings
from typing import Hashable, List, Any, Dict
from datetime import datetime, timedelta, timezone

from .models import Period, Ticker, Candle
from .symbols import yfinance_symbol

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


class Source:
    def __init__(self, with_prepostmarket: bool):
        self.with_prepostmarket = with_prepostmarket

    def get_hourly_candles(
        self, tickers: List[Ticker], days: int
    ) -> Dict[Ticker, List[Candle]]:
        now = datetime.now(timezone.utc)

        return self._get_candles(
            tickers=tickers,
            period=Period.Hour,
            start=now - timedelta(days=days),
            end=now,
        )

    def get_daily_candles(
        self, tickers: List[Ticker], days: int
    ) -> Dict[Ticker, List[Candle]]:
        now = datetime.now(timezone.utc)

        return self._get_candles(
            tickers=tickers,
            period=Period.Day,
            start=now - timedelta(days=days),
            end=now,
        )

    def get_dayly_candles(
        self, tickers: List[Ticker], days: int
    ) -> Dict[Ticker, List[Candle]]:
        warnings.warn(
            "get_dayly_candles is deprecated; use get_daily_candles",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_daily_candles(tickers, days)

    def get_minutely_candles(
        self, tickers: List[Ticker], days: int
    ) -> Dict[Ticker, List[Candle]]:
        now = datetime.now(timezone.utc)

        return self._get_candles(
            tickers=tickers,
            period=Period.Minute,
            start=now - timedelta(days=days),
            end=now,
        )

    def _get_current_prices(self, tickers: List[Ticker]) -> Dict[Ticker, float]:
        result: Dict[Ticker, float] = {}
        for ticker in tickers:
            yf_ticker = yfinance_symbol(ticker)
            t = yf.Ticker(yf_ticker)

            price = t.fast_info.get("lastPrice")

            if price is not None:
                result[ticker] = float(price)

        return result

    def _get_candles(
        self, tickers: List[Ticker], period: Period, start: datetime, end: datetime
    ) -> Dict[Ticker, List[Candle]]:
        interval = parse_period(period)
        yf_tickers = [yfinance_symbol(t) for t in tickers]

        logger.info(
            "Downloading candles: [%s - %s] period=%s",
            start.strftime("%Y-%m-%d %H:%M:%S %Z"),
            end.strftime("%Y-%m-%d %H:%M:%S %Z"),
            period.value,
        )
        data = yf.download(
            start=start,
            end=end,
            tickers=yf_tickers,
            interval=interval,
            group_by="ticker",
            auto_adjust=False,
            threads=True,
            progress=False,
            prepost=self.with_prepostmarket,
        )

        result: Dict[Ticker, List[Candle]] = {ticker: [] for ticker in tickers}
        if data is None or data.empty:
            raise ValueError(
                f"No candles returned from yfinance, period={period.value}"
            )

        for ticker, yf_ticker in zip(tickers, yf_tickers):
            if yf_ticker not in data:
                logger.error(
                    "No candles returned for ticker=%s, yf_ticker=%s, period=%s",
                    ticker.value,
                    yf_ticker,
                    period.value,
                )
                raise ValueError(
                    f"No candles returned for ticker={ticker.value}, "
                    f"yf_ticker={yf_ticker}, period={period.value}"
                )

            df = data[yf_ticker].dropna()

            candles: List[Candle] = []
            for index, row in df.iterrows():
                candles.append(self._parse_candle(index, row))

            result[ticker] = candles

        return result

    def _parse_candle(self, index: Hashable, row: pd.Series) -> Candle:
        if not isinstance(index, pd.Timestamp):
            raise TypeError(f"Expected pd.Timestamp, got {type(index)}")

        return Candle(
            time=index.to_pydatetime(),
            open=_require_float(row["Open"], "Open"),
            high=_require_float(row["High"], "High"),
            low=_require_float(row["Low"], "Low"),
            close=_require_float(row["Close"], "Close"),
            volume=_require_float(row["Volume"], "Volume"),
        )


def _require_float(value: Any, field: str) -> float:
    if not isinstance(value, (float, int)):
        raise TypeError(f"{field} must be float, got {type(value)}")
    return float(value)


def parse_period(period: Period) -> str:
    if period == Period.Day:
        return "1d"
    if period == Period.Hour:
        return "1h"
    if period == Period.Minute:
        return "1m"
    raise ValueError(f"Unsupported period: {period!r}")
