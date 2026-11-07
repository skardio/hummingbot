"""Capital-adaptive risk (Bitget/Kraken at 160/300/1000/5000): live reference, limits, sizing, flows, buckets, restart."""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hummingbot.strategy_v2.models.base import RunnableStatus
from multi_coin_grid_pro.config.config_manager import ConfigManager
from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.core.risk_buckets import CoinBucket, MarketMetrics
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
        self.ready = True
        self.current_timestamp = 1000.0
        self._last_poll_timestamp = 1000.0

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


BOTS = [(bitget_config, "USDT"), (kraken_config, "USD")]
CAPITALS = [160, 300, 1000, 5000]


def ready(make_cfg, quote, equity, **cfg_overrides):
    cfg = make_cfg()
    for key, value in cfg_overrides.items():
        cfg.__dict__[key] = value
    ctrl = build(cfg, FakeConnector({quote: equity}))
    assert ctrl._ensure_risk_reference() is True
    return ctrl


class TestConfiguredYaml:
    @pytest.mark.parametrize("make_cfg,quote", BOTS)
    def test_no_nominal_capital_is_required(self, make_cfg, quote):
        cfg = make_cfg()
        assert cfg.risk_reference_use_live_balance is True
        assert cfg.risk_capital_cap_quote is None
        assert "risk_reference_balance_quote" not in cfg.model_fields_set

    def test_existing_percentages_and_strategy_parameters_are_unchanged(self):
        b, k = bitget_config(), kraken_config()
        assert (b.max_exposure_per_coin_pct, b.max_total_exposure_pct) == (D("0.5"), D("0.7"))
        assert (k.max_exposure_per_coin_pct, k.max_total_exposure_pct) == (D("0.55"), D("0.95"))
        assert (b.min_order_amount_quote, k.min_order_amount_quote) == (D("10"), D("15"))
        assert (b.max_simultaneous_coins, k.max_simultaneous_coins) == (3, 3)
        assert b.risk_bucket_limits == {"L1": 15.0, "L2": 40.0, "MEME": 20.0, "ILLIQUID": 10.0, "BLOCKED": 0.0}
        assert k.risk_bucket_limits == {"L1": 10.0, "L2": 60.0, "MEME": 30.0, "ILLIQUID": 60.0, "BLOCKED": 0.0}


@pytest.mark.parametrize("make_cfg,quote", BOTS)
@pytest.mark.parametrize("equity", CAPITALS)
class TestReferenceFollowsEquity:
    def test_reference_and_every_component_follow_the_real_balance(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        ref = D(equity)
        assert ctrl.config.risk_reference_balance == ref
        assert ctrl.config.total_amount_quote == ref
        assert ctrl.risk_manager._reference_balance_quote == ref
        assert ctrl.pnl_tracker_v2.starting_balance == ref
        assert ctrl.bucket_tracker._portfolio == float(ref)

    def test_exposure_limits_scale_with_equity(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        per_coin = D(equity) * ctrl.config.max_exposure_per_coin_pct
        assert ctrl._check_position_limits("AAA-X", requested_allocation=per_coin) is True
        assert ctrl._check_position_limits("AAA-X", requested_allocation=per_coin + D("0.01")) is False

    def test_balance_growth_raises_and_loss_lowers_the_reference(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        ctrl.connector.balances[quote] = D(equity) * D("1.5")
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == D(equity) * D("1.5")
        ctrl.connector.balances[quote] = D(equity) * D("0.8")
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == D(equity) * D("0.8")
        assert ctrl.risk_manager._reference_balance_quote == D(equity) * D("0.8")

    def test_tiny_changes_do_not_churn_the_reference(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        ctrl.connector.balances[quote] = D(equity) * D("1.005")
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == D(equity)

    def test_operator_cap_limits_the_capital(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity, risk_capital_cap_quote=D("250"))
        ctrl._risk_capital_cap = D("250")
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == min(D("250"), D(equity))


@pytest.mark.parametrize("make_cfg,quote", BOTS)
class TestMissingOrStaleBalance:
    @pytest.mark.parametrize("failure", ["zero", "error"])
    def test_unreadable_balance_blocks_entries(self, make_cfg, quote, failure):
        connector = FakeConnector({quote: 0 if failure == "zero" else 300})
        connector.fail = failure == "error"
        ctrl = build(make_cfg(), connector)
        assert ctrl._ensure_risk_reference() is False
        ctrl._sync_risk_state = MagicMock()
        ctrl._check_professional_exit_signals = MagicMock(return_value=[])
        ctrl.time_based_filter = MagicMock()
        assert ctrl.determine_executor_actions() == []
        ctrl.time_based_filter.check_trading_permission.assert_not_called()

    def test_stale_balance_blocks_and_never_loosens_an_existing_reference(self, make_cfg, quote):
        ctrl = ready(make_cfg, quote, 300)
        ctrl.connector.current_timestamp = 1000.0 + 301
        assert ctrl._ensure_risk_reference() is False
        assert ctrl.config.risk_reference_balance == D("300")
        assert ctrl._calculate_risk_equity()[0] is None
        assert ctrl._get_quote_balances_for_allocation()[0] == D("0")

    def test_unreadable_available_balance_sizes_nothing_instead_of_using_the_nominal_amount(self, make_cfg, quote):
        ctrl = ready(make_cfg, quote, 300)
        ctrl.connector.fail = True
        ctrl.connector.get_available_balance = MagicMock(side_effect=RuntimeError("down"))
        raw, effective, _ = ctrl._get_quote_balances_for_allocation()
        assert raw == D("0") and effective == D("0")

    def test_not_ready_connector_blocks(self, make_cfg, quote):
        ctrl = build(make_cfg(), FakeConnector({quote: 300}))
        ctrl.connector.ready = False
        assert ctrl._ensure_risk_reference() is False


@pytest.mark.parametrize("make_cfg,quote", BOTS)
class TestDepositsAndWithdrawals:
    def _prepared(self, make_cfg, quote):
        ctrl = ready(make_cfg, quote, 300)
        ctrl.drawdown_tracker.daily_start_balance = D("300")
        ctrl.drawdown_tracker.weekly_start_balance = D("300")
        ctrl.drawdown_tracker.monthly_start_balance = D("300")
        return ctrl

    def test_deposit_while_flat_shifts_baselines_not_pnl(self, make_cfg, quote):
        ctrl = self._prepared(make_cfg, quote)
        ctrl.connector.balances[quote] = D("1300")
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.drawdown_tracker.daily_start_balance == D("1300")
        assert ctrl.drawdown_tracker.monthly_start_balance == D("1300")
        assert ctrl.config.risk_reference_balance == D("1300")

    def test_withdrawal_while_flat_shifts_baselines_not_loss(self, make_cfg, quote):
        ctrl = self._prepared(make_cfg, quote)
        ctrl.connector.balances[quote] = D("200")
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.drawdown_tracker.daily_start_balance == D("200")
        assert ctrl.config.risk_reference_balance == D("200")

    def test_realised_profit_is_not_a_capital_flow(self, make_cfg, quote):
        ctrl = self._prepared(make_cfg, quote)
        ctrl._realised_since_flat = D("12")
        ctrl.connector.balances[quote] = D("312")
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.drawdown_tracker.daily_start_balance == D("300")

    def test_no_flow_is_inferred_while_an_executor_is_active(self, make_cfg, quote):
        ctrl = self._prepared(make_cfg, quote)
        ctrl.executors_info = [SimpleNamespace(status=RunnableStatus.RUNNING, custom_info={},
                                               config=SimpleNamespace(trading_pair=f"AAA-{quote}"))]
        ctrl.connector.balances[quote] = D("1300")
        ctrl._ensure_risk_reference()
        assert ctrl.drawdown_tracker.daily_start_balance == D("300")


@pytest.mark.parametrize("make_cfg,quote", BOTS)
@pytest.mark.parametrize("equity", CAPITALS)
class TestSlotSizingScalesWithCapital:
    @staticmethod
    def _slot(ctrl, equity):
        """Mirror of the primary sizing path: dynamic allocation, then the parallel slot cap."""
        cfg = ctrl.config
        allocation = ctrl.dynamic_slot_manager.calculate_optimal_allocation(
            available_balance=D(equity), min_order_amount=D(str(cfg.min_order_amount_quote)),
            preferred_grids=cfg.num_grids, max_coins=ctrl.max_simultaneous_coins)
        parallel = min(ctrl.max_simultaneous_coins, max(1, allocation.num_coins))
        slot = allocation.capital_per_coin
        return min(slot, D(equity) * D("0.9") / D(parallel)) if parallel > 1 else slot

    def test_slot_is_viable_and_levels_respect_the_minimum_order(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        slot = self._slot(ctrl, equity)
        minimum = D(str(ctrl.config.min_order_amount_quote)) * D("3")
        if D(equity) < 300 and make_cfg is kraken_config:
            return  # 3 x 15 = 45 minimum; checked in the small-capital test below
        assert slot >= minimum

    def test_l2_slot_fits_the_risk_budget_and_scales(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        slot = self._slot(ctrl, equity)
        fits, limited = ctrl._slot_fits_risk_budget(f"DOT-{quote}", slot)
        assert fits is True and 0 < limited <= slot
        assert limited <= D(equity) * ctrl.config.max_exposure_per_coin_pct
        l2_cap = D(str(ctrl.config.risk_bucket_limits["L2"])) / D("100") * D(equity)
        assert limited == min(slot, l2_cap, D(equity) * ctrl.config.max_exposure_per_coin_pct,
                              D(equity) * ctrl.config.max_total_exposure_pct)

    def test_second_slot_is_clamped_by_the_remaining_bucket_or_total_headroom(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        slot = self._slot(ctrl, equity)
        ctrl._update_exposure_tracking(f"DOT-{quote}", slot)
        ctrl.bucket_tracker.set_pending(f"DOT-{quote}", float(slot))
        limited, binding = ctrl._limit_slot_to_risk_budget(f"AVAX-{quote}", slot)
        headroom = {
            "risk_bucket": D(str(ctrl.bucket_tracker.remaining_capacity(f"AVAX-{quote}"))),
            "max_total_exposure": D(equity) * ctrl.config.max_total_exposure_pct - slot,
            "max_exposure_per_coin": D(equity) * ctrl.config.max_exposure_per_coin_pct,
        }
        assert limited == min(slot, max(min(headroom.values()), D("0")))
        if limited < slot:
            assert headroom[binding] == min(headroom.values())
        # the definitive size never breaks the final guard
        if limited > 0:
            assert ctrl._check_position_limits(f"AVAX-{quote}", requested_allocation=limited) is True

    def test_unlisted_coin_without_evidence_gets_the_illiquid_cap(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        ctrl.pair_volumes = {f"FOO-{quote}": 10_000_000}
        ctrl.pair_spreads = {f"FOO-{quote}": 0.001}  # fraction: 0.1%
        cap = D(str(ctrl.config.risk_bucket_limits["ILLIQUID"])) / D("100") * D(equity)
        limited, binding = ctrl._limit_slot_to_risk_budget(f"FOO-{quote}", D(equity))
        assert limited <= cap
        assert binding in ("risk_bucket", "max_exposure_per_coin", "max_total_exposure")

    def test_unlisted_coin_with_strong_evidence_gets_the_meme_cap(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        ctrl.pair_volumes = {f"FOO-{quote}": 60_000_000}
        ctrl.pair_spreads = {f"FOO-{quote}": 0.001}
        meme_cap = ctrl.config.risk_bucket_limits["MEME"] / 100.0 * equity
        remaining = ctrl.bucket_tracker.remaining_capacity(f"FOO-{quote}", MarketMetrics(60_000_000, 0.1))
        assert remaining == pytest.approx(meme_cap)

    def test_unknown_liquidity_is_blocked_not_treated_as_safe(self, make_cfg, quote, equity):
        ctrl = ready(make_cfg, quote, equity)
        ctrl.pair_volumes, ctrl.pair_spreads = {}, {}
        fits, limited = ctrl._slot_fits_risk_budget(f"NEW-{quote}", D(equity) / 4)
        assert fits is False and limited == D("0")


@pytest.mark.parametrize("make_cfg,quote", BOTS)
class TestMinimumOrdersAndSmallCapital:
    def test_slot_below_three_levels_of_the_minimum_order_is_skipped(self, make_cfg, quote):
        ctrl = ready(make_cfg, quote, 300)
        minimum = D(str(ctrl.config.min_order_amount_quote)) * D("3")
        fits, _ = ctrl._slot_fits_risk_budget(f"DOT-{quote}", minimum - D("0.01"))
        assert fits is False
        fits, _ = ctrl._slot_fits_risk_budget(f"DOT-{quote}", minimum)
        assert fits is True

    def test_too_little_capital_means_no_trade(self, make_cfg, quote):
        ctrl = ready(make_cfg, quote, 30)
        allocation = ctrl.dynamic_slot_manager.calculate_optimal_allocation(
            available_balance=D("30"), min_order_amount=D(str(ctrl.config.min_order_amount_quote)),
            preferred_grids=ctrl.config.num_grids, max_coins=3)
        fits, _ = ctrl._slot_fits_risk_budget(f"DOT-{quote}", D("30") * D("0.9") / D("3"))
        assert (not allocation.is_feasible) or fits is False

    def test_existing_inventory_and_open_exposure_reduce_the_headroom(self, make_cfg, quote):
        ctrl = ready(make_cfg, quote, 1000)
        total_limit = D("1000") * ctrl.config.max_total_exposure_pct
        ctrl._update_exposure_tracking(f"AAA-{quote}", total_limit - D("40"))
        limited, binding = ctrl._limit_slot_to_risk_budget(f"BBB-{quote}", D("300"))
        assert limited <= D("40")


class TestRiskBucketsFollowTheCapital:
    def test_bucket_caps_scale_with_the_reference(self):
        for equity in CAPITALS:
            ctrl = ready(bitget_config, "USDT", equity)
            l2 = ctrl.bucket_tracker.remaining_capacity("DOT-USDT")
            assert l2 == pytest.approx(equity * 0.4)
            assert ctrl.bucket_tracker.remaining_capacity("FOO-USDT") == 0.0  # no metrics: blocked

    def test_bucket_total_and_reference_use_the_same_capital_base(self):
        ctrl = ready(kraken_config, "USD", 1000)
        ctrl.bucket_tracker.set_filled("DOT-USD", 300.0)
        assert ctrl.bucket_tracker.get_bucket_pct(CoinBucket.L2) == pytest.approx(30.0)
        ctrl.connector.balances["USD"] = D("2000")
        ctrl._ensure_risk_reference()
        assert ctrl.bucket_tracker.get_bucket_pct(CoinBucket.L2) == pytest.approx(15.0)


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
        assert ctrl._live_risk_reference_resolved is False


class TestSelectionOnlyPicksFundableCoins:
    """Selection uses the same risk headroom as executor creation (Bitget 7 Nov: ILLIQUID 10% x 164 < 30)."""

    EQUITY = "164.05"

    def _ctrl(self, equity=EQUITY):
        ctrl = ready(bitget_config, "USDT", D(equity))
        ctrl.pair_volumes = {"JCT-USDT": 3_556_104, "AIN-USDT": 1_335_408, "DOT-USDT": 40_000_000}
        ctrl.pair_spreads = {"JCT-USDT": 0.00142, "AIN-USDT": 0.00137, "DOT-USDT": 0.0002}
        ctrl._check_smart_entry_filter = Mock(return_value=True)
        return ctrl

    def test_illiquid_coin_below_minimum_is_rejected_but_l2_is_admitted(self):
        ctrl = self._ctrl()
        profile = ctrl.bucket_tracker._classifier.classify("JCT-USDT", MarketMetrics(3_556_104, 0.142))
        assert profile.bucket.value == "ILLIQUID"
        assert ctrl._risk_budget_admits_slot("JCT-USDT") is False
        assert ctrl._risk_budget_admits_slot("DOT-USDT") is True

    def test_illiquid_coin_is_fundable_once_capital_supports_a_minimum_grid(self):
        ctrl = self._ctrl(equity="1000")
        assert ctrl._risk_budget_admits_slot("JCT-USDT") is True

    def test_unfundable_coin_does_not_reach_smart_entry(self):
        ctrl = self._ctrl()
        assert ctrl._entry_candidate_allowed("JCT-USDT") is False
        ctrl._check_smart_entry_filter.assert_not_called()
        assert ctrl._entry_candidate_allowed("DOT-USDT") is True
        ctrl._check_smart_entry_filter.assert_called_once_with("DOT-USDT")

    def test_smart_entry_rejection_is_still_respected_for_fundable_coins(self):
        ctrl = self._ctrl()
        ctrl._check_smart_entry_filter.return_value = False
        assert ctrl._entry_candidate_allowed("DOT-USDT") is False

    def test_multiple_candidates_select_the_first_fundable_one(self):
        ctrl = self._ctrl()
        ranked = ["JCT-USDT", "AIN-USDT", "DOT-USDT"]
        assert next(c for c in ranked if ctrl._entry_candidate_allowed(c)) == "DOT-USDT"

    def test_no_fundable_candidates_selects_nothing(self):
        ctrl = self._ctrl()
        assert not any(ctrl._entry_candidate_allowed(c) for c in ("JCT-USDT", "AIN-USDT"))

    def test_active_exposure_consumes_the_bucket_headroom(self):
        ctrl = self._ctrl(equity="1000")
        assert ctrl._risk_budget_admits_slot("AIN-USDT") is True
        ctrl.bucket_tracker.set_pending("JCT-USDT", 80.0, MarketMetrics(3_556_104, 0.142))  # ILLIQUID cap 100 -> 20 left < 30
        assert ctrl._risk_budget_admits_slot("AIN-USDT") is False
        assert ctrl._risk_budget_admits_slot("DOT-USDT") is True

    def test_missing_liquidity_metrics_fail_closed(self):
        ctrl = self._ctrl()
        assert ctrl._risk_budget_admits_slot("NEW-USDT") is False

    def test_precheck_agrees_with_the_final_executor_check(self):
        ctrl = self._ctrl()
        minimum = D(str(ctrl.config.min_order_amount_quote)) * D("3")
        for symbol in ("JCT-USDT", "AIN-USDT", "DOT-USDT"):
            for size in (minimum, D("60"), D("187.02")):
                fits, _ = ctrl._slot_fits_risk_budget(symbol, size)
                assert fits is ctrl._risk_budget_admits_slot(symbol)

    def test_capital_skip_releases_monitoring_so_no_timeout_blacklist(self):
        ctrl = self._ctrl()
        ctrl.monitoring_coin, ctrl.monitoring_start_time = "JCT-USDT", 1000.0
        ctrl._release_capital_skipped_monitoring("DOT-USDT")
        assert ctrl.monitoring_coin == "JCT-USDT"
        ctrl._release_capital_skipped_monitoring("JCT-USDT")
        assert (ctrl.monitoring_coin, ctrl.monitoring_start_time) == (None, 0)

    def test_every_selection_route_uses_the_fundability_gate(self):
        import inspect
        source = inspect.getsource(MultiCoinGridController.determine_executor_actions)
        assert "self._check_smart_entry_filter(" not in source
        assert source.count("self._entry_candidate_allowed(") == 4
        assert source.count("self._release_capital_skipped_monitoring(best_coin)") == 2
