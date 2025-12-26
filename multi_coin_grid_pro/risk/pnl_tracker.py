"""
Real-time P&L Tracker v2.0

Tracks:
- Realized P&L (from closed trades)
- Unrealized P&L (from open positions)
- Total fees paid
- Daily/weekly/monthly P&L
- Equity curve
"""
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from core.models import Position, TradeFill

sys.path.insert(0, str(Path(__file__).parent.parent))


class RealtimePnLTracker:
    """
    Real-time P&L tracking with daily/weekly/monthly aggregation

    Usage:
        tracker = RealtimePnLTracker(starting_balance=Decimal("100"))
        tracker.on_trade_fill(fill)
        tracker.update_unrealized({"BTC-EUR": Decimal("50000")})

        print(f"Equity: €{tracker.equity()}")
        print(f"Daily P&L: {tracker.daily_pnl_pct():.2f}%")
    """

    def __init__(
        self,
        starting_balance: Decimal,
        logger: logging.Logger = None
    ):
        """
        Initialize P&L tracker

        Args:
            starting_balance: Initial account balance
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)

        # Balances
        self.starting_balance = starting_balance
        self.current_balance = starting_balance  # Available balance

        # P&L tracking
        self.realized_pnl = Decimal("0")
        self.unrealized_pnl = Decimal("0")
        self.fees_paid = Decimal("0")

        # Positions
        self.positions: Dict[str, Position] = {}

        # Daily tracking
        self.daily_start_equity = starting_balance
        self.daily_start_ts = int(time.time())
        self.daily_reset_ts = int(time.time())

        # Weekly tracking
        self.weekly_start_equity = starting_balance
        self.weekly_start_ts = int(time.time())

        # Monthly tracking
        self.monthly_start_equity = starting_balance
        self.monthly_start_ts = int(time.time())

        # Trade history
        self.trade_history: List[TradeFill] = []

        self.logger.info("=" * 80)
        self.logger.info("💰 RealtimePnLTracker v2.0 initialized")
        self.logger.info(f"   Starting balance: €{starting_balance}")
        self.logger.info("=" * 80)

    def equity(self) -> Decimal:
        """
        Calculate total equity (balance + unrealized P&L)

        Returns:
            Total account equity
        """
        return self.current_balance + self.unrealized_pnl

    def daily_pnl(self) -> Decimal:
        """Calculate daily P&L in absolute terms"""
        return self.equity() - self.daily_start_equity

    def daily_pnl_pct(self) -> float:
        """Calculate daily P&L as percentage"""
        if self.daily_start_equity == 0:
            return 0.0
        return float((self.equity() / self.daily_start_equity - 1) * 100)

    def weekly_pnl_pct(self) -> float:
        """Calculate weekly P&L as percentage"""
        if self.weekly_start_equity == 0:
            return 0.0
        return float((self.equity() / self.weekly_start_equity - 1) * 100)

    def monthly_pnl_pct(self) -> float:
        """Calculate monthly P&L as percentage"""
        if self.monthly_start_equity == 0:
            return 0.0
        return float((self.equity() / self.monthly_start_equity - 1) * 100)

    def on_new_day(self):
        """Reset daily P&L tracking (call at midnight)"""
        self.daily_start_equity = self.equity()
        self.daily_reset_ts = int(time.time())
        self.logger.info(f"📅 Daily P&L reset - new baseline: €{self.daily_start_equity:.2f}")

    def on_new_week(self):
        """Reset weekly P&L tracking"""
        self.weekly_start_equity = self.equity()
        self.weekly_start_ts = int(time.time())
        self.logger.info(f"📅 Weekly P&L reset - new baseline: €{self.weekly_start_equity:.2f}")

    def on_new_month(self):
        """Reset monthly P&L tracking"""
        self.monthly_start_equity = self.equity()
        self.monthly_start_ts = int(time.time())
        self.logger.info(f"📅 Monthly P&L reset - new baseline: €{self.monthly_start_equity:.2f}")

    def on_trade_fill(self, fill: TradeFill):
        """
        Process a trade fill and update P&L

        Args:
            fill: TradeFill object with trade details
        """
        self.trade_history.append(fill)
        self.fees_paid += fill.fee

        symbol = fill.symbol

        # Update position
        if symbol not in self.positions:
            self.positions[symbol] = Position(
                symbol=symbol,
                size=Decimal("0"),
                avg_entry_price=Decimal("0"),
                notional_eur=Decimal("0"),
            )

        pos = self.positions[symbol]

        if fill.side == "buy":
            # Increase position
            old_notional = pos.size * pos.avg_entry_price
            new_notional = old_notional + (fill.size * fill.price)
            pos.size += fill.size
            pos.avg_entry_price = new_notional / pos.size if pos.size > 0 else Decimal("0")
            pos.notional_eur = new_notional

            self.current_balance -= (fill.size * fill.price + fill.fee)

            self.logger.info(
                f"📈 BUY: {fill.size} {symbol} @ €{fill.price:.4f} "
                f"(fee: €{fill.fee:.4f}, pos: {pos.size}, avg: €{pos.avg_entry_price:.4f})"
            )

        elif fill.side == "sell":
            # Reduce position and realize P&L
            if pos.size > 0:
                realized_pnl_this_trade = (fill.price - pos.avg_entry_price) * fill.size
                self.realized_pnl += realized_pnl_this_trade

                pos.size -= fill.size
                if pos.size <= Decimal("0.00001"):
                    pos.size = Decimal("0")
                    pos.avg_entry_price = Decimal("0")
                    pos.notional_eur = Decimal("0")
                else:
                    pos.notional_eur = pos.size * pos.avg_entry_price

                self.current_balance += (fill.size * fill.price - fill.fee)

                self.logger.info(
                    f"📉 SELL: {fill.size} {symbol} @ €{fill.price:.4f} "
                    f"(realized: €{realized_pnl_this_trade:+.4f}, fee: €{fill.fee:.4f}, pos: {pos.size})"
                )

    def update_unrealized(self, prices: Dict[str, Decimal]):
        """
        Update unrealized P&L based on current market prices

        Args:
            prices: Dict mapping symbol -> current price
        """
        total_unrealized = Decimal("0")

        for symbol, pos in self.positions.items():
            if pos.size <= 0:
                continue

            current_price = prices.get(symbol)
            if not current_price:
                self.logger.warning(f"⚠️ No price for {symbol} - can't update unrealized P&L")
                continue

            unrealized_this_pos = (current_price - pos.avg_entry_price) * pos.size
            pos.unrealized_pnl = unrealized_this_pos
            total_unrealized += unrealized_this_pos

        self.unrealized_pnl = total_unrealized

    def get_summary(self) -> dict:
        """
        Get P&L summary

        Returns:
            Dict with all P&L metrics
        """
        return {
            "equity": float(self.equity()),
            "balance": float(self.current_balance),
            "realized_pnl": float(self.realized_pnl),
            "unrealized_pnl": float(self.unrealized_pnl),
            "fees_paid": float(self.fees_paid),
            "daily_pnl_pct": self.daily_pnl_pct(),
            "weekly_pnl_pct": self.weekly_pnl_pct(),
            "monthly_pnl_pct": self.monthly_pnl_pct(),
            "num_positions": len([p for p in self.positions.values() if p.size > 0]),
            "num_trades": len(self.trade_history),
        }
