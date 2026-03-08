"""
Dynamic Slot Manager - Account-Size and Regime-Aware Slot Allocation

Task 3.1: Dynamic Slot Manager
- Account-size-aware slot scaling (€350 → 4, €1000 → 6, €2000 → 8)
- Regime multipliers (BULL 1.5x, CHOP 0.75x, BEAR 0x)
- Smooth scaling between thresholds

ENHANCED: Fully dynamic allocation based on ACTUAL available balance
- Automatically calculates optimal slots AND grid levels
- Works with any account size from €50 to €50000+
- No config changes needed - just set your available capital
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass
class DynamicAllocation:
    """Result of dynamic allocation calculation."""
    available_capital: Decimal      # Actual usable capital
    num_coins: int                  # How many coins to trade simultaneously
    num_grids: int                  # Grid levels per coin
    capital_per_coin: Decimal       # Capital allocated per coin
    amount_per_grid_level: Decimal  # Amount per individual grid order
    is_feasible: bool               # Whether trading is possible
    reason: str                     # Explanation of the allocation


class DynamicSlotManager:
    """
    Dynamically calculate max simultaneous slots based on account size and regime.

    Examples:
        €350 baseline → 4 slots, BULL → 6 slots, CHOP → 3 slots
        €1000 baseline → 6 slots, BULL → 9 slots, CHOP → 4 slots
        €2000 baseline → 8 slots, BULL → 12 slots, CHOP → 6 slots
    """

    # Account size thresholds and corresponding base slots
    SLOT_TIERS = [
        (Decimal("350"), 4),    # Small account: 4 slots
        (Decimal("700"), 5),    # Medium-small: 5 slots
        (Decimal("1000"), 6),   # Medium: 6 slots
        (Decimal("1500"), 7),   # Medium-large: 7 slots
        (Decimal("2000"), 8),   # Large: 8 slots
        (Decimal("3000"), 10),  # Very large: 10 slots
    ]

    # Regime multipliers
    REGIME_MULTIPLIERS = {
        "BULL": Decimal("1.5"),   # 50% more slots in bull
        "CHOP": Decimal("0.75"),  # 25% fewer slots in chop
        "BEAR": Decimal("0.25"),  # Only 1 slot in bear (defensive)
    }

    def __init__(self, config: dict, logger: Optional[logging.Logger] = None):
        """
        Initialize dynamic slot manager.

        Args:
            config: dict with optional keys:
                - enabled (bool): Enable dynamic slots (default True)
                - min_slots (int): Minimum slots (default 1)
                - max_slots (int): Maximum slots (default 12)
                - regime_multipliers (dict): Custom regime multipliers
                - quote_asset (str): Quote asset for logging (default EUR)
                - min_order_amount_quote (Decimal): Min order size (default 5)
                - num_grids (int): Number of grid levels (default 8)
                - total_amount_quote (Decimal): Total trading capital (default None)
            logger: Optional logger instance
        """
        self.config = config
        self._logger = logger

        self.enabled = config.get("enabled", True)
        self.min_slots = config.get("min_slots", 1)
        self.max_slots = config.get("max_slots", 12)
        self.quote_asset = config.get("quote_asset", "EUR")

        # Order size constraints for feasibility check
        self.min_order_amount = Decimal(str(config.get("min_order_amount_quote", 5)))
        self.num_grids = config.get("num_grids", 8)
        self.total_amount_quote = config.get("total_amount_quote", None)

        # Currency symbol for logging
        self.currency_symbol = "$" if self.quote_asset in ("USD", "USDT", "USDC") else "€"

        # Allow config to override regime multipliers (ensure Decimal type)
        custom_multipliers = config.get("regime_multipliers", {})
        # Convert custom multipliers to Decimal to avoid type mismatch
        custom_multipliers_decimal = {
            k: Decimal(str(v)) if not isinstance(v, Decimal) else v
            for k, v in custom_multipliers.items()
        }
        self.regime_multipliers = {**self.REGIME_MULTIPLIERS, **custom_multipliers_decimal}

    def logger(self) -> logging.Logger:
        if self._logger is None:
            self._logger = logging.getLogger(__name__)
        return self._logger

    def get_dynamic_slots(
        self,
        account_balance_eur: Decimal,
        current_regime: str = "baseline",
        static_fallback: int = 4
    ) -> int:
        """
        Calculate dynamic slot count based on account size and regime.

        Also enforces minimum order size constraint:
        - per_coin = total_amount / slots
        - per_level = per_coin / num_grids
        - per_level MUST be >= min_order_amount

        Args:
            account_balance_eur: Current account balance in EUR
            current_regime: Current market regime (BULL/CHOP/BEAR/baseline)
            static_fallback: Fallback if dynamic slots disabled

        Returns:
            int: Number of slots (1-12)

        Examples:
            >>> manager.get_dynamic_slots(Decimal("350"), "baseline")
            4
            >>> manager.get_dynamic_slots(Decimal("350"), "BULL")
            6
            >>> manager.get_dynamic_slots(Decimal("1000"), "BULL")
            9
            >>> manager.get_dynamic_slots(Decimal("2000"), "CHOP")
            6
        """
        if not self.enabled:
            return static_fallback

        # Calculate base slots from account size
        base_slots = self._get_base_slots_from_balance(account_balance_eur)

        # Apply regime multiplier
        regime_multiplier = self._get_regime_multiplier(current_regime)
        adjusted_slots = base_slots * regime_multiplier

        # Round and constrain
        final_slots = max(self.min_slots, min(self.max_slots, int(adjusted_slots)))

        # ============================================================
        # FEASIBILITY CHECK: Ensure orders meet minimum size
        # ============================================================
        # Formula: total_amount / slots / num_grids >= min_order_amount
        # Rearranged: slots <= total_amount / (min_order_amount * num_grids)
        trading_capital = self.total_amount_quote
        if trading_capital is not None and trading_capital > 0:
            trading_capital = Decimal(str(trading_capital))
            min_order_required = self.min_order_amount * Decimal(str(self.num_grids))

            if min_order_required > 0:
                max_feasible_slots = int(trading_capital / min_order_required)
                max_feasible_slots = max(1, max_feasible_slots)  # At least 1 slot

                if final_slots > max_feasible_slots:
                    self.logger().warning(
                        f"⚠️ Dynamic slots capped by min order size: "
                        f"{final_slots} → {max_feasible_slots} "
                        f"(capital={self.currency_symbol}{trading_capital}, "
                        f"min_order={self.currency_symbol}{self.min_order_amount}, "
                        f"grids={self.num_grids})"
                    )
                    final_slots = max_feasible_slots

        self.logger().debug(
            f"Dynamic slots: balance={self.currency_symbol}{account_balance_eur:.0f}, "
            f"regime={current_regime}, base={base_slots}, "
            f"multiplier={regime_multiplier}, final={final_slots}"
        )

        return final_slots

    def _get_base_slots_from_balance(self, balance: Decimal) -> Decimal:
        """
        Calculate base slot count from account balance using tiered approach.

        Uses linear interpolation between tiers for smooth scaling.

        Args:
            balance: Account balance in EUR

        Returns:
            Decimal: Base slot count (can be fractional for regime multiplier)
        """
        # Find the tier we're in or above
        for i, (threshold, slots) in enumerate(self.SLOT_TIERS):
            if balance < threshold:
                # Interpolate between previous and current tier
                if i == 0:
                    # Below first tier - use first tier value
                    return Decimal(str(slots))

                prev_threshold, prev_slots = self.SLOT_TIERS[i - 1]

                # Linear interpolation
                ratio = (balance - prev_threshold) / (threshold - prev_threshold)
                interpolated = prev_slots + (slots - prev_slots) * ratio
                return Decimal(str(float(interpolated)))

        # Above all tiers - use highest tier
        return Decimal(str(self.SLOT_TIERS[-1][1]))

    def _get_regime_multiplier(self, regime: str) -> Decimal:
        """
        Get regime multiplier, handling case variations and baseline.

        Args:
            regime: Regime name (BULL/CHOP/BEAR/baseline/etc)

        Returns:
            Decimal: Multiplier (1.0 for baseline/unknown)
        """
        regime_upper = regime.upper()

        # Handle baseline or unknown regimes
        if regime_upper in ("BASELINE", "NEUTRAL", ""):
            return Decimal("1.0")

        return self.regime_multipliers.get(regime_upper, Decimal("1.0"))

    def get_slot_report(
        self,
        account_balance_eur: Decimal,
        current_regime: str = "baseline"
    ) -> str:
        """
        Generate a human-readable slot allocation report.

        Args:
            account_balance_eur: Current account balance
            current_regime: Current regime

        Returns:
            str: Multi-line report string
        """
        if not self.enabled:
            return "Dynamic slots: DISABLED"

        base_slots = self._get_base_slots_from_balance(account_balance_eur)
        current_slots = self.get_dynamic_slots(account_balance_eur, current_regime)

        lines = [
            "📊 Dynamic Slot Allocation:",
            f"   Balance: €{account_balance_eur:.2f}",
            f"   Base slots: {float(base_slots):.1f}",
            f"   Regime: {current_regime} ({self._get_regime_multiplier(current_regime)}x)",
            f"   ➜ Active slots: {current_slots}",
            "",
            "What-if scenarios:"
        ]

        for regime_name in ["baseline", "BULL", "CHOP", "BEAR"]:
            slots = self.get_dynamic_slots(account_balance_eur, regime_name)
            multiplier = self._get_regime_multiplier(regime_name)
            marker = "←" if regime_name.upper() == current_regime.upper() else " "
            lines.append(f"   {marker} {regime_name:8}: {slots} slots ({multiplier}x)")

        return "\n".join(lines)

    def calculate_optimal_allocation(
        self,
        available_balance: Decimal,
        min_order_amount: Optional[Decimal] = None,
        preferred_grids: Optional[int] = None,
        max_coins: Optional[int] = None,
        current_regime: str = "baseline",
        buffer_pct: Decimal = Decimal("0.05")
    ) -> DynamicAllocation:
        """
        Calculate optimal allocation based on ACTUAL available balance.

        This is the key method for fully dynamic trading. It calculates:
        1. How much capital is actually usable (with buffer for fees)
        2. How many coins can be traded simultaneously
        3. How many grid levels per coin
        4. Whether trading is even feasible

        The algorithm prioritizes:
        1. Meeting minimum order size (non-negotiable)
        2. Maximizing grid levels (better coverage)
        3. Then maximizing coins (diversification)

        Args:
            available_balance: Actual USDT/quote balance available
            min_order_amount: Minimum order size (default from config or 5)
            preferred_grids: Preferred grid levels (default from config or 7)
            max_coins: Maximum coins to consider (default from config or 12)
            current_regime: Market regime for slot multiplier
            buffer_pct: Buffer for fees/slippage (default 5%)

        Returns:
            DynamicAllocation with optimal settings

        Examples:
            €79 available → 1 coin, 7 grids, €10.71/level
            €300 available → 2 coins, 7 grids, €20.35/level
            €1000 available → 4 coins, 7 grids, €33.93/level
            €5000 available → 6 coins, 10 grids, €79.17/level
        """
        # Use config defaults if not specified
        min_order = min_order_amount or self.min_order_amount
        grids = preferred_grids or self.num_grids
        max_slots = max_coins or self.max_slots

        # Apply buffer for fees and slippage
        usable_capital = available_balance * (Decimal("1") - buffer_pct)

        # Check if trading is even possible
        # Minimum viable: 1 coin × 3 grids × min_order
        min_viable_capital = min_order * Decimal("3")  # At least 3 grid levels
        if usable_capital < min_viable_capital:
            return DynamicAllocation(
                available_capital=usable_capital,
                num_coins=0,
                num_grids=0,
                capital_per_coin=Decimal("0"),
                amount_per_grid_level=Decimal("0"),
                is_feasible=False,
                reason=f"Insufficient capital: {self.currency_symbol}{usable_capital:.2f} < "
                       f"{self.currency_symbol}{min_viable_capital:.2f} minimum (3 grids × {self.currency_symbol}{min_order})"
            )

        # Calculate max coins based on regime (this gives us the upper bound)
        regime_adjusted_max = self.get_dynamic_slots(available_balance, current_regime)
        effective_max_coins = min(max_slots, regime_adjusted_max)

        # Now find optimal combination of coins and grids
        best_allocation = self._find_optimal_allocation(
            usable_capital=usable_capital,
            min_order=min_order,
            preferred_grids=grids,
            max_coins=effective_max_coins
        )

        return best_allocation

    def _find_optimal_allocation(
        self,
        usable_capital: Decimal,
        min_order: Decimal,
        preferred_grids: int,
        max_coins: int
    ) -> DynamicAllocation:
        """
        Find the optimal number of coins and grid levels.

        Strategy:
        1. Start with preferred_grids and see how many coins fit
        2. If not enough for even 1 coin, reduce grids
        3. Aim for at least 20% above min_order for safety margin
        """
        safety_margin = Decimal("1.2")  # 20% above minimum
        target_order_amount = min_order * safety_margin

        best_coins = 0
        best_grids = 0
        best_per_level = Decimal("0")

        # Try different grid counts from preferred down to minimum (3)
        for grids in range(preferred_grids, 2, -1):
            # Calculate how many coins we can afford with this grid count
            # Formula: capital_per_coin = usable_capital / num_coins
            #          per_level = capital_per_coin / grids
            #          per_level >= target_order_amount
            # Therefore: num_coins <= usable_capital / (grids * target_order_amount)

            max_affordable_coins = int(usable_capital / (Decimal(str(grids)) * target_order_amount))
            max_affordable_coins = max(1, min(max_affordable_coins, max_coins))

            # Calculate actual per-level amount
            capital_per_coin = usable_capital / Decimal(str(max_affordable_coins))
            per_level = capital_per_coin / Decimal(str(grids))

            # Check if this meets minimum (not just target)
            if per_level >= min_order:
                # This is a valid allocation
                # Prefer more grids if per_level is comfortable (>= 1.5x minimum)
                if per_level >= min_order * Decimal("1.5") or grids == preferred_grids:
                    best_coins = max_affordable_coins
                    best_grids = grids
                    best_per_level = per_level
                    break
                elif best_coins == 0:
                    # First valid allocation found
                    best_coins = max_affordable_coins
                    best_grids = grids
                    best_per_level = per_level

        # If still no valid allocation, try with just minimum requirements
        if best_coins == 0:
            # Absolute minimum: 1 coin, 3 grids
            per_level = usable_capital / Decimal("3")
            if per_level >= min_order:
                best_coins = 1
                best_grids = 3
                best_per_level = per_level

        if best_coins == 0:
            return DynamicAllocation(
                available_capital=usable_capital,
                num_coins=0,
                num_grids=0,
                capital_per_coin=Decimal("0"),
                amount_per_grid_level=Decimal("0"),
                is_feasible=False,
                reason=f"Cannot meet minimum order size {self.currency_symbol}{min_order} with available capital"
            )

        capital_per_coin = usable_capital / Decimal(str(best_coins))

        return DynamicAllocation(
            available_capital=usable_capital,
            num_coins=best_coins,
            num_grids=best_grids,
            capital_per_coin=capital_per_coin,
            amount_per_grid_level=best_per_level,
            is_feasible=True,
            reason=f"{best_coins} coin(s) × {best_grids} grids = "
                   f"{self.currency_symbol}{best_per_level:.2f}/level "
                   f"(min: {self.currency_symbol}{min_order})"
        )

    def get_allocation_report(
        self,
        available_balance: Decimal,
        current_regime: str = "baseline"
    ) -> str:
        """
        Generate a detailed allocation report for the given balance.

        Args:
            available_balance: Actual available balance
            current_regime: Current market regime

        Returns:
            str: Multi-line report
        """
        alloc = self.calculate_optimal_allocation(
            available_balance=available_balance,
            current_regime=current_regime
        )

        if not alloc.is_feasible:
            return (
                f"❌ ALLOCATION NOT FEASIBLE\n"
                f"   Available: {self.currency_symbol}{available_balance:.2f}\n"
                f"   Reason: {alloc.reason}\n"
                f"   Minimum needed: {self.currency_symbol}{self.min_order_amount * 3:.2f} (3 grids × min order)"
            )

        lines = [
            "✅ DYNAMIC ALLOCATION",
            f"   Available: {self.currency_symbol}{available_balance:.2f}",
            f"   Usable (after 5% buffer): {self.currency_symbol}{alloc.available_capital:.2f}",
            f"   Regime: {current_regime}",
            "",
            "📊 Optimal Setup:",
            f"   Coins: {alloc.num_coins}",
            f"   Grids per coin: {alloc.num_grids}",
            f"   Capital per coin: {self.currency_symbol}{alloc.capital_per_coin:.2f}",
            f"   Per grid level: {self.currency_symbol}{alloc.amount_per_grid_level:.2f}",
            f"   Min order required: {self.currency_symbol}{self.min_order_amount:.2f}",
            f"   Safety margin: {float(alloc.amount_per_grid_level / self.min_order_amount):.1f}x",
        ]

        return "\n".join(lines)
