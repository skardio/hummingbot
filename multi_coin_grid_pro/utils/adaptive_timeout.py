"""
Story D1: Adaptive Timeout Calculator
======================================

Dynamically adjusts executor timeout based on market volatility to:
- Reduce false timeouts during high volatility (more time for fills)
- Detect stalls faster during low volatility (tighter timeout)

Volatility measured using ATR (Average True Range) or rolling standard deviation.

Usage:
    calculator = AdaptiveTimeout(base_timeout_sec=600)
    adjusted_timeout = calculator.calculate_timeout(
        symbol="PEPE-USD",
        current_price=0.00001234,
        volatility_data=recent_candles
    )
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import List


@dataclass
class VolatilityMetrics:
    """Volatility indicators for timeout adjustment"""

    atr: Decimal  # Average True Range
    atr_pct: float  # ATR as % of current price
    rolling_std: Decimal  # Rolling standard deviation
    std_pct: float  # Std dev as % of mean price

    # Classification
    regime: str  # "LOW", "NORMAL", "HIGH", "EXTREME"


@dataclass
class TimeoutAdjustment:
    """Calculated timeout with adjustment reasoning"""

    original_timeout_sec: int
    adjusted_timeout_sec: int
    adjustment_factor: float  # multiplier applied (e.g., 1.5 = +50%)
    volatility_regime: str  # "LOW", "NORMAL", "HIGH", "EXTREME"
    reasoning: str  # human-readable explanation


class AdaptiveTimeout:
    """Calculate optimal timeout based on volatility"""

    # Volatility regime thresholds (ATR as % of price)
    LOW_VOL_THRESHOLD = 0.01  # <1% ATR
    NORMAL_VOL_THRESHOLD = 0.03  # 1-3% ATR
    HIGH_VOL_THRESHOLD = 0.06  # 3-6% ATR
    # >6% = EXTREME

    # Timeout adjustment factors by regime
    TIMEOUT_MULTIPLIERS = {
        "LOW": 0.7,      # -30% (faster timeout)
        "NORMAL": 1.0,   # no change
        "HIGH": 1.5,     # +50% (more time)
        "EXTREME": 2.0,  # +100% (much more time)
    }

    # Bounds to prevent extreme timeouts
    MIN_TIMEOUT_SEC = 180  # 3 minutes minimum
    MAX_TIMEOUT_SEC = 1800  # 30 minutes maximum

    def __init__(
        self,
        base_timeout_sec: int = 600,
        use_atr: bool = True,
        atr_period: int = 14
    ):
        """
        Args:
            base_timeout_sec: Default timeout (e.g., 600 = 10 minutes)
            use_atr: Use ATR for volatility (if False, use rolling std)
            atr_period: Period for ATR calculation (default: 14 candles)
        """
        self.base_timeout_sec = base_timeout_sec
        self.use_atr = use_atr
        self.atr_period = atr_period
        self.logger = logging.getLogger(__name__)

    def calculate_timeout(
        self,
        symbol: str,
        current_price: Decimal,
        high_prices: List[Decimal],
        low_prices: List[Decimal],
        close_prices: List[Decimal]
    ) -> TimeoutAdjustment:
        """
        Calculate adjusted timeout based on recent price volatility.

        Args:
            symbol: Trading pair (for logging)
            current_price: Current market price
            high_prices: Recent high prices (last N candles)
            low_prices: Recent low prices (last N candles)
            close_prices: Recent close prices (last N candles)

        Returns:
            TimeoutAdjustment with reasoning
        """
        # Calculate volatility metrics
        vol_metrics = self._calculate_volatility(
            current_price, high_prices, low_prices, close_prices
        )

        # Determine regime
        regime = self._classify_regime(vol_metrics)

        # Get multiplier
        multiplier = self.TIMEOUT_MULTIPLIERS[regime]

        # Calculate adjusted timeout
        adjusted = int(self.base_timeout_sec * multiplier)

        # Apply bounds
        adjusted = max(self.MIN_TIMEOUT_SEC, min(self.MAX_TIMEOUT_SEC, adjusted))

        # Build reasoning
        reasoning = self._build_reasoning(regime, vol_metrics, multiplier, adjusted)

        return TimeoutAdjustment(
            original_timeout_sec=self.base_timeout_sec,
            adjusted_timeout_sec=adjusted,
            adjustment_factor=multiplier,
            volatility_regime=regime,
            reasoning=reasoning
        )

    def _calculate_volatility(
        self,
        current_price: Decimal,
        highs: List[Decimal],
        lows: List[Decimal],
        closes: List[Decimal]
    ) -> VolatilityMetrics:
        """Calculate ATR and rolling std dev"""
        if not highs or not lows or not closes:
            # No data - assume normal volatility
            return VolatilityMetrics(
                atr=Decimal("0"),
                atr_pct=0.02,  # 2% default
                rolling_std=Decimal("0"),
                std_pct=0.02,
                regime="NORMAL"
            )

        # Calculate ATR (simplified: average of high-low ranges)
        if self.use_atr:
            # True Range for each period
            true_ranges = []
            for i in range(len(highs)):
                high_low = highs[i] - lows[i]

                if i > 0:
                    high_close = abs(highs[i] - closes[i - 1])
                    low_close = abs(lows[i] - closes[i - 1])
                    true_range = max(high_low, high_close, low_close)
                else:
                    true_range = high_low

                true_ranges.append(true_range)

            # Average True Range
            atr = sum(true_ranges) / len(true_ranges)
            atr_pct = float(atr / current_price) if current_price > 0 else 0.0
        else:
            atr = Decimal("0")
            atr_pct = 0.0

        # Calculate rolling standard deviation
        mean_price = sum(closes) / len(closes)
        variance = sum((p - mean_price) ** 2 for p in closes) / len(closes)
        std_dev = variance ** Decimal("0.5")
        std_pct = float(std_dev / mean_price) if mean_price > 0 else 0.0

        return VolatilityMetrics(
            atr=atr,
            atr_pct=atr_pct,
            rolling_std=std_dev,
            std_pct=std_pct,
            regime="UNKNOWN"  # classified later
        )

    def _classify_regime(self, vol_metrics: VolatilityMetrics) -> str:
        """Classify volatility as LOW/NORMAL/HIGH/EXTREME"""
        # Use ATR% if available, otherwise std%
        vol_pct = vol_metrics.atr_pct if self.use_atr else vol_metrics.std_pct

        if vol_pct < self.LOW_VOL_THRESHOLD:
            return "LOW"
        elif vol_pct < self.NORMAL_VOL_THRESHOLD:
            return "NORMAL"
        elif vol_pct < self.HIGH_VOL_THRESHOLD:
            return "HIGH"
        else:
            return "EXTREME"

    def _build_reasoning(
        self,
        regime: str,
        vol_metrics: VolatilityMetrics,
        multiplier: float,
        adjusted: int
    ) -> str:
        """Build human-readable reasoning string"""
        vol_pct = vol_metrics.atr_pct if self.use_atr else vol_metrics.std_pct
        vol_type = "ATR" if self.use_atr else "StdDev"

        direction = "increased" if multiplier > 1.0 else "decreased" if multiplier < 1.0 else "unchanged"
        pct_change = abs((multiplier - 1.0) * 100)

        return (
            f"{regime} volatility ({vol_type}={vol_pct:.2%}) → "
            f"timeout {direction} by {pct_change:.0f}% to {adjusted}s"
        )

    def get_recommended_timeout(
        self,
        symbol: str,
        market_data: dict
    ) -> int:
        """
        Simplified interface - extract data and return timeout integer.

        Args:
            symbol: Trading pair
            market_data: Dict with 'current_price', 'highs', 'lows', 'closes'

        Returns:
            Adjusted timeout in seconds
        """
        try:
            adjustment = self.calculate_timeout(
                symbol=symbol,
                current_price=Decimal(str(market_data['current_price'])),
                high_prices=[Decimal(str(h)) for h in market_data['highs']],
                low_prices=[Decimal(str(low)) for low in market_data['lows']],
                close_prices=[Decimal(str(c)) for c in market_data['closes']]
            )

            self.logger.info(
                f"AdaptiveTimeout symbol={symbol} {adjustment.reasoning}"
            )

            return adjustment.adjusted_timeout_sec

        except Exception as e:
            self.logger.warning(
                f"AdaptiveTimeout failed for {symbol}: {e}, using base timeout"
            )
            return self.base_timeout_sec


# Convenience function for simple usage
def get_recommended_timeout(
    symbol: str,
    current_price: float,
    high_prices: list,
    low_prices: list,
    close_prices: list,
    base_timeout_sec: int = 600,
    atr_period: int = 14
) -> TimeoutAdjustment:
    """
    Standalone convenience function for calculating adaptive timeout.

    Args:
        symbol: Trading pair symbol
        current_price: Current market price
        high_prices: List of recent high prices
        low_prices: List of recent low prices
        close_prices: List of recent close prices
        base_timeout_sec: Base timeout in seconds (default: 600)
        atr_period: ATR calculation period (default: 14)

    Returns:
        TimeoutAdjustment with adjusted timeout and reasoning
    """
    calculator = AdaptiveTimeout(
        base_timeout_sec=base_timeout_sec,
        atr_period=atr_period
    )

    return calculator.calculate_timeout(
        symbol=symbol,
        current_price=Decimal(str(current_price)),
        high_prices=[Decimal(str(h)) for h in high_prices],
        low_prices=[Decimal(str(low)) for low in low_prices],
        close_prices=[Decimal(str(c)) for c in close_prices]
    )
