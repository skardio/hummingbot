"""
Grid Builder v2.0 - ATR-Based Grid Construction

Builds optimized grid structures with:
- ATR-based spacing (adaptive to volatility)
- Asymmetric grids (more levels in trend direction)
- Dynamic ranges based on market conditions
"""
import logging
from decimal import Decimal
from typing import Dict, List, Optional, Tuple


class GridLevel:
    """Single grid level with buy/sell prices"""

    def __init__(self, level_id: int, buy_price: Decimal, sell_price: Decimal, size: Decimal):
        self.level_id = level_id
        self.buy_price = buy_price
        self.sell_price = sell_price
        self.size = size
        self.buy_filled = False
        self.sell_filled = False


class GridBuilder:
    """
    Build ATR-based adaptive grid structures

    Usage:
        builder = GridBuilder(config, logger)
        grid = builder.build_grid(
            symbol="BTC-EUR",
            center_price=Decimal("50000"),
            atr_pct=2.5,
            num_grids=7,
            capital=Decimal("1000")
        )
    """

    def __init__(
        self,
        cfg: dict,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Grid Builder

        Args:
            cfg: Config dict with grid parameters
            logger: Optional logger instance
        """
        self.cfg = cfg
        self.logger = logger or logging.getLogger(__name__)

        # Grid configuration
        self.use_atr_ranges = cfg.get("use_atr_grid_ranges", True)
        self.atr_multiplier_down = cfg.get("atr_multiplier_down", 1.5)
        self.atr_multiplier_up = cfg.get("atr_multiplier_up", 2.0)
        self.use_asymmetric = cfg.get("use_asymmetric_grids", True)

        # Fallback ranges (if not using ATR)
        self.default_range_down_pct = cfg.get("grid_range_pct_down", 1.5)
        self.default_range_up_pct = cfg.get("grid_range_pct_up", 8.0)

        self.min_order_size_eur = Decimal(str(cfg.get("min_order_amount_quote", 10)))

        self.logger.info("=" * 80)
        self.logger.info("🏗️  GridBuilder v2.0 initialized")
        self.logger.info(f"   ATR-based ranges: {self.use_atr_ranges}")
        if self.use_atr_ranges:
            self.logger.info(f"   ATR multipliers: down={self.atr_multiplier_down}x, up={self.atr_multiplier_up}x")
        self.logger.info(f"   Asymmetric grids: {self.use_asymmetric}")
        self.logger.info(f"   Min order size: €{self.min_order_size_eur}")
        self.logger.info("=" * 80)

    def build_grid(
        self,
        symbol: str,
        center_price: Decimal,
        atr_pct: float,
        num_grids: int,
        capital: Decimal,
        trend_pct: float = 0.0
    ) -> Tuple[List[GridLevel], Dict]:
        """
        Build grid structure

        Args:
            symbol: Trading pair
            center_price: Current market price
            atr_pct: ATR as percentage (e.g., 2.5 = 2.5%)
            num_grids: Number of grid levels
            capital: Available capital for this grid
            trend_pct: Current trend percentage (for asymmetric grids)

        Returns:
            Tuple of (grid_levels, metadata_dict)
        """
        self.logger.info("=" * 80)
        self.logger.info(f"🏗️  Building grid for {symbol}")
        self.logger.info(f"   Center price: €{center_price:.4f}")
        self.logger.info(f"   ATR: {atr_pct:.2f}%")
        self.logger.info(f"   Grids: {num_grids}")
        self.logger.info(f"   Capital: €{capital:.2f}")
        self.logger.info(f"   Trend: {trend_pct:+.2f}%")

        # 1) Calculate grid range
        if self.use_atr_ranges:
            range_down_pct = atr_pct * self.atr_multiplier_down
            range_up_pct = atr_pct * self.atr_multiplier_up
        else:
            range_down_pct = self.default_range_down_pct
            range_up_pct = self.default_range_up_pct

        # 2) Asymmetric adjustment based on trend
        if self.use_asymmetric and abs(trend_pct) > 0.3:
            if trend_pct > 0:
                # Uptrend → more grids below (buy opportunities)
                grids_below = int(num_grids * 0.6)
                grids_above = num_grids - grids_below
            else:
                # Downtrend → more grids above (sell opportunities)
                grids_above = int(num_grids * 0.6)
                grids_below = num_grids - grids_above
        else:
            # Balanced
            grids_below = num_grids // 2
            grids_above = num_grids - grids_below

        self.logger.info(f"   Range: -{range_down_pct:.2f}% / +{range_up_pct:.2f}%")
        self.logger.info(f"   Distribution: {grids_below} below / {grids_above} above")

        # 3) Calculate price levels
        lowest_price = center_price * (1 - Decimal(str(range_down_pct / 100)))
        highest_price = center_price * (1 + Decimal(str(range_up_pct / 100)))

        # 4) Calculate spacing
        spacing_below = (center_price - lowest_price) / Decimal(grids_below) if grids_below > 0 else Decimal("0")
        spacing_above = (highest_price - center_price) / Decimal(grids_above) if grids_above > 0 else Decimal("0")

        # 5) Build grid levels
        grid_levels: List[GridLevel] = []

        # Size per level (equal distribution for now)
        size_per_level_eur = capital / Decimal(num_grids)

        # Below center price (buy levels)
        for i in range(grids_below):
            buy_price = center_price - spacing_below * Decimal(i + 1)
            sell_price = buy_price * Decimal("1.015")  # 1.5% profit target

            size_eur = max(size_per_level_eur, self.min_order_size_eur)

            grid_levels.append(GridLevel(
                level_id=-(i + 1),
                buy_price=buy_price,
                sell_price=sell_price,
                size=size_eur
            ))

        # Above center price (sell levels - if we already have position)
        for i in range(grids_above):
            sell_price = center_price + spacing_above * Decimal(i + 1)
            buy_price = sell_price * Decimal("0.985")  # Re-entry 1.5% below

            size_eur = max(size_per_level_eur, self.min_order_size_eur)

            grid_levels.append(GridLevel(
                level_id=i + 1,
                level_buy_price=buy_price,
                sell_price=sell_price,
                size=size_eur
            ))

        # Sort by price
        grid_levels.sort(key=lambda x: x.buy_price)

        # Metadata
        metadata = {
            "symbol": symbol,
            "center_price": float(center_price),
            "lowest_price": float(lowest_price),
            "highest_price": float(highest_price),
            "range_down_pct": range_down_pct,
            "range_up_pct": range_up_pct,
            "grids_below": grids_below,
            "grids_above": grids_above,
            "total_capital": float(capital),
            "atr_pct": atr_pct,
            "trend_pct": trend_pct,
        }

        self.logger.info(f"✅ Grid built: {len(grid_levels)} levels")
        self.logger.info(f"   Price range: €{lowest_price:.4f} - €{highest_price:.4f}")
        self.logger.info("=" * 80)

        return grid_levels, metadata
