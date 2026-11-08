"""
Regression tests for the premature ICNT grid_profit_exit (Bitget, 2026-11-08 08:15:10).

Legacy Layer 5 divided realized net PnL of ONE completed level (0.284 USDT) by the
REMAINING position (11.04 USDT) and subtracted 0.31% fees again: 2.57% gross → 2.26% net
≥ 1.5% → PRO EXIT, while the deployed capital was ~22.11 USDT and the executor price was stale.

All tests are offline; no connector or order activity.
"""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo, RunnableStatus

try:
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
except ImportError:  # pragma: no cover
    from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
    from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

NOW = 1_000_000.0
COIN = "ICNT-USDT"
ENTRY = Decimal("0.3174")
BUY_BASE = Decimal("34.83")
BASE_FEE = Decimal("0.03483")  # Bitget 0.1% buy fee charged in ICNT
HELD_BASE = BUY_BASE - BASE_FEE  # 34.79517
# Completed level: BUY 34.83 @0.3174, SELL 34.79 @0.3262 (0.1% USDT fee), dust cost removed.
REALIZED_BUY_QUOTE = Decimal("11.0534")
REALIZED_NET = Decimal("0.2838")
POSITION_SIZE_QUOTE = HELD_BASE * ENTRY  # 11.04399
POSITION_FEES_QUOTE = BASE_FEE * ENTRY  # 0.011055
TAKER = Decimal("0.0020")  # spot_grid_bitget.yaml fee_aware_filter.taker_fee_pct = 0.20


def position_pnl(price: Decimal) -> Decimal:
    """GridExecutor.update_position_metrics formula (BUY side)."""
    return (price - ENTRY) / ENTRY * POSITION_SIZE_QUOTE - POSITION_FEES_QUOTE


def icnt_info(price: Decimal, **extra) -> dict:
    info = {
        "realized_pnl_quote": REALIZED_NET,
        "realized_buy_size_quote": REALIZED_BUY_QUOTE,
        "position_size_quote": POSITION_SIZE_QUOTE,
        "position_fees_quote": POSITION_FEES_QUOTE,
        "position_pnl_quote": position_pnl(price),
        "price_reliable": True,
        "trailing_active": False,
    }
    info.update(extra)
    return info


def make_controller(connector_name="bitget", **overrides):
    params = dict(
        controller_name="test_controller",
        connector_name=connector_name,
        quote_asset="USDT",
        manual_trading_pairs=[COIN],
        min_hold_time_seconds=1800,
        emergency_exit_pct=-12.0,
        hard_stop_pct=-15.0,
        min_grid_profit_pct=1.5,
        exit_short_threshold=-4.0,
        exit_mid_threshold=-3.0,
        fee_aware_filter={"taker_fee_pct": 0.20},
        max_price_age_ms=35000,  # spot_grid_bitget.yaml runtime value
        risk_reference_balance_quote=Decimal("10000"),
        risk_max_daily_loss_pct=Decimal("2"),
        risk_max_balance_per_trade_pct=Decimal("0.5"),
        risk_max_total_open_risk_pct=Decimal("3"),
        risk_exit_cooldown_minutes=30,
        risk_symbol_switch_cooldown_minutes=45,
        risk_consecutive_loss_cooldown_minutes=60,
    )
    params.update(overrides)
    mdp = MagicMock()
    mdp.time.return_value = NOW
    ctrl = MultiCoinGridController(
        config=MultiCoinGridConfig(**params), market_data_provider=mdp, actions_queue=MagicMock(),
        connectors={connector_name: MagicMock()}, update_interval=10.0,
    )
    ctrl.trend_calculator = MagicMock()
    ctrl.executors_info = []
    ctrl.last_switch_time = NOW - 7200.0  # hold time passed
    return ctrl


def attach(ctrl, custom_info, ticker_price=Decimal("0.3287"), ticker_age=10.0):
    ctrl.trend_calculator._last_price_cache = {COIN: (float(ticker_price), NOW - ticker_age)}
    trend = MagicMock()
    trend.current_price = ticker_price
    trend.trend_60m = 0.5
    trend.trend_240m = 1.0
    trend.trend_1440m = 2.0
    trend.last_updated = NOW - 10
    trend.consensus_trend_pct = Decimal("1.5")
    trend.trend_pct = Decimal("1.5")
    trend.trend_score = Decimal("1.5")
    ctrl.trend_calculator.get_trend.return_value = trend
    ctrl.entry_prices[COIN] = ENTRY
    ctrl.active_coin = COIN
    ctrl.active_executor_id = "icnt-2"
    ctrl.executors_info = [ExecutorInfo(
        id="icnt-2", timestamp=NOW, type="grid_executor", status=RunnableStatus.RUNNING,
        config=GridExecutorConfig(
            id="icnt-2", timestamp=NOW, controller_id="test_controller", connector_name="bitget",
            trading_pair=COIN, side=TradeType.BUY, start_price=Decimal("0.3150"), end_price=Decimal("0.3200"),
            limit_price=Decimal("0.3000"), total_amount_quote=Decimal("33"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.05"), take_profit=Decimal("0.02"),
                open_order_type=OrderType.LIMIT, take_profit_order_type=OrderType.LIMIT,
            ),
        ),
        net_pnl_pct=Decimal("0"), net_pnl_quote=Decimal("0"), cum_fees_quote=Decimal("0"),
        filled_amount_quote=Decimal("22.1"), is_active=True, is_trading=True,
        custom_info=custom_info, controller_id="test_controller",
    )]


STALE = Decimal("0.3178")
FRESH = Decimal("0.3287")


class TestIcntReconstruction:
    def test_legacy_formula_reproduces_premature_exit(self):
        ctrl = make_controller(grid_profit_exit_mode="legacy")
        attach(ctrl, icnt_info(STALE))
        assert ctrl.should_exit_position(COIN) == "grid_profit_exit"  # 2.57% − 0.31% = 2.26% ≥ 1.5%

    def test_total_net_on_deployed_capital_does_not_exit(self):
        ctrl = make_controller()  # bitget → total_net by default
        pnl = ctrl._total_net_grid_profit(icnt_info(STALE))
        assert pnl["deployed"] == pytest.approx(Decimal("22.1084"), abs=Decimal("1e-4"))
        assert pnl["total_pct"] == pytest.approx(1.197, abs=0.01)
        attach(ctrl, icnt_info(STALE))
        assert ctrl.should_exit_position(COIN) is None

    def test_fees_are_not_double_counted(self):
        ctrl = make_controller()
        pnl = ctrl._total_net_grid_profit(icnt_info(FRESH))
        exit_value = HELD_BASE * FRESH  # size_base × price
        assert pnl["exit_fee"] == pytest.approx(exit_value * TAKER, abs=Decimal("1e-9"))
        assert pnl["total"] == pytest.approx(REALIZED_NET + position_pnl(FRESH) - exit_value * TAKER,
                                             abs=Decimal("1e-9"))
        assert pnl["remaining_net"] == pytest.approx(position_pnl(FRESH) - exit_value * TAKER, abs=Decimal("1e-9"))

    def test_fresh_price_above_threshold_exits(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(FRESH))  # total ≈ 2.91% of deployed
        assert ctrl.should_exit_position(COIN) == "grid_profit_exit"


class TestTotalNetGuards:
    def test_unreliable_executor_price_blocks_profit_exit(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(FRESH, price_reliable=False))
        assert ctrl.should_exit_position(COIN) is None

    def test_hard_grace_period_is_respected(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(FRESH))
        ctrl.last_switch_time = NOW - 600.0  # 10 min < 30 min hold
        assert ctrl.should_exit_position(COIN) is None

    def test_active_trailing_is_not_interrupted(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(FRESH, trailing_active=True, trailing_stop_trigger_pct=Decimal("0.0246")))
        assert ctrl.should_exit_position(COIN) is None

    def test_emergency_exit_during_trailing_and_feed_outage(self):
        ctrl = make_controller()
        info = icnt_info(STALE, trailing_active=True, price_reliable=False)
        attach(ctrl, info, ticker_price=ENTRY * Decimal("0.87"))  # −13% on the independent ticker
        assert ctrl.should_exit_position(COIN) == "emergency_exit"

    def test_hard_stop_during_feed_outage(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(STALE, price_reliable=False), ticker_price=ENTRY * Decimal("0.84"))
        assert ctrl.should_exit_position(COIN) in ("emergency_exit", "hard_stop_exit")

    def test_remaining_profitability_option_off_by_default(self):
        info = icnt_info(Decimal("0.3170"), realized_pnl_quote=Decimal("0.80"))  # remaining slightly negative
        ctrl = make_controller()
        assert ctrl._total_net_grid_profit(info)["remaining_net"] < 0
        attach(ctrl, info)
        assert ctrl.should_exit_position(COIN) == "grid_profit_exit"
        ctrl = make_controller(grid_profit_exit_require_remaining_profitable=True)
        attach(ctrl, info)
        assert ctrl.should_exit_position(COIN) is None


class TestModeResolution:
    @pytest.mark.parametrize("connector,mode", [("bitget", "total_net"), ("kraken", "legacy"), ("okx", "legacy")])
    def test_default_mode_per_exchange(self, connector, mode):
        assert make_controller(connector_name=connector)._grid_profit_exit_mode() == mode

    def test_explicit_override(self):
        assert make_controller("kraken", grid_profit_exit_mode="total_net")._grid_profit_exit_mode() == "total_net"
        assert make_controller("bitget", grid_profit_exit_mode="legacy")._grid_profit_exit_mode() == "legacy"

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValidationError):
            make_controller(grid_profit_exit_mode="aggressive")

    @pytest.mark.parametrize("connector", ["kraken", "okx"])
    def test_kraken_okx_keep_legacy_exit(self, connector):
        ctrl = make_controller(connector_name=connector)
        attach(ctrl, icnt_info(STALE))
        assert ctrl.should_exit_position(COIN) == "grid_profit_exit"


class TestEmergencyExitFrozenTicker:
    """Controller ticker frozen at entry (3.5 h) while the market falls through the emergency threshold."""

    FROZEN_AGE = 3.5 * 3600

    def test_fresh_executor_bid_triggers_emergency_exit(self):
        crash = ENTRY * Decimal("0.87")  # −13% ≤ −12%
        ctrl = make_controller()
        attach(ctrl, icnt_info(crash, reliable_bid=crash, reliable_bid_ts=NOW - 2),
               ticker_price=ENTRY, ticker_age=self.FROZEN_AGE)
        assert ctrl.should_exit_position(COIN) == "emergency_exit"

    def test_hard_stop_from_fresh_executor_bid(self):
        crash = ENTRY * Decimal("0.84")  # −16%
        ctrl = make_controller(emergency_exit_pct=-20.0)
        attach(ctrl, icnt_info(crash, reliable_bid=crash, reliable_bid_ts=NOW - 2),
               ticker_price=ENTRY, ticker_age=self.FROZEN_AGE)
        assert ctrl.should_exit_position(COIN) == "hard_stop_exit"

    def test_stale_executor_bid_is_ignored(self):
        crash = ENTRY * Decimal("0.87")
        ctrl = make_controller()
        attach(ctrl, icnt_info(ENTRY, reliable_bid=crash, reliable_bid_ts=NOW - 120),
               ticker_price=ENTRY, ticker_age=self.FROZEN_AGE)
        assert ctrl.should_exit_position(COIN) is None

    def test_higher_executor_bid_never_weakens_ticker_emergency(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(ENTRY, reliable_bid=ENTRY, reliable_bid_ts=NOW - 2),
               ticker_price=ENTRY * Decimal("0.87"))
        assert ctrl.should_exit_position(COIN) == "emergency_exit"

    def test_no_fresh_price_escalates_once_without_exit(self):
        ctrl = make_controller()
        ctrl.logger = MagicMock(return_value=MagicMock())
        attach(ctrl, icnt_info(ENTRY, price_reliable=False, reliable_bid=None, reliable_bid_ts=NOW),
               ticker_price=ENTRY, ticker_age=self.FROZEN_AGE)
        assert ctrl.should_exit_position(COIN) is None
        assert ctrl.should_exit_position(COIN) is None
        critical = [c.args[0] for c in ctrl.logger.return_value.critical.call_args_list]
        assert sum("EMERGENCY_PRICE_STALE" in m for m in critical) == 1  # throttled

    @pytest.mark.parametrize("connector", ["kraken", "okx"])
    def test_kraken_okx_emergency_price_unchanged(self, connector):
        crash = ENTRY * Decimal("0.87")
        ctrl = make_controller(connector_name=connector)
        assert ctrl._emergency_reference_price(COIN, ENTRY) == ENTRY
        attach(ctrl, icnt_info(ENTRY, reliable_bid=crash, reliable_bid_ts=NOW - 2),
               ticker_price=ENTRY, ticker_age=self.FROZEN_AGE)
        assert ctrl.should_exit_position(COIN) != "emergency_exit"


class TestEmergencyPriceFreshnessOnly:
    """P0 (commit 401dfd7d): min(ticker, bid) let a stale LOW ticker trigger an emergency exit."""

    STALE_AGE = 3.5 * 3600
    CRASH = ENTRY * Decimal("0.87")  # −13%

    def test_stale_low_ticker_with_fresh_bid_does_not_exit(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(ENTRY, reliable_bid=ENTRY, reliable_bid_ts=NOW - 2),
               ticker_price=self.CRASH, ticker_age=self.STALE_AGE)
        assert ctrl._emergency_reference_price(COIN, self.CRASH) == ENTRY
        assert ctrl.should_exit_position(COIN) not in ("emergency_exit", "hard_stop_exit")

    def test_stale_low_ticker_without_fresh_bid_does_not_exit(self):
        ctrl = make_controller()
        ctrl.logger = MagicMock(return_value=MagicMock())
        attach(ctrl, icnt_info(ENTRY, price_reliable=False, reliable_bid=None, reliable_bid_ts=None),
               ticker_price=ENTRY * Decimal("0.80"), ticker_age=self.STALE_AGE)
        assert ctrl._emergency_reference_price(COIN, ENTRY * Decimal("0.80")) is None
        assert ctrl.should_exit_position(COIN) not in ("emergency_exit", "hard_stop_exit")
        critical = [c.args[0] for c in ctrl.logger.return_value.critical.call_args_list]
        assert any("EMERGENCY_PRICE_STALE" in m for m in critical)

    def test_fresh_ticker_only_real_crash_exits(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(self.CRASH, reliable_bid=None, reliable_bid_ts=None), ticker_price=self.CRASH)
        assert ctrl.should_exit_position(COIN) == "emergency_exit"

    def test_fresh_bid_only_real_crash_exits(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(self.CRASH, reliable_bid=self.CRASH, reliable_bid_ts=NOW - 1),
               ticker_price=ENTRY, ticker_age=self.STALE_AGE)
        assert ctrl.should_exit_position(COIN) == "emergency_exit"

    def test_both_fresh_uses_conservative_lower_price(self):
        ctrl = make_controller()
        attach(ctrl, icnt_info(self.CRASH, reliable_bid=self.CRASH, reliable_bid_ts=NOW - 1), ticker_price=ENTRY)
        assert ctrl._emergency_reference_price(COIN, ENTRY) == self.CRASH
        assert ctrl.should_exit_position(COIN) == "emergency_exit"

    @pytest.mark.parametrize("bid_ts", [NOW + 5, float("nan"), "bad"])
    def test_future_or_invalid_bid_timestamp_rejected(self, bid_ts):
        ctrl = make_controller()
        attach(ctrl, icnt_info(ENTRY, reliable_bid=self.CRASH, reliable_bid_ts=bid_ts), ticker_price=ENTRY)
        assert ctrl._emergency_reference_price(COIN, ENTRY) == ENTRY

    @pytest.mark.parametrize("connector", ["kraken", "okx"])
    def test_kraken_okx_still_use_ticker_unchanged(self, connector):
        ctrl = make_controller(connector_name=connector)
        attach(ctrl, icnt_info(ENTRY), ticker_price=self.CRASH, ticker_age=self.STALE_AGE)
        assert ctrl._emergency_reference_price(COIN, self.CRASH) == self.CRASH
        assert ctrl.should_exit_position(COIN) == "emergency_exit"  # legacy behaviour kept
