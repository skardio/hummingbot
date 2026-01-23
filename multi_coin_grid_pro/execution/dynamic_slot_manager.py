"""
Dynamic Slot Manager - Account-Size and Regime-Aware Slot Allocation

Task 3.1: Dynamic Slot Manager
- Account-size-aware slot scaling (€350 → 4, €1000 → 6, €2000 → 8)
- Regime multipliers (BULL 1.5x, CHOP 0.75x, BEAR 0x)
- Smooth scaling between thresholds
"""

import logging
from decimal import Decimal
from typing import Optional


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
            logger: Optional logger instance
        """
        self.config = config
        self._logger = logger

        self.enabled = config.get("enabled", True)
        self.min_slots = config.get("min_slots", 1)
        self.max_slots = config.get("max_slots", 12)
        self.quote_asset = config.get("quote_asset", "EUR")

        # Currency symbol for logging
        self.currency_symbol = "$" if self.quote_asset in ("USD", "USDT", "USDC") else "€"

        # Allow config to override regime multipliers
        custom_multipliers = config.get("regime_multipliers", {})
        self.regime_multipliers = {**self.REGIME_MULTIPLIERS, **custom_multipliers}

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
