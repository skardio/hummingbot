"""
Unit tests for GridExecutor balance check fixes

Tests the balance check functionality added to prevent "Insufficient funds" errors.
"""

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors import CloseType

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


# Mark all tests as async
pytestmark = pytest.mark.asyncio


class TestGridExecutorBalanceCheck:
    """Test suite for GridExecutor balance check functionality"""

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        """Create mock strategy"""
        strategy = MagicMock()
        strategy.current_timestamp = 1000.0
        strategy.cancel = Mock()
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("100.0"))
        connector.get_price = Mock(return_value=Decimal("1.5"))
        connector.trading_rules = {
            "XRP-EUR": TradingRule(
                trading_pair="XRP-EUR",
                min_order_size=Decimal("10.0"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.0001"),
                min_base_amount_increment=Decimal("0.0001")
            )
        }
        return connector

    @pytest.fixture
    def grid_config(self):
        """Create grid executor config"""
        return GridExecutorConfig(
            id="test_executor",
            connector_name="kraken",
            trading_pair="XRP-EUR",
            side=TradeType.BUY,
            total_amount_quote=Decimal("120"),
            num_levels=3,
            start_price=Decimal("1.5"),
            end_price=Decimal("1.6"),
            limit_price=Decimal("1.4"),  # Required field
            min_spread_between_orders=Decimal("0.01"),
            min_order_amount_quote=Decimal("10"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.08"),
                take_profit=Decimal("0.02"),
                time_limit=3600,
                time_limit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
            )
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        """Create executor instance"""
        with patch('hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_metrics'), \
                patch('hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_position_metrics'), \
                patch.object(GridExecutor, 'get_price', return_value=Decimal("1.5")):  # noqa: E501
            executor = GridExecutor(
                strategy=mock_strategy,
                config=grid_config,
                update_interval=1.0
            )
            executor.connectors = {"kraken": mock_connector}
            executor.trading_rules = mock_connector.trading_rules["XRP-EUR"]
            executor.position_size_base = Decimal("50.0")  # Position to close
            executor.close_order_side = TradeType.SELL
            executor.mid_price = Decimal("1.5")
            executor.current_close_quote = Decimal("1.55")
            return executor

    async def test_balance_check_sufficient_balance(self, executor, mock_connector):
        """Test that order is placed when balance is sufficient"""
        # Setup: sufficient balance
        mock_connector.get_available_balance.return_value = Decimal("100.0")
        executor.position_size_base = Decimal("50.0")

        # Mock place_order
        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        # Call place_close_order_and_cancel_open_orders
        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify balance was checked
        mock_connector.get_available_balance.assert_called_once_with("XRP")

        # Verify order was placed with correct amount
        executor.place_order.assert_called_once()
        call_args = executor.place_order.call_args
        assert call_args[1]['amount'] == Decimal("50.0"), "Should use full position size"

    async def test_balance_check_insufficient_balance_adjusts_amount(self, executor, mock_connector):
        """Test that order amount is adjusted when balance is insufficient"""
        # Setup: insufficient balance but above minimum
        mock_connector.get_available_balance.return_value = Decimal("30.0")  # Less than position
        executor.position_size_base = Decimal("50.0")
        executor.trading_rules.min_order_size = Decimal("10.0")

        # Mock place_order
        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        # Call place_close_order_and_cancel_open_orders
        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify order was placed with adjusted amount
        executor.place_order.assert_called_once()
        call_args = executor.place_order.call_args
        assert call_args[1]['amount'] == Decimal("30.0"), "Should use available balance"

    async def test_balance_check_insufficient_balance_below_minimum(self, executor, mock_connector):
        """Test that order is not placed when balance is below minimum order size"""
        # Setup: balance below minimum order size
        mock_connector.get_available_balance.return_value = Decimal("5.0")  # Below minimum
        executor.position_size_base = Decimal("50.0")
        executor.trading_rules.min_order_size = Decimal("10.0")

        # Mock place_order
        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        # Call place_close_order_and_cancel_open_orders
        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify order was NOT placed
        executor.place_order.assert_not_called()

    async def test_balance_check_handles_exception(self, executor, mock_connector):
        """Test that balance check handles exceptions gracefully"""
        # Setup: balance check raises exception
        mock_connector.get_available_balance.side_effect = Exception("Connection error")
        executor.position_size_base = Decimal("50.0")

        # Mock place_order
        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        # Call place_close_order_and_cancel_open_orders
        # Should not crash, should proceed with original amount
        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify order was still placed (with original amount as fallback)
        executor.place_order.assert_called_once()
        call_args = executor.place_order.call_args
        assert call_args[1]['amount'] == Decimal("50.0"), "Should use original amount on error"

    async def test_balance_check_logs_warning_on_adjustment(self, executor, mock_connector):
        """Test that balance check logs info when using min(position, balance)"""
        # Setup: insufficient balance (Phase 3.5: uses min(position_size, available_balance))
        mock_connector.get_available_balance.return_value = Decimal("30.0")
        executor.position_size_base = Decimal("50.0")
        executor.trading_rules.min_order_size = Decimal("10.0")

        # Mock place_order and logger
        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        # Capture log output (Phase 3.5: logs info with production format)
        with patch.object(executor.logger(), 'info') as mock_info:
            executor.place_close_order_and_cancel_open_orders(
                close_type=CloseType.EARLY_STOP,
                price=Decimal("1.55")
            )

            # Verify info was logged with Phase 3.5 format
            assert mock_info.called, "Should log info with close amount calculation"
            info_calls = [str(call) for call in mock_info.call_args_list]
            assert any("Close amount calculation" in str(call) or "executor_position" in str(call)
                       for call in info_calls), "Should log Phase 3.5 close amount calculation"

    async def test_balance_check_logs_error_on_insufficient(self, executor, mock_connector):
        """Test that balance check terminates with TERMINATED status when balance is dust"""
        # Setup: balance below minimum (Phase 3.5: terminates with TERMINATED status)
        mock_connector.get_available_balance.return_value = Decimal("5.0")
        executor.position_size_base = Decimal("50.0")
        executor.trading_rules.min_order_size = Decimal("10.0")

        # Mock place_order
        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        # Call place_close_order_and_cancel_open_orders
        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify order was NOT placed (dust handling)
        executor.place_order.assert_not_called()

        # Verify executor status is TERMINATED (Phase 3.5: CLOSED_WITH_DUST)
        from hummingbot.strategy_v2.models.base import RunnableStatus
        assert executor._status == RunnableStatus.TERMINATED, "Should be TERMINATED when dust"
        assert executor._closing_in_progress is False, "Should reset closing guard"
        assert executor.close_type == CloseType.EARLY_STOP, "Should set close_type"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
