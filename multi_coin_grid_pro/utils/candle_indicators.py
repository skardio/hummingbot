"""
Candle Indicators Calculator

Berekent technische indicators van 5m OHLCV candles:
- RSI(14)
- VWAP (session)
- ATR(14) as percentage
- Wick ratio (market structure)
- Trend percentages (1h, 4h, 24h)
- 5m change percentage
"""

import logging
from decimal import Decimal
from typing import List

logger = logging.getLogger(__name__)


class CandleIndicatorsCalculator:
    """
    Berekent indicators van OHLCV candle data voor SmartEntryFilter.
    """

    def __init__(self):
        self.rsi_period = 14
        self.atr_period = 14

    def calculate_rsi(self, closes: List[Decimal], period: int = 14) -> float:
        """
        Berekent RSI(14) van close prices.

        Returns:
            RSI waarde 0-100, of 50.0 als insufficient data
        """
        if len(closes) < period + 1:
            return 50.0  # Neutral RSI

        # Calculate price changes
        changes = []
        for i in range(1, len(closes)):
            changes.append(float(closes[i] - closes[i - 1]))

        if len(changes) < period:
            return 50.0

        # Separate gains and losses
        gains = [max(c, 0) for c in changes[-period:]]
        losses = [abs(min(c, 0)) for c in changes[-period:]]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0  # No losses = overbought

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def calculate_vwap(
        self,
        highs: List[Decimal],
        lows: List[Decimal],
        closes: List[Decimal],
        volumes: List[Decimal]
    ) -> Decimal:
        """
        Berekent session VWAP (Volume Weighted Average Price).

        Returns:
            VWAP price, or last close if insufficient data
        """
        if not closes or len(closes) < 1:
            return Decimal("0")

        if len(highs) != len(lows) or len(lows) != len(closes) or len(closes) != len(volumes):
            return closes[-1]  # Fallback to last close

        # Typical price = (high + low + close) / 3
        total_volume = Decimal("0")
        total_pv = Decimal("0")

        for i in range(len(closes)):
            typical_price = (highs[i] + lows[i] + closes[i]) / Decimal("3")
            volume = volumes[i]

            total_pv += typical_price * volume
            total_volume += volume

        if total_volume == 0:
            return closes[-1]

        vwap = total_pv / total_volume
        return vwap

    def calculate_atr_pct(
        self,
        highs: List[Decimal],
        lows: List[Decimal],
        closes: List[Decimal],
        period: int = 14
    ) -> float:
        """
        Berekent ATR(14) als percentage van prijs.

        Returns:
            ATR% (e.g. 1.5 = 1.5%), or 0.0 if insufficient data
        """
        if len(closes) < period + 1:
            return 0.0

        # Calculate True Ranges
        true_ranges = []
        for i in range(1, len(closes)):
            high_low = float(highs[i] - lows[i])
            high_close = abs(float(highs[i] - closes[i - 1]))
            low_close = abs(float(lows[i] - closes[i - 1]))

            tr = max(high_low, high_close, low_close)
            true_ranges.append(tr)

        if len(true_ranges) < period:
            return 0.0

        # Average True Range
        atr = sum(true_ranges[-period:]) / period

        # Convert to percentage of current price
        current_price = float(closes[-1])
        if current_price == 0:
            return 0.0

        atr_pct = (atr / current_price) * 100
        return atr_pct

    def calculate_wick_ratio(
        self,
        high: Decimal,
        low: Decimal,
        open_price: Decimal,
        close: Decimal
    ) -> float:
        """
        Berekent wick ratio van laatste candle.

        REVISED: (upper_wick + lower_wick) / body

        Ratio > 0.25 = voldoende wicks voor healthy structure
        Ratio < 0.25 = body-dominant / no wicks (trending hard, mogelijk onveilig voor grid)

        Returns:
            Wick ratio (typically 0.0 - 3.0)
        """
        body_high = max(open_price, close)
        body_low = min(open_price, close)

        upper_wick = float(high - body_high)
        lower_wick = float(body_low - low)
        body = float(body_high - body_low)

        # Total wick length
        total_wick = upper_wick + lower_wick

        # Avoid division by zero - if body is tiny, use tiny denominator
        if body < 0.0001:
            # Doji or very small body - check if there are wicks
            if total_wick > 0.001:
                return 2.0  # Has wicks but no body = neutral/good structure
            else:
                return 0.0  # No body, no wicks = bad data

        ratio = total_wick / body

        # Clamp to reasonable range
        ratio = max(0.0, min(ratio, 10.0))

        return ratio

    def calculate_trend_pct(
        self,
        closes: List[Decimal],
        lookback_candles: int
    ) -> float:
        """
        Berekent % change over lookback period.

        Args:
            closes: List of close prices (most recent last)
            lookback_candles: Number of candles to look back

        Returns:
            Percentage change (e.g. 2.5 = +2.5%), or 0.0 if insufficient data
        """
        if len(closes) < lookback_candles + 1:
            return 0.0

        start_price = closes[-(lookback_candles + 1)]
        end_price = closes[-1]

        if start_price == 0:
            return 0.0

        pct_change = float((end_price - start_price) / start_price * 100)
        return pct_change

    def calculate_change_5m_pct(
        self,
        open_price: Decimal,
        close: Decimal
    ) -> float:
        """
        Berekent % change van laatste 5m candle.

        Returns:
            Percentage change (e.g. -1.2 = -1.2%)
        """
        if open_price == 0:
            return 0.0

        pct_change = float((close - open_price) / open_price * 100)
        return pct_change
