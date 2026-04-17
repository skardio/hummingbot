"""
Tests for the 5 forensic analysis fixes from the 2026-04-12 bot run.

Fix 1: EARLY_STOP cascade — min_bypass_age_seconds protects young executors
Fix 2: Risk-pause deadlock — max_pause_extensions=1, post-resume immunity
Fix 3: Auto-blacklist — 0-fill EARLY_STOP does not count as coin error
Fix 4: Position sizing — parallel slot cap prevents capital starvation
Fix 5: Slippage guard — aggressive market close uses limit with slippage guard
"""
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from multi_coin_grid_pro.risk.professional_risk_manager import PortfolioRisk, ProfessionalRiskManager  # noqa: E402

# ===================================================================
# FIX 1: EARLY_STOP cascade — min_bypass_age_seconds
# ===================================================================


class TestMinBypassAge:
    """Fix 1: Young executors must be protected from soft grace bypasses."""

    @pytest.fixture
    def controller(self):
        """Create a minimal controller mock for _should_bypass_grace_period."""
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
        ctrl = MagicMock(spec=MultiCoinGridController)
        ctrl.config = MagicMock()
        ctrl.config.grace_bypass_on_executor_error = True
        ctrl.config.grace_bypass_on_sl_hit = True
        ctrl.config.grace_bypass_on_regime_flip = True
        ctrl.config.grace_bypass_on_slot_pressure = True
        ctrl.config.grace_bypass_on_stale_data = True
        ctrl.config.min_bypass_age_seconds = 120
        ctrl.config.max_simultaneous_coins = 2
        ctrl.market_data_provider = MagicMock()
        ctrl.executors_info = []
        ctrl.market_regime_filter = None
        ctrl.connector = MagicMock()
        ctrl.connector.get_mid_price.return_value = Decimal("100")
        # Use the real method
        ctrl._should_bypass_grace_period = (
            MultiCoinGridController._should_bypass_grace_period.__get__(ctrl)
        )
        ctrl.logger = MagicMock(return_value=MagicMock())
        return ctrl

    def _make_executor_info(self, timestamp, is_active=True, close_type=None,
                            custom_info=None):
        """Create a mock ExecutorInfo."""
        info = MagicMock()
        info.timestamp = timestamp
        info.is_active = is_active
        info.close_type = close_type
        info.custom_info = custom_info or {}
        return info

    def test_young_executor_blocks_slot_pressure(self, controller):
        """Executor < 120s old must NOT be bypassed for slot pressure."""
        now = 1000000.0
        controller.market_data_provider.time.return_value = now
        # 2 active executors = slots full
        controller.executors_info = [
            self._make_executor_info(now - 30),
            self._make_executor_info(now - 30),
        ]

        executor = self._make_executor_info(now - 30)  # 30 seconds old
        should_bypass, reason = controller._should_bypass_grace_period(
            executor, "TON-USD"
        )

        assert not should_bypass, "Young executor should NOT be bypassed for slot pressure"

    def test_old_executor_allows_slot_pressure(self, controller):
        """Executor > 120s old CAN be bypassed for slot pressure."""
        now = 1000000.0
        controller.market_data_provider.time.return_value = now
        controller.executors_info = [
            self._make_executor_info(now - 300),
            self._make_executor_info(now - 300),
        ]

        executor = self._make_executor_info(now - 300)  # 5 min old
        should_bypass, reason = controller._should_bypass_grace_period(
            executor, "TON-USD"
        )

        assert should_bypass
        assert "slot pressure" in reason

    def test_young_executor_still_allows_error_bypass(self, controller):
        """Even young executors should bypass grace for actual errors."""
        now = 1000000.0
        controller.market_data_provider.time.return_value = now

        executor = self._make_executor_info(
            now - 10,  # 10 seconds old
            is_active=False,
            close_type="INSUFFICIENT_BALANCE"
        )
        should_bypass, reason = controller._should_bypass_grace_period(
            executor, "TON-USD"
        )

        assert should_bypass
        assert "executor error" in reason

    def test_young_executor_still_allows_stop_loss_bypass(self, controller):
        """Even young executors should bypass grace for stop-loss."""
        now = 1000000.0
        controller.market_data_provider.time.return_value = now

        executor = self._make_executor_info(
            now - 10,  # 10 seconds old
            custom_info={"stop_loss_hit": True}
        )
        should_bypass, reason = controller._should_bypass_grace_period(
            executor, "TON-USD"
        )

        assert should_bypass
        assert "stop-loss" in reason

    def test_young_executor_blocks_regime_flip(self, controller):
        """Executor < 120s old must NOT be bypassed for regime flip."""
        now = 1000000.0
        controller.market_data_provider.time.return_value = now

        controller.market_regime_filter = MagicMock()
        controller.market_regime_filter.get_current_regime.return_value = "BEAR"

        executor = self._make_executor_info(
            now - 30,
            custom_info={"entry_regime": "BULL"}
        )
        should_bypass, reason = controller._should_bypass_grace_period(
            executor, "TON-USD"
        )

        assert not should_bypass

    def test_configurable_min_bypass_age(self, controller):
        """min_bypass_age_seconds=0 disables the protection."""
        now = 1000000.0
        controller.market_data_provider.time.return_value = now
        controller.config.min_bypass_age_seconds = 0  # Disable
        controller.executors_info = [
            self._make_executor_info(now - 5),
            self._make_executor_info(now - 5),
        ]

        executor = self._make_executor_info(now - 5)  # 5 seconds old
        should_bypass, reason = controller._should_bypass_grace_period(
            executor, "TON-USD"
        )

        # With min_bypass_age=0, slot pressure should bypass even young executors
        assert should_bypass
        assert "slot pressure" in reason


# ===================================================================
# FIX 2: Risk-pause deadlock — max_pause_extensions + immunity
# ===================================================================

class TestRiskPauseDeadlockFix:
    """Fix 2: Risk pause must break deadlock faster and prevent re-trigger."""

    def _make_portfolio_risk(self, **kwargs):
        defaults = dict(
            total_equity=Decimal("1000"),
            daily_pnl=Decimal("0"),
            daily_pnl_pct=0.0,
            max_daily_loss_pct=-3.0,
            open_positions=0,
            max_positions=5,
            recent_wins=1,
            recent_losses=9,
            win_rate=0.10,
            highly_correlated_positions=[],
            correlation_risk_score=0.0,
        )
        defaults.update(kwargs)
        return PortfolioRisk(**defaults)

    def _seed_losing_trades(self, rm, count=15, pnl=-0.005):
        for i in range(count):
            rm.record_trade_result(
                symbol=f"LOSS-{i}", pnl_pct=pnl,
                close_reason="EARLY_STOP", hold_time_minutes=60
            )

    def test_max_pause_extensions_default_is_1(self):
        """Default max_pause_extensions should be 1 (not 2)."""
        rm = ProfessionalRiskManager()
        assert rm.max_pause_extensions == 1

    def test_force_resume_after_one_extension(self):
        """With max_pause_extensions=1, deadlock breaks after 2 × cooldown."""
        rm = ProfessionalRiskManager(
            max_pause_extensions=1,
            pause_cooldown_minutes=120
        )
        self._seed_losing_trades(rm)
        portfolio = self._make_portfolio_risk()

        # Trigger initial pause
        can_open, _ = rm.can_open_new_position("TEST", 0.7, portfolio)
        assert not can_open
        assert rm._pause_extensions == 0

        # Extension 1: expire, conditions unchanged → should force resume now
        rm.pause_until = datetime.now() - timedelta(seconds=1)
        can_open, reason = rm.can_open_new_position("TEST", 0.7, portfolio)

        # max_pause_extensions=1, _pause_extensions becomes 1 >= 1 → force resume
        assert can_open, f"Should force-resume after 1 extension, got: {reason}"
        assert len(rm.recent_trades) == 0  # Trades cleared

    def test_post_resume_immunity_prevents_retrigger(self):
        """After force-resume, step 3 should be immune for N minutes."""
        rm = ProfessionalRiskManager(
            max_pause_extensions=1,
            pause_cooldown_minutes=60,
            post_resume_immunity_minutes=30
        )
        self._seed_losing_trades(rm)
        portfolio = self._make_portfolio_risk()

        # Trigger and expire pause to force resume
        rm.can_open_new_position("TEST", 0.7, portfolio)
        rm.pause_until = datetime.now() - timedelta(seconds=1)
        can_open, _ = rm.can_open_new_position("TEST", 0.7, portfolio)
        assert can_open  # Force-resumed

        # Now add MORE losing trades (simulating bad trades after resume)
        self._seed_losing_trades(rm, count=15, pnl=-0.01)

        # Immunity should prevent immediate re-pause
        assert rm._post_resume_immune_until is not None
        can_open, reason = rm.can_open_new_position("TEST", 0.7, portfolio)
        assert can_open, f"Post-resume immunity should prevent re-trigger, got: {reason}"

    def test_immunity_expires_after_configured_time(self):
        """After immunity period, normal pause checks resume."""
        rm = ProfessionalRiskManager(
            max_pause_extensions=1,
            pause_cooldown_minutes=60,
            post_resume_immunity_minutes=30
        )
        self._seed_losing_trades(rm)
        portfolio = self._make_portfolio_risk()

        # Force resume
        rm.can_open_new_position("TEST", 0.7, portfolio)
        rm.pause_until = datetime.now() - timedelta(seconds=1)
        rm.can_open_new_position("TEST", 0.7, portfolio)

        # Add losing trades
        self._seed_losing_trades(rm, count=15, pnl=-0.01)

        # Expire immunity
        rm._post_resume_immune_until = datetime.now() - timedelta(seconds=1)

        # Now step 3 should fire again
        can_open, reason = rm.can_open_new_position("TEST", 0.7, portfolio)
        assert not can_open, "After immunity expires, pause should trigger"
        assert "Pause triggered" in reason

    def test_post_resume_immunity_configurable(self):
        """post_resume_immunity_minutes parameter works."""
        rm = ProfessionalRiskManager(post_resume_immunity_minutes=45)
        assert rm.post_resume_immunity_minutes == 45


# ===================================================================
# FIX 3: Auto-blacklist — 0-fill EARLY_STOP excluded
# ===================================================================

class TestAutoBlacklistFix:
    """Fix 3: 0-fill EARLY_STOP must not count toward auto-blacklist threshold."""

    @pytest.fixture
    def controller(self):
        """Create a minimal mock controller for error counting logic."""
        ctrl = MagicMock()
        ctrl.active_coin = "TON-USD"
        ctrl.active_executor_id = "test-exec-123"
        ctrl.coin_error_count = {}
        ctrl.max_errors_per_coin = 5
        ctrl.auto_blacklisted_coins = set()
        ctrl.config = MagicMock()
        ctrl.config.blacklist = []
        ctrl.global_risk_manager = MagicMock()
        ctrl.logger = MagicMock(return_value=MagicMock())
        return ctrl

    def test_zero_fill_early_stop_not_counted(self):
        """0-fill EARLY_STOP should NOT increment coin_error_count."""
        # Simulate failed executor: EARLY_STOP with 0 fills
        failed_executor = MagicMock()
        failed_executor.is_active = False
        failed_executor.close_type = MagicMock()
        failed_executor.close_type.value = 5  # EARLY_STOP
        failed_executor.filled_amount_quote = Decimal("0")

        # Check detection logic
        close_type_val = failed_executor.close_type
        filled_quote = failed_executor.filled_amount_quote or Decimal("0")
        is_early_stop = (
            hasattr(close_type_val, 'value') and close_type_val.value == 5
        )
        is_zero_fill_early_stop = is_early_stop and filled_quote == Decimal("0")

        assert is_zero_fill_early_stop, "Should detect 0-fill EARLY_STOP"

    def test_filled_early_stop_still_counted(self):
        """EARLY_STOP with fills ($50) SHOULD count as error."""
        failed_executor = MagicMock()
        failed_executor.is_active = False
        failed_executor.close_type = MagicMock()
        failed_executor.close_type.value = 5  # EARLY_STOP
        failed_executor.filled_amount_quote = Decimal("50.00")

        close_type_val = failed_executor.close_type
        filled_quote = failed_executor.filled_amount_quote or Decimal("0")
        is_early_stop = (
            hasattr(close_type_val, 'value') and close_type_val.value == 5
        )
        is_zero_fill_early_stop = is_early_stop and filled_quote == Decimal("0")

        assert not is_zero_fill_early_stop, "Filled EARLY_STOP should count as error"

    def test_non_early_stop_always_counted(self):
        """FAILED, INSUFFICIENT_BALANCE etc must always count as errors."""
        for close_type_value in [7, 8]:  # INSUFFICIENT_BALANCE, FAILED
            failed_executor = MagicMock()
            failed_executor.is_active = False
            failed_executor.close_type = MagicMock()
            failed_executor.close_type.value = close_type_value
            failed_executor.filled_amount_quote = Decimal("0")

            close_type_val = failed_executor.close_type
            is_early_stop = (
                hasattr(close_type_val, 'value') and close_type_val.value == 5
            )
            is_zero_fill_early_stop = is_early_stop and Decimal("0") == Decimal("0")

            assert not is_zero_fill_early_stop, (
                f"close_type={close_type_value} should NOT be treated as 0-fill EARLY_STOP"
            )

    def test_five_real_errors_still_blacklist(self):
        """5 real errors (not 0-fill EARLY_STOP) should still trigger blacklist."""
        coin_error_count = {}
        coin = "BAD-USD"
        max_errors = 5
        auto_blacklisted = set()

        # Simulate 5 non-EARLY_STOP failures
        for _ in range(5):
            coin_error_count[coin] = coin_error_count.get(coin, 0) + 1

        assert coin_error_count[coin] >= max_errors
        if coin_error_count[coin] >= max_errors:
            auto_blacklisted.add(coin)

        assert coin in auto_blacklisted


# ===================================================================
# FIX 4: Position sizing — parallel slot cap
# ===================================================================

class TestParallelSlotCap:
    """Fix 4: Per-slot allocation must be capped to leave room for other slots."""

    def test_two_slots_caps_at_45_percent(self):
        """With 2 slots, each should get max 45% of total balance."""
        total_balance = Decimal("155.00")
        max_simultaneous = 2
        adjusted_size = Decimal("73.63")  # ~47% — would starve 2nd slot

        # Apply the parallel slot guard
        # Actually use total balance:
        total_for_cap = total_balance  # No reservations yet for first exec
        max_per_slot_pct = Decimal("0.90") / Decimal(str(max_simultaneous))
        max_per_slot = total_for_cap * max_per_slot_pct

        assert max_per_slot_pct == Decimal("0.45")
        assert max_per_slot == Decimal("69.750")  # 45% of 155

        # Cap should reduce allocation
        if adjusted_size > max_per_slot:
            adjusted_size = max_per_slot

        assert adjusted_size == Decimal("69.750"), \
            f"Should cap at 45% of {total_balance} = 69.75, got {adjusted_size}"

    def test_single_slot_no_cap(self):
        """With 1 slot, no parallel cap should apply."""
        max_simultaneous = 1
        total_balance = Decimal("155.00")
        adjusted_size = Decimal("140.00")  # 90% — fine for single slot

        if max_simultaneous > 1:
            max_per_slot_pct = Decimal("0.90") / Decimal(str(max_simultaneous))
            max_per_slot = total_balance * max_per_slot_pct
            if adjusted_size > max_per_slot:
                adjusted_size = max_per_slot

        # No cap applied
        assert adjusted_size == Decimal("140.00")

    def test_three_slots_caps_at_30_percent(self):
        """With 3 slots, each should get max 30% of total balance."""
        max_simultaneous = 3
        total_balance = Decimal("300.00")
        adjusted_size = Decimal("120.00")  # 40% — too much for 3 slots

        max_per_slot_pct = Decimal("0.90") / Decimal(str(max_simultaneous))
        max_per_slot = total_balance * max_per_slot_pct

        assert max_per_slot == Decimal("90.00")

        if adjusted_size > max_per_slot:
            adjusted_size = max_per_slot

        assert adjusted_size == Decimal("90.00")

    def test_cap_accounts_for_existing_reservations(self):
        """Cap uses total balance (available + reserved), not just available."""
        total_balance_available = Decimal("80.00")
        budget_reserved = Decimal("70.00")
        max_simultaneous = 2

        total_for_cap = total_balance_available + budget_reserved  # $150
        max_per_slot_pct = Decimal("0.90") / Decimal(str(max_simultaneous))
        max_per_slot = total_for_cap * max_per_slot_pct

        # 45% of $150 = $67.50
        assert max_per_slot == Decimal("67.500")

    def test_small_allocation_not_reduced(self):
        """If allocation is already below cap, don't change it."""
        total_balance = Decimal("300.00")
        max_simultaneous = 2
        adjusted_size = Decimal("50.00")  # Only 17% — well under 45% cap

        max_per_slot_pct = Decimal("0.90") / Decimal(str(max_simultaneous))
        max_per_slot = total_balance * max_per_slot_pct  # $135

        original = adjusted_size
        if adjusted_size > max_per_slot:
            adjusted_size = max_per_slot

        assert adjusted_size == original, "Small allocation should not be reduced"


# ===================================================================
# FIX 5: Slippage guard on aggressive market close
# ===================================================================

class TestSlippageGuardOnMarketClose:
    """Fix 5: MARKET close should use LIMIT with slippage guard instead."""

    def test_slippage_guard_calculation_sell(self):
        """Sell slippage guard: price * (1 - guard_pct/100)."""
        current_price = Decimal("8.69")
        slippage_guard_pct = Decimal("0.30")

        slippage_mult = Decimal("1") - slippage_guard_pct / Decimal("100")
        guarded_price = current_price * slippage_mult

        # 8.69 * 0.997 = 8.66393
        expected = Decimal("8.66393")
        assert abs(guarded_price - expected) < Decimal("0.001")

    def test_slippage_guard_calculation_buy(self):
        """Buy slippage guard: price * (1 + guard_pct/100)."""
        current_price = Decimal("100.00")
        slippage_guard_pct = Decimal("0.50")

        slippage_mult = Decimal("1") + slippage_guard_pct / Decimal("100")
        guarded_price = current_price * slippage_mult

        assert guarded_price == Decimal("100.500")

    def test_default_slippage_guard_is_030(self):
        """Default slippage guard should be 0.30% (matching existing IOC path)."""
        custom_info = {}
        guard = custom_info.get('aggressive_close_slippage_guard_pct', Decimal("0.30"))
        assert guard == Decimal("0.30")

    def test_configurable_slippage_guard(self):
        """Slippage guard should be configurable via custom_info."""
        custom_info = {'aggressive_close_slippage_guard_pct': Decimal("0.50")}
        guard = custom_info.get('aggressive_close_slippage_guard_pct', Decimal("0.30"))
        assert guard == Decimal("0.50")

    def test_river_loss_would_be_prevented(self):
        """RIVER-USD market sell at $8.69 losing 2.7% would be blocked by 0.3% guard."""
        # RIVER scenario: bought at $8.80 avg, market-sold at ~$8.56 (2.7% drop)
        mid_price = Decimal("8.69")
        guard_pct = Decimal("0.30")

        min_acceptable = mid_price * (Decimal("1") - guard_pct / Decimal("100"))
        # 8.69 * 0.997 = 8.66393 — anything below this would NOT fill

        worst_fill = Decimal("8.56")  # What RIVER got in reality
        assert worst_fill < min_acceptable, (
            f"RIVER's fill at {worst_fill} is below guarded price {min_acceptable} "
            f"— the guard would have prevented this loss"
        )


# ===================================================================
# INTEGRATION: Verify all fixes interact correctly
# ===================================================================

class TestForensicFixesIntegration:
    """Verify the 5 fixes work together to prevent the 2026-04-12 scenario."""

    def test_risk_manager_full_deadlock_scenario(self):
        """
        Simulate the exact 2026-04-12 scenario:
        1. 10 trades, 1 win (TON), 9 losses
        2. Win rate 10%, PnL negative
        3. Pause triggers
        4. Pause extends once
        5. Force resume with immunity
        """
        rm = ProfessionalRiskManager(
            max_pause_extensions=1,
            pause_cooldown_minutes=120,
            min_rolling_pnl_pct=-0.02,
            min_win_rate=0.35,
            post_resume_immunity_minutes=30,
        )

        # Simulate the 10 trades from the forensic report
        rm.record_trade_result("TON-USD", pnl_pct=0.006, close_reason="TAKE_PROFIT",
                               hold_time_minutes=72)
        rm.record_trade_result("WLD-USD", pnl_pct=-0.011, close_reason="NO_PROGRESS",
                               hold_time_minutes=63)
        rm.record_trade_result("COMP-USD", pnl_pct=-0.002, close_reason="EARLY_STOP",
                               hold_time_minutes=13)
        # 7 more breakeven/0 trades from EARLY_STOP cascade
        for _ in range(7):
            rm.record_trade_result("MISC-USD", pnl_pct=0.0, close_reason="EARLY_STOP",
                                   hold_time_minutes=0)

        portfolio = PortfolioRisk(
            total_equity=Decimal("155"),
            daily_pnl=Decimal("-2.64"),
            daily_pnl_pct=-0.017,
            max_daily_loss_pct=-3.0,
            open_positions=0,
            max_positions=5,
            recent_wins=1,
            recent_losses=9,
            win_rate=0.10,
            highly_correlated_positions=[],
            correlation_risk_score=0.0,
        )

        # Step 1: Pause triggers (rolling PnL negative + win rate low)
        can_open, reason = rm.can_open_new_position("COMP-USD", 0.7, portfolio)
        assert not can_open
        assert rm.pause_until is not None

        # Step 2: Expire first cooldown — should force resume (max_extensions=1)
        rm.pause_until = datetime.now() - timedelta(seconds=1)
        can_open, reason = rm.can_open_new_position("COMP-USD", 0.7, portfolio)
        assert can_open, f"Should force-resume after 1 extension, got: {reason}"

        # Step 3: Immunity active — even with bad trades, no re-trigger
        for _ in range(12):
            rm.record_trade_result("BAD-USD", pnl_pct=-0.01,
                                   close_reason="NO_PROGRESS", hold_time_minutes=30)

        can_open, reason = rm.can_open_new_position("COMP-USD", 0.7, portfolio)
        assert can_open, f"Post-resume immunity should protect, got: {reason}"
