"""
Признаки свечей для ``TechnicalAgentInput`` — зеркало ``pystockinvest/agent/market/candles.py``.
"""

from __future__ import annotations

import statistics
from typing import List

from domain import Candle, TickerData

from ..market_dto import CandleFeaturesInput


def calculate_candle_features(ticker_data: TickerData) -> CandleFeaturesInput:
    daily_candles = ticker_data.daily_candles
    hourly_candles = ticker_data.hourly_candles

    current_candle = daily_candles[-1]
    last_close_price = current_candle.close

    change_1d = _calculate_change(daily_candles, 1, last_close_price)
    change_3d = _calculate_change(daily_candles, 3, last_close_price)
    change_5d = _calculate_change(daily_candles, 5, last_close_price)

    range_1d = _calculate_range_1d(current_candle)
    volatility_5d = _calculate_volatility(daily_candles, 5)
    volume_vs_avg = _calculate_volume_vs_avg(daily_candles, 5)

    last_5_candles = daily_candles[-5:]
    high_5d = max(c.high for c in last_5_candles)
    low_5d = min(c.low for c in last_5_candles)

    distance_from_5d_high = _calculate_distance_from_level(last_close_price, high_5d)
    distance_from_5d_low = _calculate_distance_from_level(last_close_price, low_5d)

    last_20 = daily_candles[-20:]
    high_20d = max(c.high for c in last_20)
    low_20d = min(c.low for c in last_20)

    distance_from_20d_high = _calculate_distance_from_level(last_close_price, high_20d)
    distance_from_20d_low = _calculate_distance_from_level(last_close_price, low_20d)

    intraday_change = _calculate_intraday_change(current_candle)

    change_3h = _calculate_change(hourly_candles, 3, hourly_candles[-1].close)
    change_6h = _calculate_change(hourly_candles, 6, hourly_candles[-1].close)
    change_12h = _calculate_change(hourly_candles, 12, hourly_candles[-1].close)
    change_24h = _calculate_change(hourly_candles, 24, hourly_candles[-1].close)

    last_24h = hourly_candles[-24:]
    high_24h = max(c.high for c in last_24h)
    low_24h = min(c.low for c in last_24h)

    distance_from_24h_high = _calculate_distance_from_level(
        hourly_candles[-1].close, high_24h
    )
    distance_from_24h_low = _calculate_distance_from_level(
        hourly_candles[-1].close, low_24h
    )
    volume_vs_24h_avg = _calculate_volume_vs_avg(hourly_candles, 24)

    last_hour = hourly_candles[-1]
    body_pct = _calculate_body_pct(last_hour)
    upper_wick_pct = _calculate_upper_wick_pct(last_hour)
    lower_wick_pct = _calculate_lower_wick_pct(last_hour)
    close_position_in_range = _calculate_close_position(last_hour)

    return CandleFeaturesInput(
        current_price=ticker_data.current_price,
        change_1d=change_1d,
        change_3d=change_3d,
        change_5d=change_5d,
        range_1d=range_1d,
        volatility_5d=volatility_5d,
        volume_vs_avg=volume_vs_avg,
        distance_from_5d_high=distance_from_5d_high,
        distance_from_5d_low=distance_from_5d_low,
        distance_from_20d_high=distance_from_20d_high,
        distance_from_20d_low=distance_from_20d_low,
        intraday_change=intraday_change,
        change_3h=change_3h,
        change_6h=change_6h,
        change_12h=change_12h,
        change_24h=change_24h,
        distance_from_24h_high=distance_from_24h_high,
        distance_from_24h_low=distance_from_24h_low,
        volume_vs_24h_avg=volume_vs_24h_avg,
        body_pct=body_pct,
        upper_wick_pct=upper_wick_pct,
        lower_wick_pct=lower_wick_pct,
        close_position_in_range=close_position_in_range,
    )


def _calculate_change(candles: List[Candle], periods: int, current_price: float) -> float:
    if len(candles) <= periods:
        return 0.0

    old_price = candles[-periods - 1].close
    if old_price == 0:
        return 0.0

    return ((current_price - old_price) / old_price) * 100


def _calculate_range_1d(candle: Candle) -> float:
    price_range = candle.high - candle.low
    return (price_range / candle.close) * 100


def _calculate_volatility(candles: List[Candle], days: int) -> float:
    analysis_candles = candles[-days:]
    daily_changes = []
    for i in range(1, len(analysis_candles)):
        prev_close = analysis_candles[i - 1].close
        curr_close = analysis_candles[i].close

        if prev_close != 0:
            change = ((curr_close - prev_close) / prev_close) * 100
            daily_changes.append(change)

    return statistics.stdev(daily_changes) if len(daily_changes) > 1 else 0.0


def _calculate_volume_vs_avg(candles: List[Candle], periods: int) -> float:
    if not candles:
        return 100.0

    current_volume = candles[-1].volume
    analysis_candles = candles[-periods:]
    avg_volume = sum(c.volume for c in analysis_candles) / len(analysis_candles)
    if avg_volume == 0:
        return 100.0

    return (current_volume / avg_volume) * 100


def _calculate_distance_from_level(current_price: float, level: float) -> float:
    return ((current_price - level) / level) * 100


def _calculate_intraday_change(candle: Candle) -> float:
    change = candle.close - candle.open
    return (change / candle.open) * 100


def _calculate_body_pct(candle: Candle) -> float:
    if candle.high == candle.low:
        return 0.0

    body = abs(candle.close - candle.open)
    return (body / (candle.high - candle.low)) * 100


def _calculate_upper_wick_pct(candle: Candle) -> float:
    if candle.high == candle.low:
        return 0.0

    upper_wick = candle.high - max(candle.close, candle.open)
    return (upper_wick / (candle.high - candle.low)) * 100


def _calculate_lower_wick_pct(candle: Candle) -> float:
    if candle.high == candle.low:
        return 0.0

    lower_wick = min(candle.close, candle.open) - candle.low
    return (lower_wick / (candle.high - candle.low)) * 100


def _calculate_close_position(candle: Candle) -> float:
    if candle.high == candle.low:
        return 50.0

    return ((candle.close - candle.low) / (candle.high - candle.low)) * 100
