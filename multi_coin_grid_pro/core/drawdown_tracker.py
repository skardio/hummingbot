"""
Phase 1 Fix #2 & #3: Drawdown & Daily Loss Tracking

Tracks daily/weekly/monthly drawdown limits and daily euro loss limits.
Professional bots ALWAYS have these limits to prevent catastrophic losses.

IMPORTANT: Uses TOTAL PORTFOLIO VALUE (quote + coin values) for drawdown calculation,
not just the quote asset balance. This prevents false drawdown triggers when
quote currency is converted to coins.
"""

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Callable, Dict, Optional, Tuple

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class DrawdownTracker:
    """
    Track daily/weekly/monthly drawdown and daily euro loss limits

    Prevents bot from trading when loss limits are exceeded.
    Professional risk management feature used by all serious trading bots.

    IMPORTANT: Uses TOTAL PORTFOLIO VALUE for drawdown calculation, not just
    quote asset balance. This means if you have €80 EUR and €20 worth of BTC,
    your portfolio value is €100, not €80.
    """

    def __init__(
        self,
        max_daily_loss_pct: Decimal = Decimal("5.0"),
        max_weekly_loss_pct: Decimal = Decimal("10.0"),
        max_monthly_loss_pct: Decimal = Decimal("15.0"),
        max_daily_loss_eur: Optional[Decimal] = None,
        quote_asset: str = "EUR",
        portfolio_value_calculator: Optional[Callable[[], Decimal]] = None
    ):
        """
        Initialize drawdown tracker

        Args:
            max_daily_loss_pct: Max daily loss percentage (default 5%)
            max_weekly_loss_pct: Max weekly loss percentage (default 10%)
            max_monthly_loss_pct: Max monthly loss percentage (default 15%)
            max_daily_loss_eur: Max daily loss in euro/quote asset (optional)
            quote_asset: Quote asset name (EUR, USDT, etc.)
            portfolio_value_calculator: Optional callback to calculate total portfolio value
                                        If not provided, uses raw balance passed to methods
        """
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_weekly_loss_pct = max_weekly_loss_pct
        self.max_monthly_loss_pct = max_monthly_loss_pct
        self.max_daily_loss_eur = max_daily_loss_eur
        self.quote_asset = quote_asset
        self._portfolio_value_calculator = portfolio_value_calculator

        # Starting balances (reset at beginning of period)
        # NOTE: These now store TOTAL PORTFOLIO VALUE, not just quote asset
        self.daily_start_balance: Optional[Decimal] = None
        self.weekly_start_balance: Optional[Decimal] = None
        self.monthly_start_balance: Optional[Decimal] = None

        # Track realized P&L (for euro loss tracking)
        self.daily_realized_pnl: Decimal = Decimal("0")
        self.daily_trades: list = []  # Store trades for debugging

        # Track last reset dates
        self.last_reset_day: Optional[date] = None
        self.last_reset_week: Optional[int] = None  # ISO week number
        self.last_reset_month: Optional[int] = None

        # Pause state
        self.is_paused = False
        self.pause_reason: Optional[str] = None
        self.paused_at: Optional[datetime] = None

        # Last known portfolio value (for debugging)
        self._last_portfolio_value: Optional[Decimal] = None
        self._last_quote_balance: Optional[Decimal] = None

        logger.info(
            f"📊 DrawdownTracker initialized: "
            f"Daily: {max_daily_loss_pct}%, Weekly: {max_weekly_loss_pct}%, Monthly: {max_monthly_loss_pct}%"
        )
        if max_daily_loss_eur:
            logger.info(f"💰 Daily euro loss limit: {max_daily_loss_eur} {quote_asset}")
        if portfolio_value_calculator:
            logger.info("✅ Using TOTAL PORTFOLIO VALUE for drawdown (quote + coins)")
        else:
            logger.warning("⚠️ Using QUOTE ONLY for drawdown - may trigger false positives!")

    def set_portfolio_value_calculator(self, calculator: Callable[[], Decimal]) -> None:
        """
        Set the portfolio value calculator callback

        Args:
            calculator: Callback that returns total portfolio value in quote asset
        """
        self._portfolio_value_calculator = calculator
        logger.info("✅ Portfolio value calculator set - using total portfolio for drawdown")

    def _get_portfolio_value(self, fallback_balance: Decimal) -> Decimal:
        """
        Get total portfolio value, using calculator if available

        Args:
            fallback_balance: Balance to use if calculator not available

        Returns:
            Total portfolio value in quote asset
        """
        if self._portfolio_value_calculator:
            try:
                portfolio_value = self._portfolio_value_calculator()
                self._last_portfolio_value = portfolio_value
                self._last_quote_balance = fallback_balance
                return portfolio_value
            except Exception as e:
                logger.warning(f"Portfolio calculator error, using fallback: {e}")
                return fallback_balance
        return fallback_balance

    def initialize_balances(self, current_balance: Decimal) -> None:
        """
        Initialize starting balances using TOTAL PORTFOLIO VALUE

        Args:
            current_balance: Current quote asset balance (used as fallback)
        """
        now = datetime.now()
        today = now.date()

        # Get total portfolio value (quote + coins)
        portfolio_value = self._get_portfolio_value(current_balance)

        if self.daily_start_balance is None:
            self.daily_start_balance = portfolio_value
            self.last_reset_day = today
            logger.info(
                f"📅 Daily portfolio value initialized: {portfolio_value:.2f} {self.quote_asset} "
                f"(quote balance: {current_balance:.2f})"
            )

        if self.weekly_start_balance is None:
            self.weekly_start_balance = portfolio_value
            self.last_reset_week = now.isocalendar()[1]
            logger.info(f"📅 Weekly portfolio value initialized: {portfolio_value:.2f} {self.quote_asset}")

        if self.monthly_start_balance is None:
            self.monthly_start_balance = portfolio_value
            self.last_reset_month = now.month
            logger.info(f"📅 Monthly portfolio value initialized: {portfolio_value:.2f} {self.quote_asset}")

    def record_trade_pnl(self, pnl: Decimal, symbol: str = "") -> None:
        """
        Record P&L from a completed trade

        Args:
            pnl: Realized profit/loss in quote asset
            symbol: Trading pair symbol (for logging)
        """
        self.daily_realized_pnl += pnl
        self.daily_trades.append({
            'symbol': symbol,
            'pnl': pnl,
            'timestamp': datetime.now(),
            'cumulative': self.daily_realized_pnl
        })

        logger.info(
            f"💰 Trade P&L recorded: {symbol} {pnl:+.2f} {self.quote_asset} "
            f"(Daily total: {self.daily_realized_pnl:+.2f} {self.quote_asset})"
        )

    def check_drawdown_limits(self, current_balance: Decimal) -> Tuple[bool, str]:
        """
        Check if any drawdown limits are exceeded.

        ALWAYS evaluates current drawdown with fresh portfolio values.
        Never returns a cached/frozen reason — this ensures:
        1. Log messages always show current portfolio values
        2. Auto-recovery when portfolio recovers within limits
        3. Period resets (midnight) work correctly

        Args:
            current_balance: Current quote asset balance (used as fallback if no calculator)

        Returns:
            (is_allowed, reason) - False if trading should be paused
        """
        # Get total portfolio value (quote + active executor coins)
        portfolio_value = self._get_portfolio_value(current_balance)

        # Reset counters if needed (resets start balances at day/week/month boundary)
        self._reset_if_needed(portfolio_value)

        # Initialize balances if first check
        if self.daily_start_balance is None:
            self.initialize_balances(current_balance)
            return True, "OK"

        # Guard against division by zero
        if self.daily_start_balance == Decimal("0"):
            logger.warning("Daily start balance is 0, skipping drawdown check")
            return True, "OK (no balance yet)"

        # --- Always evaluate fresh (never short-circuit on cached is_paused) ---

        # Check daily drawdown (percentage)
        daily_pnl_pct = (portfolio_value - self.daily_start_balance) / self.daily_start_balance * Decimal("100")
        if daily_pnl_pct < -self.max_daily_loss_pct:
            # Sanity check: phantom drawdown detection.
            # If portfolio says large drop but realized PnL is small, it's likely
            # due to stale balance data, executor timing, or inconsistent pricing.
            realized_pnl_pct = Decimal("0")
            if self.daily_start_balance > 0:
                realized_pnl_pct = self.daily_realized_pnl / self.daily_start_balance * Decimal("100")
            # Phantom threshold = 2× daily limit (was hardcoded 10%, too conservative)
            phantom_threshold = self.max_daily_loss_pct * Decimal("2")
            abs_portfolio_drop = abs(daily_pnl_pct)
            abs_realized = abs(realized_pnl_pct)
            if abs_portfolio_drop > phantom_threshold and abs_realized < self.max_daily_loss_pct:
                logger.warning(
                    f"⚠️ PHANTOM DRAWDOWN DETECTED: Portfolio says {daily_pnl_pct:.2f}% but "
                    f"realized PnL is only {realized_pnl_pct:.2f}% ({self.daily_realized_pnl:+.2f} {self.quote_asset}). "
                    f"Likely stale balance or executor timing. NOT pausing."
                )
                # Phantom detected — skip ALL period checks (weekly/monthly would
                # see the same phantom drop and incorrectly pause)
                return True, "OK (phantom drawdown detected, skipping all period checks)"
            else:
                reason = (
                    f"Daily drawdown limit exceeded: {daily_pnl_pct:.2f}% < -{self.max_daily_loss_pct}% "
                    f"(Start portfolio: {self.daily_start_balance:.2f} → Current: {portfolio_value:.2f} {self.quote_asset})"
                )
                self._pause_trading(reason)
                return False, reason

        # Check weekly drawdown (percentage)
        if self.weekly_start_balance and self.weekly_start_balance != Decimal("0"):
            weekly_pnl_pct = (portfolio_value - self.weekly_start_balance) / self.weekly_start_balance * Decimal("100")
            if weekly_pnl_pct < -self.max_weekly_loss_pct:
                reason = (
                    f"Weekly drawdown limit exceeded: {weekly_pnl_pct:.2f}% < -{self.max_weekly_loss_pct}% "
                    f"(Start portfolio: {self.weekly_start_balance:.2f} → Current: {portfolio_value:.2f})"
                )
                self._pause_trading(reason)
                return False, reason

        # Check monthly drawdown (percentage)
        if self.monthly_start_balance and self.monthly_start_balance != Decimal("0"):
            monthly_pnl_pct = (portfolio_value - self.monthly_start_balance) / \
                self.monthly_start_balance * Decimal("100")
            if monthly_pnl_pct < -self.max_monthly_loss_pct:
                reason = (
                    f"Monthly drawdown limit exceeded: {monthly_pnl_pct:.2f}% < -{self.max_monthly_loss_pct}% "
                    f"(Start portfolio: {self.monthly_start_balance:.2f} → Current: {portfolio_value:.2f})"
                )
                self._pause_trading(reason)
                return False, reason

        # Check daily euro loss (absolute)
        if self.max_daily_loss_eur:
            daily_portfolio_change = portfolio_value - self.daily_start_balance
            if daily_portfolio_change < -self.max_daily_loss_eur:
                reason = (
                    f"Daily {self.quote_asset} loss limit exceeded: "
                    f"{daily_portfolio_change:.2f} < -{self.max_daily_loss_eur} {self.quote_asset} "
                    f"(Start portfolio: {self.daily_start_balance:.2f} → Current: {portfolio_value:.2f})"
                )
                self._pause_trading(reason)
                return False, reason

        # All checks passed — auto-recover if previously paused
        if self.is_paused:
            logger.info(
                f"✅ DRAWDOWN RECOVERED: All limits OK — trading resumed! "
                f"Daily: {daily_pnl_pct:+.2f}% (limit: -{self.max_daily_loss_pct}%), "
                f"Portfolio: {portfolio_value:.2f} {self.quote_asset}"
            )
            self.is_paused = False
            self.pause_reason = None
            self.paused_at = None

        return True, "OK"

    def _pause_trading(self, reason: str) -> None:
        """
        Pause trading due to limit breach.

        Only logs CRITICAL on first pause to avoid log spam (the controller
        logs every blocked tick already). Updates reason every call so
        the cached value always reflects the latest portfolio numbers.

        Args:
            reason: Reason for pause
        """
        was_paused = self.is_paused
        self.is_paused = True
        self.pause_reason = reason
        if not was_paused:
            self.paused_at = datetime.now()
            logger.critical(f"🛑 TRADING PAUSED: {reason}")
            logger.critical(
                "🛑 Trading will resume when portfolio recovers or at period reset"
            )

    def _check_all_limits_ok(self, portfolio_value: Decimal) -> Tuple[bool, Optional[str]]:
        """
        Check if ALL limits are within bounds.

        Args:
            portfolio_value: Current portfolio value

        Returns:
            (all_ok, violated_reason) - (True, None) if all limits OK, (False, reason) if any violated
        """
        # Check daily percentage (use Decimal throughout for consistency)
        daily_pnl_pct = (
            (portfolio_value - self.daily_start_balance)
            / self.daily_start_balance * Decimal("100")
        )
        if daily_pnl_pct < -self.max_daily_loss_pct:
            return False, f"Daily drawdown still violated: {daily_pnl_pct:.2f}%"

        # Check weekly percentage
        if self.weekly_start_balance:
            weekly_pnl_pct = (
                (portfolio_value - self.weekly_start_balance)
                / self.weekly_start_balance * Decimal("100")
            )
            if weekly_pnl_pct < -self.max_weekly_loss_pct:
                return False, f"Weekly drawdown still violated: {weekly_pnl_pct:.2f}%"

        # Check monthly percentage
        if self.monthly_start_balance:
            monthly_pnl_pct = (
                (portfolio_value - self.monthly_start_balance)
                / self.monthly_start_balance * Decimal("100")
            )
            if monthly_pnl_pct < -self.max_monthly_loss_pct:
                return False, f"Monthly drawdown still violated: {monthly_pnl_pct:.2f}%"

        # Check daily euro loss
        if self.max_daily_loss_eur:
            daily_portfolio_change = portfolio_value - self.daily_start_balance
            if daily_portfolio_change < -self.max_daily_loss_eur:
                return False, f"Daily {self.quote_asset} loss still violated: {daily_portfolio_change:.2f}"

        return True, None

    def _reset_if_needed(self, portfolio_value: Decimal):
        """
        Reset balance counters at new day/week/month.

        Only resets start-balances and clears daily counters.
        Unpause logic is handled by check_drawdown_limits() which always
        evaluates fresh — after resetting the daily start to the current
        portfolio, the daily check will see 0% drawdown and pass.

        Args:
            portfolio_value: Current portfolio value for reset
        """
        now = datetime.now()
        today = now.date()
        current_week = now.isocalendar()[1]
        current_month = now.month

        # Check for new day
        if self.last_reset_day and today > self.last_reset_day:
            logger.info(
                f"📅 NEW DAY: Daily counter reset "
                f"(Yesterday P&L: {self.daily_realized_pnl:+.2f} {self.quote_asset}, "
                f"{len(self.daily_trades)} trades, "
                f"portfolio: {portfolio_value:.2f} {self.quote_asset})"
            )

            self.daily_start_balance = portfolio_value
            self.daily_realized_pnl = Decimal("0")
            self.daily_trades = []
            self.last_reset_day = today
            # Note: auto-unpause happens in check_drawdown_limits()
            # after all limits are re-evaluated with the fresh baseline

        # Check for new week
        if self.last_reset_week and current_week != self.last_reset_week:
            logger.info(
                f"📅 NEW WEEK: Weekly counter reset "
                f"(portfolio: {portfolio_value:.2f} {self.quote_asset})"
            )
            self.weekly_start_balance = portfolio_value
            self.last_reset_week = current_week

        # Check for new month
        if self.last_reset_month and current_month != self.last_reset_month:
            logger.info(
                f"📅 NEW MONTH: Monthly counter reset "
                f"(portfolio: {portfolio_value:.2f} {self.quote_asset})"
            )
            self.monthly_start_balance = portfolio_value
            self.last_reset_month = current_month

    def get_status(self, current_balance: Optional[Decimal] = None) -> Dict:
        """
        Get current drawdown status

        Args:
            current_balance: Current quote balance (optional, used as fallback)

        Returns:
            Status dictionary
        """
        status = {
            'is_paused': self.is_paused,
            'pause_reason': self.pause_reason,
            'paused_at': self.paused_at,
            'daily_realized_pnl': float(self.daily_realized_pnl),
            'daily_trades_count': len(self.daily_trades),
            'limits': {
                'daily_pct': float(self.max_daily_loss_pct),
                'weekly_pct': float(self.max_weekly_loss_pct),
                'monthly_pct': float(self.max_monthly_loss_pct),
                'daily_eur': float(self.max_daily_loss_eur) if self.max_daily_loss_eur else None
            },
            'uses_portfolio_value': self._portfolio_value_calculator is not None,
            'last_portfolio_value': float(self._last_portfolio_value) if self._last_portfolio_value else None,
            'last_quote_balance': float(self._last_quote_balance) if self._last_quote_balance else None
        }

        # Calculate current drawdowns if balance provided
        if current_balance and self.daily_start_balance:
            portfolio_value = self._get_portfolio_value(current_balance)
            status['current_drawdowns'] = {
                'daily_pct': float(
                    (portfolio_value
                     - self.daily_start_balance)
                    / self.daily_start_balance
                    * 100),
                'weekly_pct': float(
                    (portfolio_value
                     - self.weekly_start_balance)
                    / self.weekly_start_balance
                    * 100) if self.weekly_start_balance else None,
                'monthly_pct': float(
                    (portfolio_value
                     - self.monthly_start_balance)
                    / self.monthly_start_balance
                    * 100) if self.monthly_start_balance else None}
            status['current_portfolio_value'] = float(portfolio_value)

        return status

    def log_status(self, current_balance: Decimal):
        """
        Log current status (for monitoring)

        Args:
            current_balance: Current quote balance (used as fallback)
        """
        if not self.daily_start_balance:
            return

        portfolio_value = self._get_portfolio_value(current_balance)
        daily_pnl_pct = (portfolio_value - self.daily_start_balance) / self.daily_start_balance * 100

        logger.info(
            f"📊 Drawdown Status: "
            f"Portfolio: {portfolio_value:.2f} {self.quote_asset} (quote: {current_balance:.2f}), "
            f"Daily: {daily_pnl_pct:+.2f}% (limit: -{self.max_daily_loss_pct}%), "
            f"Realized P&L: {self.daily_realized_pnl:+.2f} {self.quote_asset}, "
            f"Trades: {len(self.daily_trades)}"
        )

    def force_reset(self, new_portfolio_value: Optional[Decimal] = None):
        """
        Force reset all balances - use when bot restarts or after manual intervention

        Args:
            new_portfolio_value: New starting portfolio value (uses calculator if None)
        """
        if new_portfolio_value is None and self._portfolio_value_calculator:
            try:
                new_portfolio_value = self._portfolio_value_calculator()
            except Exception as e:
                logger.error(f"Cannot get portfolio value for reset: {e}")
                return

        if new_portfolio_value is None:
            logger.error("Cannot force reset without portfolio value")
            return

        self.daily_start_balance = new_portfolio_value
        self.weekly_start_balance = new_portfolio_value
        self.monthly_start_balance = new_portfolio_value
        self.daily_realized_pnl = Decimal("0")
        self.daily_trades = []
        self.is_paused = False
        self.pause_reason = None
        self.paused_at = None

        now = datetime.now()
        self.last_reset_day = now.date()
        self.last_reset_week = now.isocalendar()[1]
        self.last_reset_month = now.month

        logger.info(
            f"🔄 DRAWDOWN TRACKER RESET: New portfolio value: {new_portfolio_value:.2f} {self.quote_asset}"
        )
