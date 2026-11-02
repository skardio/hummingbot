"""Regime telemetry (entry_regime, regime at every BUY fill, exit regime): observation only, idempotent, no look-ahead."""
import sqlite3
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor import grid_executor as grid_module
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors import CloseType, EarlyStopReason
from multi_coin_grid_pro.persistence import regime_telemetry as rt
from multi_coin_grid_pro.persistence.regime_telemetry import RegimeTelemetryStore

BOT = "bitget_usdt"
T0 = 1_000_000.0


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    rt.clear_regime()
    store = RegimeTelemetryStore(str(tmp_path / "regime.db"))
    monkeypatch.setattr(grid_module, "_get_regime_store", lambda: store)
    yield store
    rt.clear_regime()


@pytest.fixture
def store(_isolated):
    return _isolated


def make_executor(executor_id="ex-1", bot=BOT, connector="bitget", clock=None):
    clock = clock if clock is not None else {"now": T0}
    market = MagicMock()
    market_info = MagicMock()
    market_info.market = market
    strategy = MagicMock(spec=ScriptStrategyBase)
    type(strategy).market_info = PropertyMock(return_value=market_info)
    type(strategy).current_timestamp = PropertyMock(side_effect=lambda: clock["now"])
    conn = MagicMock(spec=ExchangePyBase)
    type(conn).trading_rules = PropertyMock(return_value={
        "BCH-USDT": TradingRule("BCH-USDT", min_order_value=Decimal("5"), min_order_size=Decimal("0.0001"),
                                min_price_increment=Decimal("0.1"))})
    strategy.connectors = {connector: conn}
    config = GridExecutorConfig(
        id=executor_id, timestamp=T0, side=TradeType.BUY, connector_name=connector, trading_pair="BCH-USDT",
        start_price=Decimal("261.4"), end_price=Decimal("271.4"), total_amount_quote=Decimal("29"),
        min_spread_between_orders=Decimal("0.005"), min_order_amount_quote=Decimal("10"),
        limit_price=Decimal("248.3"),
        triple_barrier_config=TripleBarrierConfig(take_profit=Decimal("0.075"), stop_loss=Decimal("0.05")),
        custom_info={"bot_instance_id": bot, "regime_telemetry_max_age_sec": 300.0})
    with patch("hummingbot.strategy_v2.executors.executor_base.ExecutorBase.get_price", return_value=Decimal("253.2")):
        ex = GridExecutor(strategy, config, update_interval=0.5)
    ex.update_tracked_orders_with_order_id = MagicMock()
    ex._order_belongs_to_this_executor = MagicMock(return_value=True)
    ex._clock = clock
    return ex


def fill(ex, side, order_id, trade_id, ts, price="253.2", amount="0.1"):
    ex._clock["now"] = ts
    ex.process_order_filled_event(None, None, OrderFilledEvent(
        timestamp=ts, order_id=order_id, trading_pair="BCH-USDT", trade_type=side, order_type=OrderType.LIMIT,
        price=Decimal(price), amount=Decimal(amount), trade_fee=MagicMock(), exchange_trade_id=trade_id))


def detect(regime, at, bot=BOT, source="regime_detector:btc_direct/BTC-USDT"):
    rt.publish_regime(bot, regime, source, at, 1.0)


class TestEntryAndBuyRegime:
    def test_first_buy_in_bull_sets_entry_regime_once(self, store):
        detect("BULL", T0 - 10)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        row = store.get_executor("ex-1")
        assert (row["entry_regime"], row["entry_regime_status"]) == ("BULL", "VALID")
        assert row["entry_regime_timestamp"] == T0 - 10 and row["entry_fill_timestamp"] == T0
        assert row["entry_regime_source"] == "regime_detector:btc_direct/BTC-USDT"
        info = ex.get_custom_info()
        assert info["entry_regime"] == "BULL" and info["entry_regime_timestamp"] == T0 - 10

    def test_extra_buy_after_bull_to_bear_keeps_entry_and_records_new_regime(self, store):
        detect("BULL", T0 - 10)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        detect("BEAR", T0 + 50)
        fill(ex, TradeType.BUY, "o2", "t2", T0 + 100)
        buys = store.get_buy_fills("ex-1")
        assert [b["regime"] for b in buys] == ["BULL", "BEAR"]
        assert [b["buy_sequence"] for b in buys] == [1, 2]
        assert store.get_executor("ex-1")["entry_regime"] == "BULL"
        assert ex.get_custom_info()["entry_regime"] == "BULL"

    def test_chop_is_recorded_as_valid(self, store):
        detect("CHOP", T0 - 5)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        assert store.get_buy_fills("ex-1")[0]["regime"] == "CHOP"
        assert store.get_executor("ex-1")["entry_regime"] == "CHOP"

    def test_buy_row_has_all_required_fields(self, store):
        detect("BULL", T0 - 10)
        fill(make_executor(), TradeType.BUY, "o1", "t1", T0, price="250.5", amount="0.2")
        row = store.get_buy_fills("ex-1")[0]
        assert (row["executor_id"], row["trading_pair"], row["exchange"]) == ("ex-1", "BCH-USDT", "bitget")
        assert (row["order_id"], row["fill_key"], row["fill_timestamp"]) == ("o1", "t1", T0)
        assert (row["fill_price"], row["fill_amount"]) == (250.5, 0.2)
        assert (row["regime_status"], row["regime_age_sec"], row["regime_timestamp"]) == ("VALID", 10.0, T0 - 10)


class TestMissingStaleAndLookAhead:
    def test_no_snapshot_is_unknown_with_reason_never_bull_or_bear(self, store):
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        row = store.get_executor("ex-1")
        assert row["entry_regime"] == "UNKNOWN" and row["entry_regime_status"] == "UNKNOWN"
        assert "no_regime_snapshot_published" in row["entry_regime_reason"]
        assert store.get_buy_fills("ex-1")[0]["regime"] == "UNKNOWN"

    def test_stale_regime_keeps_value_in_buy_row_but_not_as_entry_regime(self, store):
        detect("BULL", T0 - 1000)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        buy = store.get_buy_fills("ex-1")[0]
        assert (buy["regime"], buy["regime_status"]) == ("BULL", "STALE")
        entry = store.get_executor("ex-1")
        assert entry["entry_regime"] == "UNKNOWN" and entry["entry_regime_status"] == "STALE"
        assert "last known BULL" in entry["entry_regime_reason"]

    def test_failed_detection_ages_the_last_regime_into_stale_with_reason(self, store):
        detect("BULL", T0 - 100)
        rt.publish_regime_failure(BOT, "regime_detector", "detection error: boom", T0 - 50)
        fill(make_executor(), TradeType.BUY, "o1", "t1", T0)
        assert store.get_buy_fills("ex-1")[0]["regime_status"] == "VALID"  # still within 300s
        fill(make_executor("ex-2"), TradeType.BUY, "o2", "t2", T0 + 400)
        stale = store.get_buy_fills("ex-2")[0]
        assert stale["regime_status"] == "STALE" and "boom" in stale["regime_reason"]

    def test_detector_without_any_value_is_unknown(self, store):
        rt.publish_regime_failure(BOT, "regime_detector", "regime detector disabled or unavailable", T0 - 5)
        fill(make_executor(), TradeType.BUY, "o1", "t1", T0)
        assert "disabled" in store.get_executor("ex-1")["entry_regime_reason"]

    def test_regime_published_after_the_fill_is_never_used(self, store):
        detect("BULL", T0 - 10)
        detect("BEAR", T0 + 5)  # published after the fill moment
        fill(make_executor(), TradeType.BUY, "o1", "t1", T0)
        assert store.get_buy_fills("ex-1")[0]["regime"] == "BULL"

    def test_only_future_snapshots_means_unknown(self, store):
        detect("BEAR", T0 + 5)
        fill(make_executor(), TradeType.BUY, "o1", "t1", T0)
        assert store.get_buy_fills("ex-1")[0]["regime_status"] == "UNKNOWN"

    def test_bots_do_not_see_each_others_regime(self, store):
        detect("BEAR", T0 - 5, bot="kraken_usd")
        fill(make_executor(), TradeType.BUY, "o1", "t1", T0)
        assert store.get_buy_fills("ex-1")[0]["regime_status"] == "UNKNOWN"


class TestPartialFillsRetriesOwnership:
    def test_partial_fills_are_separate_rows_and_replays_are_ignored(self, store):
        detect("BULL", T0 - 10)
        ex = make_executor()
        for i, trade_id in enumerate(("t1", "t2", "t3")):
            fill(ex, TradeType.BUY, "o1", trade_id, T0 + i, amount="0.05")
        fill(ex, TradeType.BUY, "o1", "t2", T0 + 1, amount="0.05")  # replay of the same trade
        buys = store.get_buy_fills("ex-1")
        assert [b["fill_key"] for b in buys] == ["t1", "t2", "t3"]
        assert store.get_executor("ex-1")["entry_fill_timestamp"] == T0

    def test_same_trade_replayed_into_a_fresh_process_does_not_duplicate(self, store):
        detect("BULL", T0 - 10)
        fill(make_executor(), TradeType.BUY, "o1", "t1", T0)
        fill(make_executor(), TradeType.BUY, "o1", "t1", T0)  # new instance, same executor id
        assert len(store.get_buy_fills("ex-1")) == 1

    def test_fill_without_exchange_trade_id_gets_a_deterministic_key(self, store):
        detect("BULL", T0 - 10)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "", T0)
        fill(ex, TradeType.BUY, "o1", "", T0)
        assert len(store.get_buy_fills("ex-1")) == 1

    def test_events_of_other_executors_are_ignored(self, store):
        detect("BULL", T0 - 10)
        ex = make_executor()
        ex._order_belongs_to_this_executor.return_value = False
        fill(ex, TradeType.BUY, "foreign", "t1", T0)
        assert store.get_executor("ex-1") is None


class TestExit:
    def test_exit_with_sell_records_regime_at_close_and_last_sell(self, store):
        detect("BULL", T0 - 10)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        detect("BEAR", T0 + 90)
        fill(ex, TradeType.SELL, "c1", "s1", T0 + 100)
        detect("BEAR", T0 + 190)
        ex._clock["now"] = T0 + 200
        ex.close_type = CloseType.TAKE_PROFIT
        ex._record_regime_exit()
        row = store.get_executor("ex-1")
        assert (row["exit_state"], row["exit_regime"], row["exit_regime_status"]) == ("OBSERVED", "BEAR", "VALID")
        assert row["exit_timestamp"] == T0 + 200 and row["exit_close_type"] == "TAKE_PROFIT"
        assert row["exit_had_sell_fill"] == 1
        assert (row["last_sell_fill_regime"], row["last_sell_fill_timestamp"]) == ("BEAR", T0 + 100)
        assert row["entry_regime"] == "BULL"
        info = ex.get_custom_info()
        assert info["exit_regime"] == "BEAR" and info["exit_had_sell_fill"] is True

    def test_exit_without_sell_is_explicit_and_not_a_sale(self, store):
        detect("CHOP", T0 - 10)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        ex._clock["now"] = T0 + 60
        ex.close_type = CloseType.FAILED
        ex._early_stop_reason = EarlyStopReason.ORDER_REJECTED
        ex._record_regime_exit()
        row = store.get_executor("ex-1")
        assert row["exit_had_sell_fill"] == 0 and row["last_sell_fill_timestamp"] is None
        assert row["exit_close_type"] == "FAILED" and row["exit_close_reason"] == "ORDER_REJECTED"

    def test_executor_without_any_buy_gets_no_entry_regime(self, store):
        detect("BULL", T0 - 10)
        ex = make_executor()
        ex.close_type = CloseType.NO_FILL_TIMEOUT
        ex._record_regime_exit()
        row = store.get_executor("ex-1")
        assert row["entry_regime"] is None and row["entry_regime_status"] == "NO_BUY_FILL"
        assert row["exit_had_sell_fill"] == 0
        assert "entry_regime" not in ex.get_custom_info()
        assert store.get_buy_fills("ex-1") == []

    def test_exit_is_recorded_once_even_if_both_close_paths_fire(self, store):
        detect("BULL", T0 - 10)
        ex = make_executor()
        ex._clock["now"] = T0 + 10
        ex.close_type = CloseType.EARLY_STOP
        ex._record_regime_exit()
        detect("BEAR", T0 + 15)
        ex._clock["now"] = T0 + 20
        ex._record_regime_exit()
        assert store.get_executor("ex-1")["exit_regime"] == "BULL"

    def test_store_level_exit_cannot_be_overwritten(self, store):
        ref = rt.ExecutorRef("ex-9", "bitget", BOT, "BCH-USDT")
        first = rt.RegimeObservation("BULL", "VALID", "s", T0, 0.0)
        later = rt.RegimeObservation("BEAR", "VALID", "s", T0 + 5, 0.0)
        store.record_exit(ref, T0, first, "TAKE_PROFIT", "", True, 10.0)
        store.record_exit(ref, T0 + 5, later, "STOP_LOSS", "", False, 0.0)
        assert store.get_executor("ex-9")["exit_regime"] == "BULL"

    def test_exit_decision_is_recorded_once_at_first_early_stop(self, store):
        detect("BULL", T0 - 10)
        ex = make_executor()
        ex._early_stop_reason = EarlyStopReason.STOP_LOSS
        ex._clock["now"] = T0 + 30
        ex._record_regime_exit_decision()
        detect("BEAR", T0 + 35)
        ex._clock["now"] = T0 + 40
        ex._record_regime_exit_decision()
        row = store.get_executor("ex-1")
        assert (row["exit_decision_regime"], row["exit_decision_timestamp"], row["exit_decision_reason"]) == (
            "BULL", T0 + 30, "STOP_LOSS")


class TestPersistenceAndRestart:
    def test_data_survives_reopening_the_database(self, store, tmp_path):
        detect("BULL", T0 - 10)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        ex.close_type = CloseType.TAKE_PROFIT
        ex._record_regime_exit()
        reopened = RegimeTelemetryStore(str(tmp_path / "regime.db"))
        assert reopened.get_executor("ex-1")["exit_regime"] == "BULL"
        assert len(reopened.get_buy_fills("ex-1")) == 1
        con = sqlite3.connect(str(tmp_path / "regime.db"))
        assert con.execute("PRAGMA user_version").fetchone()[0] == rt.SCHEMA_VERSION

    def test_restart_marks_unclosed_executors_instead_of_inventing_an_exit(self, store, tmp_path):
        detect("BULL", T0 - 10)
        fill(make_executor("alive"), TradeType.BUY, "o1", "t1", T0)
        fill(make_executor("other-bot", bot="kraken_usd", connector="kraken"), TradeType.BUY, "o2", "t2", T0)
        rt.clear_regime()  # new process: no snapshots
        reopened = RegimeTelemetryStore(str(tmp_path / "regime.db"))
        assert reopened.mark_unobserved_exits(BOT, "bitget") == 1
        assert reopened.mark_unobserved_exits(BOT, "bitget") == 0  # idempotent
        row = reopened.get_executor("alive")
        assert row["exit_state"] == "NOT_OBSERVED_RESTART" and row["exit_regime"] is None
        assert row["entry_regime"] == "BULL" and len(reopened.get_buy_fills("alive")) == 1
        assert reopened.get_executor("other-bot")["exit_state"] is None

    def test_exit_after_restart_marker_is_still_possible_only_for_new_state(self, store):
        ref = rt.ExecutorRef("ex-5", "bitget", BOT, "BCH-USDT")
        store.record_buy_fill(ref, "o", "k", 1, T0, 1.0, 1.0, rt.RegimeObservation("BULL", "VALID", "s", T0, 0.0), True)
        store.mark_unobserved_exits(BOT, "bitget")
        assert store.record_exit(ref, T0 + 1, rt.RegimeObservation("BEAR", "VALID", "s", T0, 1.0),
                                 "TAKE_PROFIT", "", True, 5.0)
        assert store.get_executor("ex-5")["exit_state"] == "NOT_OBSERVED_RESTART"  # marker is never rewritten


class TestNoTradingImpact:
    def test_database_failure_never_raises_and_does_not_change_executor_state(self, store, monkeypatch):
        detect("BULL", T0 - 10)
        store._conn.close()
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        ex.close_type = CloseType.TAKE_PROFIT
        ex._record_regime_exit()
        assert store.record_sell_fill(rt.ExecutorRef("x", "b", "k", "p"), T0,
                                      rt.RegimeObservation("BULL", "VALID", "s", T0, 0.0)) is False
        assert ex.close_type == CloseType.TAKE_PROFIT

    def test_unavailable_store_is_tolerated(self, monkeypatch):
        monkeypatch.setattr(grid_module, "_get_regime_store", lambda: None)
        detect("BULL", T0 - 10)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        assert ex.get_custom_info()["entry_regime"] == "BULL"

    def test_store_exception_is_swallowed(self, monkeypatch):
        def boom():
            raise RuntimeError("disk full")
        monkeypatch.setattr(grid_module, "_get_regime_store", boom)
        detect("BULL", T0 - 10)
        ex = make_executor()
        fill(ex, TradeType.BUY, "o1", "t1", T0)
        ex.close_type = CloseType.TAKE_PROFIT
        ex._record_regime_exit()

    def test_executor_state_is_identical_with_telemetry_disabled(self, store, monkeypatch):
        detect("BULL", T0 - 10)
        on = make_executor("a")
        fill(on, TradeType.BUY, "o1", "t1", T0)
        monkeypatch.setattr(grid_module, "HAS_REGIME_TELEMETRY", False)
        off = make_executor("b")
        fill(off, TradeType.BUY, "o1", "t1", T0)
        regime_keys = {k for k in on.get_custom_info() if "regime" in k or k == "entry_fill_timestamp"}
        strip = lambda info: {k: v for k, v in info.items() if k not in regime_keys}  # noqa: E731
        assert strip(on.get_custom_info()) == strip(off.get_custom_info())
        assert regime_keys and not any("regime" in k for k in off.get_custom_info())
        assert on._last_fill_timestamp == off._last_fill_timestamp


class TestBotConfigurations:
    @pytest.mark.parametrize("name", ["bitget", "kraken_usd"])
    def test_both_bots_share_the_contract(self, name):
        from multi_coin_grid_pro.config.config_manager import ConfigManager
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.spot_bitget.config_manager import SpotGridBitgetConfigManager
        from multi_coin_grid_pro.spot_bitget.config_schema import SpotGridBitgetConfig
        if name == "bitget":
            cfg = SpotGridBitgetConfig(**{**SpotGridBitgetConfigManager().load_config(), "telegram": {}})
        else:
            cfg = MultiCoinGridConfig(**{**ConfigManager().load_config("spot_grid_kraken_usd"), "telegram": {}})
        assert cfg.regime_telemetry_max_age_seconds == 300
        assert cfg.adaptive_regime_detection["enabled"] is True

    def test_controller_key_matches_the_executor_key_and_publishes_failure_without_detector(self, store, monkeypatch):
        from datetime import datetime
        from unittest.mock import AsyncMock, Mock

        from multi_coin_grid_pro.config.config_manager import ConfigManager
        from multi_coin_grid_pro.controllers import multi_coin_grid_controller as ctrl_module
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        monkeypatch.setattr(ctrl_module, "get_regime_store", lambda: store)
        cfg = MultiCoinGridConfig(**{**ConfigManager().load_config("spot_grid_kraken_usd"), "telegram": {}})
        provider = MagicMock()
        provider.time = Mock(return_value=datetime.now().timestamp())
        with patch.object(ctrl_module, "CoinDiscovery"), patch.object(ctrl_module, "TrendCalculator"):
            ctrl = ctrl_module.MultiCoinGridController(
                config=cfg, market_data_provider=provider, actions_queue=[],
                connectors={cfg.connector_name: AsyncMock()}, update_interval=10.0)
        assert ctrl._regime_bot_key() == str(getattr(cfg, "instance_id", None) or cfg.controller_name)
        ctrl.regime_detector = None
        ctrl._init_regime_telemetry()
        obs = rt.observe_regime(ctrl._regime_bot_key(), provider.time() + 1)
        assert obs.status == "UNKNOWN" and "disabled" in obs.reason
