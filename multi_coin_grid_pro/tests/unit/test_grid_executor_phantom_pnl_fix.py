"""
Unit tests for GridExecutor phantom PnL fixes.

Tests two critical safety fixes:
1. NO_FILL_TIMEOUT suppression when position_size_base > 0 (fill event missed)
2. start_forced_close no longer overrides position_size_base from exchange balance
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

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

pytestmark = pytest.mark.asyncio


class TestPhantomPnlFixes:
    """Tests for the NO_FILL_TIMEOUT suppression and balance override removal."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("100.0"))
        connector.get_balance = Mock(return_value=Decimal("100.0"))
        connector.get_price = Mock(return_value=Decimal("0.42"))
        connector.trading_rules = {
            "TIA-USD": TradingRule(
                trading_pair="TIA-USD",
                min_order_size=Decimal("1.0"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.0001"),
                min_base_amount_increment=Decimal("0.0001"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 3000.0  # Well past any timeout
        strategy.cancel = Mock()
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_phantom",
            connector_name="kraken",
            trading_pair="TIA-USD",
            side=TradeType.BUY,
            total_amount_quote=Decimal("45"),
            start_price=Decimal("0.42"),
            end_price=Decimal("0.43"),
            limit_price=Decimal("0.40"),
            min_spread_between_orders=Decimal("0.007"),
            min_order_amount_quote=Decimal("15"),
            max_open_orders=3,
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.03"),
                take_profit=Decimal("0.05"),
                time_limit=3600,
                time_limit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
            ),
            custom_info={
                "no_fill_timeout_sec": 1800,
                "no_progress_timeout_sec": 2700,
            },
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with (
            patch(
                "hummingbot.strategy_v2.executors.grid_executor"
                ".grid_executor.GridExecutor.update_metrics"
            ),
            patch(
                "hummingbot.strategy_v2.executors.grid_executor"
                ".grid_executor.GridExecutor.update_position_metrics"
            ),
            patch.object(
                GridExecutor, "get_price", return_value=Decimal("0.42")
            ),
        ):
            executor = GridExecutor(
                strategy=mock_strategy,
                config=grid_config,
                update_interval=1.0,
            )
            executor.connectors = {"kraken": mock_connector}
            executor.trading_rules = mock_connector.trading_rules["TIA-USD"]
            executor.mid_price = Decimal("0.42")
            executor.current_close_quote = Decimal("0.43")
            executor.close_order_side = TradeType.SELL
            # Set to RUNNING so timeout checks don't exit early
            from hummingbot.strategy_v2.models.base import RunnableStatus
            executor._status = RunnableStatus.RUNNING
            return executor

    # ── Fix 1: NO_FILL_TIMEOUT suppressed when position_size_base > 0 ───

    async def test_no_fill_timeout_suppressed_when_has_inventory(self, executor):
        """
        If _last_fill_timestamp is None but position_size_base > 0,
        NO_FILL_TIMEOUT must NOT trigger — the fill event was missed.
        """
        executor._last_fill_timestamp = None
        # Make age exceed no_fill_timeout (1800s)
        executor._start_timestamp = executor._strategy.current_timestamp - 2000
        # Simulate grid level fill detected by update_position_metrics
        executor.position_size_base = Decimal("53.66")

        # _check_timeout_conditions reads position via update_position_metrics
        # which we mock to keep the already-set value
        with patch.object(executor, "update_position_metrics"):
            result = executor._check_timeout_triggers()

        assert result is False, (
            "Should return False (suppressed), allowing re-eval"
        )
        # _last_fill_timestamp should be patched to creation time
        assert executor._last_fill_timestamp == executor.config.timestamp
        # Should NOT have set close_type to NO_FILL_TIMEOUT
        assert executor.close_type is None

    async def test_no_fill_timeout_fires_when_no_inventory(self, executor):
        """
        If _last_fill_timestamp is None AND position_size_base is 0,
        NO_FILL_TIMEOUT should fire normally and shut down.
        """
        executor._last_fill_timestamp = None
        executor._start_timestamp = executor._strategy.current_timestamp - 2000
        executor.position_size_base = Decimal("0")

        with patch.object(executor, "update_position_metrics"), \
                patch.object(executor, "cancel_open_orders"):
            result = executor._check_timeout_triggers()

        assert result is True, "Should fire NO_FILL_TIMEOUT"
        from hummingbot.strategy_v2.models.executors import CloseType
        assert executor.close_type == CloseType.NO_FILL_TIMEOUT

    async def test_no_fill_timeout_not_triggered_when_fills_exist(self, executor):
        """
        Normal case: _last_fill_timestamp is set, no timeout triggered.
        """
        executor._start_timestamp = executor._strategy.current_timestamp - 2000
        executor._last_fill_timestamp = executor._strategy.current_timestamp - 100
        executor.position_size_base = Decimal("53.66")

        executor._check_timeout_triggers()

        # Should not trigger NO_FILL_TIMEOUT (timestamp is set)
        assert executor.close_type is None

    # ── Fix 2: exchange balance override removed ──────────────────────────

    async def test_start_forced_close_does_not_override_from_exchange_balance(
        self, executor, mock_connector
    ):
        """
        start_forced_close must NOT set position_size_base from exchange balance.
        Even if exchange shows 53.66 TIA but tracked position is 0, we must not
        sell coins from other executors/sessions.
        """
        executor.position_size_base = Decimal("0")
        mock_connector.get_available_balance.return_value = Decimal("53.66")

        from hummingbot.strategy_v2.models.executors import CloseType

        with (
            patch.object(executor, "update_position_metrics"),
            patch.object(executor, "update_metrics"),
        ):
            executor.start_forced_close(CloseType.NO_FILL_TIMEOUT)

        # position_size_base must still be 0 — NOT overridden to 53.66
        assert executor.position_size_base == Decimal("0"), (
            "Must not override position_size_base from exchange balance"
        )

    async def test_start_forced_close_preserves_tracked_position(
        self, executor, mock_connector
    ):
        """
        When position_size_base is already correct (from grid level fills),
        start_forced_close should keep it as-is.
        """
        executor.position_size_base = Decimal("53.66")
        mock_connector.get_available_balance.return_value = Decimal("53.66")

        from hummingbot.strategy_v2.models.executors import CloseType

        with (
            patch.object(executor, "update_position_metrics"),
            patch.object(executor, "update_metrics"),
        ):
            executor.start_forced_close(CloseType.NO_FILL_TIMEOUT)

        assert executor.position_size_base == Decimal("53.66")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
