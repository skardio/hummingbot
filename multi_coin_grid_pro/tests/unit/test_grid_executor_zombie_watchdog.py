"""
Unit tests for GridExecutor zombie close order watchdog.

Tests the fix for orphaned coins caused by close orders that are placed
locally but never confirmed by the exchange (DOGE scenario).
"""

from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import pytest

from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, GridLevel, GridLevelStates
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors import CloseType, TrackedOrder


class TestZombieCloseOrderWatchdog:
    """Test the zombie close order watchdog that resets unconfirmed orders."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("100.0"))
        connector.get_balance = Mock(return_value=Decimal("100.0"))
        connector.get_price = Mock(return_value=Decimal("1.5"))
        connector.trading_rules = {
            "DOGE-USD": TradingRule(
                trading_pair="DOGE-USD",
                min_order_size=Decimal("10.0"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.00001"),
                min_base_amount_increment=Decimal("1")
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1000.0
        strategy.cancel = Mock()
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_zombie",
            connector_name="kraken",
            trading_pair="DOGE-USD",
            side=TradeType.BUY,
            total_amount_quote=Decimal("100"),
            num_levels=2,
            start_price=Decimal("0.10"),
            end_price=Decimal("0.12"),
            limit_price=Decimal("0.09"),
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
        with patch.object(GridExecutor, "get_trading_rules", return_value=TradingRule(
            trading_pair="DOGE-USD",
            min_order_size=Decimal("10.0"),
            min_notional_size=Decimal("5.0"),
            min_price_increment=Decimal("0.00001"),
            min_base_amount_increment=Decimal("1")
        )), patch.object(GridExecutor, 'get_price', return_value=Decimal("0.11")), \
                patch.object(GridExecutor, 'update_metrics'), \
                patch.object(GridExecutor, 'update_position_metrics'):
            executor = GridExecutor(mock_strategy, grid_config)
            executor._strategy = mock_strategy
            executor.connectors = {"kraken": mock_connector}
            return executor

    def _make_zombie_close_order(self, order_id="zombie_123"):
        """Create a TrackedOrder with no InFlightOrder (zombie)."""
        tracked = TrackedOrder(order_id=order_id)
        assert tracked.order is None  # Confirms it's a zombie
        return tracked

    def _make_confirmed_close_order(self, order_id="confirmed_456"):
        """Create a TrackedOrder with InFlightOrder (confirmed)."""
        tracked = TrackedOrder(order_id=order_id)
        tracked.order = MagicMock()  # InFlightOrder exists
        return tracked

    def _make_level_with_close_order(self, tracked_order):
        """Create a GridLevel in CLOSE_ORDER_PLACED state."""
        level = MagicMock(spec=GridLevel)
        level.active_close_order = tracked_order
        return level

    # ===== Test: Zombie detected and reset after timeout =====

    def test_zombie_order_reset_after_timeout(self, executor):
        """Zombie close order (no InFlightOrder) is reset after watchdog timeout."""
        zombie = self._make_zombie_close_order("zombie_001")
        level = self._make_level_with_close_order(zombie)

        # Simulate: order placed at t=1000, now it's t=1070 (70s > 60s threshold)
        executor._close_order_local_ts["zombie_001"] = 1000.0
        executor._strategy.current_timestamp = 1070.0
        executor.levels_by_state = {
            GridLevelStates.CLOSE_ORDER_PLACED: [level],
            GridLevelStates.OPEN_ORDER_PLACED: [],
            GridLevelStates.OPEN_ORDER_FILLED: [],
            GridLevelStates.NOT_ACTIVE: [],
            GridLevelStates.COMPLETE: [],
        }

        executor._check_zombie_close_orders()

        # Level should be reset
        level.reset_close_order.assert_called_once()
        assert "zombie_001" in executor._failed_orders
        assert "zombie_001" not in executor._close_order_local_ts

    # ===== Test: Zombie NOT reset within timeout window =====

    def test_zombie_order_not_reset_within_timeout(self, executor):
        """Zombie close order within timeout window is NOT reset — exchange may still respond."""
        zombie = self._make_zombie_close_order("zombie_002")
        level = self._make_level_with_close_order(zombie)

        # Order placed 30s ago (within 60s threshold)
        executor._close_order_local_ts["zombie_002"] = 1000.0
        executor._strategy.current_timestamp = 1030.0
        executor.levels_by_state = {
            GridLevelStates.CLOSE_ORDER_PLACED: [level],
            GridLevelStates.OPEN_ORDER_PLACED: [],
            GridLevelStates.OPEN_ORDER_FILLED: [],
            GridLevelStates.NOT_ACTIVE: [],
            GridLevelStates.COMPLETE: [],
        }

        executor._check_zombie_close_orders()

        # Should NOT be reset
        level.reset_close_order.assert_not_called()
        assert "zombie_002" not in executor._failed_orders

    # ===== Test: Confirmed order is NOT reset =====

    def test_confirmed_order_not_reset(self, executor):
        """Confirmed close order (has InFlightOrder) is never reset by watchdog."""
        confirmed = self._make_confirmed_close_order("confirmed_003")
        level = self._make_level_with_close_order(confirmed)

        # Even with old timestamp
        executor._close_order_local_ts["confirmed_003"] = 500.0
        executor._strategy.current_timestamp = 2000.0
        executor.levels_by_state = {
            GridLevelStates.CLOSE_ORDER_PLACED: [level],
            GridLevelStates.OPEN_ORDER_PLACED: [],
            GridLevelStates.OPEN_ORDER_FILLED: [],
            GridLevelStates.NOT_ACTIVE: [],
            GridLevelStates.COMPLETE: [],
        }

        executor._check_zombie_close_orders()

        level.reset_close_order.assert_not_called()
        assert "confirmed_003" not in executor._failed_orders
        # Tracking should be cleaned up for confirmed orders
        assert "confirmed_003" not in executor._close_order_local_ts

    # ===== Test: Unknown order (no tracking entry) starts being tracked =====

    def test_unknown_order_starts_tracking(self, executor):
        """Order without tracking entry gets registered for tracking (not immediately reset)."""
        zombie = self._make_zombie_close_order("unknown_004")
        level = self._make_level_with_close_order(zombie)

        # No entry in _close_order_local_ts
        executor._strategy.current_timestamp = 2000.0
        executor.levels_by_state = {
            GridLevelStates.CLOSE_ORDER_PLACED: [level],
            GridLevelStates.OPEN_ORDER_PLACED: [],
            GridLevelStates.OPEN_ORDER_FILLED: [],
            GridLevelStates.NOT_ACTIVE: [],
            GridLevelStates.COMPLETE: [],
        }

        executor._check_zombie_close_orders()

        # Should NOT reset — just start tracking
        level.reset_close_order.assert_not_called()
        assert executor._close_order_local_ts["unknown_004"] == 2000.0

    # ===== Test: Multiple levels — only zombie is reset =====

    def test_mixed_levels_only_zombie_reset(self, executor):
        """With mix of zombie and confirmed orders, only the zombie is reset."""
        zombie = self._make_zombie_close_order("zombie_005")
        confirmed = self._make_confirmed_close_order("confirmed_006")

        level_z = self._make_level_with_close_order(zombie)
        level_c = self._make_level_with_close_order(confirmed)

        executor._close_order_local_ts["zombie_005"] = 900.0
        executor._close_order_local_ts["confirmed_006"] = 900.0
        executor._strategy.current_timestamp = 1000.0  # 100s > 60s
        executor.levels_by_state = {
            GridLevelStates.CLOSE_ORDER_PLACED: [level_z, level_c],
            GridLevelStates.OPEN_ORDER_PLACED: [],
            GridLevelStates.OPEN_ORDER_FILLED: [],
            GridLevelStates.NOT_ACTIVE: [],
            GridLevelStates.COMPLETE: [],
        }

        executor._check_zombie_close_orders()

        level_z.reset_close_order.assert_called_once()
        level_c.reset_close_order.assert_not_called()

    # ===== Test: Level with None active_close_order is skipped =====

    def test_none_active_close_order_skipped(self, executor):
        """Level with None active_close_order doesn't crash the watchdog."""
        level = MagicMock(spec=GridLevel)
        level.active_close_order = None

        executor._strategy.current_timestamp = 2000.0
        executor.levels_by_state = {
            GridLevelStates.CLOSE_ORDER_PLACED: [level],
            GridLevelStates.OPEN_ORDER_PLACED: [],
            GridLevelStates.OPEN_ORDER_FILLED: [],
            GridLevelStates.NOT_ACTIVE: [],
            GridLevelStates.COMPLETE: [],
        }

        # Should not crash
        executor._check_zombie_close_orders()
        level.reset_close_order.assert_not_called()


class TestOrphanRiskAlert:
    """Test the ORPHAN_RISK alert when executor terminates with inventory."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("100.0"))
        connector.get_balance = Mock(return_value=Decimal("100.0"))
        connector.trading_rules = {
            "PENGU-USD": TradingRule(
                trading_pair="PENGU-USD",
                min_order_size=Decimal("100.0"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.00001"),
                min_base_amount_increment=Decimal("1")
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1000.0
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_orphan",
            connector_name="kraken",
            trading_pair="PENGU-USD",
            side=TradeType.BUY,
            total_amount_quote=Decimal("100"),
            num_levels=2,
            start_price=Decimal("0.007"),
            end_price=Decimal("0.008"),
            limit_price=Decimal("0.006"),
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
        with patch.object(GridExecutor, "get_trading_rules", return_value=TradingRule(
            trading_pair="PENGU-USD",
            min_order_size=Decimal("100.0"),
            min_notional_size=Decimal("5.0"),
            min_price_increment=Decimal("0.00001"),
            min_base_amount_increment=Decimal("1")
        )), patch.object(GridExecutor, 'get_price', return_value=Decimal("0.0075")), \
                patch.object(GridExecutor, 'update_metrics'), \
                patch.object(GridExecutor, 'update_position_metrics'):
            executor = GridExecutor(mock_strategy, grid_config)
            executor._strategy = mock_strategy
            executor.connectors = {"kraken": mock_connector}
            return executor

    def test_orphan_risk_logged_when_inventory_remains(self, executor):
        """ORPHAN_RISK is logged when executor terminates with inventory."""
        executor.position_size_base = Decimal("10251")
        executor.mid_price = Decimal("0.0072")
        executor.close_type = CloseType.FAILED
        executor._early_stop_reason = None

        mock_logger = MagicMock()
        with patch.object(executor, "update_position_metrics"), \
             patch.object(type(executor), "logger", return_value=mock_logger):
            executor._log_orphan_risk_if_inventory()

        mock_logger.error.assert_called_once()
        log_msg = mock_logger.error.call_args[0][0]
        assert "ORPHAN_RISK" in log_msg
        assert "PENGU-USD" in log_msg

    def test_no_orphan_risk_when_no_inventory(self, executor):
        """No ORPHAN_RISK logged when position is fully closed."""
        executor.position_size_base = Decimal("0")
        executor.mid_price = Decimal("0.0072")

        mock_logger = MagicMock()
        with patch.object(executor, "update_position_metrics"), \
             patch.object(type(executor), "logger", return_value=mock_logger):
            executor._log_orphan_risk_if_inventory()

        mock_logger.error.assert_not_called()

    def test_orphan_risk_on_max_retries(self, executor):
        """evaluate_max_retries attempts forced close first, then logs orphan risk on second call."""
        executor._current_retries = 100
        executor._max_retries = 10
        executor.position_size_base = Decimal("821")
        executor.mid_price = Decimal("0.094")

        mock_logger = MagicMock()
        with patch.object(executor, "update_position_metrics"), \
             patch.object(type(executor), "logger", return_value=mock_logger), \
             patch.object(executor, "start_forced_close") as mock_forced_close, \
             patch.object(executor, "stop"):
            # First call: should attempt forced close instead of orphan risk
            executor.evaluate_max_retries()
            mock_forced_close.assert_called_once()
            mock_logger.error.assert_not_called()

            # Second call: market retry already attempted, should log ORPHAN_RISK
            executor.evaluate_max_retries()

        mock_logger.error.assert_called()
        logged_errors = [call[0][0] for call in mock_logger.error.call_args_list]
        assert any("ORPHAN_RISK" in msg for msg in logged_errors)


class TestAdjustAndPlaceCloseOrderTracking:
    """Test that close order placement timestamps are tracked."""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("1000.0"))
        connector.get_balance = Mock(return_value=Decimal("1000.0"))
        connector.get_order_size_quantum = Mock(return_value=Decimal("1"))
        connector.trading_rules = {
            "DOGE-USD": TradingRule(
                trading_pair="DOGE-USD",
                min_order_size=Decimal("10.0"),
                min_notional_size=Decimal("5.0"),
                min_price_increment=Decimal("0.00001"),
                min_base_amount_increment=Decimal("1")
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 5000.0
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_tracking",
            connector_name="kraken",
            trading_pair="DOGE-USD",
            side=TradeType.BUY,
            total_amount_quote=Decimal("100"),
            num_levels=2,
            start_price=Decimal("0.10"),
            end_price=Decimal("0.12"),
            limit_price=Decimal("0.09"),
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
        with patch.object(GridExecutor, "get_trading_rules", return_value=TradingRule(
            trading_pair="DOGE-USD",
            min_order_size=Decimal("10.0"),
            min_notional_size=Decimal("5.0"),
            min_price_increment=Decimal("0.00001"),
            min_base_amount_increment=Decimal("1")
        )), patch.object(GridExecutor, 'get_price', return_value=Decimal("0.11")), \
                patch.object(GridExecutor, 'update_metrics'), \
                patch.object(GridExecutor, 'update_position_metrics'):
            executor = GridExecutor(mock_strategy, grid_config)
            executor._strategy = mock_strategy
            executor.connectors = {"kraken": mock_connector}
            return executor

    def test_close_order_timestamp_tracked_on_place(self, executor):
        """When adjust_and_place_close_order succeeds, timestamp is recorded."""
        level = MagicMock(spec=GridLevel)
        level.price = Decimal("0.10")
        level.take_profit = Decimal("0.02")
        level.side = TradeType.BUY
        level.active_close_order = None

        # Mock the order placement to return an order_id
        with patch.object(executor, "_get_close_order_candidate") as mock_candidate, \
             patch.object(executor, "adjust_order_candidates"), \
             patch.object(executor, "_validated_place_order", return_value="order_abc"):
            mock_oc = MagicMock()
            mock_oc.amount = Decimal("100")
            mock_oc.price = Decimal("0.102")
            mock_oc.order_side = TradeType.SELL
            mock_candidate.return_value = mock_oc

            executor.position_size_base = Decimal("100")
            executor.adjust_and_place_close_order(level)

        # Timestamp should be tracked
        assert "order_abc" in executor._close_order_local_ts
        assert executor._close_order_local_ts["order_abc"] == 5000.0
