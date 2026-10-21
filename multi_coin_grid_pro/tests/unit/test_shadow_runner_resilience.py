"""Runner-level safety behaviour for the A/B shadow sandbox:

* A single failing iteration must never crash the loop (fail-safe, not
  fail-open — the loop logs and continues to the next poll).
* The runner must never call anything resembling a live stop/order action.
* Disabling/stopping the shadow (``request_stop``) must be clean: no
  exception, no dangling live-state mutation (there is none to begin with).
"""
import asyncio
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from multi_coin_grid_pro.shadow.ab_shadow_runner import ABShadowRunner


@pytest.fixture(autouse=True)
def _restore_event_loop_after_test():
    """asyncio.run() closes the event loop it creates. Other, unrelated test
    modules in the same pytest session (e.g. test_t2_ops.py) still use the
    legacy `asyncio.get_event_loop()` pattern, which raises once this
    thread's loop has been closed with nothing put back. Restoring a fresh,
    open loop after each test here keeps this file from leaking that state
    into tests collected later in the same run."""
    yield
    try:
        asyncio.set_event_loop(asyncio.new_event_loop())
    except Exception:
        pass


@pytest.fixture
def runner(tmp_path):
    with patch("multi_coin_grid_pro.shadow.ab_shadow_runner.PublicKrakenMarketAdapter") as MockAdapter:
        mock_market = MagicMock()
        mock_market.close = MagicMock(return_value=_async_noop())
        MockAdapter.return_value = mock_market
        r = ABShadowRunner(
            pairs=["XRP-USD"],
            capital_quote=Decimal("300"),
            max_slots=2,
            poll_seconds=0.01,
            results_db_path=str(tmp_path / "shadow.db"),
        )
        yield r


async def _async_noop():
    return None


def test_a_failing_iteration_does_not_stop_the_loop(runner):
    """Inject a hard failure into _refresh() on the first iteration and
    confirm the loop survives to run a second iteration instead of raising."""
    call_count = {"n": 0}

    async def _bootstrap_noop():
        return None

    async def _flaky_refresh():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated transient market-data failure")

    runner._bootstrap = _bootstrap_noop
    runner._refresh = _flaky_refresh
    runner._select_variant_a = MagicMock(return_value=[])
    runner._select_variant_b = MagicMock(return_value=[])
    runner._maybe_open = MagicMock()
    runner._tick_positions = MagicMock()

    asyncio.run(runner.run(max_iterations=2))

    assert call_count["n"] == 2, "the loop must have reached a second iteration despite the first one raising"


def test_request_stop_halts_the_loop_cleanly(runner):
    async def _bootstrap_noop():
        return None

    runner._bootstrap = _bootstrap_noop
    runner._refresh = MagicMock(return_value=_async_noop())
    runner._select_variant_a = MagicMock(return_value=[])
    runner._select_variant_b = MagicMock(return_value=[])
    runner._maybe_open = MagicMock()
    runner._tick_positions = MagicMock(side_effect=lambda *a, **k: runner.request_stop())

    # Without max_iterations, only request_stop() (triggered from inside the
    # loop body above) may end the run — proves the stop flag is honoured.
    asyncio.run(runner.run(max_iterations=None))

    assert runner._stop_requested is True


def test_runner_module_never_constructs_a_stop_executor_action():
    """Static guard: the runner source must not reference StopExecutorAction
    or any live controller/orchestrator symbol anywhere."""
    import multi_coin_grid_pro.shadow.ab_shadow_runner as runner_module
    with open(runner_module.__file__, "r", encoding="utf-8") as f:
        source = f.read()
    for forbidden in ("StopExecutorAction", "ExecutorOrchestrator", "MultiCoinGridController", "KrakenAuth"):
        assert forbidden not in source


def test_runner_results_db_path_is_never_the_live_database_by_default():
    import inspect

    from multi_coin_grid_pro.shadow import ab_shadow_runner as runner_module

    source = inspect.getsource(runner_module._build_arg_parser)
    assert "multi_coin_grid_v2_usd.sqlite" not in source
    assert "realised_pnl_ledger" not in source
    assert "shadow_ab_results.db" in source
