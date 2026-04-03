import logging
import pytz
from typing import cast, List, Optional
from datetime import datetime

from .models import Ticker, Earnings
from .symbols import yfinance_symbol

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
        yf_ticker = yf.Ticker(yfinance_symbol(t))

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
