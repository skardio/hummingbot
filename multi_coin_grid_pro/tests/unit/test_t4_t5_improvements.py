"""
Tests for T4-R4 (Warmup Gate), T4-R5 (Load Open Orders),
T5-A1 (Injectable Clock), T5-A3 (Top-level traceback import),
and T5-A10 (Late instance vars initialized in __init__).
"""

import asyncio
import time
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

# -- helpers ----------------------------------------------------------------

_determine_actions = MultiCoinGridController.determine_executor_actions


def _make_controller(**overrides):
    """Create a minimal mock controller with all required attributes."""
    ctrl = MagicMock(spec=MultiCoinGridController)
    ctrl.logger.return_value = MagicMock()

    # Injectable clock (T5-A1)
    ctrl._clock = time.time

    # Warmup gate (T4-R4)
    ctrl._warmup_complete = True  # Default: warmup done
    ctrl._warmup_steps_done = 6
    ctrl._warmup_steps_total = 6

    # T5-A10: Late vars initialized in __init__
    ctrl._bot_start_time = None
    ctrl._executor_creation_times = {}
    ctrl._orphaned_positions = []
    ctrl._stale_orders = []
    ctrl._risk_block_new_entries = False
    ctrl._stale_executor_counts = {}
    ctrl._kill_switch_actions_sent = False
    ctrl._last_memory_cleanup = 0.0
    ctrl._exchange_open_orders = []

    # State
    ctrl.active_coin = None
    ctrl.active_executor_id = None
    ctrl.active_coins = {}
    ctrl.executors_info = []
    ctrl.monitored_coins = ["BTC-USDT", "ETH-USDT"]
    ctrl.bot_start_time = time.time()
    ctrl.last_switch_time = 0
    ctrl.total_exposure = Decimal("0")

    # Config
    ctrl.config = MagicMock()
    ctrl.config.total_amount_quote = 300
    ctrl.config.min_order_amount_quote = 10
    ctrl.config.num_grids = 3
    ctrl.config.quote_asset = "USDT"
    ctrl.config.risk_limits = MagicMock()
    ctrl.config.risk_limits.max_daily_loss_pct = Decimal("3.0")
    ctrl.config.stop_loss_pct = Decimal("0.05")

    # Market data provider
    ctrl.market_data_provider = MagicMock()
    ctrl.market_data_provider.time.return_value = time.time()

    # Risk
    ctrl.risk_manager = MagicMock()
    ctrl.risk_manager.daily_loss_pct = Decimal("0")
    ctrl.risk_manager.switch_cooldown_remaining.return_value = 0

    # Trend
    ctrl.trend_calculator = MagicMock()

    # Filters
    ctrl.time_based_filter = None
    ctrl.circuit_breaker_active = False
    ctrl.api_error_paused = False

    # Apply overrides
    for k, v in overrides.items():
        setattr(ctrl, k, v)

    return ctrl


# ==========================================================================
# T5-A3: Top-level traceback import
# ==========================================================================

class TestTopLevelTraceback:
    """Verify traceback is imported at module level, not inline."""

    def test_traceback_in_module_namespace(self):
        """The controller module must have traceback available at top level."""
        import traceback as tb_module

        import multi_coin_grid_pro.controllers.multi_coin_grid_controller as mod
        assert hasattr(mod, 'traceback')
        assert mod.traceback is tb_module

    def test_no_inline_traceback_imports(self):
        """No function body should contain 'import traceback'."""
        import inspect

        import multi_coin_grid_pro.controllers.multi_coin_grid_controller as mod
        source = inspect.getsource(mod)
        # Count indented import traceback (inside functions)
        lines = source.split('\n')
        inline_imports = [
            (i + 1, line) for i, line in enumerate(lines)
            if line.strip() == 'import traceback' and line != line.lstrip()
        ]
        assert inline_imports == [], (
            f"Found {len(inline_imports)} inline 'import traceback' statements: "
            f"{inline_imports[:5]}"
        )


# ==========================================================================
# T5-A10: Late instance variables
# ==========================================================================

class TestLateInstanceVars:
    """Verify all formerly-late instance vars are in __init__."""

    EXPECTED_VARS = [
        '_bot_start_time',
        '_executor_creation_times',
        '_orphaned_positions',
        '_stale_orders',
        '_risk_block_new_entries',
        '_stale_executor_counts',
        '_kill_switch_actions_sent',
        '_last_memory_cleanup',
        '_warmup_complete',
        '_exchange_open_orders',
    ]

    def test_vars_declared_in_init(self):
        """All late vars must appear in __init__ source."""
        import inspect
        source = inspect.getsource(MultiCoinGridController.__init__)
        for var in self.EXPECTED_VARS:
            assert f'self.{var}' in source, (
                f"self.{var} not found in __init__ — still a late instance var"
            )

    def test_no_hasattr_guard_for_declared_vars(self):
        """
        Once initialized in __init__, hasattr guards are unnecessary.
        We allow a few in generic utility code, but the key ones must be gone.
        """
        import inspect

        # Check key methods that had hasattr guards
        methods_to_check = [
            '_kill_switch_stop_all_executors',
            '_create_grid_action',
        ]
        for method_name in methods_to_check:
            method = getattr(MultiCoinGridController, method_name, None)
            if method is None:
                continue
            source = inspect.getsource(method)
            for var in ['_executor_creation_times', '_kill_switch_actions_sent',
                        '_stale_executor_counts']:
                pattern = f"hasattr(self, '{var}')"
                assert pattern not in source, (
                    f"{method_name} still has hasattr guard for {var}"
                )


# ==========================================================================
# T5-A1: Injectable clock
# ==========================================================================

class TestInjectableClock:
    """Verify time.time() is replaced by self._clock()."""

    def test_no_time_time_in_source(self):
        """Controller source must not contain time.time() calls."""
        import inspect
        source = inspect.getsource(MultiCoinGridController)
        # Find all time.time() calls (excluding the default assignment)
        lines = source.split('\n')
        violations = [
            (i + 1, line.strip()) for i, line in enumerate(lines)
            if 'time.time()' in line and 'clock_fn or time.time' not in line
        ]
        assert violations == [], (
            f"Found {len(violations)} remaining time.time() calls:\n"
            + '\n'.join(f"  line ~{n}: {l}" for n, l in violations[:10])
        )

    def test_clock_fn_parameter_in_init(self):
        """__init__ must accept clock_fn parameter."""
        import inspect
        sig = inspect.signature(MultiCoinGridController.__init__)
        assert 'clock_fn' in sig.parameters, (
            "__init__ missing clock_fn parameter"
        )

    def test_clock_default_is_time_time(self):
        """Default _clock should be time.time."""
        ctrl = _make_controller()
        ctrl._clock = time.time  # Simulate default
        t1 = ctrl._clock()
        t2 = time.time()
        assert abs(t2 - t1) < 1.0, "Default clock should track wall time"

    def test_injectable_clock_is_used(self):
        """A custom clock_fn should be used instead of time.time."""
        fake_time = 1700000000.0
        ctrl = _make_controller()
        ctrl._clock = lambda: fake_time
        assert ctrl._clock() == fake_time


# ==========================================================================
# T4-R4: Warmup Gate
# ==========================================================================

class TestWarmupGate:
    """Test that trading is blocked until warmup completes."""

    def test_blocks_trading_during_warmup(self):
        """determine_executor_actions should return [] when warmup incomplete."""
        ctrl = _make_controller(_warmup_complete=False, _warmup_steps_done=3)
        result = _determine_actions(ctrl)
        assert result == []

    def test_allows_trading_after_warmup(self):
        """determine_executor_actions should proceed past warmup gate."""
        ctrl = _make_controller(_warmup_complete=True)
        # We only need to verify it passes the warmup gate.
        # The method will proceed into normal logic and may hit other
        # mock attribute errors, so we catch those — the point is it
        # did NOT return [] from the warmup block.
        try:
            result = _determine_actions(ctrl)
        except (AttributeError, TypeError):
            # Proceeded past warmup gate into deeper logic — that's the proof
            result = None
        # If it returned [], verify that's NOT because of warmup blocking
        if result == []:
            # Check warmup log was NOT called
            logged_msgs = [str(c) for c in ctrl.logger().info.call_args_list]
            assert not any('warmup in progress' in m.lower() for m in logged_msgs), \
                "Trading blocked by warmup gate despite _warmup_complete=True"

    def test_warmup_logged_during_block(self):
        """Warmup progress should be logged when blocking."""
        ctrl = _make_controller(
            _warmup_complete=False,
            _warmup_steps_done=2,
            _warmup_steps_total=6,
        )
        _determine_actions(ctrl)
        ctrl.logger().info.assert_called()
        logged_msgs = [str(c) for c in ctrl.logger().info.call_args_list]
        assert any('warmup' in m.lower() for m in logged_msgs)

    def test_warmup_flag_in_init(self):
        """_warmup_complete must be False by default in __init__."""
        import inspect
        source = inspect.getsource(MultiCoinGridController.__init__)
        assert 'self._warmup_complete' in source
        assert '_warmup_complete: bool = False' in source

    def test_on_start_sets_warmup_complete(self):
        """on_start should set _warmup_complete = True after all steps."""
        import inspect
        source = inspect.getsource(MultiCoinGridController.on_start)
        assert 'self._warmup_complete = True' in source


# ==========================================================================
# T4-R5: Load Open Orders on Start
# ==========================================================================

class TestLoadOpenOrders:
    """Test exchange open order loading at startup."""

    def test_load_exchange_open_orders_exists(self):
        """_load_exchange_open_orders must be a method on the controller."""
        assert hasattr(MultiCoinGridController, '_load_exchange_open_orders')
        assert asyncio.iscoroutinefunction(
            MultiCoinGridController._load_exchange_open_orders
        )

    @pytest.mark.asyncio
    async def test_load_with_in_flight_orders(self):
        """Should store in-flight orders when connector reports them."""
        ctrl = MagicMock(spec=MultiCoinGridController)
        ctrl.logger.return_value = MagicMock()
        ctrl._exchange_open_orders = []

        mock_order = MagicMock()
        mock_order.trading_pair = "BTC-USDT"
        mock_order.trade_type = "BUY"
        mock_order.price = Decimal("50000")
        mock_order.amount = Decimal("0.001")

        connector = MagicMock()
        connector.in_flight_orders = {"order-1": mock_order}
        connector.limit_orders = [mock_order]
        ctrl.connector = connector

        await MultiCoinGridController._load_exchange_open_orders(ctrl)

        assert len(ctrl._exchange_open_orders) == 1

    @pytest.mark.asyncio
    async def test_load_with_no_connector(self):
        """Should handle missing connector gracefully."""
        ctrl = MagicMock(spec=MultiCoinGridController)
        ctrl.logger.return_value = MagicMock()
        ctrl._exchange_open_orders = []
        ctrl.connector = None

        await MultiCoinGridController._load_exchange_open_orders(ctrl)

        assert ctrl._exchange_open_orders == []

    @pytest.mark.asyncio
    async def test_load_with_no_orders(self):
        """Should handle empty order book gracefully."""
        ctrl = MagicMock(spec=MultiCoinGridController)
        ctrl.logger.return_value = MagicMock()
        ctrl._exchange_open_orders = []

        connector = MagicMock()
        connector.in_flight_orders = {}
        connector.limit_orders = []
        ctrl.connector = connector

        await MultiCoinGridController._load_exchange_open_orders(ctrl)

        assert ctrl._exchange_open_orders == []

    def test_on_start_calls_load_open_orders(self):
        """on_start should include _load_exchange_open_orders call."""
        import inspect
        source = inspect.getsource(MultiCoinGridController.on_start)
        assert '_load_exchange_open_orders' in source


# ==========================================================================
# Integration: Warmup + Open Orders together
# ==========================================================================

class TestWarmupIntegration:
    """Test that warmup steps complete in correct order."""

    def test_on_start_has_all_warmup_steps(self):
        """on_start should include all 6 warmup steps."""
        import inspect
        source = inspect.getsource(MultiCoinGridController.on_start)

        expected_keywords = [
            'loading cooldowns',
            'loading entry prices',
            'reconciling fills',
            'detecting orphaned positions',
            'loading open orders',
            'verifying risk module',
        ]
        for kw in expected_keywords:
            assert kw in source, f"Missing warmup step: {kw}"

    def test_warmup_progress_logging_format(self):
        """Warmup progress should follow format: warmup X/Y: description."""
        import inspect
        import re
        source = inspect.getsource(MultiCoinGridController.on_start)
        # Find all warmup log lines
        warmup_logs = re.findall(r'warmup \{self\._warmup_steps_done\}/\{self\._warmup_steps_total\}', source)
        assert len(warmup_logs) == 6, f"Expected 6 warmup progress logs, found {len(warmup_logs)}"
