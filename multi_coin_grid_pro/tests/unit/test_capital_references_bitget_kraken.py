"""Operator-confirmed capital (Bitget 164 USDT, Kraken USD 280 USD): references, limits, sizing, buckets, restart."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from multi_coin_grid_pro.config.config_manager import ConfigManager
from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.core.risk_buckets import MarketMetrics
from multi_coin_grid_pro.spot_bitget.config_manager import SpotGridBitgetConfigManager
from multi_coin_grid_pro.spot_bitget.config_schema import SpotGridBitgetConfig

D = Decimal


class FakeConnector:
    """Read-only exchange double; any order action is recorded and must never happen."""

    def __init__(self, balances, available=None, mids=None, rules=None):
        self.balances = {k: D(str(v)) for k, v in balances.items()}
        self.available = {k: D(str(v)) for k, v in (available or {}).items()}
        self.mids = {k: D(str(v)) for k, v in (mids or {}).items()}
        self.trading_rules = rules or {}
        self.in_flight_orders = {}
        self.order_actions = []
        self.fail = False

    def get_balance(self, ccy):
        if self.fail:
            raise RuntimeError("balance endpoint down")
        return self.balances.get(ccy, D("0"))

    def get_available_balance(self, ccy):
        return self.available.get(ccy, self.balances.get(ccy, D("0")))

    def get_all_balances(self):
        return dict(self.balances)

    def get_mid_price(self, pair):
        return self.mids[pair]

    def _record(self, name):
        def action(*args, **kwargs):
            self.order_actions.append(name)
        return action

    def __getattr__(self, name):
        if name in ("buy", "sell", "cancel", "cancel_all", "place_order", "execute_cancel"):
            return self._record(name)
        raise AttributeError(name)


def bitget_config():
    data = SpotGridBitgetConfigManager().load_config()
    return SpotGridBitgetConfig(**{**data, "telegram": {}})


def kraken_config():
    data = ConfigManager().load_config("spot_grid_kraken_usd")
    return MultiCoinGridConfig(**{**data, "telegram": {}})


def build(cfg, connector):
    provider = MagicMock()
    provider.time = Mock(return_value=datetime.now().timestamp())
    with patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery'), \
            patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator'):
        ctrl = MultiCoinGridController(
            config=cfg, market_data_provider=provider, actions_queue=[],
            connectors={cfg.connector_name: AsyncMock()}, update_interval=10.0)
    ctrl.trend_calculator = MagicMock()
    ctrl.event_logger = None
    ctrl.active_coin = None
    ctrl.total_exposure = D("0")
    ctrl.current_exposure_per_coin = {}
    ctrl._next_allocation_quote = None
    ctrl.executors_info = []
    ctrl.connector = connector
    return ctrl


class TestConfiguredReferences:
    def test_bitget(self):
        cfg = bitget_config()
        assert cfg.risk_reference_balance == D("164")
        assert cfg.risk_reference_use_live_balance is True

    def test_kraken_usd(self):
        cfg = kraken_config()
        assert cfg.risk_reference_balance == D("280")
        assert cfg.risk_reference_use_live_balance is True

    def test_existing_percentages_and_strategy_parameters_are_unchanged(self):
        b, k = bitget_config(), kraken_config()
        assert (b.max_exposure_per_coin_pct, b.max_total_exposure_pct) == (D("0.5"), D("0.7"))
        assert (k.max_exposure_per_coin_pct, k.max_total_exposure_pct) == (D("0.55"), D("0.95"))
        assert (b.min_order_amount_quote, k.min_order_amount_quote) == (D("10"), D("15"))
        assert (b.max_simultaneous_coins, k.max_simultaneous_coins) == (3, 3)
        assert b.risk_bucket_limits == {"L1": 15.0, "L2": 40.0, "MEME": 20.0, "ILLIQUID": 10.0, "BLOCKED": 0.0}
        assert k.risk_bucket_limits == {"L1": 10.0, "L2": 60.0, "MEME": 30.0, "ILLIQUID": 60.0, "BLOCKED": 0.0}


@pytest.mark.parametrize("make_cfg,quote,ceiling,per_coin_pct,total_pct", [
    (bitget_config, "USDT", D("164"), D("0.5"), D("0.7")),
    (kraken_config, "USD", D("280"), D("0.55"), D("0.95")),
])
class TestEffectiveReferenceAndLimits:
    def _ready(self, make_cfg, quote, live):
        ctrl = build(make_cfg(), FakeConnector({quote: live}))
        assert ctrl._ensure_risk_reference() is True
        return ctrl

    def test_reference_equals_confirmed_capital(self, make_cfg, quote, ceiling, per_coin_pct, total_pct):
        ctrl = self._ready(make_cfg, quote, ceiling)
        assert ctrl.config.risk_reference_balance == ceiling
        assert ctrl.risk_manager._reference_balance_quote == ceiling
        assert ctrl.pnl_tracker_v2.starting_balance == ceiling

    def test_exposure_limits_at_confirmed_capital(self, make_cfg, quote, ceiling, per_coin_pct, total_pct):
        ctrl = self._ready(make_cfg, quote, ceiling)
        per_coin, total = ceiling * per_coin_pct, ceiling * total_pct
        assert ctrl._check_position_limits("AAA-X", requested_allocation=per_coin) is True
        assert ctrl._check_position_limits("AAA-X", requested_allocation=per_coin + D("0.01")) is False
        ctrl.total_exposure = total - D("10")
        assert ctrl._check_position_limits("BBB-X", requested_allocation=D("10")) is True
        assert ctrl._check_position_limits("BBB-X", requested_allocation=D("10.01")) is False

    def test_falling_balance_tightens_limits(self, make_cfg, quote, ceiling, per_coin_pct, total_pct):
        live = ceiling * D("0.8")
        ctrl = self._ready(make_cfg, quote, live)
        assert ctrl.config.risk_reference_balance == live
        assert ctrl._check_position_limits("AAA-X", requested_allocation=live * per_coin_pct) is True
        assert ctrl._check_position_limits("AAA-X", requested_allocation=live * per_coin_pct + D("0.01")) is False
        assert ctrl.risk_manager._reference_balance_quote == live

    def test_higher_balance_never_loosens_the_ceiling(self, make_cfg, quote, ceiling, per_coin_pct, total_pct):
        ctrl = self._ready(make_cfg, quote, ceiling * 3)
        assert ctrl.config.risk_reference_balance == ceiling

    def test_reference_is_fixed_for_the_session(
            self, make_cfg, quote, ceiling, per_coin_pct, total_pct):
        ctrl = self._ready(make_cfg, quote, ceiling)
        ctrl.connector.balances[quote] = ceiling / 2  # balance drops later in the session
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == ceiling

    @pytest.mark.parametrize("failure", ["zero", "error"])
    def test_unreadable_balance_blocks_entries(
            self, make_cfg, quote, ceiling, per_coin_pct, total_pct, failure):
        connector = FakeConnector({quote: 0 if failure == "zero" else ceiling})
        connector.fail = failure == "error"
        ctrl = build(make_cfg(), connector)
        assert ctrl._ensure_risk_reference() is False
        assert ctrl.config.risk_reference_balance == ceiling
        ctrl._sync_risk_state = MagicMock()
        ctrl._check_professional_exit_signals = MagicMock(return_value=[])
        ctrl.time_based_filter = MagicMock()
        assert ctrl.determine_executor_actions() == []
        ctrl.time_based_filter.check_trading_permission.assert_not_called()


class TestSizingAndSlots:
    def test_allocation_depends_on_the_real_balance_not_on_the_reference(self):
        bitget = build(bitget_config(), FakeConnector({"USDT": 164}))
        kraken = build(kraken_config(), FakeConnector({"USD": 280}))
        b = bitget.dynamic_slot_manager.calculate_optimal_allocation(
            available_balance=D("164"), min_order_amount=D("10"), preferred_grids=7, max_coins=3)
        k = kraken.dynamic_slot_manager.calculate_optimal_allocation(
            available_balance=D("280"), min_order_amount=D("15"), preferred_grids=3, max_coins=3)
        assert b.is_feasible and b.amount_per_grid_level >= D("10")
        assert k.is_feasible and k.amount_per_grid_level >= D("15") and k.num_coins == 3

    def test_slot_budget_after_parallel_cap_still_meets_the_minimum_order(self):
        for balance, min_order in ((D("164"), D("10")), (D("280"), D("15"))):
            slot = balance * D("0.90") / D("3")
            assert int(slot / min_order) >= 1  # grid creation auto-reduces levels until per-level >= min order

    def test_kraken_three_slots_fit_the_total_limit(self):
        ctrl = build(kraken_config(), FakeConnector({"USD": 280}))
        assert ctrl._ensure_risk_reference() is True
        slot = D("280") * D("0.90") / D("3")  # 84
        for i in range(3):
            assert ctrl._check_position_limits(f"C{i}-USD", requested_allocation=slot) is True
            ctrl._update_exposure_tracking(f"C{i}-USD", slot)

    def test_bitget_third_full_slot_exceeds_the_70_percent_total_limit(self):
        ctrl = build(bitget_config(), FakeConnector({"USDT": 164}))
        assert ctrl._ensure_risk_reference() is True
        slot = D("164") * D("0.90") / D("3")  # 49.2
        results = []
        for i in range(3):
            results.append(ctrl._check_position_limits(f"C{i}-USDT", requested_allocation=slot))
            ctrl._update_exposure_tracking(f"C{i}-USDT", slot)
        assert results == [True, True, False]  # 2 x 49.2 = 98.4 fits 114.8, the third does not
        ctrl.current_exposure_per_coin = {}
        ctrl.total_exposure = D("0")
        for i in range(3):  # three slots fit once each stays within 70% / 3 = 38.2
            assert ctrl._check_position_limits(f"D{i}-USDT", requested_allocation=D("38.2")) is True
            ctrl._update_exposure_tracking(f"D{i}-USDT", D("38.2"))


class TestRiskBucketsAtConfirmedCapital:
    """Characterises the bucket caps that become binding with a real reference (percentages unchanged)."""

    def test_bitget_caps(self):
        ctrl = build(bitget_config(), FakeConnector({"USDT": 164}))
        assert ctrl._ensure_risk_reference() is True
        tracker = ctrl.bucket_tracker
        illiquid = MarketMetrics(volume_24h_usd=2_000_000, spread_pct=0.1)
        assert tracker.can_add("FOO-USDT", 16.4, metrics=illiquid)[0] is True    # ILLIQUID 10% = 16.4
        assert tracker.can_add("FOO-USDT", 49.2, metrics=illiquid)[0] is False   # a full slot is refused
        assert tracker.can_add("DOT-USDT", 49.2)[0] is True                       # L2 40% = 65.6
        tracker.set_pending("DOT-USDT", 49.2)
        assert tracker.can_add("AVAX-USDT", 16.4)[0] is True
        assert tracker.can_add("AVAX-USDT", 16.5)[0] is False                     # second L2 slot refused
        assert tracker.can_add("DOGE-USDT", 32.8)[0] is True                      # MEME 20% = 32.8
        assert tracker.can_add("DOGE-USDT", 49.2)[0] is False

    def test_kraken_caps(self):
        ctrl = build(kraken_config(), FakeConnector({"USD": 280}))
        assert ctrl._ensure_risk_reference() is True
        tracker = ctrl.bucket_tracker
        illiquid = MarketMetrics(volume_24h_usd=2_000_000, spread_pct=0.1)
        assert tracker.can_add("FOO-USD", 84, metrics=illiquid)[0] is True       # ILLIQUID 60% = 168
        tracker.set_pending("FOO-USD", 84, metrics=illiquid)
        assert tracker.can_add("BAR-USD", 84, metrics=illiquid)[0] is True
        tracker.set_pending("BAR-USD", 84, metrics=illiquid)
        assert tracker.can_add("BAZ-USD", 84, metrics=illiquid)[0] is False      # third illiquid slot refused
        assert tracker.can_add("ONDO-USD", 84)[0] is True                         # L2 60% = 168
        assert tracker.can_add("BTC-USD", 84)[0] is False                         # L1 10% = 28


@pytest.mark.parametrize("make_cfg,quote,live", [(bitget_config, "USDT", 164), (kraken_config, "USD", 280)])
class TestOpenOrdersBeforeRestart:
    def _gate(self, make_cfg, connector):
        ctrl = build(make_cfg(), connector)
        return ctrl, ctrl._startup_exposure_gate()

    def test_clean_account_passes(self, make_cfg, quote, live):
        assert self._gate(make_cfg, FakeConnector({quote: live}))[1] is True

    @pytest.mark.parametrize("locked", ["0.5"])
    def test_rounding_noise_is_ignored(self, make_cfg, quote, live, locked):
        connector = FakeConnector({quote: live}, available={quote: D(live) - D(locked)})
        assert self._gate(make_cfg, connector)[1] is True

    @pytest.mark.parametrize("locked", ["3", "10", "20", "60"])
    def test_open_buy_orders_are_detected_even_when_small(self, make_cfg, quote, live, locked):
        connector = FakeConnector({quote: live}, available={quote: D(live) - D(locked)})
        ctrl, passed = self._gate(make_cfg, connector)
        assert passed is False
        assert "locked in open orders" in ctrl._startup_block_reason

    def test_open_sell_order_is_seen_as_untracked_inventory(self, make_cfg, quote, live):
        connector = FakeConnector({quote: 100, "AAA": 5}, mids={f"AAA-{quote}": 10},
                                  rules={f"AAA-{quote}": SimpleNamespace(min_order_size=D("0.01"),
                                                                         min_notional=D("5"))})
        ctrl, passed = self._gate(make_cfg, connector)
        assert passed is False and "AAA" in ctrl._startup_block_reason

    def test_nothing_is_cancelled_or_sold_and_entries_stay_blocked(self, make_cfg, quote, live):
        connector = FakeConnector({quote: live}, available={quote: D(live) - 30})
        ctrl = build(make_cfg(), connector)
        ctrl._sync_risk_state = MagicMock()
        ctrl._check_professional_exit_signals = MagicMock(return_value=[])
        assert ctrl.determine_executor_actions() == []
        assert connector.order_actions == []
        assert ctrl._ensure_risk_reference() is False  # live reference waits for a clean account
        assert ctrl.config.risk_reference_balance == D(live)
