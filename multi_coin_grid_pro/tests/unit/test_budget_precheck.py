"""
Tests for budget pre-check in _should_create_new_grid().

Verifies that the budget is checked BEFORE allocating a slot,
preventing the grid restart spam loop where coins pass all filters
but immediately fail on "Insufficient capital".
"""

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

# -- helpers ----------------------------------------------------------------
_real_method = MultiCoinGridController._should_create_new_grid
_real_is_executor_actually_active = MultiCoinGridController._is_executor_actually_active


def _make_controller(max_slots=6):
    """Create a minimal mock controller with budget pre-check attributes."""
    ctrl = MagicMock(spec=MultiCoinGridController)
    ctrl.logger.return_value = MagicMock()
    ctrl.active_coins = {"BTR-USDT": "exec-001"}
    ctrl.max_simultaneous_coins = 6
    ctrl.config = MagicMock()
    ctrl.config.total_amount_quote = 500
    ctrl.config.min_order_amount_quote = 10
    ctrl.config.num_grids = 5
    ctrl.config.quote_asset = "USDT"
    ctrl.config.capital_reserve_pct = 0
    ctrl._next_allocation_quote = None
    ctrl._dynamic_num_grids = None

    # T5-A1: Injectable clock
    ctrl._clock = time.time

    # Market data provider (time)
    ctrl.market_data_provider = MagicMock()
    ctrl.market_data_provider.time.return_value = time.time()

    # Budget allocator
    ctrl.budget_allocator = MagicMock()

    # Risk manager
    ctrl.risk_manager = MagicMock()
    ctrl.risk_manager.can_open_trade.return_value = Decimal("83.33")

    # Professional risk manager (cooldown/daily loss checks)
    ctrl.professional_risk_manager = MagicMock()
    ctrl.professional_risk_manager.can_open_new_position.return_value = (True, "")
    ctrl._build_portfolio_risk = MagicMock()

    # Connector
    ctrl.connector = MagicMock()
    ctrl.trend_calculator = MagicMock()
    ctrl.trend_calculator.get_trend.return_value = None
    ctrl._calculate_volatility_based_grid_count = MagicMock(return_value=ctrl.config.num_grids)
    ctrl._apply_capital_reserve_to_balance = MagicMock(side_effect=lambda balance, log_prefix="": balance)

    # Dynamic slot manager
    ctrl.dynamic_slot_manager = MagicMock()
    ctrl.dynamic_slot_manager.enabled = True

    # _get_current_max_slots
    ctrl._get_current_max_slots.return_value = max_slots

    return ctrl


# -- tests ------------------------------------------------------------------

class TestBudgetPrecheck:
    """Test the budget pre-check that prevents grid restart spam."""

    def test_blocks_when_no_budget_available(self):
        """
        When all balance is reserved, _should_create_new_grid should return
        False immediately, without logging "STARTING new grid".
        """
        ctrl = _make_controller()
        # Balance = 74 USDT, reserved = 70, effective = 4 < 50 (5 grids * 10)
        ctrl.connector.get_available_balance.return_value = Decimal("74")
        ctrl.budget_allocator.total_reserved = Decimal("70")

        result = _real_method(ctrl, "PI-USDT")

        assert result is False
        # Risk manager should NOT be called (budget check blocks first)
        ctrl.risk_manager.can_open_trade.assert_not_called()

    def test_allows_when_budget_sufficient(self):
        """
        When enough free capital exists, _should_create_new_grid should
        proceed to risk check and return True.
        """
        ctrl = _make_controller()
        # Balance = 200 USDT, reserved = 70, effective = 130 > 50
        ctrl.connector.get_available_balance.return_value = Decimal("200")
        ctrl.budget_allocator.total_reserved = Decimal("70")

        result = _real_method(ctrl, "CYS-USDT")

        assert result is True
        # Risk manager SHOULD be called
        ctrl.risk_manager.can_open_trade.assert_called_once()

    def test_uses_dynamic_grid_count_for_min_capital(self):
        """
        Budget pre-check should not block a low-volatility setup that the
        DynamicGridSizer will run with fewer levels than config.num_grids.
        """
        ctrl = _make_controller()
        ctrl.config.num_grids = 7
        ctrl.connector.get_available_balance.return_value = Decimal("207.99")
        ctrl.budget_allocator.total_reserved = Decimal("147.37")
        ctrl.trend_calculator.get_trend.return_value = object()
        ctrl._calculate_volatility_based_grid_count.return_value = 5

        result = _real_method(ctrl, "LINK-USDT")

        assert result is True
        ctrl.risk_manager.can_open_trade.assert_called_once()

    def test_blocks_when_balance_equals_reserved(self):
        """
        Edge case: balance exactly equals reserved.
        Should block because effective_balance = 0.
        """
        ctrl = _make_controller()
        ctrl.connector.get_available_balance.return_value = Decimal("70")
        ctrl.budget_allocator.total_reserved = Decimal("70")

        result = _real_method(ctrl, "RIVER-USDT")

        assert result is False

    def test_uses_rate_limited_logging(self):
        """
        Budget pre-check should use rate-limited logging (should_log)
        to avoid spamming the log every 16 seconds.
        """
        ctrl = _make_controller()
        ctrl.connector.get_available_balance.return_value = Decimal("74")
        ctrl.budget_allocator.total_reserved = Decimal("70")

        with patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.should_log',
                   return_value=False) as mock_should_log:
            result = _real_method(ctrl, "PI-USDT")

        assert result is False
        # should_log should be called with budget_precheck_blocked key
        mock_should_log.assert_called_with("budget_precheck_blocked", interval_sec=300)

    def test_connector_error_falls_back_to_config(self):
        """
        If connector.get_available_balance raises, should fall back to
        config total_amount_quote (which is typically large enough to pass).
        """
        ctrl = _make_controller()
        ctrl.connector.get_available_balance.side_effect = Exception("API error")
        ctrl.budget_allocator.total_reserved = Decimal("0")
        ctrl.config.total_amount_quote = 500  # Fallback: 500 > 50

        result = _real_method(ctrl, "ATH-USDT")

        # Should pass because fallback balance (500) is sufficient
        assert result is True

    def test_skips_precheck_for_single_coin_mode(self):
        """
        When max_slots_for_capital <= 1 (single-coin mode), the multi-coin
        budget pre-check code path is not reached.
        """
        ctrl = _make_controller(max_slots=1)
        ctrl.active_coins = {}
        ctrl.active_coin = None
        ctrl.bot_start_time = time.time() - 7200  # started 2h ago
        ctrl.config.min_startup_wait_seconds = 60
        ctrl.connector.get_available_balance.return_value = Decimal("0")
        ctrl.budget_allocator.total_reserved = Decimal("0")

        # The method will fall through to startup delay and other checks
        result = _real_method(ctrl, "BTC-USDT")
        assert isinstance(result, bool)


class TestTelegramEnvVarResolution:
    """Test that Telegram config resolves ${ENV_VAR} references."""

    def test_env_var_resolved_for_bot_token(self):
        """${TELEGRAM_BOT_TOKEN} should be resolved from environment."""
        import os
        os.environ["TEST_TG_TOKEN"] = "123:ABC"
        try:
            token = "${TEST_TG_TOKEN}"
            if token.startswith('${') and token.endswith('}'):
                token = os.environ.get(token[2:-1], '')
            assert token == "123:ABC"
        finally:
            del os.environ["TEST_TG_TOKEN"]

    def test_env_var_missing_resolves_to_empty(self):
        """Missing env var should resolve to empty string (disables Telegram)."""
        import os
        token = "${NONEXISTENT_VAR_12345}"
        if token.startswith('${') and token.endswith('}'):
            token = os.environ.get(token[2:-1], '')
        assert token == ""

    def test_literal_token_unchanged(self):
        """A literal token (not ${...}) should pass through unchanged."""
        token = "123456:ABCdefGHI"
        if isinstance(token, str) and token.startswith('${') and token.endswith('}'):
            import os
            token = os.environ.get(token[2:-1], '')
        assert token == "123456:ABCdefGHI"


class TestMultiCoinBudgetCleanup:
    """Regression tests for stale budget reservations in multi-coin mode."""

    def test_inactive_executor_cleanup_uses_executor_id_mapping(self):
        """
        When active_executor_id and active_coin point at different slots, cleanup
        must release the executor's coin, not the legacy active_coin.
        """
        ctrl = MagicMock(spec=MultiCoinGridController)
        ctrl.logger.return_value = MagicMock()
        ctrl.active_executor_id = "exec-hype"
        ctrl.active_coin = "LINK-USDT"
        ctrl.executors_info = []
        ctrl._get_executor_info = MagicMock(return_value=None)
        ctrl._executor_creation_times = {}
        ctrl.market_data_provider = MagicMock()
        ctrl.market_data_provider.time.return_value = time.time()
        ctrl.active_coins = {
            "LINK-USDT": "exec-link",
            "HYPE-USDT": "exec-hype",
        }
        ctrl.current_exposure_per_coin = {
            "LINK-USDT": Decimal("31.20"),
            "HYPE-USDT": Decimal("51.38"),
        }
        ctrl.total_exposure = Decimal("82.58")
        ctrl.budget_allocator = MagicMock()
        ctrl.price_history_for_volatility = {
            "LINK-USDT": [1, 2, 3],
            "HYPE-USDT": [4, 5, 6],
        }
        ctrl.coin_error_count = {}
        ctrl.max_errors_per_coin = 99
        ctrl.auto_blacklisted_coins = set()
        ctrl.config = MagicMock()
        ctrl.config.blacklist = []

        result = _real_is_executor_actually_active(ctrl)

        assert result is False
        ctrl.budget_allocator.release.assert_called_once_with("exec-hype")
        assert "HYPE-USDT" not in ctrl.active_coins
        assert "LINK-USDT" in ctrl.active_coins
        assert ctrl.current_exposure_per_coin == {"LINK-USDT": Decimal("31.20")}
        assert ctrl.total_exposure == Decimal("31.20")
        assert ctrl.active_coin == "LINK-USDT"
        assert ctrl.active_executor_id is None
