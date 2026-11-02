"""Regression tests: final-size exposure guard, risk equity, restart reconciliation, stale exposure."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hummingbot.strategy_v2.models.base import RunnableStatus
from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.risk.professional_risk_manager import PortfolioRisk

D = Decimal


class FakeConnector:
    def __init__(self, balances=None, available=None, mids=None, rules=None, in_flight=None):
        self.balances = {k: D(str(v)) for k, v in (balances or {}).items()}
        self.available = {k: D(str(v)) for k, v in (available or {}).items()}
        self.mids = {k: D(str(v)) for k, v in (mids or {}).items()}
        self.trading_rules = rules if rules is not None else {}
        self.in_flight_orders = in_flight or {}

    def get_balance(self, ccy):
        return self.balances.get(ccy, D("0"))

    def get_available_balance(self, ccy):
        return self.available.get(ccy, self.balances.get(ccy, D("0")))

    def get_all_balances(self):
        return dict(self.balances)

    def get_mid_price(self, pair):
        if pair not in self.mids:
            raise KeyError(pair)
        return self.mids[pair]


def rule(min_size="0.0001", min_notional="5"):
    return SimpleNamespace(min_order_size=D(min_size), min_notional=D(min_notional))


def make_controller(reference="1000", per_coin="50.0", total="70.0", use_live=False, **extra):
    config = MultiCoinGridConfig(
        connector_name="kraken",
        quote_asset="USD",
        total_amount_quote=D("50000"),
        max_coins_to_monitor=5,
        min_24h_volume_eur=D("50000"),
        max_exposure_per_coin_pct=D(per_coin),
        max_total_exposure_pct=D(total),
        max_daily_loss_pct=3.0,
        min_order_amount_quote=D("10"),
        risk_reference_balance_quote=D(reference),
        risk_reference_use_live_balance=use_live,
        risk_max_daily_loss_pct=D("3"),
        risk_max_balance_per_trade_pct=D("100"),
        risk_max_total_open_risk_pct=D("100"),
        **extra,
    )
    provider = MagicMock()
    provider.time = Mock(return_value=datetime.now().timestamp())
    with patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery'), \
            patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator'):
        ctrl = MultiCoinGridController(
            config=config, market_data_provider=provider, actions_queue=[],
            connectors={"kraken": AsyncMock()}, update_interval=10.0,
        )
    ctrl.trend_calculator = MagicMock()
    ctrl.event_logger = None
    ctrl.active_coin = None
    ctrl.total_exposure = D("0")
    ctrl.current_exposure_per_coin = {}
    ctrl._next_allocation_quote = None
    ctrl.executors_info = []
    ctrl.all_available_pairs = []
    ctrl.connector = FakeConnector(balances={"USD": 1000})
    return ctrl


def make_executor(eid, pair, status=RunnableStatus.RUNNING, size="0", pnl="0", fees="0", break_even="1",
                  close_order_ids=()):
    levels = {"OPEN_ORDER_PLACED": [], "CLOSE_ORDER_PLACED": [
        {"active_open_order": f"o-{c}", "active_close_order": c} for c in close_order_ids]}
    info = {"position_size_quote": D(size), "position_pnl_quote": D(pnl), "position_fees_quote": D(fees),
            "break_even_price": D(break_even), "levels_by_state": levels}
    return SimpleNamespace(
        id=eid, status=status, is_active=status in (RunnableStatus.RUNNING, RunnableStatus.NOT_STARTED),
        is_done=status == RunnableStatus.TERMINATED, custom_info=info,
        config=SimpleNamespace(trading_pair=pair),
    )


class TestFinalSizeGuard:
    def test_quality_multiplier_125_is_checked_on_final_amount(self):
        ctrl = make_controller(reference="1000")  # per-coin limit 500
        spy = MagicMock(wraps=ctrl._check_position_limits)
        ctrl._check_position_limits = spy
        ctrl.trend_calculator.get_trend = MagicMock(return_value=None)
        pre_multiplier = D("450")
        final = pre_multiplier * D("1.25")  # 562.5 > 500
        assert ctrl._create_grid_action("AAA-USD", final) is None
        spy.assert_called_once_with("AAA-USD", requested_allocation=final)
        ctrl.trend_calculator.get_trend.assert_not_called()

    def test_amount_within_limit_after_multiplier_reaches_grid_construction(self):
        ctrl = make_controller(reference="1000")
        ctrl._check_position_limits = MagicMock(wraps=ctrl._check_position_limits)
        ctrl.trend_calculator.get_trend = MagicMock(return_value=None)
        final = D("400") * D("1.25")  # exactly 500
        ctrl._create_grid_action("AAA-USD", final)
        ctrl.trend_calculator.get_trend.assert_called()

    def test_primary_and_secondary_paths_have_no_unguarded_create_call(self):
        import inspect
        source = inspect.getsource(MultiCoinGridController.determine_executor_actions)
        assert source.count("self._create_grid_action(") == 2
        assert "_check_position_limits(" not in source  # guard lives in _create_grid_action only


class TestRiskEquity:
    def test_free_quote_only(self):
        ctrl = make_controller()
        equity, reason = ctrl._calculate_risk_equity()
        assert equity == D("1000"), reason

    def test_open_grid_with_reserved_quote_has_no_inventory(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 1000}, available={"USD": 600})
        ctrl.executors_info = [make_executor("e1", "AAA-USD")]
        assert ctrl._calculate_risk_equity()[0] == D("1000")

    def test_filled_inventory_is_valued_at_mark(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 400})
        # 60 base bought at 10, now marked 11 -> pnl +60
        ctrl.executors_info = [make_executor("e1", "AAA-USD", size="600", pnl="60", break_even="10")]
        assert ctrl._calculate_risk_equity()[0] == D("1060")

    def test_multiple_positions_are_summed(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 300})
        ctrl.executors_info = [
            make_executor("e1", "AAA-USD", size="300", break_even="10"),
            make_executor("e2", "BBB-USD", size="200", pnl="-20", break_even="2"),
        ]
        assert ctrl._calculate_risk_equity()[0] == D("780")

    def test_partial_close_fill_is_not_double_counted(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(
            balances={"USD": 400},
            in_flight={"close-1": SimpleNamespace(executed_amount_base=D("10"))})
        ctrl.executors_info = [make_executor(
            "e1", "AAA-USD", size="600", break_even="10", close_order_ids=("close-1",))]
        assert ctrl._calculate_risk_equity()[0] == D("900")  # 400 + 600 - 10 * 10

    def test_unknown_close_order_fails_closed(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 400})
        ctrl.executors_info = [make_executor(
            "e1", "AAA-USD", size="600", break_even="10", close_order_ids=("missing",))]
        equity, reason = ctrl._calculate_risk_equity()
        assert equity is None and "missing" in reason

    def test_shutting_down_executor_is_excluded_as_safe_lower_bound(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 400})
        ctrl.executors_info = [make_executor("e1", "AAA-USD", RunnableStatus.SHUTTING_DOWN, size="600")]
        assert ctrl._calculate_risk_equity()[0] == D("400")

    @pytest.mark.parametrize("balance", [0, -1])
    def test_missing_quote_balance_fails_closed(self, balance):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": balance})
        assert ctrl._calculate_risk_equity()[0] is None

    def test_connector_error_fails_closed(self):
        ctrl = make_controller()
        ctrl.connector = MagicMock()
        ctrl.connector.get_balance.side_effect = RuntimeError("boom")
        assert ctrl._calculate_risk_equity()[0] is None


class TestDailyLossUsesEquity:
    def _allowed(self, ctrl):
        return ctrl._professional_risk_allows("AAA-USD")

    def test_inventory_is_part_of_the_denominator(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 400})
        ctrl.executors_info = [make_executor("e1", "BBB-USD", size="600", break_even="10")]
        ctrl.risk_manager._daily_realised_pnl_quote = D("-12")
        # quote-only: -12/400 = -3% (blocked); equity based: -12/1000 = -1.2% (allowed)
        assert self._allowed(ctrl) is True

    def test_loss_beyond_three_percent_of_equity_blocks(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 400})
        ctrl.executors_info = [make_executor("e1", "BBB-USD", size="600", break_even="10")]
        ctrl.risk_manager._daily_realised_pnl_quote = D("-31")
        assert self._allowed(ctrl) is False

    def test_missing_equity_blocks_entries(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 0})
        assert self._allowed(ctrl) is False
        assert ctrl._build_portfolio_risk() is None

    def test_portfolio_risk_carries_equity_and_fraction(self):
        ctrl = make_controller()
        ctrl.risk_manager._daily_realised_pnl_quote = D("-10")
        risk = ctrl._build_portfolio_risk()
        assert isinstance(risk, PortfolioRisk)
        assert risk.total_equity == D("1000")
        assert risk.daily_pnl_pct == pytest.approx(-0.01)


class TestStartupReconciliation:
    def test_clean_account_passes_and_is_sticky(self):
        ctrl = make_controller()
        assert ctrl._startup_exposure_gate() is True
        ctrl.connector = FakeConnector(balances={"USD": 1000, "AAA": 50}, mids={"AAA-USD": 100},
                                       rules={"AAA-USD": rule()})
        assert ctrl._startup_exposure_gate() is True  # already reconciled for this session

    def test_untracked_open_orders_block(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 1000}, available={"USD": 700})
        assert ctrl._startup_exposure_gate() is False
        assert "locked" in ctrl._startup_block_reason

    def test_acknowledged_locked_quote_passes(self):
        ctrl = make_controller(startup_reconcile_ack_locked_quote=D("300"))
        ctrl.connector = FakeConnector(balances={"USD": 1000}, available={"USD": 700})
        assert ctrl._startup_exposure_gate() is True

    def test_untracked_inventory_blocks(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 900, "AAA": 2}, mids={"AAA-USD": 50},
                                       rules={"AAA-USD": rule()})
        assert ctrl._startup_exposure_gate() is False
        assert "AAA" in ctrl._startup_block_reason

    def test_acknowledged_asset_is_ignored(self):
        ctrl = make_controller(startup_reconcile_ack_assets=["aaa"])
        ctrl.connector = FakeConnector(balances={"USD": 900, "AAA": 2}, mids={"AAA-USD": 50},
                                       rules={"AAA-USD": rule()})
        assert ctrl._startup_exposure_gate() is True

    def test_dust_below_min_order_size_is_ignored_without_price(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 900, "AAA": "0.00001"},
                                       rules={"AAA-USD": rule(min_size="0.001")})
        assert ctrl._startup_exposure_gate() is True

    def test_value_below_min_notional_is_ignored(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 900, "AAA": 1}, mids={"AAA-USD": 2},
                                       rules={"AAA-USD": rule(min_notional="5")})
        assert ctrl._startup_exposure_gate() is True

    def test_unpriceable_inventory_fails_closed(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 900, "AAA": 5}, rules={"AAA-USD": rule()})
        assert ctrl._startup_exposure_gate() is False
        assert "AAA" in ctrl._startup_block_reason

    def test_asset_without_quote_pair_is_ignored(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 900, "XYZ": 5})
        assert ctrl._startup_exposure_gate() is True

    def test_missing_balances_block(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={})
        assert ctrl._startup_exposure_gate() is False

    def test_disabled_flag_skips_check(self):
        ctrl = make_controller(startup_reconcile_enabled=False)
        ctrl.connector = FakeConnector(balances={"USD": 1000}, available={"USD": 100})
        assert ctrl._startup_exposure_gate() is True

    def test_gate_is_rechecked_after_operator_clears_exposure(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 1000}, available={"USD": 700})
        assert ctrl._startup_exposure_gate() is False
        ctrl._last_startup_check_ts = 0.0
        ctrl.connector = FakeConnector(balances={"USD": 1000})
        assert ctrl._startup_exposure_gate() is True

    def test_decision_loop_places_no_entries_while_blocked(self):
        ctrl = make_controller()
        ctrl._sync_risk_state = MagicMock()
        ctrl._check_professional_exit_signals = MagicMock(return_value=[])
        ctrl.time_based_filter = MagicMock()
        ctrl.connector = FakeConnector(balances={"USD": 1000}, available={"USD": 700})
        assert ctrl.determine_executor_actions() == []
        ctrl.time_based_filter.check_trading_permission.assert_not_called()


class TestLiveReferencePreconditions:
    def test_reference_is_not_resolved_while_exposure_is_unreconciled(self):
        ctrl = make_controller(reference="50000", use_live=True)
        ctrl.connector = FakeConnector(balances={"USD": 1000}, available={"USD": 700})
        assert ctrl._ensure_risk_reference() is False
        assert ctrl.config.risk_reference_balance == D("50000")

    def test_reference_is_not_resolved_with_active_executors(self):
        ctrl = make_controller(reference="50000", use_live=True)
        ctrl.executors_info = [make_executor("e1", "AAA-USD", size="100", break_even="10")]
        assert ctrl._ensure_risk_reference() is False

    def test_reference_uses_total_quote_when_clean(self):
        ctrl = make_controller(reference="50000", use_live=True)
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == D("1000")

    def test_acknowledged_locked_quote_is_excluded_from_reference(self):
        ctrl = make_controller(reference="50000", use_live=True, startup_reconcile_ack_locked_quote=D("300"))
        ctrl.connector = FakeConnector(balances={"USD": 1000}, available={"USD": 700})
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == D("700")

    def test_bitget_yaml_does_not_assume_a_dedicated_account(self):
        from multi_coin_grid_pro.spot_bitget.config_manager import SpotGridBitgetConfigManager
        data = SpotGridBitgetConfigManager().load_config()
        assert data.get("risk_reference_use_live_balance", False) is False


class TestStaleExposureReconciliation:
    def _track(self, ctrl, symbol="AAA-USD", eid="e1", amount="100"):
        ctrl._update_exposure_tracking(symbol, D(amount))
        ctrl.active_coins[symbol] = eid
        ctrl.risk_manager.register_open_trade(symbol=symbol, notional=D(amount), now=1.0)

    def _tick(self, ctrl, t):
        ctrl.market_data_provider.time = Mock(return_value=t)
        ctrl._reconcile_stale_exposure()

    def test_live_executor_keeps_exposure(self):
        ctrl = make_controller()
        self._track(ctrl)
        ctrl.executors_info = [make_executor("e1", "AAA-USD")]
        self._tick(ctrl, 1000.0)
        self._tick(ctrl, 5000.0)
        assert ctrl.total_exposure == D("100") and "AAA-USD" in ctrl.active_coins

    def test_shutting_down_executor_keeps_exposure(self):
        ctrl = make_controller()
        self._track(ctrl)
        ctrl.executors_info = [make_executor("e1", "AAA-USD", RunnableStatus.SHUTTING_DOWN)]
        self._tick(ctrl, 1000.0)
        self._tick(ctrl, 5000.0)
        assert ctrl.total_exposure == D("100")

    def test_absent_executor_within_grace_keeps_exposure(self):
        ctrl = make_controller()
        self._track(ctrl)
        self._tick(ctrl, 1000.0)
        self._tick(ctrl, 1060.0)  # grace is 120 s
        assert ctrl.total_exposure == D("100")

    def test_absent_executor_after_grace_releases_everything_once(self):
        ctrl = make_controller()
        self._track(ctrl)
        self._tick(ctrl, 1000.0)
        self._tick(ctrl, 1121.0)
        assert ctrl.total_exposure == D("0")
        assert ctrl.current_exposure_per_coin == {}
        assert "AAA-USD" not in ctrl.active_coins
        assert ctrl.risk_manager.total_open_notional == D("0")
        self._tick(ctrl, 1300.0)  # idempotent
        assert ctrl.total_exposure == D("0")

    def test_reappearing_executor_resets_the_timer(self):
        ctrl = make_controller()
        self._track(ctrl)
        self._tick(ctrl, 1000.0)
        ctrl.executors_info = [make_executor("e1", "AAA-USD")]
        self._tick(ctrl, 1100.0)
        ctrl.executors_info = []
        self._tick(ctrl, 1200.0)
        self._tick(ctrl, 1250.0)
        assert ctrl.total_exposure == D("100")

    def test_leftover_inventory_keeps_exposure(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 900, "AAA": 5}, mids={"AAA-USD": 20},
                                       rules={"AAA-USD": rule()})
        self._track(ctrl)
        self._tick(ctrl, 1000.0)
        self._tick(ctrl, 1200.0)
        assert ctrl.total_exposure == D("100") and "AAA-USD" in ctrl.active_coins

    def test_unverifiable_inventory_keeps_exposure(self):
        ctrl = make_controller()
        ctrl.connector = FakeConnector(balances={"USD": 900, "AAA": 5}, rules={"AAA-USD": rule()})
        self._track(ctrl)
        self._tick(ctrl, 1000.0)
        self._tick(ctrl, 1200.0)
        assert ctrl.total_exposure == D("100")

    def test_other_symbols_are_untouched(self):
        ctrl = make_controller()
        self._track(ctrl, "AAA-USD", "e1")
        self._track(ctrl, "BBB-USD", "e2", "50")
        ctrl.executors_info = [make_executor("e2", "BBB-USD")]
        self._tick(ctrl, 1000.0)
        self._tick(ctrl, 1200.0)
        assert ctrl.current_exposure_per_coin == {"BBB-USD": D("50")}
        assert ctrl.total_exposure == D("50")
