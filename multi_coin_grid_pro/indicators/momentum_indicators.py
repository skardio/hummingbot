"""
Momentum Indicator Service for Entry Health Guards.

Provides unified indicator calculations for VWAP slopes and price acceleration
across multiple timeframes. Supports both Kraken EUR and Bitget USDT connectors.

Part of EPIC v3.4 - Momentum Health Guards
"""

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class MomentumMetrics:
    """
    Container for momentum health metrics.

    All percentage values are expressed as percentages (e.g., 5.0 = 5%).
    None values indicate missing data with reason provided.
    """
    timestamp: float
    symbol: str

    # VWAP metrics
    vwap_deviation_pct: Optional[float]  # Current price vs VWAP
    vwap_slope_5m_pct: Optional[float]   # VWAP momentum: now vs 5m ago
    vwap_slope_15m_pct: Optional[float]  # VWAP momentum: now vs 15m ago

    # Price acceleration metrics
    accel_5m_pct: Optional[float]   # Price change over 5 minutes
    accel_15m_pct: Optional[float]  # Price change over 15 minutes

    # Diagnostic info
    reason: Optional[str] = None  # Explanation if any metric is None

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"MomentumMetrics({self.symbol}: "
            f"vwap_dev={self.vwap_deviation_pct:.2f}% " if self.vwap_deviation_pct else f"MomentumMetrics({self.symbol}: vwap_dev=None "
            f"slope5m={self.vwap_slope_5m_pct:.2f}% " if self.vwap_slope_5m_pct else "slope5m=None "
            f"slope15m={self.vwap_slope_15m_pct:.2f}% " if self.vwap_slope_15m_pct else "slope15m=None "
            f"acc5m={self.accel_5m_pct:.2f}% " if self.accel_5m_pct else "acc5m=None "
            f"acc15m={self.accel_15m_pct:.2f}%)" if self.accel_15m_pct else "acc15m=None)"
        )


class MomentumIndicatorService:
    """
    Calculates momentum health indicators from candle data.

    Supports both Kraken EUR and Bitget USDT connectors with unified interface.
    Handles missing data gracefully with descriptive error messages.
    """

    # Minimum candles required for each calculation
    MIN_CANDLES_5M = 5    # 5 minutes of 1m candles
    MIN_CANDLES_15M = 15  # 15 minutes of 1m candles

    def __init__(self, connector_name: str, logger: Optional[logging.Logger] = None):
        """
        Initialize indicator service.

        Args:
            connector_name: Exchange connector ("kraken" or "bitget")
            logger: Optional logger instance (creates default if None)
        """
        self.connector_name = connector_name
        self.logger = logger or logging.getLogger(__name__)

        # Rate limiting for warnings (symbol -> last_warning_timestamp)
        self._warning_timestamps: Dict[str, float] = {}
        self._warning_cooldown_sec = 300  # 5 minutes

    def calculate_metrics(
        self,
        symbol: str,
        current_price: float,
        current_vwap: Optional[float],
        candles: List[Dict],
        timestamp: Optional[float] = None
    ) -> MomentumMetrics:
        """
        Calculate all momentum metrics for a symbol.

        Args:
            symbol: Trading pair symbol (e.g., "PEPE-EUR", "BTC-USDT")
            current_price: Current market price
            current_vwap: Current VWAP value (None if unavailable)
            candles: List of candle dicts with keys: timestamp, open, high, low, close, volume, vwap
                    Ordered chronologically (oldest first)
            timestamp: Optional timestamp (defaults to current time)

        Returns:
            MomentumMetrics with all calculated values or None with reason
        """
        ts = timestamp or time.time()

        # Validate inputs
        if not candles:
            return self._create_error_metrics(
                symbol, ts, "insufficient_history", "No candles provided"
            )

        if current_price <= 0:
            return self._create_error_metrics(
                symbol, ts, "invalid_price", f"Invalid current price: {current_price}"
            )

        # Calculate VWAP deviation
        vwap_dev = self._calculate_vwap_deviation(current_price, current_vwap)

        # Calculate VWAP slopes (5m and 15m)
        vwap_slope_5m, reason_5m = self._calculate_vwap_slope(candles, window_minutes=5)
        vwap_slope_15m, reason_15m = self._calculate_vwap_slope(candles, window_minutes=15)

        # Calculate price acceleration (5m and 15m)
        accel_5m, accel_reason_5m = self._calculate_acceleration(candles, current_price, window_minutes=5)
        accel_15m, accel_reason_15m = self._calculate_acceleration(candles, current_price, window_minutes=15)

        # Determine overall reason if any metric failed
        reason = None
        if vwap_dev is None:
            reason = "no_vwap_data"
        elif vwap_slope_5m is None or vwap_slope_15m is None:
            reason = reason_5m or reason_15m
        elif accel_5m is None or accel_15m is None:
            reason = accel_reason_5m or accel_reason_15m

        # Log warning once per symbol if data is missing (rate-limited)
        # insufficient_history is expected at startup — log as DEBUG, not WARNING
        if reason:
            if "insufficient_history" in reason:
                self.logger.debug(f"[{self.connector_name}] {symbol}: Incomplete metrics: {reason} (startup warmup)")
            else:
                self._log_warning_once(symbol, f"Incomplete metrics: {reason}")

        return MomentumMetrics(
            timestamp=ts,
            symbol=symbol,
            vwap_deviation_pct=vwap_dev,
            vwap_slope_5m_pct=vwap_slope_5m,
            vwap_slope_15m_pct=vwap_slope_15m,
            accel_5m_pct=accel_5m,
            accel_15m_pct=accel_15m,
            reason=reason
        )

    def _calculate_vwap_deviation(
        self,
        current_price: float,
        current_vwap: Optional[float]
    ) -> Optional[float]:
        """
        Calculate percentage deviation of price from VWAP.

        Formula: (price / vwap - 1) * 100
        Positive = price above VWAP, Negative = price below VWAP

        Returns:
            Percentage deviation or None if VWAP unavailable
        """
        if current_vwap is None or current_vwap <= 0:
            return None

        try:
            deviation = (current_price / current_vwap - 1.0) * 100.0
            return round(deviation, 2)
        except (ZeroDivisionError, ValueError, TypeError):
            return None

    def _calculate_vwap_slope(
        self,
        candles: List[Dict],
        window_minutes: int
    ) -> Tuple[Optional[float], Optional[str]]:
        """
        Calculate VWAP slope over specified window.

        Formula: (vwap_now / vwap_N_minutes_ago - 1) * 100

        Args:
            candles: Candle data (ordered oldest to newest)
            window_minutes: Lookback period in minutes (5 or 15)

        Returns:
            Tuple of (slope_pct, reason_if_none)
        """
        if len(candles) < window_minutes + 1:
            return None, f"insufficient_history_for_{window_minutes}m"

        try:
            # Get VWAP from most recent candle (current)
            # Support both dict and object types
            # Fall back to typical price (H+L+C)/3 when vwap field is absent (e.g. OKX candles)
            candle_now = candles[-1]
            vwap_now = candle_now.get("vwap") if isinstance(candle_now, dict) else getattr(candle_now, "vwap", None)
            if vwap_now is None or vwap_now <= 0:
                if isinstance(candle_now, dict):
                    h, low, c = candle_now.get("high"), candle_now.get("low"), candle_now.get("close")
                else:
                    h = getattr(candle_now, "high", None)
                    low = getattr(candle_now, "low", None)
                    c = getattr(candle_now, "close", None)
                if h and low and c:
                    vwap_now = (float(h) + float(low) + float(c)) / 3.0
                else:
                    return None, "no_vwap_current"

            # Get VWAP from N minutes ago
            # Assuming candles are 1-minute intervals
            candle_ago = candles[-(window_minutes + 1)]
            vwap_ago = candle_ago.get("vwap") if isinstance(candle_ago, dict) else getattr(candle_ago, "vwap", None)
            if vwap_ago is None or vwap_ago <= 0:
                if isinstance(candle_ago, dict):
                    h, low, c = candle_ago.get("high"), candle_ago.get("low"), candle_ago.get("close")
                else:
                    h = getattr(candle_ago, "high", None)
                    low = getattr(candle_ago, "low", None)
                    c = getattr(candle_ago, "close", None)
                if h and low and c:
                    vwap_ago = (float(h) + float(low) + float(c)) / 3.0
                else:
                    return None, f"no_vwap_{window_minutes}m_ago"

            slope = (vwap_now / vwap_ago - 1.0) * 100.0
            return round(slope, 2), None

        except (ZeroDivisionError, ValueError, TypeError, IndexError):
            return None, f"calculation_unavailable_{window_minutes}m"

    def _calculate_acceleration(
        self,
        candles: List[Dict],
        current_price: float,
        window_minutes: int
    ) -> Tuple[Optional[float], Optional[str]]:
        """
        Calculate price acceleration over specified window.

        Formula: (price_now / price_N_minutes_ago - 1) * 100

        Args:
            candles: Candle data (ordered oldest to newest)
            current_price: Current market price
            window_minutes: Lookback period in minutes (5 or 15)

        Returns:
            Tuple of (acceleration_pct, reason_if_none)
        """
        if len(candles) < window_minutes + 1:
            return None, f"insufficient_history_for_{window_minutes}m"

        try:
            # Get close price from N minutes ago
            # Assuming candles are 1-minute intervals
            # Support both dict and object types
            candle_ago = candles[-(window_minutes + 1)]
            price_ago = candle_ago.get("close") if isinstance(candle_ago, dict) else getattr(candle_ago, "close", None)
            if price_ago is None or price_ago <= 0:
                return None, f"no_price_{window_minutes}m_ago"

            accel = (current_price / price_ago - 1.0) * 100.0
            return round(accel, 2), None

        except (ZeroDivisionError, ValueError, TypeError, IndexError):
            return None, f"calculation_unavailable_{window_minutes}m"

    def _create_error_metrics(
        self,
        symbol: str,
        timestamp: float,
        error_type: str,
        message: str
    ) -> MomentumMetrics:
        """Create metrics object with all None values and error reason."""
        self._log_warning_once(symbol, f"{error_type}: {message}")

        return MomentumMetrics(
            timestamp=timestamp,
            symbol=symbol,
            vwap_deviation_pct=None,
            vwap_slope_5m_pct=None,
            vwap_slope_15m_pct=None,
            accel_5m_pct=None,
            accel_15m_pct=None,
            reason=error_type
        )

    def _log_warning_once(self, symbol: str, message: str):
        """
        Log warning message with rate limiting (once per cooldown period per symbol).

        Args:
            symbol: Trading pair symbol
            message: Warning message to log
        """
        now = time.time()
        last_warning = self._warning_timestamps.get(symbol, 0)

        if now - last_warning >= self._warning_cooldown_sec:
            self.logger.warning(f"[{self.connector_name}] {symbol}: {message}")
            self._warning_timestamps[symbol] = now

    def has_sufficient_data(self, metrics: MomentumMetrics) -> bool:
        """
        Check if metrics contain all required data for guard decisions.

        Args:
            metrics: MomentumMetrics instance to check

        Returns:
            True if all metrics are available, False otherwise
        """
        return all([
            metrics.vwap_deviation_pct is not None,
            metrics.vwap_slope_5m_pct is not None,
            metrics.vwap_slope_15m_pct is not None,
            metrics.accel_5m_pct is not None,
            metrics.accel_15m_pct is not None
        ])
