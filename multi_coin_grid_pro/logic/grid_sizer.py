"""
DynamicGridSizer v2.0 - ATR-Based Grid Count Optimizer

Automatically determines optimal number of grid levels (3-7) based on ATR volatility.

Strategy:
- Low volatility (<0.7% ATR): 3 grids (tight market)
- Medium volatility (0.7-2.0%): 4-5 grids (normal)
- High volatility (2.0-4.0%): 7 grids (choppy, ideal for grids)
- Very high volatility (>4.0%): 5 grids (reduce risk)
"""
import logging
from typing import Optional


class DynamicGridSizer:
    """
    Dynamically size grid count based on ATR volatility

    Usage:
        sizer = DynamicGridSizer(config["dynamic_grid_sizer"], logger)
        num_grids = sizer.grid_count_for(atr_pct=2.5)  # Returns 7 for high vol
    """

    def __init__(self, cfg: dict, logger: Optional[logging.Logger] = None):
        """
        Initialize Dynamic Grid Sizer

        Args:
            cfg: Config dict with min_grids, max_grids, low_vol_atr_pct, mid_vol_atr_pct, high_vol_atr_pct
            logger: Optional logger instance
        """
        self.min_grids = cfg.get("min_grids", 3)
        self.max_grids = cfg.get("max_grids", 7)
        self.low_vol_atr_pct = cfg.get("low_vol_atr_pct", 0.7)
        self.mid_vol_atr_pct = cfg.get("mid_vol_atr_pct", 2.0)
        self.high_vol_atr_pct = cfg.get("high_vol_atr_pct", 4.0)
        self.logger = logger or logging.getLogger(__name__)

        self.logger.info("=" * 80)
        self.logger.info("📊 DynamicGridSizer v2.0 initialized")
        self.logger.info(f"   Grid range: {self.min_grids}-{self.max_grids} levels")
        self.logger.info(f"   Low vol: <{self.low_vol_atr_pct}% ATR → {self.min_grids} grids")
        self.logger.info(f"   Mid vol: {self.low_vol_atr_pct}-{self.mid_vol_atr_pct}% → {self.min_grids + 1}-{self.max_grids - 2} grids")
        self.logger.info(f"   High vol: {self.mid_vol_atr_pct}-{self.high_vol_atr_pct}% → {self.max_grids} grids")
        self.logger.info(f"   Very high: >{self.high_vol_atr_pct}% → {self.max_grids - 2} grids (risk reduction)")
        self.logger.info("=" * 80)

    def grid_count_for(self, atr_pct: float) -> int:
        """
        Calculate optimal grid count based on ATR volatility

        Args:
            atr_pct: Current ATR as percentage of price (e.g., 2.5 = 2.5%)

        Returns:
            Optimal number of grid levels (between min_grids and max_grids)
        """
        if atr_pct < self.low_vol_atr_pct:
            # Dead/low-vol market → minimal grids
            count = self.min_grids
            reason = "low volatility"

        elif atr_pct < self.mid_vol_atr_pct:
            # Normal/medium volatility → moderate grids
            # Linear interpolation between min+1 and max-2
            ratio = (atr_pct - self.low_vol_atr_pct) / (self.mid_vol_atr_pct - self.low_vol_atr_pct)
            count = int(self.min_grids + 1 + ratio * (self.max_grids - self.min_grids - 3))
            count = max(self.min_grids + 1, min(count, self.max_grids - 2))
            reason = "medium volatility"

        elif atr_pct < self.high_vol_atr_pct:
            # High choppy volatility → maximum grids (ideal for mean reversion)
            count = self.max_grids
            reason = "high volatility (choppy - ideal)"

        else:
            # Very high volatility → reduce grids (too chaotic, risk management)
            count = max(self.min_grids, self.max_grids - 2)
            reason = "very high volatility (risk reduction)"

        self.logger.debug(
            f"📊 DynamicGridSizer: ATR={atr_pct:.2f}% → {count} grids ({reason})"
        )

        return count

    def get_grid_spacing(self, atr_pct: float, price: float) -> dict:
        """
        Calculate grid spacing based on ATR

        Args:
            atr_pct: ATR as percentage
            price: Current price

        Returns:
            Dict with spacing_pct, spacing_abs, range_down, range_up
        """
        # Base spacing is ~0.4 * ATR per grid level
        spacing_pct = max(0.3, atr_pct * 0.4)
        spacing_abs = price * (spacing_pct / 100.0)

        num_grids = self.grid_count_for(atr_pct)

        # Range extends from current price
        range_down_pct = spacing_pct * (num_grids / 2)
        range_up_pct = spacing_pct * (num_grids / 2)

        return {
            "spacing_pct": spacing_pct,
            "spacing_abs": spacing_abs,
            "range_down_pct": range_down_pct,
            "range_up_pct": range_up_pct,
            "num_grids": num_grids,
        }
