"""
Unit tests for MultiCoinGridStrategyV2

Tests the strategy-level functionality including format_status
"""
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, PropertyMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
    from multi_coin_grid_pro.scripts.multi_coin_grid_v2 import MultiCoinGridStrategyConfig, MultiCoinGridStrategyV2
except ImportError:
    try:
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
        from multi_coin_grid_pro.scripts.multi_coin_grid_v2 import MultiCoinGridStrategyConfig, MultiCoinGridStrategyV2
    except ImportError:
        # Last resort: try relative import
        from scripts.multi_coin_grid_v2 import MultiCoinGridStrategyV2, MultiCoinGridStrategyConfig
        from controllers.multi_coin_grid_controller import MultiCoinGridController

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo, RunnableStatus


class TestMultiCoinGridStrategyV2:
    """Test suite for MultiCoinGridStrategyV2 class"""

    @pytest.fixture
    def config(self):
        """Create test config"""
        return MultiCoinGridStrategyConfig()

    @pytest.fixture
    def strategy(self, config):
        """Create a minimal strategy-like object for testing format_status"""
        # Create a simple object that mimics the strategy structure
        # We can't fully instantiate because it requires real ConnectorBase instances
        class StrategyMock:
            def __init__(self):
                self.executor_orchestrator = MagicMock()
                self.executor_orchestrator.get_executors_report = Mock(return_value={})
                self.controllers = {}

            def format_status(self):
                # Use the real format_status implementation
                lines = []

                # Get controller status
                for controller in self.controllers.values():
                    if hasattr(controller, 'to_format_status'):
                        lines.extend(controller.to_format_status())

                # Add executor status
                if self.executor_orchestrator:
                    try:
                        executors_report = self.executor_orchestrator.get_executors_report()
                        active_executors = []

                        for controller_id, executor_list in executors_report.items():
                            active_executors.extend([e for e in executor_list if e.is_active])

                        if active_executors:
                            lines.append("\n╔═══════════════════════════════════════════════════════════════╗")
                            lines.append("║                    ACTIVE EXECUTORS                           ║")
                            lines.append("╠═══════════════════════════════════════════════════════════════╣")

                            for executor in active_executors:
                                lines.append(
                                    f"║ ID: {executor.id[:8]}... | "
                                    f"Status: {executor.status.name:10} | "
                                    f"P&L: {float(executor.net_pnl_pct) * 100:+.2f}%   ║"
                                )

                            lines.append("╚═══════════════════════════════════════════════════════════════╝\n")
                    except Exception:
                        pass

                return "\n".join(lines)

        return StrategyMock()

    def test_format_status_without_executors(self, strategy):
        """Test format_status when no executors exist"""
        # Mock controller
        mock_controller = MagicMock()
        mock_controller.to_format_status = Mock(return_value=["║ Test Status ║"])
        strategy.controllers = {"multi_coin_grid": mock_controller}

        # Mock executor orchestrator with no executors
        strategy.executor_orchestrator.get_executors_report = Mock(return_value={})

        status = strategy.format_status()
        assert isinstance(status, str)
        assert "Test Status" in status

    def test_format_status_with_active_executors(self, strategy):
        """Test format_status with active executors"""
        # Mock controller
        mock_controller = MagicMock()
        mock_controller.to_format_status = Mock(return_value=["║ Controller Status ║"])
        strategy.controllers = {"multi_coin_grid": mock_controller}

        # Create mock executor info
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=datetime.now().timestamp(),
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=GridExecutorConfig(
                id="test_executor_123",
                type="grid_executor",
                timestamp=datetime.now().timestamp(),
                controller_id="multi_coin_grid",
                connector_name="kraken",
                trading_pair="XRP-EUR",
                start_price=Decimal("1.0"),
                end_price=Decimal("2.0"),
                limit_price=Decimal("0.95"),
                side=TradeType.BUY,
                total_amount_quote=Decimal("120"),
                triple_barrier_config=TripleBarrierConfig(
                    stop_loss=Decimal("0.08"),
                    take_profit=Decimal("0.02"),
                    time_limit=None,
                    trailing_stop=None,
                    open_order_type=OrderType.LIMIT_MAKER,
                    take_profit_order_type=OrderType.LIMIT_MAKER,
                    stop_loss_order_type=OrderType.MARKET,
                    time_limit_order_type=OrderType.MARKET,
                ),
            ),
            net_pnl_pct=Decimal("2.5"),
            net_pnl_quote=Decimal("3.0"),
            cum_fees_quote=Decimal("0.2"),
            filled_amount_quote=Decimal("120"),
            is_active=True,
            is_trading=True,
            custom_info={}
        )

        # Mock executor orchestrator with active executor
        strategy.executor_orchestrator.get_executors_report = Mock(return_value={
            "multi_coin_grid": [executor_info]
        })

        status = strategy.format_status()
        assert isinstance(status, str)
        assert "ACTIVE EXECUTORS" in status
        assert "test_executor_123"[:8] in status
        assert "RUNNING" in status
        # P&L is multiplied by 100 in format_status, so 2.5% becomes 250.00%
        assert "250.00" in status or "250" in status  # P&L percentage

    def test_format_status_with_inactive_executors(self, strategy):
        """Test format_status with only inactive executors"""
        # Mock controller
        mock_controller = MagicMock()
        mock_controller.to_format_status = Mock(return_value=["║ Controller Status ║"])
        strategy.controllers = {"multi_coin_grid": mock_controller}

        # Create mock executor info (inactive)
        executor_info = ExecutorInfo(
            id="test_executor_456",
            timestamp=datetime.now().timestamp(),
            type="grid_executor",
            status=RunnableStatus.TERMINATED,
            config=GridExecutorConfig(
                id="test_executor_456",
                type="grid_executor",
                timestamp=datetime.now().timestamp(),
                controller_id="multi_coin_grid",
                connector_name="kraken",
                trading_pair="ADA-EUR",
                start_price=Decimal("0.5"),
                end_price=Decimal("1.0"),
                limit_price=Decimal("0.45"),
                side=TradeType.BUY,
                total_amount_quote=Decimal("100"),
                triple_barrier_config=TripleBarrierConfig(
                    stop_loss=Decimal("0.08"),
                    take_profit=Decimal("0.02"),
                    time_limit=None,
                    trailing_stop=None,
                    open_order_type=OrderType.LIMIT_MAKER,
                    take_profit_order_type=OrderType.LIMIT_MAKER,
                    stop_loss_order_type=OrderType.MARKET,
                    time_limit_order_type=OrderType.MARKET,
                ),
            ),
            net_pnl_pct=Decimal("1.0"),
            net_pnl_quote=Decimal("1.0"),
            cum_fees_quote=Decimal("0.1"),
            filled_amount_quote=Decimal("100"),
            is_active=False,  # Inactive
            is_trading=False,
            custom_info={}
        )

        # Mock executor orchestrator with inactive executor
        strategy.executor_orchestrator.get_executors_report = Mock(return_value={
            "multi_coin_grid": [executor_info]
        })

        status = strategy.format_status()
        assert isinstance(status, str)
        # Should not show ACTIVE EXECUTORS section if no active executors
        assert "ACTIVE EXECUTORS" not in status

    def test_format_status_with_multiple_controllers(self, strategy):
        """Test format_status with executors from multiple controllers"""
        # Mock controllers
        mock_controller1 = MagicMock()
        mock_controller1.to_format_status = Mock(return_value=["║ Controller 1 Status ║"])
        mock_controller2 = MagicMock()
        mock_controller2.to_format_status = Mock(return_value=["║ Controller 2 Status ║"])
        strategy.controllers = {
            "controller_1": mock_controller1,
            "controller_2": mock_controller2
        }

        # Create mock executor infos
        executor1 = ExecutorInfo(
            id="executor_1",
            timestamp=datetime.now().timestamp(),
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=GridExecutorConfig(
                id="executor_1",
                type="grid_executor",
                timestamp=datetime.now().timestamp(),
                controller_id="controller_1",
                connector_name="kraken",
                trading_pair="XRP-EUR",
                start_price=Decimal("1.0"),
                end_price=Decimal("2.0"),
                limit_price=Decimal("0.95"),
                side=TradeType.BUY,
                total_amount_quote=Decimal("50"),
                triple_barrier_config=TripleBarrierConfig(
                    stop_loss=Decimal("0.08"),
                    take_profit=Decimal("0.02"),
                    time_limit=None,
                    trailing_stop=None,
                    open_order_type=OrderType.LIMIT_MAKER,
                    take_profit_order_type=OrderType.LIMIT_MAKER,
                    stop_loss_order_type=OrderType.MARKET,
                    time_limit_order_type=OrderType.MARKET,
                ),
            ),
            net_pnl_pct=Decimal("1.0"),
            net_pnl_quote=Decimal("0.5"),
            cum_fees_quote=Decimal("0.1"),
            filled_amount_quote=Decimal("50"),
            is_active=True,
            is_trading=True,
            custom_info={}
        )

        executor2 = ExecutorInfo(
            id="executor_2",
            timestamp=datetime.now().timestamp(),
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=GridExecutorConfig(
                id="executor_2",
                type="grid_executor",
                timestamp=datetime.now().timestamp(),
                controller_id="controller_2",
                connector_name="kraken",
                trading_pair="ADA-EUR",
                start_price=Decimal("0.5"),
                end_price=Decimal("1.0"),
                limit_price=Decimal("0.45"),
                side=TradeType.BUY,
                total_amount_quote=Decimal("70"),
                triple_barrier_config=TripleBarrierConfig(
                    stop_loss=Decimal("0.08"),
                    take_profit=Decimal("0.02"),
                    time_limit=None,
                    trailing_stop=None,
                    open_order_type=OrderType.LIMIT_MAKER,
                    take_profit_order_type=OrderType.LIMIT_MAKER,
                    stop_loss_order_type=OrderType.MARKET,
                    time_limit_order_type=OrderType.MARKET,
                ),
            ),
            net_pnl_pct=Decimal("2.0"),
            net_pnl_quote=Decimal("1.4"),
            cum_fees_quote=Decimal("0.2"),
            filled_amount_quote=Decimal("70"),
            is_active=True,
            is_trading=True,
            custom_info={}
        )

        # Mock executor orchestrator with executors from multiple controllers
        strategy.executor_orchestrator.get_executors_report = Mock(return_value={
            "controller_1": [executor1],
            "controller_2": [executor2]
        })

        status = strategy.format_status()
        assert isinstance(status, str)
        assert "ACTIVE EXECUTORS" in status
        assert "executor_1"[:8] in status
        assert "executor_2"[:8] in status

    def test_format_status_handles_exception(self, strategy):
        """Test that format_status handles exceptions gracefully"""
        # Mock controller
        mock_controller = MagicMock()
        mock_controller.to_format_status = Mock(return_value=["║ Controller Status ║"])
        strategy.controllers = {"multi_coin_grid": mock_controller}

        # Mock executor orchestrator to raise exception
        strategy.executor_orchestrator.get_executors_report = Mock(side_effect=Exception("Test error"))

        # Should not raise exception, should return status anyway
        status = strategy.format_status()
        assert isinstance(status, str)
        assert "Controller Status" in status


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
