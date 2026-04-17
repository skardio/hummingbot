"""
Fee-Aware Grid Filter

Pre-entry check: is this grid worth trading after fees?

Calculates expected grid profit per level and compares against
round-trip trading fees. Rejects grids where expected profit
is too thin to overcome fee drag.

Kraken fees:
  - Taker: 0.26% per side → 0.52% round-trip
  - Maker: 0.16% per side → 0.32% round-trip

A grid level earns: grid_spread_pct between buy and sell.
Net profit per level ≈ grid_spread_pct - round_trip_fee_pct.
"""
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FeeCheckResult:
    """Result of fee-awareness check."""
    passed: bool
    symbol: str
    grid_spread_pct: float       # Expected spread per grid level
    round_trip_fee_pct: float    # Total fee cost (buy + sell)
    net_profit_pct: float        # grid_spread - fees
    min_profit_pct: float        # Configured minimum
    reason: str


class FeeAwareFilter:
    """
    Checks if a grid trade is worth it after fees.

    Usage:
        faf = FeeAwareFilter(config)
        result = faf.check(symbol, grid_range_pct, num_grids, atr_pct)
        if not result.passed:
            logger.warning(f"Skipping {symbol}: {result.reason}")
    """

    def __init__(self, config: dict, log: Optional[logging.Logger] = None):
        """
        Args:
            config: Dict with keys:
                - taker_fee_pct: float (default 0.26)
                - maker_fee_pct: float (default 0.16)
                - use_maker_fees: bool (default False)
                - fee_model: str 'worst_case' | 'average' | 'best_case' (default 'worst_case')
                - min_net_profit_pct: float (default 0.3)
                - enabled: bool (default True)
        """
        self.config = config or {}
        self.log = log or logger

        self.enabled = self.config.get('enabled', True)
        self.taker_fee_pct = self.config.get('taker_fee_pct', 0.26)
        self.maker_fee_pct = self.config.get('maker_fee_pct', 0.16)
        self.use_maker_fees = self.config.get('use_maker_fees', False)
        self.fee_model = self.config.get('fee_model', 'worst_case')
        self.min_net_profit_pct = self.config.get('min_net_profit_pct', 0.3)

    @property
    def round_trip_fee_pct(self) -> float:
        """Round-trip fee (buy + sell) based on configured fee_model.

        Fee models:
        - worst_case: both sides taker (safest, most conservative)
        - average:    one side maker, one side taker (realistic for grids)
        - best_case:  both sides maker (optimistic)
        """
        if self.use_maker_fees:
            # Legacy compat: explicit use_maker_fees overrides fee_model
            return self.maker_fee_pct * 2

        if self.fee_model == 'best_case':
            return self.maker_fee_pct * 2
        elif self.fee_model == 'average':
            return self.taker_fee_pct + self.maker_fee_pct
        else:  # worst_case (default)
            return self.taker_fee_pct * 2

    def check(
        self,
        symbol: str,
        grid_range_pct: float,
        num_grids: int,
        atr_pct: Optional[float] = None,
    ) -> FeeCheckResult:
        """
        Check if a grid on this symbol is worth it after fees.

        Args:
            symbol: Trading pair
            grid_range_pct: Total grid range in % (e.g., 4.0 for 4%)
            num_grids: Number of grid levels
            atr_pct: Optional ATR% for more accurate spread estimate

        Returns:
            FeeCheckResult with pass/fail and reasoning
        """
        if not self.enabled:
            return FeeCheckResult(
                passed=True, symbol=symbol,
                grid_spread_pct=0.0, round_trip_fee_pct=0.0,
                net_profit_pct=0.0, min_profit_pct=0.0,
                reason="Fee filter disabled",
            )

        # Estimate spread per grid level
        if num_grids > 1:
            grid_spread_pct = grid_range_pct / (num_grids - 1)
        else:
            grid_spread_pct = grid_range_pct

        # If ATR is available, use it as a reality check
        # ATR tells us how much the price actually moves
        if atr_pct is not None and atr_pct > 0:
            # Effective spread is min of grid spacing and typical price movement
            # If grid is wider than ATR, fills will be slow
            effective_spread = min(grid_spread_pct, atr_pct * 2)
        else:
            effective_spread = grid_spread_pct

        rt_fee = self.round_trip_fee_pct
        net_profit = effective_spread - rt_fee

        passed = net_profit >= self.min_net_profit_pct

        if passed:
            reason = (
                f"✅ Grid profitable: {effective_spread:.2f}% spread "
                f"- {rt_fee:.2f}% fees = {net_profit:.2f}% net "
                f"(min: {self.min_net_profit_pct:.2f}%)"
            )
        else:
            reason = (
                f"❌ Grid unprofitable: {effective_spread:.2f}% spread "
                f"- {rt_fee:.2f}% fees = {net_profit:.2f}% net "
                f"< {self.min_net_profit_pct:.2f}% minimum"
            )

        return FeeCheckResult(
            passed=passed,
            symbol=symbol,
            grid_spread_pct=effective_spread,
            round_trip_fee_pct=rt_fee,
            net_profit_pct=net_profit,
            min_profit_pct=self.min_net_profit_pct,
            reason=reason,
        )

    def estimate_grid_profitability(
        self,
        symbol: str,
        grid_range_pct: float,
        num_grids: int,
        total_amount_quote: float,
        expected_fill_rate: float = 0.5,
    ) -> dict:
        """
        Estimate total grid profitability for logging/observability.

        Args:
            symbol: Trading pair
            grid_range_pct: Total grid range %
            num_grids: Grid levels
            total_amount_quote: Capital deployed
            expected_fill_rate: Fraction of levels expected to fill (0-1)

        Returns:
            Dict with profitability estimates
        """
        check = self.check(symbol, grid_range_pct, num_grids)
        per_level_capital = total_amount_quote / max(1, num_grids)
        filled_levels = int(num_grids * expected_fill_rate)

        gross_profit = (
            per_level_capital * (check.grid_spread_pct / 100)
            * filled_levels
        )
        total_fees = (
            per_level_capital * (check.round_trip_fee_pct / 100)
            * filled_levels
        )
        net = gross_profit - total_fees

        return {
            "symbol": symbol,
            "per_level_spread_pct": check.grid_spread_pct,
            "round_trip_fee_pct": check.round_trip_fee_pct,
            "net_per_level_pct": check.net_profit_pct,
            "expected_filled_levels": filled_levels,
            "estimated_gross_profit": round(gross_profit, 2),
            "estimated_fees": round(total_fees, 2),
            "estimated_net_profit": round(net, 2),
            "profitable": net > 0,
        }
