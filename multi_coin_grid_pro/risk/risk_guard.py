"""
RiskGuard v2.0 - Kill Switch & Risk Management

Monitors:
- Daily/weekly/monthly loss limits
- Position size limits
- Drawdown protection
- Emergency stop conditions

Automatically disables trading when limits are breached.
"""
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from risk.pnl_tracker import RealtimePnLTracker


class RiskGuardV2:
    """
    Risk management kill switch with multiple safety layers

    Usage:
        guard = RiskGuardV2(config, pnl_tracker, telegram_alerter, logger)

        if guard.check_limits():
            # Safe to trade
        else:
            # Kill switch activated - stop all trading
    """

    def __init__(
        self,
        cfg: dict,
        pnl_tracker: RealtimePnLTracker,
        alerter,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Risk Guard

        Args:
            cfg: Config dict with risk limits
            pnl_tracker: PnL tracker instance
            alerter: Telegram alerter for critical notifications
            logger: Optional logger instance
        """
        self.cfg = cfg
        self.pnl = pnl_tracker
        self.alerter = alerter
        self.logger = logger or logging.getLogger(__name__)

        # Risk limits
        self.max_daily_loss_pct = cfg.get("max_daily_loss_pct", 3.0)
        self.max_weekly_loss_pct = cfg.get("max_weekly_loss_pct", 8.0)
        self.max_monthly_loss_pct = cfg.get("max_monthly_loss_pct", 12.0)
        self.max_daily_loss_eur = cfg.get("max_daily_loss_eur", None)

        # State
        self.trading_enabled = True
        self.kill_reason = None

        self.logger.info("=" * 80)
        self.logger.info("🛡️  RiskGuard v2.0 initialized")
        self.logger.info(f"   Max daily loss: {self.max_daily_loss_pct}%")
        self.logger.info(f"   Max weekly loss: {self.max_weekly_loss_pct}%")
        self.logger.info(f"   Max monthly loss: {self.max_monthly_loss_pct}%")
        if self.max_daily_loss_eur:
            self.logger.info(f"   Max daily loss (abs): €{self.max_daily_loss_eur}")
        self.logger.info("=" * 80)

    def check_limits(self) -> bool:
        """
        Check all risk limits

        Returns:
            True if trading is allowed, False if kill switch activated
        """
        if not self.trading_enabled:
            return False

        # 1) Daily loss percentage check
        daily_pct = self.pnl.daily_pnl_pct()
        if daily_pct <= -self.max_daily_loss_pct:
            self._kill(f"Daily loss {daily_pct:.2f}% ≤ -{self.max_daily_loss_pct}%")
            return False

        # 2) Daily loss absolute check
        if self.max_daily_loss_eur:
            daily_loss_eur = self.pnl.daily_pnl()
            if daily_loss_eur <= -Decimal(str(self.max_daily_loss_eur)):
                self._kill(f"Daily loss €{daily_loss_eur:.2f} ≤ -€{self.max_daily_loss_eur}")
                return False

        # 3) Weekly loss check
        weekly_pct = self.pnl.weekly_pnl_pct()
        if weekly_pct <= -self.max_weekly_loss_pct:
            self._kill(f"Weekly loss {weekly_pct:.2f}% ≤ -{self.max_weekly_loss_pct}%")
            return False

        # 4) Monthly loss check
        monthly_pct = self.pnl.monthly_pnl_pct()
        if monthly_pct <= -self.max_monthly_loss_pct:
            self._kill(f"Monthly loss {monthly_pct:.2f}% ≤ -{self.max_monthly_loss_pct}%")
            return False

        return True

    def _kill(self, reason: str):
        """
        Activate kill switch

        Args:
            reason: Reason for activation
        """
        self.trading_enabled = False
        self.kill_reason = reason

        msg = f"🚨 KILL SWITCH ACTIVATED: {reason}"
        self.logger.critical(msg)
        self.alerter.critical(msg)

        # Log P&L summary
        summary = self.pnl.get_summary()
        self.logger.critical(f"   Equity: €{summary['equity']:.2f}")
        self.logger.critical(f"   Realized P&L: €{summary['realized_pnl']:+.2f}")
        self.logger.critical(f"   Unrealized P&L: €{summary['unrealized_pnl']:+.2f}")
        self.logger.critical(f"   Fees paid: €{summary['fees_paid']:.2f}")

    def can_open_position(self, symbol: str, size_eur: Decimal) -> tuple[bool, str]:
        """
        Check if opening a new position is allowed

        Args:
            symbol: Trading pair
            size_eur: Position size in EUR

        Returns:
            Tuple of (allowed, reason)
        """
        if not self.trading_enabled:
            return False, f"Kill switch active: {self.kill_reason}"

        # Check max exposure per coin
        max_per_coin_pct = self.cfg.get("max_exposure_per_coin_pct", 40)
        max_per_coin_eur = self.pnl.starting_balance * Decimal(str(max_per_coin_pct)) / 100

        if size_eur > max_per_coin_eur:
            return False, f"Position size €{size_eur:.2f} > max €{max_per_coin_eur:.2f} ({max_per_coin_pct}%)"

        # Check total exposure
        max_total_pct = self.cfg.get("max_total_exposure_pct", 80)
        max_total_eur = self.pnl.starting_balance * Decimal(str(max_total_pct)) / 100

        total_exposure = sum(p.notional_eur for p in self.pnl.positions.values())
        if total_exposure + size_eur > max_total_eur:
            return False, f"Total exposure €{total_exposure + size_eur:.2f} > max €{max_total_eur:.2f} ({max_total_pct}%)"

        return True, "Position allowed"

    def reset_kill_switch(self):
        """Manually reset kill switch (use with caution!)"""
        self.trading_enabled = True
        self.kill_reason = None
        self.logger.warning("⚠️  Kill switch MANUALLY RESET - trading re-enabled")
        self.alerter.warning("Kill switch manually reset - trading re-enabled")
