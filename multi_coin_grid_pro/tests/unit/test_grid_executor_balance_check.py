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
        connector.get_balance = Mock(return_value=Decimal("100.0"))
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
        """Test that order is placed using position_size_base (not available_balance)"""
        mock_connector.get_balance.return_value = Decimal("100.0")
        executor.position_size_base = Decimal("50.0")

        # Mock place_order
        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify get_balance called for monitoring
        mock_connector.get_balance.assert_called_once_with("XRP")

        # Verify order was placed with full position_size_base (not capped by balance)
        executor.place_order.assert_called_once()
        call_args = executor.place_order.call_args
        assert call_args[1]['amount'] == Decimal("50.0"), "Should use full position size"

    async def test_low_balance_uses_position_size_not_available(self, executor, mock_connector):
        """Test that order uses position_size_base even when wallet balance is lower.

        This is the FIX for the RIVER/QNT bug: available_balance can be stale
        or reduced by pending cancels, so we use position_size_base directly.
        """
        mock_connector.get_balance.return_value = Decimal("30.0")  # Less than position
        executor.position_size_base = Decimal("50.0")
        executor.trading_rules.min_order_size = Decimal("10.0")

        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify order was placed with full position_size_base (NOT capped to 30.0)
        executor.place_order.assert_called_once()
        call_args = executor.place_order.call_args
        assert call_args[1]['amount'] == Decimal("50.0"), \
            "Should use position_size_base, not wallet balance"

    async def test_dust_position_below_minimum_skips_close(self, executor, mock_connector):
        """Test that order is not placed when position_size_base is below minimum"""
        mock_connector.get_balance.return_value = Decimal("5.0")
        executor.position_size_base = Decimal("5.0")  # Below min_order_size
        executor.trading_rules.min_order_size = Decimal("10.0")

        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify order was NOT placed (dust handling)
        executor.place_order.assert_not_called()

    async def test_balance_monitoring_handles_exception(self, executor, mock_connector):
        """Test that balance monitoring exception doesn't block close order"""
        mock_connector.get_balance.side_effect = Exception("Connection error")
        executor.position_size_base = Decimal("50.0")

        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify order was still placed with position_size_base
        executor.place_order.assert_called_once()
        call_args = executor.place_order.call_args
        assert call_args[1]['amount'] == Decimal("50.0"), "Should use position_size_base"

    async def test_balance_check_logs_close_amount(self, executor, mock_connector):
        """Test that close amount info is logged with wallet balance"""
        mock_connector.get_balance.return_value = Decimal("30.0")
        executor.position_size_base = Decimal("50.0")
        executor.trading_rules.min_order_size = Decimal("10.0")

        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        with patch.object(executor.logger(), 'info') as mock_info:
            executor.place_close_order_and_cancel_open_orders(
                close_type=CloseType.EARLY_STOP,
                price=Decimal("1.55")
            )

            assert mock_info.called, "Should log close amount info"
            info_calls = [str(call) for call in mock_info.call_args_list]
            assert any("Close amount" in str(call) or "wallet_total" in str(call)
                       for call in info_calls), "Should log close amount with wallet info"

    async def test_dust_position_sets_terminated_status(self, executor, mock_connector):
        """Test that dust position (<min_order_size) terminates executor correctly"""
        mock_connector.get_balance.return_value = Decimal("5.0")
        executor.position_size_base = Decimal("5.0")  # Below min_order_size
        executor.trading_rules.min_order_size = Decimal("10.0")

        executor.place_order = Mock(return_value="order_123")
        executor.cancel_open_orders = Mock()

        executor.place_close_order_and_cancel_open_orders(
            close_type=CloseType.EARLY_STOP,
            price=Decimal("1.55")
        )

        # Verify order was NOT placed (dust handling)
        executor.place_order.assert_not_called()

        # Verify executor status is TERMINATED
        from hummingbot.strategy_v2.models.base import RunnableStatus
        assert executor._status == RunnableStatus.TERMINATED, "Should be TERMINATED when dust"
        assert executor._closing_in_progress is False, "Should reset closing guard"
        assert executor.close_type == CloseType.EARLY_STOP, "Should set close_type"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
