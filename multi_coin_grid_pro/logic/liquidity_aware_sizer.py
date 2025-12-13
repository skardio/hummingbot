"""
Liquidity-Aware Smart Sizing (Feature 1.2b)

Prevents excessive order sizing from bonus stacking by applying a global cap
on combined multipliers from time-based, regime-based, and volatility-based adjustments.

Purpose:
- Cap total sizing multiplier at 1.2x (configurable)
- Prevent scenarios where 1.10 × 1.15 × 1.10 = 1.39x oversizing
- Maintain EUR-based risk limits while optimizing for market conditions
"""
import logging
from decimal import Decimal
from typing import Optional


class LiquidityAwareSizing:
    """
    Apply liquidity-aware sizing cap to prevent bonus stacking.

    This is a MINIMAL implementation that reads config and applies max_total_size_multiplier.

    Usage:
        sizer = LiquidityAwareSizing(config["liquidity_aware_sizing"], logger)
        final_size = sizer.apply_sizing_cap(base_size, calculated_multiplier)
    """

    def __init__(self, cfg: dict, logger: Optional[logging.Logger] = None):
        """
        Initialize Liquidity-Aware Sizer

        Args:
            cfg: Config dict with enabled, max_total_size_multiplier, log_sizing_calc
            logger: Optional logger instance
        """
        self.enabled = cfg.get("enabled", False)
        self.max_total_size_multiplier = Decimal(str(cfg.get("max_total_size_multiplier", 1.2)))
        self.log_sizing_calc = cfg.get("log_sizing_calc", True)
        self.logger = logger or logging.getLogger(__name__)

        if self.enabled:
            self.logger.info("=" * 80)
            self.logger.info("🎯 Liquidity-Aware Smart Sizing (Feature 1.2b) initialized")
            self.logger.info(f"   Max total multiplier cap: {self.max_total_size_multiplier}x")
            self.logger.info(f"   Audit logging: {'enabled' if self.log_sizing_calc else 'disabled'}")
            self.logger.info("   Purpose: Prevent bonus stacking (e.g., 1.10 × 1.15 × 1.10 = 1.39x)")
            self.logger.info("=" * 80)
        else:
            self.logger.debug("⚪ Liquidity-Aware Smart Sizing: disabled")

    def apply_sizing_cap(
        self,
        base_size: Decimal,
        calculated_multiplier: float = 1.0,
        coin_symbol: str = "UNKNOWN"
    ) -> Decimal:
        """
        Apply sizing cap to prevent excessive multipliers

        Args:
            base_size: Base position size before multipliers (EUR)
            calculated_multiplier: Combined multiplier from all sources (time × regime × volatility)
            coin_symbol: Trading pair symbol for logging

        Returns:
            Final size with cap applied if enabled, otherwise base_size * calculated_multiplier
        """
        if not self.enabled:
            # Feature disabled - return original calculation
            return base_size * Decimal(str(calculated_multiplier))

        # Convert to Decimal for precision
        multiplier_decimal = Decimal(str(calculated_multiplier))

        # Apply cap
        capped_multiplier = min(multiplier_decimal, self.max_total_size_multiplier)
        final_size = base_size * capped_multiplier

        # Logging
        if self.log_sizing_calc:
            was_capped = multiplier_decimal > self.max_total_size_multiplier

            if was_capped:
                self.logger.info(
                    f"🎯 Feature 1.2b [{coin_symbol}]: Position size CAPPED "
                    f"(Base: €{base_size:.2f}, Multiplier: {calculated_multiplier:.3f}x → "
                    f"{capped_multiplier:.3f}x, Final: €{final_size:.2f})"
                )
            else:
                self.logger.debug(
                    f"🎯 Feature 1.2b [{coin_symbol}]: Position size within cap "
                    f"(Base: €{base_size:.2f}, Multiplier: {calculated_multiplier:.3f}x, "
                    f"Final: €{final_size:.2f})"
                )

        return final_size

    def get_effective_multiplier(self, requested_multiplier: float) -> float:
        """
        Get the effective multiplier after applying cap (for pre-calculation checks)

        Args:
            requested_multiplier: Combined multiplier from all sources

        Returns:
            Capped multiplier as float
        """
        if not self.enabled:
            return requested_multiplier

        return float(min(Decimal(str(requested_multiplier)), self.max_total_size_multiplier))
