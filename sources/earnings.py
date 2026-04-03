import logging
import pytz
from typing import cast, List, Optional
from datetime import datetime

from .models import Ticker, Earnings

import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)


class Source:
    def get_closest_earnings(self, tickers: List[Ticker]) -> List[Earnings]:
        earnings: List[Earnings] = []
        logger.info("Loading earnings: tickers=%s", [t.value for t in tickers])

        for ticker in tickers:
            if not ticker.is_stock():
                continue

            earning = self._load_closest_earnings(ticker)
            if not earning:
                continue
            earnings.append(earning)

        return earnings

    def _load_closest_earnings(self, t: Ticker) -> Optional[Earnings]:
        yf_ticker = yf.Ticker(parse_ticker(t))

        df = yf_ticker.get_earnings_dates()
        if df is None or df.empty:
            logger.warning("Earnings dates not found: ticker=%s", t.value)
            return None

        dt_index = pd.to_datetime(df.index).tz_convert("UTC")
        now = datetime.now(pytz.UTC)

        future_dates = dt_index[dt_index > now]
        past_dates = dt_index[dt_index <= now]

        logger.info(
            "Loaded earnings: ticker=%s now=%s index=%s",
            t.value,
            now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            [str(x) for x in dt_index],
        )
        if len(future_dates) == 0 or len(past_dates) == 0:
            raise Exception("future/past earnings dates not found")

        return Earnings(
            ticker=t,
            next_earnings_date=cast(datetime, future_dates.min()),
            prev_earnings_date=cast(datetime, past_dates.max()),
        )


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
        return "^VIX"
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
