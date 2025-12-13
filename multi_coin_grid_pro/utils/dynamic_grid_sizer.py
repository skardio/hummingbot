"""
Dynamic Grid Sizer - ATR-based Grid Count Adjustment

Bepaalt aantal grid levels (3-7) op basis van ATR volatility.
Logica:
- Dead market (ATR < 0.7%) → 3 grids (minimaal)
- Normal market (0.7-2.0%) → 4-5 grids
- Choppy market (2.0-4.0%) → 7 grids (maximaal, grid paradise)
- Extreme volatility (> 4.0%) → 5 grids (reduce risk)
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DynamicGridSizer:
    """
    Dynamically adjusts grid count based on market volatility (ATR).
    """

    def __init__(
        self,
        min_grids: int = 3,
        max_grids: int = 7,
        low_vol_atr_pct: float = 0.7,
        mid_vol_atr_pct: float = 2.0,
        high_vol_atr_pct: float = 4.0,
    ):
        """
        Args:
            min_grids: Minimum aantal grids (dead market)
            max_grids: Maximum aantal grids (choppy paradise)
            low_vol_atr_pct: Threshold voor dead market (< 0.7%)
            mid_vol_atr_pct: Threshold voor normal market (< 2.0%)
            high_vol_atr_pct: Threshold voor choppy market (< 4.0%)
        """
        self.min_grids = min_grids
        self.max_grids = max_grids
        self.low_vol_atr_pct = low_vol_atr_pct
        self.mid_vol_atr_pct = mid_vol_atr_pct
        self.high_vol_atr_pct = high_vol_atr_pct

        logger.info("📊 DynamicGridSizer initialized")
        logger.info(f"   Grid range: {min_grids}-{max_grids}")
        logger.info(f"   Volatility thresholds: {low_vol_atr_pct}% / {mid_vol_atr_pct}% / {high_vol_atr_pct}%")

    def grid_count_for(
        self,
        atr_pct: float,
        symbol: Optional[str] = None
    ) -> int:
        """
        Bepaalt aantal grids o.b.v. ATR%.

        Args:
            atr_pct: ATR as percentage of price (e.g. 1.5 = 1.5%)
            symbol: Optional symbol name voor logging

        Returns:
            Number of grids (between min_grids and max_grids)
        """

        # Dead market - weinig grids (of zelfs pauzeren)
        if atr_pct < self.low_vol_atr_pct:
            count = self.min_grids
            logger.debug(
                f"{'[' + symbol + '] ' if symbol else ''}"
                f"Dead market (ATR={atr_pct:.2f}%) → {count} grids"
            )
            return count

        # Normal market - moderate grids
        if atr_pct < self.mid_vol_atr_pct:
            # Lineair schalen tussen min+1 en max-2
            # Bij ATR=0.7%: 4 grids
            # Bij ATR=2.0%: 5 grids
            ratio = (atr_pct - self.low_vol_atr_pct) / (self.mid_vol_atr_pct - self.low_vol_atr_pct)
            count = int(self.min_grids + 1 + ratio * (self.max_grids - self.min_grids - 3))
            count = max(self.min_grids + 1, min(count, self.max_grids - 2))
            logger.debug(
                f"{'[' + symbol + '] ' if symbol else ''}"
                f"Normal market (ATR={atr_pct:.2f}%) → {count} grids"
            )
            return count

        # Choppy market - GRID PARADISE! Maximum grids
        if atr_pct < self.high_vol_atr_pct:
            count = self.max_grids
            logger.info(
                f"{'[' + symbol + '] ' if symbol else ''}"
                f"🎰 CHOPPY MARKET (ATR={atr_pct:.2f}%) → {count} grids (MAX!)"
            )
            return count

        # Extreme volatility - reduce grids for safety
        count = max(self.min_grids, self.max_grids - 2)  # e.g. 5 grids
        logger.warning(
            f"{'[' + symbol + '] ' if symbol else ''}"
            f"⚠️ EXTREME VOLATILITY (ATR={atr_pct:.2f}%) → {count} grids (reduced for safety)"
        )
        return count

    def get_grid_stats(self, atr_pct: float) -> dict:
        """
        Returns stats voor monitoring/debugging.
        """
        return {
            "atr_pct": atr_pct,
            "grid_count": self.grid_count_for(atr_pct),
            "regime": self._get_regime_name(atr_pct),
            "config": {
                "min_grids": self.min_grids,
                "max_grids": self.max_grids,
                "thresholds": {
                    "low_vol": self.low_vol_atr_pct,
                    "mid_vol": self.mid_vol_atr_pct,
                    "high_vol": self.high_vol_atr_pct,
                }
            }
        }

    def _get_regime_name(self, atr_pct: float) -> str:
        """Helper to get human-readable regime name"""
        if atr_pct < self.low_vol_atr_pct:
            return "dead"
        elif atr_pct < self.mid_vol_atr_pct:
            return "normal"
        elif atr_pct < self.high_vol_atr_pct:
            return "choppy"
        else:
            return "extreme"
