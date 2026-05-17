"""
Tests for the hardened orphan detection system (post-review improvements).

Covers:
1. max_sell_amount cap prevents overselling manually-held coins
2. Runtime orphan check skips when active executor is present
3. Runtime orphan trigger passes unsold_quote from executor custom_info
4. early_stop_reason_from_stop_reason maps time_stop → NO_PROGRESS_TIMEOUT
5. Case 3 balance check now retries before terminating
"""
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine without leaving legacy get_event_loop() tests loop-less."""
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()
        asyncio.set_event_loop(asyncio.new_event_loop())


def _make_controller_stub(
    auto_sell: bool = True,
    min_notional: float = 5.0,
    wallet_balance: Decimal = Decimal("50"),
):
    """Return a minimal controller-like object with the methods under test."""
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    with patch.object(MultiCoinGridController, '__init__', lambda self, *a, **kw: None):
        ctrl = MultiCoinGridController.__new__(MultiCoinGridController)

    config = MagicMock()
    config.auto_sell_orphaned_positions = auto_sell
    config.min_notional = Decimal(str(min_notional))
    config.quote_asset = "USD"
    config.market_list = ["STRK-USD"]
    ctrl.config = config
    ctrl.executors_info = []
    ctrl.active_coins = {}

    # Connector stub
    connector = MagicMock()
    connector._account_balances = {"STRK": wallet_balance}
    connector.get_mid_price.return_value = Decimal("0.05")
    connector.get_balance.return_value = wallet_balance
    connector.trading_rules = {}
    connector._in_flight_orders = {}
    ctrl.connector = connector

    # Logger stub
    ctrl.logger = MagicMock(return_value=MagicMock())

    # Bind the real methods
    ctrl._check_single_orphan = MultiCoinGridController._check_single_orphan.__get__(ctrl)
    ctrl._detect_orphaned_positions = MultiCoinGridController._detect_orphaned_positions.__get__(ctrl)
    ctrl._sell_orphaned_positions = AsyncMock()
    ctrl._cleanup_stale_orders = AsyncMock()

    return ctrl


# ---------------------------------------------------------------------------
# Test 1: max_sell_amount cap — wallet larger than bot-tracked amount
# ---------------------------------------------------------------------------

def test_orphan_sell_capped_to_bot_tracked_amount():
    """
    Wallet holds 500 STRK (including manual holdings).
    Bot only bought 100 STRK (max_sell_quote=5.0 USD @ 0.05 USD = 100 STRK).
    _check_single_orphan must cap the sell to 100, not 500.
    """
    ctrl = _make_controller_stub(auto_sell=True, wallet_balance=Decimal("500"))

    with patch("asyncio.sleep", new_callable=AsyncMock):
        _run(ctrl._check_single_orphan("STRK-USD", max_sell_quote=Decimal("5.0")))

    ctrl._sell_orphaned_positions.assert_awaited_once()
    pos_arg = ctrl._sell_orphaned_positions.call_args[0][0][0]
    assert pos_arg['max_sell_amount'] is not None
    # max_sell_quote=5.0 / mid_price=0.05 = 100.0
    assert abs(pos_arg['max_sell_amount'] - 100.0) < 0.01, (
        f"Expected ~100, got {pos_arg['max_sell_amount']}"
    )


def test_orphan_sell_no_cap_when_no_tracked_amount():
    """
    When max_sell_quote is None (startup detection, no executor data),
    the pos dict must NOT have a max_sell_amount key set (or it's None).
    wallet=200 @ mid=0.05 → notional=10 > min_notional=5 so it proceeds.
    """
    ctrl = _make_controller_stub(auto_sell=True, wallet_balance=Decimal("200"))
    ctrl.connector._account_balances = {"STRK": Decimal("200")}

    with patch("asyncio.sleep", new_callable=AsyncMock):
        _run(ctrl._check_single_orphan("STRK-USD", max_sell_quote=None))

    ctrl._sell_orphaned_positions.assert_awaited_once()
    pos_arg = ctrl._sell_orphaned_positions.call_args[0][0][0]
    assert pos_arg.get('max_sell_amount') is None


def test_orphan_check_prefers_base_cap_when_market_dropped():
    """
    Bot bought 100 STRK at 0.05, but current mid is 0.04.
    A quote cap of 5 / 0.04 would be 125 STRK, so runtime recovery must prefer
    the explicit bot-tracked base cap of 100 STRK.
    """
    ctrl = _make_controller_stub(auto_sell=True, wallet_balance=Decimal("500"))
    ctrl.connector.get_mid_price.return_value = Decimal("0.04")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        _run(
            ctrl._check_single_orphan(
                "STRK-USD",
                max_sell_quote=Decimal("5.0"),
                max_sell_amount=Decimal("100"),
                require_sell_cap=True,
            )
        )

    ctrl._sell_orphaned_positions.assert_awaited_once()
    pos_arg = ctrl._sell_orphaned_positions.call_args[0][0][0]
    assert pos_arg['max_sell_amount'] == 100.0


def test_orphan_check_requires_cap_before_runtime_autosell():
    """Runtime recovery must not blindly sell the full wallet if no bot cap is known."""
    ctrl = _make_controller_stub(auto_sell=True, wallet_balance=Decimal("500"))

    with patch("asyncio.sleep", new_callable=AsyncMock):
        _run(ctrl._check_single_orphan("STRK-USD", require_sell_cap=True))

    ctrl._sell_orphaned_positions.assert_not_awaited()


def test_tracked_orphan_base_uses_position_size_base():
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    custom_info = {
        "position_size_base": "477.66449",
        "position_size_quote": "25.7031262069",
        "break_even_price": "0.05381",
    }

    assert MultiCoinGridController._tracked_orphan_base_from_custom_info(custom_info) == Decimal("477.66449")


def test_tracked_orphan_base_falls_back_to_position_quote_break_even():
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    custom_info = {
        "position_size_quote": "25.7031262069",
        "break_even_price": "0.05381",
    }

    base = MultiCoinGridController._tracked_orphan_base_from_custom_info(custom_info)

    assert base.quantize(Decimal("0.00001")) == Decimal("477.66449")


def test_startup_orphan_detection_passes_bot_tracked_base_cap():
    """Startup orphan recovery must cap sells using persisted executor inventory."""
    ctrl = _make_controller_stub(auto_sell=True, wallet_balance=Decimal("500"))

    executor_info = MagicMock()
    executor_info.is_active = False
    executor_info.trading_pair = "STRK-USD"
    executor_info.custom_info = {"position_size_base": "100"}
    ctrl.executors_info = [executor_info]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        _run(ctrl._detect_orphaned_positions())

    ctrl._sell_orphaned_positions.assert_awaited_once()
    pos_arg = ctrl._sell_orphaned_positions.call_args[0][0][0]
    assert pos_arg["max_sell_amount"] == 100.0


def test_startup_orphan_detection_blocks_uncapped_autosell():
    """Startup recovery must alert rather than sell full wallet when no bot cap is known."""
    ctrl = _make_controller_stub(auto_sell=True, wallet_balance=Decimal("500"))
    ctrl.executors_info = []

    with patch("asyncio.sleep", new_callable=AsyncMock):
        _run(ctrl._detect_orphaned_positions())

    ctrl._sell_orphaned_positions.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 2: _sell_orphaned_positions respects max_sell_amount
# ---------------------------------------------------------------------------

def test_sell_orphaned_caps_balance_to_max_sell_amount():
    """
    _sell_orphaned_positions re-reads wallet (500) but pos['max_sell_amount']=100.
    It must pass sell_amount <= 100 to connector.sell().
    """
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    with patch.object(MultiCoinGridController, '__init__', lambda self, *a, **kw: None):
        ctrl = MultiCoinGridController.__new__(MultiCoinGridController)

    config = MagicMock()
    config.min_notional = Decimal("5")
    ctrl.config = config
    ctrl.logger = MagicMock(return_value=MagicMock())

    connector = MagicMock()
    connector.get_balance.return_value = Decimal("500")  # wallet has 500
    connector.get_mid_price.return_value = Decimal("0.05")
    trading_rule = MagicMock()
    trading_rule.min_order_size = Decimal("1")
    connector.trading_rules = {"STRK-USD": trading_rule}
    connector.quantize_order_amount.side_effect = lambda tp, a: a
    connector._in_flight_orders = {}
    connector.sell.return_value = "order_001"
    ctrl.connector = connector

    # Bind the real method
    ctrl._sell_orphaned_positions = MultiCoinGridController._sell_orphaned_positions.__get__(ctrl)

    with patch("asyncio.sleep", new_callable=AsyncMock):
        _run(
            ctrl._sell_orphaned_positions([{
                'asset': 'STRK',
                'trading_pair': 'STRK-USD',
                'amount': 500.0,
                'price': 0.05,
                'notional': 25.0,
                'max_sell_amount': 100.0,  # bot-tracked
            }])
        )

    connector.sell.assert_called_once()
    sell_amount = connector.sell.call_args[1]['amount']
    assert sell_amount <= Decimal("100.0"), (
        f"Should be capped to 100, got {sell_amount}"
    )


# ---------------------------------------------------------------------------
# Test 3: Skip when active executor present
# ---------------------------------------------------------------------------

def test_orphan_check_skips_with_active_executor():
    """If a new executor has been started for the same pair, do nothing."""
    ctrl = _make_controller_stub(auto_sell=True, wallet_balance=Decimal("50"))

    active_ei = MagicMock()
    active_ei.is_active = True
    active_ei.trading_pair = "STRK-USD"
    ctrl.executors_info = [active_ei]

    with patch("asyncio.sleep", new_callable=AsyncMock):
        _run(ctrl._check_single_orphan("STRK-USD"))

    ctrl._sell_orphaned_positions.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 4: Skip when balance is zero
# ---------------------------------------------------------------------------

def test_orphan_check_skips_when_balance_zero():
    ctrl = _make_controller_stub(auto_sell=True, wallet_balance=Decimal("0"))
    ctrl.connector._account_balances = {"STRK": Decimal("0")}

    with patch("asyncio.sleep", new_callable=AsyncMock):
        _run(ctrl._check_single_orphan("STRK-USD"))

    ctrl._sell_orphaned_positions.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 5: _early_stop_reason_from_stop_reason — time_stop maps correctly
# ---------------------------------------------------------------------------

def test_early_stop_reason_time_stop_maps_to_no_progress_timeout():
    from hummingbot.strategy_v2.models.executors import EarlyStopReason
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    result = MultiCoinGridController._early_stop_reason_from_stop_reason("time_stop")
    assert result == EarlyStopReason.NO_PROGRESS_TIMEOUT


def test_early_stop_reason_time_limit_maps_to_no_progress_timeout():
    from hummingbot.strategy_v2.models.executors import EarlyStopReason
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    result = MultiCoinGridController._early_stop_reason_from_stop_reason("time_limit")
    assert result == EarlyStopReason.NO_PROGRESS_TIMEOUT


def test_early_stop_reason_stop_loss_unchanged():
    from hummingbot.strategy_v2.models.executors import EarlyStopReason
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    result = MultiCoinGridController._early_stop_reason_from_stop_reason("stop_loss")
    assert result == EarlyStopReason.STOP_LOSS


def test_early_stop_reason_profit_lock_returns_none():
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

    result = MultiCoinGridController._early_stop_reason_from_stop_reason("profit_lock")
    assert result is None


# ---------------------------------------------------------------------------
# Test 6: grid_executor.early_stop — NO_PROGRESS_TIMEOUT reason sets correct close_type
# ---------------------------------------------------------------------------

def test_early_stop_no_progress_sets_no_progress_close_type():
    """
    When early_stop() is called with reason=NO_PROGRESS_TIMEOUT, the executor
    close_type must be set to NO_PROGRESS_TIMEOUT (not EARLY_STOP) so the
    fee-aware timeout bypass is available.
    """
    from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
    from hummingbot.strategy_v2.models.base import RunnableStatus
    from hummingbot.strategy_v2.models.executors import CloseType, EarlyStopReason

    with patch.object(GridExecutor, '__init__', lambda self, *a, **kw: None):
        executor = GridExecutor.__new__(GridExecutor)

    executor._status = RunnableStatus.RUNNING
    executor.close_type = None
    executor._early_stop_reason = None
    executor._unwind_phase = "NONE"
    executor._unwind_close_reason = None
    executor.config = MagicMock()
    executor.config.trading_pair = "STRK-USD"
    executor.config.connector_name = "kraken"
    executor.connectors = {"kraken": MagicMock()}
    executor.logger = MagicMock(return_value=MagicMock())

    # Stub out side effects of early_stop we don't need
    executor.cancel_open_orders = MagicMock()
    executor.update_position_metrics = MagicMock()
    executor.update_metrics = MagicMock()
    executor.position_size_base = Decimal("0")
    executor.trading_rules = MagicMock()
    executor.trading_rules.min_order_size = Decimal("1")

    mock_connector = MagicMock()
    executor.connectors["kraken"] = mock_connector

    executor.early_stop(keep_position=False, reason=EarlyStopReason.NO_PROGRESS_TIMEOUT)

    assert executor.close_type == CloseType.NO_PROGRESS_TIMEOUT, (
        f"Expected NO_PROGRESS_TIMEOUT, got {executor.close_type}"
    )


def test_early_stop_no_fill_timeout_sets_no_progress_close_type():
    from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
    from hummingbot.strategy_v2.models.base import RunnableStatus
    from hummingbot.strategy_v2.models.executors import CloseType, EarlyStopReason

    with patch.object(GridExecutor, '__init__', lambda self, *a, **kw: None):
        executor = GridExecutor.__new__(GridExecutor)

    executor._status = RunnableStatus.RUNNING
    executor.close_type = None
    executor._early_stop_reason = None
    executor._unwind_phase = "NONE"
    executor._unwind_close_reason = None
    executor.config = MagicMock()
    executor.config.trading_pair = "FIL-USD"
    executor.config.connector_name = "kraken"
    executor.connectors = {"kraken": MagicMock()}
    executor.logger = MagicMock(return_value=MagicMock())
    executor.cancel_open_orders = MagicMock()
    executor.update_position_metrics = MagicMock()
    executor.update_metrics = MagicMock()
    executor.position_size_base = Decimal("0")
    executor.trading_rules = MagicMock()
    executor.trading_rules.min_order_size = Decimal("1")

    executor.early_stop(keep_position=False, reason=EarlyStopReason.NO_FILL_TIMEOUT)

    assert executor.close_type == CloseType.NO_PROGRESS_TIMEOUT, (
        f"Expected NO_PROGRESS_TIMEOUT, got {executor.close_type}"
    )


def test_early_stop_strategy_switch_keeps_early_stop_type():
    """STRATEGY_SWITCH is not an emergency and not a timeout — stays EARLY_STOP."""
    from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
    from hummingbot.strategy_v2.models.base import RunnableStatus
    from hummingbot.strategy_v2.models.executors import CloseType, EarlyStopReason

    with patch.object(GridExecutor, '__init__', lambda self, *a, **kw: None):
        executor = GridExecutor.__new__(GridExecutor)

    executor._status = RunnableStatus.RUNNING
    executor.close_type = None
    executor._early_stop_reason = None
    executor._unwind_phase = "NONE"
    executor._unwind_close_reason = None
    executor.config = MagicMock()
    executor.config.trading_pair = "ARB-USD"
    executor.config.connector_name = "kraken"
    executor.connectors = {"kraken": MagicMock()}
    executor.logger = MagicMock(return_value=MagicMock())
    executor.cancel_open_orders = MagicMock()
    executor.update_position_metrics = MagicMock()
    executor.update_metrics = MagicMock()
    executor.position_size_base = Decimal("0")
    executor.trading_rules = MagicMock()
    executor.trading_rules.min_order_size = Decimal("1")

    executor.early_stop(keep_position=False, reason=EarlyStopReason.STRATEGY_SWITCH)

    assert executor.close_type == CloseType.EARLY_STOP, (
        f"Expected EARLY_STOP, got {executor.close_type}"
    )
