"""
Unit tests for _calculate_portfolio_value() — investment coin exclusion.

Verifies that the drawdown calculator only counts:
1. Quote asset balance
2. Coins in active bot executors
And EXCLUDES investment coins held on the same exchange account.
"""

from decimal import Decimal
from unittest.mock import MagicMock

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController


class TestCalculatePortfolioValue:
    """Test that _calculate_portfolio_value excludes investment coins."""

    def _make_controller(
        self,
        quote_balance: Decimal,
        account_balances: dict,
        active_coins: dict,
        executors_info=None,
        mid_prices: dict = None,
    ):
        """Build a minimal mock controller bound to the real method."""
        ctrl = MagicMock(spec=MultiCoinGridController)
        ctrl.config = MagicMock()
        ctrl.config.quote_asset = "USD"
        ctrl.active_coins = active_coins
        ctrl.executors_info = executors_info or []

        connector = MagicMock()
        connector.get_balance = MagicMock(return_value=quote_balance)
        connector._account_balances = account_balances

        def mock_mid_price(pair):
            if mid_prices and pair in mid_prices:
                return mid_prices[pair]
            return Decimal("0")

        connector.get_mid_price = mock_mid_price
        ctrl.connector = connector

        # Bind real method
        ctrl._calculate_portfolio_value = (
            MultiCoinGridController._calculate_portfolio_value.__get__(ctrl)
        )
        return ctrl

    def test_excludes_investment_coins(self):
        """BTC/ETH investment holdings must NOT be included."""
        ctrl = self._make_controller(
            quote_balance=Decimal("300"),
            account_balances={
                "USD": Decimal("300"),
                "BTC": Decimal("0.015"),      # ~$1,282 investment
                "ETH": Decimal("0.5"),         # ~$900 investment
                "XDC": Decimal("5000"),         # bot position
            },
            active_coins={"XDC-USD": "executor_1"},
            mid_prices={
                "BTC-USD": Decimal("85000"),
                "ETH-USD": Decimal("1800"),
                "XDC-USD": Decimal("0.04"),
            },
        )

        result = ctrl._calculate_portfolio_value()

        # Should be: $300 (quote) + 5000*0.04 (XDC) = $500
        # NOT: $300 + $1275 (BTC) + $900 (ETH) + $200 (XDC) = $2675
        assert result == Decimal("300") + Decimal("5000") * Decimal("0.04")

    def test_includes_active_executor_coins(self):
        """Coins from active executors must be included."""
        ctrl = self._make_controller(
            quote_balance=Decimal("150"),
            account_balances={
                "USD": Decimal("150"),
                "ADI": Decimal("200"),
            },
            active_coins={"ADI-USD": "executor_2"},
            mid_prices={"ADI-USD": Decimal("0.50")},
        )

        result = ctrl._calculate_portfolio_value()
        # $150 + 200*0.50 = $250
        assert result == Decimal("250")

    def test_quote_only_when_no_active_positions(self):
        """With no active executors, return only quote balance."""
        ctrl = self._make_controller(
            quote_balance=Decimal("300"),
            account_balances={
                "USD": Decimal("300"),
                "BTC": Decimal("0.015"),
                "SOL": Decimal("5.0"),
            },
            active_coins={},
            mid_prices={
                "BTC-USD": Decimal("85000"),
                "SOL-USD": Decimal("130"),
            },
        )

        result = ctrl._calculate_portfolio_value()
        # Only quote — no active coins means no bot positions counted
        assert result == Decimal("300")

    def test_multiple_active_coins(self):
        """Multiple active executors should all be included."""
        ctrl = self._make_controller(
            quote_balance=Decimal("100"),
            account_balances={
                "USD": Decimal("100"),
                "XDC": Decimal("3000"),
                "ADI": Decimal("400"),
                "BTC": Decimal("0.01"),  # investment, excluded
            },
            active_coins={
                "XDC-USD": "exec_1",
                "ADI-USD": "exec_2",
            },
            mid_prices={
                "XDC-USD": Decimal("0.04"),
                "ADI-USD": Decimal("0.50"),
                "BTC-USD": Decimal("85000"),
            },
        )

        result = ctrl._calculate_portfolio_value()
        expected = Decimal("100") + Decimal("3000") * Decimal("0.04") + Decimal("400") * Decimal("0.50")
        assert result == expected

    def test_executor_info_coins_included(self):
        """Coins from executors_info (not in active_coins) are also included."""
        executor_info = MagicMock()
        executor_info.trading_pair = "RENDER-USD"
        executor_info.config = MagicMock()
        executor_info.config.trading_pair = "RENDER-USD"

        ctrl = self._make_controller(
            quote_balance=Decimal("200"),
            account_balances={
                "USD": Decimal("200"),
                "RENDER": Decimal("100"),
            },
            active_coins={},
            executors_info=[executor_info],
            mid_prices={"RENDER-USD": Decimal("3.50")},
        )

        result = ctrl._calculate_portfolio_value()
        # $200 + 100*3.50 = $550
        assert result == Decimal("550")

    def test_dust_amounts_excluded(self):
        """Dust amounts below 0.0001 are excluded even for active coins."""
        ctrl = self._make_controller(
            quote_balance=Decimal("300"),
            account_balances={
                "USD": Decimal("300"),
                "XDC": Decimal("0.00001"),  # dust
            },
            active_coins={"XDC-USD": "exec_1"},
            mid_prices={"XDC-USD": Decimal("0.04")},
        )

        result = ctrl._calculate_portfolio_value()
        assert result == Decimal("300")

    def test_real_scenario_kraken_usd(self):
        """
        Real production scenario: $300 bot capital, $1282 in BTC/ETH investment.
        BTC drops 1% → should NOT trigger drawdown for bot.
        """
        # Start of day
        ctrl_start = self._make_controller(
            quote_balance=Decimal("300"),
            account_balances={
                "USD": Decimal("300"),
                "BTC": Decimal("0.015"),
                "ETH": Decimal("0.5"),
            },
            active_coins={},
            mid_prices={
                "BTC-USD": Decimal("85000"),
                "ETH-USD": Decimal("1800"),
            },
        )
        start_value = ctrl_start._calculate_portfolio_value()

        # BTC drops 5%, ETH drops 3% — but bot has no positions
        ctrl_now = self._make_controller(
            quote_balance=Decimal("300"),
            account_balances={
                "USD": Decimal("300"),
                "BTC": Decimal("0.015"),
                "ETH": Decimal("0.5"),
            },
            active_coins={},
            mid_prices={
                "BTC-USD": Decimal("80750"),   # -5%
                "ETH-USD": Decimal("1746"),    # -3%
            },
        )
        current_value = ctrl_now._calculate_portfolio_value()

        # Bot portfolio should be unchanged ($300 → $300)
        assert start_value == Decimal("300")
        assert current_value == Decimal("300")
        assert current_value - start_value == Decimal("0")
