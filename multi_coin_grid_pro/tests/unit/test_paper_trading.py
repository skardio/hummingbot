"""
Unit tests for Paper Trading Module
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from multi_coin_grid_pro.paper_trading.paper_trading_mode import PaperTradingMode
except ImportError:
    from paper_trading.paper_trading_mode import PaperTradingMode


class TestPaperTradingMode:
    """Test PaperTradingMode class"""

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        connector = AsyncMock()
        connector.name = "kraken"
        connector.get_available_balance = AsyncMock(return_value=1000.0)
        connector.get_price = AsyncMock(return_value=2.0)
        return connector

    @pytest.fixture
    def paper_trading(self, mock_connector):
        """Create paper trading instance"""
        from decimal import Decimal
        config = {"maker_fee_pct": 0.0016}
        return PaperTradingMode(initial_capital=Decimal("1000"), config=config)

    def test_initialization(self, paper_trading):
        """Test paper trading initialization"""
        from decimal import Decimal
        assert paper_trading.initial_capital == Decimal("1000")
        assert paper_trading.current_capital == Decimal("1000")
        assert paper_trading.positions is not None
        assert paper_trading.open_orders is not None

    def test_simulate_buy_order(self, paper_trading):
        """Test simulating buy order"""
        from decimal import Decimal

        trade = paper_trading.simulate_buy_order(
            symbol="XRP-EUR",
            price=Decimal("2.0"),
            amount=Decimal("100.0")
        )

        assert trade is not None
        assert trade.side == "BUY"
        assert trade.amount == Decimal("100.0")
        assert trade.price == Decimal("2.0")

    def test_simulate_sell_order(self, paper_trading):
        """Test simulating sell order"""
        from decimal import Decimal

        # First create a position by buying (MARKET order fills immediately)
        paper_trading.simulate_buy_order(
            symbol="XRP-EUR",
            price=Decimal("2.0"),
            amount=Decimal("100.0"),
            order_type="MARKET"
        )

        # Now sell (MARKET order fills immediately)
        trade = paper_trading.simulate_sell_order(
            symbol="XRP-EUR",
            price=Decimal("2.1"),
            amount=Decimal("50.0"),
            order_type="MARKET"
        )

        assert trade is not None
        assert trade.side == "SELL"
        assert trade.amount == Decimal("50.0")
        assert trade.filled is True

    def test_simulate_buy_order_insufficient_capital(self, paper_trading):
        """Test simulating buy order with insufficient capital"""
        from decimal import Decimal

        # Try to buy more than capital allows
        trade = paper_trading.simulate_buy_order(
            symbol="XRP-EUR",
            price=Decimal("2.0"),
            amount=Decimal("10000.0"),  # Would cost way more than 1000 EUR
            order_type="MARKET"
        )

        # Should return None or have error
        assert trade is None or not trade.filled

    def test_get_position(self, paper_trading):
        """Test getting position"""
        from decimal import Decimal

        # Create a position (MARKET order fills immediately)
        paper_trading.simulate_buy_order(
            symbol="XRP-EUR",
            price=Decimal("2.0"),
            amount=Decimal("100.0"),
            order_type="MARKET"
        )

        # Position should exist in positions dict
        assert "XRP-EUR" in paper_trading.positions
        position = paper_trading.positions["XRP-EUR"]
        assert position.symbol == "XRP-EUR"
        assert position.amount == Decimal("100.0")
