"""
Unit tests for EPIC_GRID_BOT_RISK_AND_EDGE_IMPROVEMENTS user stories.

US2  — fee_aware_timeout_bypass_sec: after the hold limit the fee-aware guard is lifted.
US4  — HARD_CAP_TIME_LIMIT is NOT in _is_fee_guarded_close_type (must always close).
US10 — FEE_AWARE_EXIT_BLOCKED log is rate-limited to once per 60 s per close_type.
US5  — resolve_connector_config() returns per-connector overrides with correct precedence.
US6  — get_effective_blacklist() merges global + per-connector blacklists.
US7  — _warn_blacklist_profile_overlap() logs when a coin is in both blacklist and coin_profiles.
"""

from decimal import Decimal
from test.isolated_asyncio_wrapper_test_case import IsolatedAsyncioWrapperTestCase
from test.logger_mixin_for_test import LoggerMixinForTest
from unittest.mock import MagicMock, PropertyMock, patch

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import TradeType
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors import CloseType

# ---------------------------------------------------------------------------
# Shared executor-level test helpers
# ---------------------------------------------------------------------------


def _make_strategy(timestamp: float = 1_000_000.0) -> MagicMock:
    market = MagicMock()
    market_info = MagicMock()
    market_info.market = market
    strategy = MagicMock(spec=ScriptStrategyBase)
    type(strategy).market_info = PropertyMock(return_value=market_info)
    type(strategy).trading_pair = PropertyMock(return_value="ETH-USDT")
    type(strategy).current_timestamp = PropertyMock(return_value=timestamp)
    strategy.cancel.return_value = None
    connector = MagicMock(spec=ExchangePyBase)
    type(connector).trading_rules = PropertyMock(return_value={
        "ETH-USDT": TradingRule(
            trading_pair="ETH-USDT",
            min_order_value=Decimal("5"),
            min_price_increment=Decimal("0.1"),
        )
    })
    strategy.connectors = {"binance": connector}
    return strategy


def _make_grid_config(**custom_info_overrides) -> GridExecutorConfig:
    custom_info = {
        "no_fill_timeout_sec": 1800,
        "no_progress_timeout_sec": 2700,
        "fee_aware_timeout_bypass_sec": 0,
        "max_hold_time_sec": 5400,
        "fee_aware_exit_fee_rate": 0.002,  # avoids MagicMock from _get_fee_rates() in tests
    }
    custom_info.update(custom_info_overrides)
    return GridExecutorConfig(
        id="test-epic",
        timestamp=1_000_000.0,
        side=TradeType.BUY,
        connector_name="binance",
        trading_pair="ETH-USDT",
        start_price=Decimal("100"),
        end_price=Decimal("120"),
        total_amount_quote=Decimal("100"),
        min_spread_between_orders=Decimal("0.01"),
        min_order_amount_quote=Decimal("9"),
        limit_price=Decimal("90"),
        triple_barrier_config=TripleBarrierConfig(
            take_profit=Decimal("0.05"),
            stop_loss=Decimal("0.015"),
        ),
        custom_info=custom_info,
    )


def _make_executor(
    config: GridExecutorConfig,
    start_ts: float = 1_000_000.0,
    strategy_ts: float = None,
) -> GridExecutor:
    if strategy_ts is None:
        strategy_ts = start_ts
    strategy = _make_strategy(timestamp=strategy_ts)
    # Patch get_price on ExecutorBase (where it is actually defined) so that
    # _generate_grid_levels() receives a valid Decimal price during __init__.
    with patch("hummingbot.strategy_v2.executors.executor_base.ExecutorBase.get_price",
               return_value=Decimal("110")):
        executor = GridExecutor(strategy, config, update_interval=0.5)
    executor._start_timestamp = start_ts
    return executor


# ---------------------------------------------------------------------------
# US4 — HARD_CAP_TIME_LIMIT must NOT be fee-guarded
# ---------------------------------------------------------------------------

class TestUS4HardCapNotFeeGuarded(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """US4: Absolute max hold (HARD_CAP_TIME_LIMIT) must always close."""

    def setUp(self):
        super().setUp()
        config = _make_grid_config()
        self.executor = _make_executor(config)
        self.set_loggers([self.executor.logger()])

    def test_hard_cap_not_in_fee_guarded_set(self):
        """HARD_CAP_TIME_LIMIT returns False from _is_fee_guarded_close_type."""
        result = self.executor._is_fee_guarded_close_type(CloseType.HARD_CAP_TIME_LIMIT)
        self.assertFalse(result, "HARD_CAP_TIME_LIMIT must NOT be fee-guarded (US4)")

    def test_time_limit_still_fee_guarded(self):
        """TIME_LIMIT (soft hold) remains fee-guarded."""
        result = self.executor._is_fee_guarded_close_type(CloseType.TIME_LIMIT)
        self.assertTrue(result, "TIME_LIMIT should still be fee-guarded")

    def test_no_progress_not_fee_guarded(self):
        """NO_PROGRESS_TIMEOUT must NOT be fee-guarded (stuck-CLOSING fix).

        A deadlocked grid cannot reach break-even; guarding this close type
        creates an infinite GRACEFUL_RETRY → FEE_AWARE_EXIT_BLOCKED loop.
        """
        result = self.executor._is_fee_guarded_close_type(CloseType.NO_PROGRESS_TIMEOUT)
        self.assertFalse(result, "NO_PROGRESS_TIMEOUT must NOT be fee-guarded (safety exit)")

    def test_stop_loss_never_fee_guarded(self):
        """STOP_LOSS was never fee-guarded and must still return False."""
        result = self.executor._is_fee_guarded_close_type(CloseType.STOP_LOSS)
        self.assertFalse(result, "STOP_LOSS must never be fee-guarded")

    def test_hard_cap_fee_aware_close_allowed_returns_true(self):
        """_fee_aware_close_allowed returns True for HARD_CAP_TIME_LIMIT."""
        result = self.executor._fee_aware_close_allowed(CloseType.HARD_CAP_TIME_LIMIT)
        self.assertTrue(result, "_fee_aware_close_allowed must return True for HARD_CAP_TIME_LIMIT")


# ---------------------------------------------------------------------------
# US2 — fee_aware_timeout_bypass_sec wires through to the guard
# ---------------------------------------------------------------------------

class TestUS2FeeAwareBypass(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """US2: After bypass_sec the fee-aware guard is overridden."""

    def _executor_with_age(self, bypass_sec: int, age_sec: float) -> GridExecutor:
        """Build executor where age_sec time has elapsed since start."""
        start_ts = 1_000_000.0
        now_ts = start_ts + age_sec
        config = _make_grid_config(fee_aware_timeout_bypass_sec=bypass_sec)
        executor = _make_executor(config, start_ts=start_ts, strategy_ts=now_ts)
        # Simulate a non-zero position so the fee-guard reaches the break-even check
        executor.position_size_base = Decimal("1")
        executor.position_size_quote = Decimal("110")
        executor.position_break_even_price = Decimal("110")
        executor.position_fees_quote = Decimal("0")
        return executor

    def test_bypass_before_threshold_does_not_log_forced(self):
        """If age < bypass_sec the bypass is NOT applied; BYPASS_FORCED is not logged."""
        executor = self._executor_with_age(bypass_sec=3600, age_sec=1800)
        self.set_loggers([executor.logger()])
        # Use TIME_LIMIT — it stays fee-guarded so the time-bypass path is exercised.
        executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=Decimal("80"))
        self.assertFalse(
            self.is_partially_logged("WARNING", "FEE_AWARE_BYPASS_FORCED"),
            "Bypass must NOT trigger before threshold (US2)",
        )

    def test_bypass_at_threshold_overrides_guard(self):
        """If age >= bypass_sec the guard is overridden and True is returned."""
        bypass_sec = 3600
        executor = self._executor_with_age(bypass_sec=bypass_sec, age_sec=bypass_sec + 1)
        self.set_loggers([executor.logger()])
        # Use TIME_LIMIT — it stays fee-guarded so the time-bypass path is exercised.
        result = executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=Decimal("80"))
        self.assertTrue(result, "Fee-aware guard must be overridden after bypass_sec (US2)")
        self.assertTrue(
            self.is_partially_logged("WARNING", "FEE_AWARE_BYPASS_FORCED"),
            "BYPASS_FORCED warning must be emitted (US2)",
        )

    def test_bypass_zero_never_overrides(self):
        """bypass_sec=0 disables the time-based bypass entirely."""
        executor = self._executor_with_age(bypass_sec=0, age_sec=999_999)
        self.set_loggers([executor.logger()])
        # Use TIME_LIMIT — it stays fee-guarded so the time-bypass path is exercised.
        executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=Decimal("80"))
        self.assertFalse(
            self.is_partially_logged("WARNING", "FEE_AWARE_BYPASS_FORCED"),
            "bypass_sec=0 must never trigger BYPASS_FORCED (US2)",
        )


# ---------------------------------------------------------------------------
# US10 — FEE_AWARE_EXIT_BLOCKED log rate limiting
# ---------------------------------------------------------------------------

class TestUS10LogRateLimiting(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """US10: BLOCKED log for a given close_type fires at most once per 60 s."""

    def setUp(self):
        super().setUp()
        start_ts = 1_000_000.0
        config = _make_grid_config(fee_aware_timeout_bypass_sec=0)
        self.executor = _make_executor(config, start_ts=start_ts, strategy_ts=start_ts)
        # Put executor in a state where the fee-guard BLOCKS (position below break-even):
        # position_size_base > 0 → break-even check runs; price=80 < break_even=110.
        self.executor.position_size_base = Decimal("1")
        self.executor.position_size_quote = Decimal("110")
        self.executor.position_break_even_price = Decimal("110")
        self.executor.position_fees_quote = Decimal("0")
        self.set_loggers([self.executor.logger()])

    def _advance_timestamp(self, delta: float):
        current = self.executor._strategy.current_timestamp
        type(self.executor._strategy).current_timestamp = PropertyMock(return_value=current + delta)

    def test_first_block_logs_immediately(self):
        """First BLOCKED call always logs."""
        self.executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=Decimal("80"))
        self.assertTrue(
            self.is_partially_logged("WARNING", "FEE_AWARE_EXIT_BLOCKED"),
            "First BLOCKED call must log immediately (US10)",
        )

    def test_second_block_within_60s_suppressed(self):
        """A second BLOCKED call within 60 s produces no additional log line."""
        price = Decimal("80")
        self.executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=price)
        first_count = sum(
            1 for r in self.log_records if "FEE_AWARE_EXIT_BLOCKED" in r.getMessage()
        )
        # Advance only 30 s (within rate-limit window)
        self._advance_timestamp(30)
        self.executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=price)
        second_count = sum(
            1 for r in self.log_records if "FEE_AWARE_EXIT_BLOCKED" in r.getMessage()
        )
        self.assertEqual(first_count, second_count,
                         "Second BLOCKED within 60 s must NOT log again (US10)")

    def test_block_after_60s_logs_again_with_count(self):
        """After 60 s a new BLOCKED log is emitted with accumulated count."""
        price = Decimal("80")
        self.executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=price)
        self._advance_timestamp(30)  # suppressed
        self.executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=price)
        self._advance_timestamp(31)  # now > 60 s → logs again
        self.executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=price)
        self.assertTrue(
            self.is_partially_logged("WARNING", "\u00d72"),
            "Rate-limited log must include accumulated count \u00d72 (US10)",
        )

    def test_different_close_types_have_independent_rate_limits(self):
        """Each close_type has its own 60 s rate-limit bucket."""
        price = Decimal("80")
        self.executor._fee_aware_close_allowed(CloseType.TIME_LIMIT, current_price=price)
        self.executor._fee_aware_close_allowed(CloseType.EARLY_STOP, current_price=price)
        blocked_count = sum(
            1 for r in self.log_records if "FEE_AWARE_EXIT_BLOCKED" in r.getMessage()
        )
        self.assertEqual(blocked_count, 2,
                         "Each close_type gets its own rate-limit bucket (US10)")


# ---------------------------------------------------------------------------
# US5 — connector_overrides / resolve_connector_config
# ---------------------------------------------------------------------------

class TestUS5ConnectorOverrides(IsolatedAsyncioWrapperTestCase):
    """US5: per-connector overrides take precedence over global config values."""

    def test_resolve_no_overrides_returns_empty(self):
        """With no connector_overrides configured, resolve returns {}."""
        cfg = MultiCoinGridConfig()
        result = cfg.resolve_connector_config("kraken_spot")
        self.assertEqual(result, {})

    def test_resolve_returns_matching_connector(self):
        """resolve_connector_config returns the correct connector's dict."""
        cfg = MultiCoinGridConfig(connector_overrides={
            "kraken_spot": {"min_grid_level_spacing_pct": 0.75},
            "bitget_spot": {"min_grid_level_spacing_pct": 0.50},
        })
        result = cfg.resolve_connector_config("kraken_spot")
        self.assertEqual(result["min_grid_level_spacing_pct"], 0.75)

    def test_resolve_unknown_connector_returns_empty(self):
        """An unconfigured connector name returns {}."""
        cfg = MultiCoinGridConfig(connector_overrides={
            "kraken_spot": {"min_grid_level_spacing_pct": 0.75},
        })
        result = cfg.resolve_connector_config("okx_spot")
        self.assertEqual(result, {})

    def test_resolve_does_not_mutate_original(self):
        """resolve_connector_config returns a copy, not the original dict."""
        cfg = MultiCoinGridConfig(connector_overrides={
            "kraken_spot": {"min_grid_level_spacing_pct": 0.75},
        })
        result = cfg.resolve_connector_config("kraken_spot")
        result["min_grid_level_spacing_pct"] = 999
        self.assertEqual(
            cfg.resolve_connector_config("kraken_spot")["min_grid_level_spacing_pct"],
            0.75,
            "resolve_connector_config must return a copy (not a reference)",
        )


# ---------------------------------------------------------------------------
# US6 — get_effective_blacklist merges global + connector blacklists
# ---------------------------------------------------------------------------

class TestUS6EffectiveBlacklist(IsolatedAsyncioWrapperTestCase):
    """US6: effective blacklist = global union connector-specific blacklist."""

    def test_empty_config_returns_empty_set(self):
        cfg = MultiCoinGridConfig()
        result = cfg.get_effective_blacklist("kraken_spot")
        self.assertEqual(result, set())

    def test_global_blacklist_included(self):
        cfg = MultiCoinGridConfig(blacklist=["SCAM-USD", "RUG-USD"])
        result = cfg.get_effective_blacklist("kraken_spot")
        self.assertIn("SCAM-USD", result)
        self.assertIn("RUG-USD", result)

    def test_connector_blacklist_included(self):
        cfg = MultiCoinGridConfig(connector_overrides={
            "kraken_spot": {"blacklist": ["XDC-USD", "HYPE-USD"]},
        })
        result = cfg.get_effective_blacklist("kraken_spot")
        self.assertIn("XDC-USD", result)
        self.assertIn("HYPE-USD", result)

    def test_effective_blacklist_is_union(self):
        cfg = MultiCoinGridConfig(
            blacklist=["SCAM-USD"],
            connector_overrides={
                "kraken_spot": {"blacklist": ["XDC-USD"]},
                "bitget_spot": {"blacklist": ["PENGU-USD"]},
            },
        )
        kraken_bl = cfg.get_effective_blacklist("kraken_spot")
        self.assertEqual(kraken_bl, {"SCAM-USD", "XDC-USD"})

    def test_connector_blacklist_does_not_pollute_other_connectors(self):
        """XDC-USD blacklisted on kraken_spot must NOT appear in bitget_spot blacklist."""
        cfg = MultiCoinGridConfig(connector_overrides={
            "kraken_spot": {"blacklist": ["XDC-USD"]},
        })
        bitget_bl = cfg.get_effective_blacklist("bitget_spot")
        self.assertNotIn("XDC-USD", bitget_bl,
                         "Per-connector blacklist must not affect other connectors (US6)")

    def test_unknown_connector_returns_only_global(self):
        cfg = MultiCoinGridConfig(blacklist=["SCAM-USD"])
        result = cfg.get_effective_blacklist("okx_spot")
        self.assertEqual(result, {"SCAM-USD"})


# ---------------------------------------------------------------------------
# US7 — _warn_blacklist_profile_overlap
# ---------------------------------------------------------------------------

class TestUS7BlacklistProfileOverlap(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """US7: Startup warning when coin_profiles and blacklist overlap."""

    def _make_controller(self, blacklist=None, coin_profiles=None, connector_overrides=None):
        """Build a minimal controller-like object with just the fields we test."""
        from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
        cfg = MultiCoinGridConfig(
            connector_name="kraken_spot",
            quote_asset="USD",
            blacklist=blacklist or [],
            coin_profiles=coin_profiles or {},
            connector_overrides=connector_overrides or {},
        )
        ctrl = MultiCoinGridController.__new__(MultiCoinGridController)
        ctrl.config = cfg
        ctrl._loggers = {}
        return ctrl

    def test_no_overlap_no_warning(self):
        """No warning when blacklist and coin_profiles are disjoint."""
        ctrl = self._make_controller(
            blacklist=["SCAM-USD"],
            coin_profiles={"XDC": {}},
        )
        self.set_loggers([ctrl.logger()])
        ctrl._warn_blacklist_profile_overlap()
        self.assertFalse(
            self.is_partially_logged("WARNING", "US7 CONFIG INCONSISTENCY"),
            "No warning expected for disjoint blacklist and coin_profiles (US7)",
        )

    def test_overlap_logs_warning(self):
        """Warning logged when a coin_profiles key matches a blacklisted pair."""
        ctrl = self._make_controller(
            blacklist=["XDC-USD"],
            coin_profiles={"XDC": {}},
        )
        self.set_loggers([ctrl.logger()])
        ctrl._warn_blacklist_profile_overlap()
        self.assertTrue(
            self.is_partially_logged("WARNING", "US7 CONFIG INCONSISTENCY"),
            "Warning must be logged for blacklist/profile overlap (US7)",
        )

    def test_connector_blacklist_overlap_also_warns(self):
        """Warning is triggered even when the blacklist entry is connector-specific."""
        ctrl = self._make_controller(
            coin_profiles={"HYPE": {}},
            connector_overrides={"kraken_spot": {"blacklist": ["HYPE-USD"]}},
        )
        self.set_loggers([ctrl.logger()])
        ctrl._warn_blacklist_profile_overlap()
        self.assertTrue(
            self.is_partially_logged("WARNING", "US7 CONFIG INCONSISTENCY"),
            "Connector-specific blacklist overlap must also warn (US7)",
        )

    def test_empty_coin_profiles_skips_check(self):
        """With no coin_profiles the method exits early without logging."""
        ctrl = self._make_controller(blacklist=["XDC-USD"])
        self.set_loggers([ctrl.logger()])
        ctrl._warn_blacklist_profile_overlap()
        self.assertFalse(
            self.is_partially_logged("WARNING", "US7 CONFIG INCONSISTENCY"),
            "No warning expected when coin_profiles is empty (US7)",
        )


# ---------------------------------------------------------------------------
# US1 — per-connector fee model and edge gate overrides
# ---------------------------------------------------------------------------

class TestUS1EdgeGatePerConnector(IsolatedAsyncioWrapperTestCase):
    """US1: fee_aware_filter and economic_edge_gate are overrideable per connector."""

    def _cfg(self, **kwargs):
        return MultiCoinGridConfig(**kwargs)

    def test_global_fee_filter_used_when_no_override(self):
        """Global fee_aware_filter is returned as-is when no connector_overrides set."""
        cfg = self._cfg(
            fee_aware_filter={"taker_fee_pct": 0.35, "fee_model": "worst_case"},
        )
        conn_cfg = cfg.resolve_connector_config("kraken_spot")
        # No connector-level fee_aware_filter → empty override dict
        self.assertEqual(conn_cfg.get("fee_aware_filter"), None)

    def test_connector_fee_filter_returned_by_resolve(self):
        """resolve_connector_config exposes connector-specific fee_aware_filter dict."""
        cfg = self._cfg(
            fee_aware_filter={"taker_fee_pct": 0.26, "fee_model": "worst_case"},
            connector_overrides={
                "kraken_spot": {
                    "fee_aware_filter": {"taker_fee_pct": 0.35, "fee_model": "best_case"},
                }
            },
        )
        conn_cfg = cfg.resolve_connector_config("kraken_spot")
        overridden = conn_cfg.get("fee_aware_filter", {})
        self.assertEqual(overridden.get("taker_fee_pct"), 0.35)
        self.assertEqual(overridden.get("fee_model"), "best_case")

    def test_merged_fee_cfg_overrides_global(self):
        """Simulates the controller merge: connector values win over global defaults."""
        global_fee_cfg = {"taker_fee_pct": 0.26, "fee_model": "worst_case", "maker_fee_pct": 0.16}
        connector_fee_cfg = {"taker_fee_pct": 0.35, "fee_model": "best_case"}
        merged = {**global_fee_cfg, **connector_fee_cfg}
        # Connector wins on the overridden keys
        self.assertEqual(merged["taker_fee_pct"], 0.35)
        self.assertEqual(merged["fee_model"], "best_case")
        # Global survives for keys not in connector override
        self.assertEqual(merged["maker_fee_pct"], 0.16)

    def test_connector_edge_gate_min_edge_overrides_global(self):
        """Connector-specific min_edge_pct takes precedence over global setting."""
        cfg = self._cfg(
            economic_edge_gate={"enabled": True, "min_edge_pct": 0.10},
            connector_overrides={
                "kraken_spot": {
                    "economic_edge_gate": {"min_edge_pct": 0.25},
                }
            },
        )
        conn_cfg = cfg.resolve_connector_config("kraken_spot")
        conn_edge = conn_cfg.get("economic_edge_gate", {})
        self.assertEqual(conn_edge.get("min_edge_pct"), 0.25)

    def test_unknown_connector_returns_global_unchanged(self):
        """An unconfigured connector receives no edge_gate overrides."""
        cfg = self._cfg(
            connector_overrides={
                "kraken_spot": {"economic_edge_gate": {"min_edge_pct": 0.25}},
            },
        )
        conn_cfg = cfg.resolve_connector_config("bitget_spot")
        self.assertEqual(conn_cfg.get("economic_edge_gate"), None)


# ---------------------------------------------------------------------------
# US8 — BEAR regime startup validation
# ---------------------------------------------------------------------------

class TestUS8BearConfigValidation(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """US8: _validate_bear_config() catches contradictory/redundant BEAR settings."""

    def _make_controller(self, bear_allow_meanrev=False, bear_auto_light=False,
                         bear_max_grids=None):
        from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
        adaptive_filters = {"BEAR": {"bear_allow_meanrev": bear_allow_meanrev}}
        if bear_max_grids is not None:
            adaptive_filters["BEAR"]["max_active_grids"] = bear_max_grids

        cfg = MultiCoinGridConfig(
            connector_name="kraken_spot",
            quote_asset="USD",
            adaptive_filters=adaptive_filters,
            adaptive_regime_detection={"bear_auto_light_enabled": bear_auto_light},
        )
        ctrl = MultiCoinGridController.__new__(MultiCoinGridController)
        ctrl.config = cfg
        ctrl._loggers = {}
        return ctrl

    def test_conservative_mode_logs_info(self):
        """Both flags False → conservative mode; logs info message."""
        ctrl = self._make_controller(bear_allow_meanrev=False, bear_auto_light=False)
        self.set_loggers([ctrl.logger()])
        ctrl._validate_bear_config()
        self.assertTrue(
            self.is_partially_logged("INFO", "Conservative BEAR mode"),
            "Conservative mode must log US8 INFO (US8)",
        )

    def test_contradiction_meanrev_true_and_max_grids_zero_warns(self):
        """bear_allow_meanrev=True but max_active_grids=0 is a contradiction → WARNING."""
        ctrl = self._make_controller(bear_allow_meanrev=True, bear_max_grids=0)
        self.set_loggers([ctrl.logger()])
        ctrl._validate_bear_config()
        self.assertTrue(
            self.is_partially_logged("WARNING", "US8 BEAR CONFIG INCONSISTENCY"),
            "Contradictory BEAR settings must trigger WARNING (US8)",
        )

    def test_redundancy_meanrev_and_auto_light_both_true_warns(self):
        """bear_allow_meanrev=True AND bear_auto_light=True is redundant → WARNING."""
        ctrl = self._make_controller(bear_allow_meanrev=True, bear_auto_light=True)
        self.set_loggers([ctrl.logger()])
        ctrl._validate_bear_config()
        self.assertTrue(
            self.is_partially_logged("WARNING", "US8 BEAR CONFIG REDUNDANT"),
            "Redundant BEAR settings must trigger WARNING (US8)",
        )

    def test_auto_light_only_no_warning(self):
        """bear_auto_light=True with bear_allow_meanrev=False is the normal auto-light setup."""
        ctrl = self._make_controller(bear_allow_meanrev=False, bear_auto_light=True)
        self.set_loggers([ctrl.logger()])
        ctrl._validate_bear_config()
        self.assertFalse(
            self.is_partially_logged("WARNING", "US8 BEAR CONFIG"),
            "Auto-light only (no meanrev) must not warn (US8)",
        )

    def test_max_grids_nonzero_meanrev_true_no_inconsistency_warning(self):
        """bear_allow_meanrev=True AND max_active_grids=1 is valid — no warning."""
        ctrl = self._make_controller(bear_allow_meanrev=True, bear_max_grids=1)
        self.set_loggers([ctrl.logger()])
        ctrl._validate_bear_config()
        self.assertFalse(
            self.is_partially_logged("WARNING", "US8 BEAR CONFIG INCONSISTENCY"),
            "bear_allow_meanrev=True with max_grids=1 must NOT warn (US8)",
        )


# ---------------------------------------------------------------------------
# US9 — position size config fields exist and accept reduced values
# ---------------------------------------------------------------------------

class TestUS9PositionSizeConfig(IsolatedAsyncioWrapperTestCase):
    """US9: total_amount_quote and max_simultaneous_coins are configurable per instance."""

    def test_default_fields_exist(self):
        """Both position-size fields are present on the default config."""
        cfg = MultiCoinGridConfig()
        self.assertTrue(hasattr(cfg, "total_amount_quote"))
        self.assertTrue(hasattr(cfg, "max_simultaneous_coins"))

    def test_reduced_position_size_accepted(self):
        """Setting conservative values (US9 proposal) is valid."""
        cfg = MultiCoinGridConfig(
            total_amount_quote=Decimal("200"),
            max_simultaneous_coins=2,
        )
        self.assertEqual(cfg.total_amount_quote, Decimal("200"))
        self.assertEqual(cfg.max_simultaneous_coins, 2)

    def test_usd_instance_values(self):
        """USD bot target values per US9 are accepted by the config model."""
        cfg = MultiCoinGridConfig(
            connector_name="kraken_spot",
            quote_asset="USD",
            total_amount_quote=Decimal("200"),
            max_simultaneous_coins=2,
        )
        self.assertEqual(cfg.total_amount_quote, Decimal("200"))
        self.assertEqual(cfg.max_simultaneous_coins, 2)

    def test_eur_instance_values(self):
        """EUR bot target values per US9 are accepted by the config model."""
        cfg = MultiCoinGridConfig(
            connector_name="kraken_spot",
            quote_asset="EUR",
            total_amount_quote=Decimal("200"),
            max_simultaneous_coins=3,
        )
        self.assertEqual(cfg.total_amount_quote, Decimal("200"))
        self.assertEqual(cfg.max_simultaneous_coins, 3)

    def test_per_coin_capital_calculation(self):
        """Per-coin capital equals total / max_simultaneous_coins (as controller computes it)."""
        total = Decimal("200")
        max_coins = 2
        per_coin = total / max_coins
        self.assertEqual(per_coin, Decimal("100"))


# ---------------------------------------------------------------------------
# Safety-exit fee-aware bypass (stuck-CLOSING bug fix)
# ---------------------------------------------------------------------------

class TestSafetyExitFeeAwareBypass(IsolatedAsyncioWrapperTestCase, LoggerMixinForTest):
    """Regression tests for the stuck-CLOSING bug.

    Root cause: NO_PROGRESS_TIMEOUT was in the fee-guarded set. When price was
    below break-even, _fee_aware_close_allowed returned False, which triggered a
    reset-to-RUNNING in _place_graceful_close_orders.  Because
    _timeout_close_triggered was also cleared, the timeout check eventually fired
    again → start_forced_close → GRACEFUL → FEE_AWARE_EXIT_BLOCKED → reset →
    infinite loop.

    Fix: remove NO_PROGRESS_TIMEOUT from _is_fee_guarded_close_type so it always
    bypasses the fee guard. Safety exits must always be able to close.
    """

    # Price below break-even used in all "blocked" checks.
    _PRICE_BELOW = Decimal("80")
    _BREAK_EVEN = Decimal("110")

    def setUp(self):
        super().setUp()
        config = _make_grid_config(fee_aware_timeout_bypass_sec=0)
        self.executor = _make_executor(config)
        # Place executor in a state where fee guard would normally block:
        # position exists, price below break-even.
        self.executor.position_size_base = Decimal("1")
        self.executor.position_size_quote = self._BREAK_EVEN
        self.executor.position_break_even_price = self._BREAK_EVEN
        self.executor.position_fees_quote = Decimal("0")
        self.set_loggers([self.executor.logger()])

    # ------------------------------------------------------------------
    # Scenario 1: Normal (soft) exits ARE fee-guarded
    # ------------------------------------------------------------------

    def test_soft_exit_blocked_below_breakeven(self):
        """EARLY_STOP and SWITCH are fee-guarded; price below break-even → blocked."""
        for ct in (CloseType.EARLY_STOP, CloseType.SWITCH, CloseType.TIME_LIMIT):
            with self.subTest(close_type=ct):
                result = self.executor._fee_aware_close_allowed(ct, current_price=self._PRICE_BELOW)
                self.assertFalse(result, f"{ct.name} must be blocked below break-even")

    # ------------------------------------------------------------------
    # Scenario 2: NO_PROGRESS_TIMEOUT is NOT fee-guarded (the fix)
    # ------------------------------------------------------------------

    def test_no_progress_timeout_not_guarded(self):
        """NO_PROGRESS_TIMEOUT must NOT be in the fee-guarded set."""
        result = self.executor._is_fee_guarded_close_type(CloseType.NO_PROGRESS_TIMEOUT)
        self.assertFalse(result, "NO_PROGRESS_TIMEOUT must NOT be fee-guarded")

    def test_no_progress_timeout_allowed_below_breakeven(self):
        """_fee_aware_close_allowed returns True for NO_PROGRESS_TIMEOUT even below break-even."""
        result = self.executor._fee_aware_close_allowed(
            CloseType.NO_PROGRESS_TIMEOUT, current_price=self._PRICE_BELOW
        )
        self.assertTrue(result, "NO_PROGRESS_TIMEOUT must bypass fee guard (safety exit)")

    def test_no_progress_timeout_logs_bypassed(self):
        """FEE_AWARE_EXIT_BYPASSED is emitted when NO_PROGRESS_TIMEOUT bypasses the guard."""
        self.executor._fee_aware_close_allowed(
            CloseType.NO_PROGRESS_TIMEOUT, current_price=self._PRICE_BELOW
        )
        self.assertTrue(
            self.is_partially_logged("INFO", "FEE_AWARE_EXIT_BYPASSED"),
            "FEE_AWARE_EXIT_BYPASSED must be logged for NO_PROGRESS_TIMEOUT",
        )

    # ------------------------------------------------------------------
    # Scenario 3: HARD_CAP_TIME_LIMIT NOT blocked
    # ------------------------------------------------------------------

    def test_hard_cap_allowed_below_breakeven(self):
        """HARD_CAP_TIME_LIMIT bypasses fee guard regardless of P&L (US4 + safety)."""
        result = self.executor._fee_aware_close_allowed(
            CloseType.HARD_CAP_TIME_LIMIT, current_price=self._PRICE_BELOW
        )
        self.assertTrue(result, "HARD_CAP_TIME_LIMIT must bypass fee guard")

    # ------------------------------------------------------------------
    # Scenario 4: STOP_LOSS / RISK_KILL_SWITCH NOT blocked
    # ------------------------------------------------------------------

    def test_stop_loss_allowed_below_breakeven(self):
        """STOP_LOSS is never fee-guarded; must always be allowed."""
        result = self.executor._fee_aware_close_allowed(
            CloseType.STOP_LOSS, current_price=self._PRICE_BELOW
        )
        self.assertTrue(result, "STOP_LOSS must bypass fee guard")

    def test_risk_kill_switch_allowed_below_breakeven(self):
        """RISK_KILL_SWITCH (emergency unwind) is never fee-guarded."""
        result = self.executor._fee_aware_close_allowed(
            CloseType.RISK_KILL_SWITCH, current_price=self._PRICE_BELOW
        )
        self.assertTrue(result, "RISK_KILL_SWITCH must bypass fee guard")

    # ------------------------------------------------------------------
    # Scenario 5: fee_aware_timeout_bypass_sec=0 is explicitly disabled
    # ------------------------------------------------------------------

    def test_bypass_sec_zero_means_disabled(self):
        """bypass_sec=0 must never trigger the time-based bypass (FEE_AWARE_BYPASS_FORCED)."""
        # The executor was built with bypass_sec=0 (setUp default).
        # TIME_LIMIT is fee-guarded so the bypass path is exercised.
        self.executor._fee_aware_close_allowed(
            CloseType.TIME_LIMIT, current_price=self._PRICE_BELOW
        )
        self.assertFalse(
            self.is_partially_logged("WARNING", "FEE_AWARE_BYPASS_FORCED"),
            "bypass_sec=0 must disable the time-based bypass entirely",
        )

    # ------------------------------------------------------------------
    # Scenario 6: Stuck CLOSING loop regression test
    # ------------------------------------------------------------------

    def test_no_progress_timeout_does_not_reset_to_running(self):
        """Regression: fee guard must NOT block NO_PROGRESS_TIMEOUT closes.

        Before the fix, _fee_aware_close_allowed returned False for
        NO_PROGRESS_TIMEOUT below break-even, causing _place_graceful_close_orders
        to reset _status to RUNNING and clear close_type / _timeout_close_triggered.
        The next timeout check restarted the cycle → infinite stuck-CLOSING loop.

        Verifying that _fee_aware_close_allowed returns True guarantees the reset
        block (`if not allowed: self._status = RUNNING`) is never entered.
        """
        result = self.executor._fee_aware_close_allowed(
            CloseType.NO_PROGRESS_TIMEOUT, current_price=self._PRICE_BELOW
        )
        self.assertTrue(
            result,
            "fee guard must pass for NO_PROGRESS_TIMEOUT to prevent reset-to-RUNNING loop",
        )
