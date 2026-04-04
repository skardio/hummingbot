"""
Unit tests for insufficient balance fix (Bitget 43012).

Tests:
1. _cap_sell_to_available() — caps sell qty to available balance
2. _fees_in_base_token() — returns True for Bitget, False for Kraken
3. Integration: graceful/aggressive close honour the cap
"""

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, GridLevelStates
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

pytestmark = pytest.mark.asyncio


class TestCapSellToAvailable:
    """Tests for GridExecutor._cap_sell_to_available()"""

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "bitget"
        connector.get_available_balance = Mock(return_value=Decimal("461.538"))
        connector.get_balance = Mock(return_value=Decimal("461.538"))
        connector.get_price = Mock(return_value=Decimal("0.25"))
        connector.quantize_order_amount = lambda pair, amt: amt
        connector.quantize_order_price = lambda pair, px: px
        connector.trading_rules = {
            "FET-USDT": TradingRule(
                trading_pair="FET-USDT",
                min_order_size=Decimal("1"),
                min_notional_size=Decimal("5"),
                min_price_increment=Decimal("0.0001"),
                min_base_amount_increment=Decimal("0.001"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1000.0
        strategy.cancel = Mock()
        strategy.connectors = {"bitget": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_exec",
            connector_name="bitget",
            trading_pair="FET-USDT",
            side=TradeType.BUY,
            total_amount_quote=Decimal("120"),
            num_levels=3,
            start_price=Decimal("0.24"),
            end_price=Decimal("0.26"),
            limit_price=Decimal("0.23"),
            min_spread_between_orders=Decimal("0.001"),
            min_order_amount_quote=Decimal("5"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.08"),
                take_profit=Decimal("0.02"),
                time_limit=3600,
                time_limit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
            ),
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_metrics"
        ), patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_position_metrics"
        ), patch.object(
            GridExecutor, "get_price", return_value=Decimal("0.25")
        ):
            executor = GridExecutor(
                strategy=mock_strategy,
                config=grid_config,
                update_interval=1.0,
            )
            executor.connectors = {"bitget": mock_connector}
            executor.trading_rules = mock_connector.trading_rules["FET-USDT"]
            executor.close_order_side = TradeType.SELL
            executor.mid_price = Decimal("0.25")
            return executor

    # --- _cap_sell_to_available tests ---

    async def test_caps_sell_when_available_less_than_inventory(self, executor, mock_connector):
        """Core bug: sell 462 FET but only 461.538 available due to fees."""
        mock_connector.get_available_balance.return_value = Decimal("461.538")
        result = executor._cap_sell_to_available(Decimal("462"))
        assert result == Decimal("461.538")

    async def test_no_cap_when_available_exceeds_inventory(self, executor, mock_connector):
        """No capping needed when balance is sufficient."""
        mock_connector.get_available_balance.return_value = Decimal("500")
        result = executor._cap_sell_to_available(Decimal("462"))
        assert result == Decimal("462")

    async def test_no_cap_when_available_equals_inventory(self, executor, mock_connector):
        """Exact match — no capping."""
        mock_connector.get_available_balance.return_value = Decimal("462")
        result = executor._cap_sell_to_available(Decimal("462"))
        assert result == Decimal("462")

    async def test_returns_inventory_when_available_is_zero(self, executor, mock_connector):
        """Zero available should not cap (0 is not > 0)."""
        mock_connector.get_available_balance.return_value = Decimal("0")
        result = executor._cap_sell_to_available(Decimal("462"))
        assert result == Decimal("462")

    async def test_returns_inventory_on_connector_error(self, executor, mock_connector):
        """Graceful fallback on connector error."""
        mock_connector.get_available_balance.side_effect = Exception("API error")
        result = executor._cap_sell_to_available(Decimal("462"))
        assert result == Decimal("462")

    async def test_returns_inventory_when_connector_missing(self, executor):
        """Graceful fallback when connector is None."""
        executor.connectors = {}
        result = executor._cap_sell_to_available(Decimal("462"))
        assert result == Decimal("462")

    async def test_small_fee_gap(self, executor, mock_connector):
        """Tiny fee difference (e.g. 0.001 FET) still gets capped."""
        mock_connector.get_available_balance.return_value = Decimal("41.999")
        result = executor._cap_sell_to_available(Decimal("42"))
        assert result == Decimal("41.999")


class TestFeesInBaseToken:
    """Tests for controller._fees_in_base_token()"""

    def _make_controller(self, connector_name: str):
        """Build a minimal mock controller with _fees_in_base_token."""
        # Import the real method and bind it to a mock
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        controller = MagicMock(spec=MultiCoinGridController)
        controller.config = MagicMock()
        controller.config.connector_name = connector_name
        # Bind the real method
        controller._fees_in_base_token = (
            MultiCoinGridController._fees_in_base_token.__get__(controller)
        )
        return controller

    def test_bitget_returns_true(self):
        ctrl = self._make_controller("bitget")
        assert ctrl._fees_in_base_token() is True

    def test_bitget_spot_returns_true(self):
        ctrl = self._make_controller("bitget_spot")
        assert ctrl._fees_in_base_token() is True

    def test_kraken_returns_false(self):
        ctrl = self._make_controller("kraken")
        assert ctrl._fees_in_base_token() is False

    def test_kraken_exchange_returns_false(self):
        ctrl = self._make_controller("kraken_exchange")
        assert ctrl._fees_in_base_token() is False

    def test_case_insensitive(self):
        ctrl = self._make_controller("BITGET")
        assert ctrl._fees_in_base_token() is True

    def test_binance_returns_false(self):
        ctrl = self._make_controller("binance")
        assert ctrl._fees_in_base_token() is False


class TestGracefulCloseUsesFullInventory:
    """Verify graceful close uses full tracked inventory, NOT capped balance.

    This prevents orphaned coins when cancel-settle race conditions cause
    get_available_balance() to report stale (lower) values right after
    grid sell orders are cancelled.
    """

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "bitget"
        # Simulate fee-reduced balance: bought 462 FET, 0.462 in fees
        connector.get_available_balance = Mock(return_value=Decimal("461.538"))
        connector.get_balance = Mock(return_value=Decimal("461.538"))
        connector.get_price = Mock(return_value=Decimal("0.25"))
        connector.quantize_order_amount = lambda pair, amt: amt
        connector.quantize_order_price = lambda pair, px: px
        connector.trading_rules = {
            "FET-USDT": TradingRule(
                trading_pair="FET-USDT",
                min_order_size=Decimal("1"),
                min_notional_size=Decimal("5"),
                min_price_increment=Decimal("0.0001"),
                min_base_amount_increment=Decimal("0.001"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1000.0
        strategy.cancel = Mock()
        strategy.connectors = {"bitget": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_exec",
            connector_name="bitget",
            trading_pair="FET-USDT",
            side=TradeType.BUY,
            total_amount_quote=Decimal("120"),
            num_levels=11,
            start_price=Decimal("0.24"),
            end_price=Decimal("0.28"),
            limit_price=Decimal("0.23"),
            min_spread_between_orders=Decimal("0.001"),
            min_order_amount_quote=Decimal("5"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.08"),
                take_profit=Decimal("0.02"),
                time_limit=3600,
                time_limit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
            ),
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_metrics"
        ), patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_position_metrics"
        ), patch.object(
            GridExecutor, "get_price", return_value=Decimal("0.25")
        ):
            executor = GridExecutor(
                strategy=mock_strategy,
                config=grid_config,
                update_interval=1.0,
            )
            executor.connectors = {"bitget": mock_connector}
            executor.trading_rules = mock_connector.trading_rules["FET-USDT"]
            executor.close_order_side = TradeType.SELL
            executor.mid_price = Decimal("0.25")
            executor.current_close_quote = Decimal("0.26")
            return executor

    def test_graceful_close_uses_full_inventory(self, executor, mock_connector):
        """Graceful close should use full 462 FET, NOT cap to 461.538.

        Race condition fix: grid sell orders were just cancelled but the
        exchange may not have settled them yet, making
        get_available_balance() return a stale (lower) value.  Graceful
        close must trust the tracked inventory (position_size_base) and
        attempt to sell the full amount.  If the exchange rejects the
        order, the aggressive phase handles it with a balance-wait loop.
        """
        executor.place_order = Mock(return_value="order_graceful")

        # Pass inventory larger than available balance
        executor._place_graceful_close_orders(Decimal("462"))

        # Verify place_order was called with FULL inventory, not capped
        assert executor.place_order.called, "Should have placed a graceful order"
        call_args = executor.place_order.call_args
        placed_amount = call_args[1].get("amount") or call_args[0][4]
        assert placed_amount == Decimal("462"), (
            f"Should use full tracked inventory, not cap to available balance. Got {placed_amount}"
        )

    async def test_aggressive_close_caps_inventory(self, executor, mock_connector):
        """Aggressive close should cap 462 → 461.538 FET via _determine_close_order_amount."""
        executor.place_order = Mock(return_value="order_aggressive")
        executor._refresh_connector_balances = AsyncMock()
        executor._sleep = AsyncMock()

        await executor._place_aggressive_close_orders(Decimal("462"))

        if executor.place_order.called:
            call_args = executor.place_order.call_args
            placed_amount = call_args[1].get("amount") or call_args[0][4]
            assert placed_amount <= Decimal("461.538"), (
                f"Should cap to available balance, got {placed_amount}"
            )

    def test_graceful_close_zero_inventory_returns_early(self, executor, mock_connector):
        """If tracked inventory is 0, graceful close should return early."""
        mock_connector.get_available_balance.return_value = Decimal("0")
        executor.place_order = Mock(return_value="order_graceful")

        # Zero inventory → should return early without placing order
        executor._place_graceful_close_orders(Decimal("0"))
        executor.place_order.assert_not_called()


class TestCancelSettleRaceCondition:
    """Tests for the cancel-settle race condition fix (TRADOOR orphan bug).

    Root cause: _cancel_non_essential_orders() fires cancel for grid SELL
    orders, then _place_graceful_close_orders() immediately calls
    _cap_sell_to_available() which queries get_available_balance().  The
    exchange hasn't settled the cancel yet, so the balance is still locked
    → graceful close uses a capped (smaller) amount → remainder is orphaned.

    Fix: _place_graceful_close_orders no longer calls _cap_sell_to_available.
    It uses the full tracked inventory (position_size_base).  If the exchange
    rejects the order, the aggressive phase handles it.
    """

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "bitget"
        # Simulate stale balance: 32.82 available, but full position is 36.46
        # The missing 3.64 is locked by a grid SELL order that was just cancelled
        # but not yet settled on the exchange.
        connector.get_available_balance = Mock(return_value=Decimal("32.82"))
        connector.get_balance = Mock(return_value=Decimal("36.46"))
        connector.get_price = Mock(return_value=Decimal("2.90"))
        connector.quantize_order_amount = lambda pair, amt: amt
        connector.quantize_order_price = lambda pair, px: px
        connector.trading_rules = {
            "TRADOOR-USDT": TradingRule(
                trading_pair="TRADOOR-USDT",
                min_order_size=Decimal("0.1"),
                min_notional_size=Decimal("1"),
                min_price_increment=Decimal("0.01"),
                min_base_amount_increment=Decimal("0.01"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1000.0
        strategy.cancel = Mock()
        strategy.connectors = {"bitget": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_tradoor",
            connector_name="bitget",
            trading_pair="TRADOOR-USDT",
            side=TradeType.BUY,
            total_amount_quote=Decimal("100"),
            num_levels=5,
            start_price=Decimal("2.50"),
            end_price=Decimal("3.20"),
            limit_price=Decimal("2.40"),
            min_spread_between_orders=Decimal("0.001"),
            min_order_amount_quote=Decimal("5"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.08"),
                take_profit=Decimal("0.02"),
                time_limit=3600,
                time_limit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
            ),
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_metrics"
        ), patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_position_metrics"
        ), patch.object(
            GridExecutor, "get_price", return_value=Decimal("2.90")
        ):
            executor = GridExecutor(
                strategy=mock_strategy,
                config=grid_config,
                update_interval=1.0,
            )
            executor.connectors = {"bitget": mock_connector}
            executor.trading_rules = mock_connector.trading_rules["TRADOOR-USDT"]
            executor.close_order_side = TradeType.SELL
            executor.mid_price = Decimal("2.90")
            executor.current_close_quote = Decimal("2.91")
            return executor

    def test_graceful_close_ignores_stale_balance(self, executor, mock_connector):
        """Graceful close must use full 36.46, NOT stale available 32.82.

        This reproduces the TRADOOR orphan: cancel fires but hasn't settled,
        so get_available_balance() returns 32.82 instead of 36.46.  The old
        code would cap to 32.82 and orphan 3.64 TRADOOR.
        """
        executor.place_order = Mock(return_value="order_graceful_tradoor")

        # Full tracked inventory: 36.46 (what we should sell)
        # Stale available balance: 32.82 (what the exchange reports)
        executor._place_graceful_close_orders(Decimal("36.46"))

        assert executor.place_order.called, "Should have placed a graceful order"
        call_args = executor.place_order.call_args
        placed_amount = call_args[1].get("amount") or call_args[0][4]
        # Must be the FULL inventory amount, not capped to 32.82
        assert placed_amount == Decimal("36.46"), (
            f"Expected full inventory 36.46, but got {placed_amount}. "
            f"Race condition: graceful close is still capping to stale available balance!"
        )

    def test_cap_sell_not_called_in_graceful(self, executor, mock_connector):
        """_cap_sell_to_available must NOT be called during graceful close."""
        executor.place_order = Mock(return_value="order_graceful")
        with patch.object(executor, '_cap_sell_to_available') as mock_cap:
            executor._place_graceful_close_orders(Decimal("36.46"))
            mock_cap.assert_not_called()


class TestAggressiveCloseRaceCondition:
    """Tests for the aggressive close race condition fix.

    Root cause: graceful close's LIMIT SELL locks the base balance on the
    exchange.  When the grace period expires, the bot cancels the limit order
    and immediately tries a MARKET SELL, but the exchange still reports the
    balance as locked → 'Insufficient funds'.

    Fix: _place_aggressive_close_orders now calls _determine_close_order_amount
    which retries (up to ~5 s) waiting for the balance to unlock.
    """

    @pytest.fixture
    def executor(self):
        """Create a GridExecutor with mocked internals for Kraken ADI-USD."""
        mock_connector = MagicMock()
        mock_connector.name = "kraken"
        mock_connector.get_available_balance = Mock(return_value=Decimal("0"))
        mock_connector.get_balance = Mock(return_value=Decimal("36.51"))
        mock_connector.quantize_order_amount = lambda pair, amt: amt
        mock_connector.quantize_order_price = lambda pair, px: px
        mock_connector.trading_rules = {
            "ADI-USD": TradingRule(
                trading_pair="ADI-USD",
                min_order_size=Decimal("1"),
                min_order_value=Decimal("0.5"),
                min_base_amount_increment=Decimal("0.001"),
                min_price_increment=Decimal("0.001"),
            )
        }

        config = GridExecutorConfig(
            id="test-race",
            timestamp=1000,
            connector_name="kraken",
            trading_pair="ADI-USD",
            triple_barrier_config=TripleBarrierConfig(),
            start_price=Decimal("3.5"),
            end_price=Decimal("4.5"),
            limit_price=Decimal("3.4"),
            total_amount_quote=Decimal("150"),
            n_levels=4,
            min_order_amount=Decimal("1"),
        )

        with patch.object(GridExecutor, "__init__", lambda self, *a, **kw: None):
            executor = GridExecutor()
        executor.config = config
        executor._strategy = MagicMock()
        executor._strategy.current_timestamp = 1200
        executor.connectors = {"kraken": mock_connector}
        executor.trading_rules = mock_connector.trading_rules["ADI-USD"]
        executor.close_order_side = TradeType.SELL
        executor.mid_price = Decimal("4.0")
        executor.current_close_quote = Decimal("4.0")
        executor._close_balance_max_retries = 5
        executor._close_balance_retry_interval = 1.0
        return executor, mock_connector

    async def test_balance_unlocks_after_retry(self, executor):
        """Balance locked initially, unlocks on 3rd attempt → order placed."""
        ex, mock_conn = executor
        call_count = 0

        def available_balance_side_effect(asset):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return Decimal("0")  # Locked
            return Decimal("36.51")  # Unlocked

        mock_conn.get_available_balance.side_effect = available_balance_side_effect
        mock_conn.get_balance.return_value = Decimal("36.51")  # Total balance present
        ex.place_order = Mock(return_value="order_aggressive")
        ex._refresh_connector_balances = AsyncMock()
        ex._sleep = AsyncMock()
        ex._coerce_to_decimal = lambda v: Decimal(str(v))
        ex._safe_get_total_balance = lambda conn, asset: Decimal("36.51")
        ex._notify_manual_close_required = Mock()

        await ex._place_aggressive_close_orders(Decimal("36.51"))

        assert ex.place_order.called, "Should have placed aggressive order after balance unlocked"
        call_args = ex.place_order.call_args
        placed_amount = call_args[1].get("amount") or call_args[0][4]
        assert placed_amount == Decimal("36.51")

    async def test_balance_never_unlocks_falls_back_to_cap(self, executor):
        """Balance stays locked, _determine_close_order_amount returns None → fallback to _cap_sell_to_available."""
        ex, mock_conn = executor
        # Always return 0 available (locked)
        mock_conn.get_available_balance.return_value = Decimal("0")
        mock_conn.get_balance.return_value = Decimal("36.51")
        ex.place_order = Mock(return_value="order_aggressive")
        ex._refresh_connector_balances = AsyncMock()
        ex._sleep = AsyncMock()
        ex._coerce_to_decimal = lambda v: Decimal(str(v))
        ex._safe_get_total_balance = lambda conn, asset: Decimal("36.51")
        ex._notify_manual_close_required = Mock()
        ex._cap_sell_to_available = Mock(return_value=Decimal("0"))

        await ex._place_aggressive_close_orders(Decimal("36.51"))

        # _cap_sell_to_available was called as fallback
        ex._cap_sell_to_available.assert_called_once_with(Decimal("36.51"))
        # But since cap returned 0, no order placed
        ex.place_order.assert_not_called()

    async def test_partial_balance_unlocks(self, executor):
        """Only partial balance unlocks → order placed for partial amount."""
        ex, mock_conn = executor
        call_count = 0

        def available_balance_side_effect(asset):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return Decimal("0")
            return Decimal("20.0")  # Only partial unlocked

        mock_conn.get_available_balance.side_effect = available_balance_side_effect
        mock_conn.get_balance.return_value = Decimal("36.51")
        ex.place_order = Mock(return_value="order_aggressive")
        ex._refresh_connector_balances = AsyncMock()
        ex._sleep = AsyncMock()
        ex._coerce_to_decimal = lambda v: Decimal(str(v))
        ex._safe_get_total_balance = lambda conn, asset: Decimal("36.51")
        ex._notify_manual_close_required = Mock()

        await ex._place_aggressive_close_orders(Decimal("36.51"))

        assert ex.place_order.called, "Should place order for partial amount"
        call_args = ex.place_order.call_args
        placed_amount = call_args[1].get("amount") or call_args[0][4]
        assert placed_amount == Decimal("20.0"), f"Should place for partial balance, got {placed_amount}"

    async def test_check_unwind_phase_transition_is_async(self, executor):
        """_check_unwind_phase_transition awaits _place_aggressive_close_orders."""
        ex, mock_conn = executor
        ex._unwind_phase = "GRACEFUL"
        ex._unwind_started_ts = 1000  # 200s ago (> 120s grace)
        ex._unwind_close_reason = MagicMock()
        ex._unwind_close_reason.name = "NO_PROGRESS_TIMEOUT"
        ex.position_size_base = Decimal("36.51")
        ex.update_position_metrics = Mock()
        ex._cancel_graceful_close_orders = Mock()
        ex._cancel_remaining_grid_close_orders = Mock()
        ex._graceful_close_orders = set()
        ex._closing_in_progress = False
        ex._close_order_id = None

        # Mock _place_aggressive_close_orders as async
        ex._place_aggressive_close_orders = AsyncMock()

        await ex._check_unwind_phase_transition()

        assert ex._unwind_phase == "AGGRESSIVE"
        ex._place_aggressive_close_orders.assert_awaited_once_with(Decimal("36.51"))
        ex._cancel_remaining_grid_close_orders.assert_called_once()

    async def test_unwind_transition_cancels_grid_close_orders(self, executor):
        """Aggressive transition cancels grid close orders to free locked base tokens."""
        ex, mock_conn = executor
        ex._unwind_phase = "GRACEFUL"
        ex._unwind_started_ts = 1000
        ex._unwind_close_reason = MagicMock()
        ex._unwind_close_reason.name = "NO_PROGRESS_TIMEOUT"
        ex.position_size_base = Decimal("0.318202")
        ex.update_position_metrics = Mock()
        ex._cancel_graceful_close_orders = Mock()
        ex._graceful_close_orders = set()
        ex._closing_in_progress = False
        ex._close_order_id = None

        # Track call order
        call_order = []
        ex._cancel_graceful_close_orders = Mock(side_effect=lambda: call_order.append("graceful"))
        ex._cancel_remaining_grid_close_orders = Mock(side_effect=lambda: call_order.append("grid_close"))
        ex._place_aggressive_close_orders = AsyncMock(side_effect=lambda inv: call_order.append("aggressive"))

        await ex._check_unwind_phase_transition()

        assert call_order == ["graceful", "grid_close", "aggressive"], \
            f"Expected graceful→grid_close→aggressive, got {call_order}"


class TestCancelNonEssentialOrders:
    """Tests that _cancel_non_essential_orders cancels BOTH buy and sell grid orders."""

    @pytest.fixture
    def executor(self):
        mock_connector = MagicMock()
        mock_connector.name = "kraken"
        mock_connector.trading_rules = {
            "BCH-USD": TradingRule(
                trading_pair="BCH-USD",
                min_order_size=Decimal("0.01"),
                min_order_value=Decimal("5"),
                min_base_amount_increment=Decimal("0.000001"),
                min_price_increment=Decimal("0.01"),
            )
        }

        config = GridExecutorConfig(
            id="test-cancel",
            timestamp=1000,
            connector_name="kraken",
            trading_pair="BCH-USD",
            triple_barrier_config=TripleBarrierConfig(),
            start_price=Decimal("460"),
            end_price=Decimal("470"),
            limit_price=Decimal("455"),
            total_amount_quote=Decimal("150"),
            n_levels=4,
            min_order_amount=Decimal("0.01"),
        )

        with patch.object(GridExecutor, "__init__", lambda self, *a, **kw: None):
            executor = GridExecutor()
        executor.config = config
        executor._strategy = MagicMock()
        executor.connectors = {"kraken": mock_connector}
        return executor, mock_connector

    def test_cancels_both_open_and_close_orders(self, executor):
        """_cancel_non_essential_orders cancels buy AND sell grid orders."""
        ex, mock_conn = executor

        open_order = MagicMock()
        open_order.order_id = "buy_order_1"
        open_level = MagicMock()
        open_level.active_open_order = open_order
        open_level.price = Decimal("462")

        close_order = MagicMock()
        close_order.order_id = "sell_order_1"
        close_level = MagicMock()
        close_level.active_close_order = close_order

        ex.levels_by_state = {
            GridLevelStates.OPEN_ORDER_PLACED: [open_level],
            GridLevelStates.CLOSE_ORDER_PLACED: [close_level],
        }

        ex._cancel_non_essential_orders()

        cancel_calls = ex._strategy.cancel.call_args_list
        cancelled_ids = [call[1]["order_id"] for call in cancel_calls]
        assert "buy_order_1" in cancelled_ids, "Should cancel buy grid orders"
        assert "sell_order_1" in cancelled_ids, "Should cancel sell grid orders"

    def test_handles_empty_levels(self, executor):
        """Works when no grid orders exist."""
        ex, _ = executor
        ex.levels_by_state = {
            GridLevelStates.OPEN_ORDER_PLACED: [],
            GridLevelStates.CLOSE_ORDER_PLACED: [],
        }
        ex._cancel_non_essential_orders()  # Should not raise


class TestCloseOrderRaceCondition:
    """Tests for the close order race condition fix.

    Root cause: _place_graceful_close_orders and _place_aggressive_close_orders
    set _close_order_id but not _close_order (TrackedOrder). The main CLOSING
    loop checked `if self._close_order and self._close_order_id:` which failed,
    falling through to premature SHUTTING_DOWN.

    Fix summary:
    A) Create TrackedOrder in graceful/aggressive close
    B) Defensive else branch checks _close_order_id and _unwind_phase
    C) Keep _closing_in_progress during aggressive transition
    D) Fix early returns in _place_aggressive_close_orders
    """

    @pytest.fixture
    def mock_connector(self):
        connector = MagicMock()
        connector.name = "kraken"
        connector.get_available_balance = Mock(return_value=Decimal("100"))
        connector.get_balance = Mock(return_value=Decimal("100"))
        connector.get_price = Mock(return_value=Decimal("1.50"))
        connector.quantize_order_amount = lambda pair, amt: amt
        connector.quantize_order_price = lambda pair, px: px
        connector.in_flight_orders = {}
        connector.trading_rules = {
            "RENDER-USD": TradingRule(
                trading_pair="RENDER-USD",
                min_order_size=Decimal("1"),
                min_notional_size=Decimal("5"),
                min_price_increment=Decimal("0.01"),
                min_base_amount_increment=Decimal("0.01"),
            )
        }
        return connector

    @pytest.fixture
    def mock_strategy(self, mock_connector):
        strategy = MagicMock()
        strategy.current_timestamp = 1200.0
        strategy.cancel = Mock()
        strategy.connectors = {"kraken": mock_connector}
        return strategy

    @pytest.fixture
    def grid_config(self):
        return GridExecutorConfig(
            id="test_race",
            connector_name="kraken",
            trading_pair="RENDER-USD",
            side=TradeType.BUY,
            total_amount_quote=Decimal("50"),
            num_levels=3,
            start_price=Decimal("1.40"),
            end_price=Decimal("1.60"),
            limit_price=Decimal("1.35"),
            min_spread_between_orders=Decimal("0.001"),
            min_order_amount_quote=Decimal("5"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.08"),
                take_profit=Decimal("0.02"),
                time_limit=3600,
                time_limit_order_type=OrderType.MARKET,
                stop_loss_order_type=OrderType.MARKET,
            ),
        )

    @pytest.fixture
    def executor(self, mock_strategy, grid_config, mock_connector):
        with patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_metrics"
        ), patch(
            "hummingbot.strategy_v2.executors.grid_executor.grid_executor.GridExecutor.update_position_metrics"
        ), patch.object(
            GridExecutor, "get_price", return_value=Decimal("1.50")
        ):
            ex = GridExecutor(
                strategy=mock_strategy,
                config=grid_config,
                update_interval=1.0,
            )
            ex.connectors = {"kraken": mock_connector}
            ex.trading_rules = mock_connector.trading_rules["RENDER-USD"]
            ex.close_order_side = TradeType.SELL
            ex.mid_price = Decimal("1.50")
            return ex, mock_connector

    # --- Fix A: TrackedOrder created in graceful/aggressive close ---

    def test_graceful_close_sets_tracked_order(self, executor):
        """Fix A: _place_graceful_close_orders must set _close_order (TrackedOrder)."""
        ex, _ = executor
        ex.place_order = Mock(return_value="order_graceful_123")

        ex._place_graceful_close_orders(Decimal("30"))

        assert ex._close_order is not None, \
            "_close_order should be set after placing graceful close"
        assert ex._close_order.order_id == "order_graceful_123"
        assert ex._close_order_id == "order_graceful_123"

    async def test_aggressive_close_sets_tracked_order(self, executor):
        """Fix A: _place_aggressive_close_orders must set _close_order (TrackedOrder)."""
        ex, mock_conn = executor
        mock_conn.get_available_balance.return_value = Decimal("30")
        mock_conn.get_balance.return_value = Decimal("30")
        ex.place_order = Mock(return_value="order_aggr_456")
        ex._refresh_connector_balances = AsyncMock()
        ex._sleep = AsyncMock()
        ex._coerce_to_decimal = lambda v: Decimal(str(v))
        ex._safe_get_total_balance = lambda conn, asset: Decimal("30")

        await ex._place_aggressive_close_orders(Decimal("30"))

        assert ex._close_order is not None, \
            "_close_order should be set after placing aggressive close"
        assert ex._close_order.order_id == "order_aggr_456"

    # --- Fix B: Defensive else branch in CLOSING state handler ---

    def test_closing_with_order_id_but_no_tracked_order_waits(self, executor):
        """Fix B: When _close_order_id is set but _close_order is None,
        should NOT transition to SHUTTING_DOWN."""
        from hummingbot.strategy_v2.executors.executor_base import RunnableStatus

        ex, _ = executor
        ex._status = RunnableStatus.CLOSING
        ex._close_order_id = "pending_order_789"
        ex._close_order = None  # TrackedOrder not yet created
        ex._closing_in_progress = True
        ex._unwind_phase = "GRACEFUL"

        # The else branch should NOT trigger SHUTTING_DOWN
        assert ex._close_order_id is not None
        assert ex._status == RunnableStatus.CLOSING

    def test_closing_during_aggressive_transition_waits(self, executor):
        """Fix B: When unwind_phase is AGGRESSIVE but no close order yet
        (order being placed), should NOT transition to SHUTTING_DOWN."""
        from hummingbot.strategy_v2.executors.executor_base import RunnableStatus

        ex, _ = executor
        ex._status = RunnableStatus.CLOSING
        ex._close_order_id = None
        ex._close_order = None
        ex._closing_in_progress = True  # Set by Fix C
        ex._unwind_phase = "AGGRESSIVE"

        # Verify state: the defensive check should see _closing_in_progress=True
        assert ex._closing_in_progress is True
        assert ex._unwind_phase == "AGGRESSIVE"
        assert ex._status == RunnableStatus.CLOSING

    # --- Fix C: _closing_in_progress stays True during transition ---

    async def test_unwind_transition_keeps_closing_in_progress(self, executor):
        """Fix C: After cancelling graceful orders and before aggressive
        order is placed, _closing_in_progress must remain True."""
        from hummingbot.strategy_v2.executors.executor_base import RunnableStatus

        ex, _ = executor
        ex._status = RunnableStatus.CLOSING
        ex._unwind_phase = "GRACEFUL"
        ex._unwind_started_ts = 1000  # 200s ago (> 120s default grace)
        ex._unwind_close_reason = MagicMock()
        ex._unwind_close_reason.name = "NO_PROGRESS_TIMEOUT"
        ex.position_size_base = Decimal("30")
        ex.update_position_metrics = Mock()
        ex._graceful_close_orders = {"old_order_1"}

        closing_in_progress_during_await = None

        async def capture_state(inventory):
            nonlocal closing_in_progress_during_await
            # This runs DURING the await, simulating the race window
            closing_in_progress_during_await = ex._closing_in_progress

        ex._place_aggressive_close_orders = AsyncMock(side_effect=capture_state)

        await ex._check_unwind_phase_transition()

        assert closing_in_progress_during_await is True, \
            "_closing_in_progress should be True during aggressive order setup"
        assert ex._unwind_phase == "AGGRESSIVE"

    # --- Fix D: Early returns in _place_aggressive_close_orders ---

    async def test_aggressive_close_zero_balance_transitions_to_shutting_down(self, executor):
        """Fix D: If available balance stays 0, should SHUTTING_DOWN not hang."""
        from hummingbot.strategy_v2.executors.executor_base import RunnableStatus

        ex, mock_conn = executor
        mock_conn.get_available_balance.return_value = Decimal("0")
        mock_conn.get_balance.return_value = Decimal("30")
        ex.place_order = Mock(return_value="order_xyz")
        ex._refresh_connector_balances = AsyncMock()
        ex._sleep = AsyncMock()
        ex._coerce_to_decimal = lambda v: Decimal(str(v))
        ex._safe_get_total_balance = lambda conn, asset: Decimal("30")
        ex._cap_sell_to_available = Mock(return_value=Decimal("0"))

        await ex._place_aggressive_close_orders(Decimal("30"))

        assert ex._status == RunnableStatus.SHUTTING_DOWN, \
            "Should transition to SHUTTING_DOWN when no balance available"
        assert ex._unwind_phase == "DONE"
        assert ex._closing_in_progress is False

    async def test_aggressive_close_zero_quantized_transitions_to_shutting_down(self, executor):
        """Fix D: If quantized amount is 0, should SHUTTING_DOWN not hang."""
        from hummingbot.strategy_v2.executors.executor_base import RunnableStatus

        ex, mock_conn = executor
        mock_conn.get_available_balance.return_value = Decimal("0.001")
        mock_conn.get_balance.return_value = Decimal("0.001")
        ex.place_order = Mock(return_value="order_xyz")
        ex._refresh_connector_balances = AsyncMock()
        ex._sleep = AsyncMock()
        ex._coerce_to_decimal = lambda v: Decimal(str(v))
        ex._safe_get_total_balance = lambda conn, asset: Decimal("0.001")
        # Quantize returns 0 (amount too small)
        mock_conn.quantize_order_amount = lambda pair, amt: Decimal("0")

        await ex._place_aggressive_close_orders(Decimal("0.001"))

        assert ex._status == RunnableStatus.SHUTTING_DOWN, \
            "Should transition to SHUTTING_DOWN when quantized amount is 0"
        assert ex._unwind_phase == "DONE"
        assert ex._closing_in_progress is False
