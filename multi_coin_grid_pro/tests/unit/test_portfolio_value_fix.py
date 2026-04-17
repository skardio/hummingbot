"""
Unit tests for _calculate_portfolio_value() — executor-based coin valuation.

Verifies that the portfolio calculator uses:
1. Quote asset balance (from connector)
2. Mark-to-market coin value from ACTIVE executors' custom_info
   (position_size_quote + position_pnl_quote + position_fees_quote)
3. Held position values (from positions_held)

This prevents phantom drawdown caused by silent failures in connector
balance lookups or mid-price calls.
"""

from decimal import Decimal
from unittest.mock import MagicMock

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController


def _make_executor(is_active=True, pos_size=0, pos_pnl=0, pos_fees=0):
    """Create a mock executor with position tracking in custom_info."""
    ei = MagicMock()
    ei.is_active = is_active
    ei.custom_info = {
        'position_size_quote': Decimal(str(pos_size)),
        'position_pnl_quote': Decimal(str(pos_pnl)),
        'position_fees_quote': Decimal(str(pos_fees)),
    }
    return ei


def _make_position(amount, breakeven_price, unrealized_pnl=0):
    """Create a mock held position."""
    pos = MagicMock()
    pos.amount = Decimal(str(amount))
    pos.breakeven_price = Decimal(str(breakeven_price))
    pos.unrealized_pnl_quote = Decimal(str(unrealized_pnl))
    return pos


def _make_controller(quote_balance, executors_info=None, positions_held=None):
    """Build a minimal mock controller bound to the real method."""
    ctrl = MagicMock(spec=MultiCoinGridController)
    ctrl.config = MagicMock()
    ctrl.config.quote_asset = "USD"
    ctrl.executors_info = executors_info or []
    ctrl.positions_held = positions_held or []

    connector = MagicMock()
    connector.get_balance = MagicMock(return_value=Decimal(str(quote_balance)))
    ctrl.connector = connector

    # Bind real method
    ctrl._calculate_portfolio_value = (
        MultiCoinGridController._calculate_portfolio_value.__get__(ctrl)
    )
    return ctrl


class TestCalculatePortfolioValue:
    """Test executor-based portfolio value calculation."""

    def test_quote_only_no_executors(self):
        """With no executors, return only quote balance."""
        ctrl = _make_controller(quote_balance=300)
        assert ctrl._calculate_portfolio_value() == Decimal("300")

    def test_active_executor_buys_counted(self):
        """Active executor holding coins adds mark-to-market value."""
        # Bought $50, no PnL yet, no fees
        executor = _make_executor(is_active=True, pos_size=50, pos_pnl=0, pos_fees=0)
        ctrl = _make_controller(quote_balance=250, executors_info=[executor])
        # USD=$250 + coins $50 = $300
        assert ctrl._calculate_portfolio_value() == Decimal("300")

    def test_active_executor_with_pnl(self):
        """Executor with unrealized PnL reflects in portfolio."""
        # Bought $50, price moved up: +$3 PnL, $0.12 fees
        executor = _make_executor(is_active=True, pos_size=50, pos_pnl=3, pos_fees=Decimal("0.12"))
        ctrl = _make_controller(quote_balance=250, executors_info=[executor])
        # coins = 50 + 3 + 0.12 = 53.12
        assert ctrl._calculate_portfolio_value() == Decimal("303.12")

    def test_active_executor_with_loss(self):
        """Executor with unrealized loss reflects in portfolio."""
        # Bought $50, price dropped: -$5 PnL, $0.12 fees
        executor = _make_executor(is_active=True, pos_size=50, pos_pnl=-5, pos_fees=Decimal("0.12"))
        ctrl = _make_controller(quote_balance=250, executors_info=[executor])
        # coins = 50 + (-5) + 0.12 = 45.12
        assert ctrl._calculate_portfolio_value() == Decimal("295.12")

    def test_terminated_executor_not_counted(self):
        """Terminated executors are NOT counted."""
        executor = _make_executor(is_active=False, pos_size=50, pos_pnl=0, pos_fees=0)
        ctrl = _make_controller(quote_balance=247, executors_info=[executor])
        assert ctrl._calculate_portfolio_value() == Decimal("247")

    def test_multiple_active_executors(self):
        """Multiple active executors all contribute their coin value."""
        exe1 = _make_executor(is_active=True, pos_size=50, pos_pnl=0, pos_fees=0)
        exe2 = _make_executor(is_active=True, pos_size=30, pos_pnl=-2, pos_fees=Decimal("0.1"))
        ctrl = _make_controller(quote_balance=170, executors_info=[exe1, exe2])
        # coins = 50 + (30-2+0.1) = 78.1
        assert ctrl._calculate_portfolio_value() == Decimal("248.1")

    def test_old_coins_on_account_excluded(self):
        """
        Real bug scenario: old HYPE on account is invisible to executor-based calc.
        Only executor-tracked positions count.
        """
        executor = _make_executor(is_active=True, pos_size=50, pos_pnl=0, pos_fees=0)
        ctrl = _make_controller(quote_balance=200, executors_info=[executor])
        # $200 USD + $50 executor position = $250 (old coins excluded)
        assert ctrl._calculate_portfolio_value() == Decimal("250")

    def test_no_phantom_drawdown(self):
        """
        Key test: portfolio stays consistent when executor opens positions.
        No more phantom swings from missing coin pricing.
        """
        # Before executor starts: $250 USD, no active executors
        ctrl_before = _make_controller(quote_balance=250)
        before_val = ctrl_before._calculate_portfolio_value()

        # During executor: USD drops by $50 (bought coins), executor holds position
        executor = _make_executor(is_active=True, pos_size=50, pos_pnl=0, pos_fees=0)
        ctrl_during = _make_controller(quote_balance=200, executors_info=[executor])
        during_val = ctrl_during._calculate_portfolio_value()

        # After executor closes (sold coins back, small loss -$2)
        ctrl_after = _make_controller(quote_balance=248)
        after_val = ctrl_after._calculate_portfolio_value()

        assert before_val == Decimal("250")
        assert during_val == Decimal("250")  # $200 + $50 = $250
        assert after_val == Decimal("248")   # Reflects real $2 loss

    def test_held_positions_counted(self):
        """Positions from completed executors (POSITION_HOLD) are valued."""
        pos = _make_position(amount=1000, breakeven_price=Decimal("0.0065"),
                             unrealized_pnl=Decimal("0.50"))
        ctrl = _make_controller(quote_balance=250, positions_held=[pos])
        # coins = 1000 * 0.0065 + 0.50 = 6.50 + 0.50 = 7.00
        assert ctrl._calculate_portfolio_value() == Decimal("257.00")

    def test_custom_info_missing(self):
        """If custom_info is empty dict, executor contributes 0 (safe fallback)."""
        executor = MagicMock()
        executor.is_active = True
        executor.custom_info = {}
        ctrl = _make_controller(quote_balance=200, executors_info=[executor])
        assert ctrl._calculate_portfolio_value() == Decimal("200")

    def test_custom_info_none(self):
        """If custom_info is None, executor contributes 0 (safe fallback)."""
        executor = MagicMock()
        executor.is_active = True
        executor.custom_info = None
        ctrl = _make_controller(quote_balance=200, executors_info=[executor])
        assert ctrl._calculate_portfolio_value() == Decimal("200")
