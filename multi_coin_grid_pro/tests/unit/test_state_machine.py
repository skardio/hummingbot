"""
Unit tests for the consecutive failed-cycle state machine in GlobalRiskManager.

Item 3 — State Machine: 2x Failed Cycles → Coin Lock
"""
from decimal import Decimal

from multi_coin_grid_pro.core.global_risk_manager import GlobalRiskManager, RiskLimits

BASE_BALANCE = Decimal("1000")
NOW = 1_700_000_000.0  # fixed timestamp in the past


def make_grm(max_failures: int = 2) -> GlobalRiskManager:
    limits = RiskLimits(
        max_daily_loss_pct=Decimal("5"),
        max_balance_risk_per_trade_pct=Decimal("50"),
        max_total_open_risk_pct=Decimal("100"),
        min_hold_seconds=0,
        exit_cooldown_seconds=0,
        symbol_switch_cooldown_seconds=0,
        consecutive_loss_cooldown_seconds=0,
    )
    return GlobalRiskManager(BASE_BALANCE, limits, max_consecutive_failures=max_failures)


class TestFailedCycleInit:
    def test_initial_failed_cycles_zero(self):
        grm = make_grm()
        assert grm.get_failed_cycles("BTC-EUR") == 0

    def test_not_locked_initially(self):
        grm = make_grm()
        assert not grm.is_coin_cycle_locked("BTC-EUR")


class TestNoteFailedCycle:
    def test_single_failure_increments(self):
        grm = make_grm()
        grm.note_failed_cycle("BTC-EUR")
        assert grm.get_failed_cycles("BTC-EUR") == 1

    def test_two_failures_locks_coin(self):
        grm = make_grm(max_failures=2)
        grm.note_failed_cycle("BTC-EUR")
        grm.note_failed_cycle("BTC-EUR")
        assert grm.is_coin_cycle_locked("BTC-EUR")

    def test_one_failure_does_not_lock(self):
        grm = make_grm(max_failures=2)
        grm.note_failed_cycle("BTC-EUR")
        assert not grm.is_coin_cycle_locked("BTC-EUR")


class TestNoteSuccessfulCycle:
    def test_success_resets_failures(self):
        grm = make_grm()
        grm.note_failed_cycle("BTC-EUR")
        grm.note_failed_cycle("BTC-EUR")
        grm.note_successful_cycle("BTC-EUR")
        assert grm.get_failed_cycles("BTC-EUR") == 0
        assert not grm.is_coin_cycle_locked("BTC-EUR")

    def test_success_on_clean_coin_is_noop(self):
        grm = make_grm()
        grm.note_successful_cycle("ETH-EUR")  # should not raise
        assert grm.get_failed_cycles("ETH-EUR") == 0


class TestRegisterCloseTradeIntegration:
    def test_negative_pnl_increments_failed_cycles(self):
        grm = make_grm()
        grm.register_open_trade(symbol="BTC-EUR", notional=Decimal("100"), now=NOW)
        grm.register_close_trade(
            symbol="BTC-EUR", realised_pnl_quote=Decimal("-5"), now=NOW + 3600
        )
        assert grm.get_failed_cycles("BTC-EUR") == 1

    def test_positive_pnl_resets_failed_cycles(self):
        grm = make_grm()
        grm.note_failed_cycle("BTC-EUR")
        grm.register_open_trade(symbol="BTC-EUR", notional=Decimal("100"), now=NOW)
        grm.register_close_trade(
            symbol="BTC-EUR", realised_pnl_quote=Decimal("5"), now=NOW + 3600
        )
        assert grm.get_failed_cycles("BTC-EUR") == 0

    def test_two_losses_blocks_can_open_trade(self):
        grm = make_grm(max_failures=2)
        for _ in range(2):
            grm.register_open_trade(symbol="ETH-EUR", notional=Decimal("50"), now=NOW)
            grm.register_close_trade(
                symbol="ETH-EUR", realised_pnl_quote=Decimal("-3"), now=NOW + 1
            )
        result = grm.can_open_trade(
            symbol="ETH-EUR", requested_notional=Decimal("50"), now=NOW + 10
        )
        assert result is None


class TestDayResetClearsFailed:
    def test_new_day_resets_failed_cycles(self):
        grm = make_grm()
        grm.note_failed_cycle("BTC-EUR")
        grm.note_failed_cycle("BTC-EUR")
        assert grm.is_coin_cycle_locked("BTC-EUR")

        # Advance time by 25 hours (triggers new-day reset)
        next_day = NOW + 25 * 3600
        grm._reset_if_new_day(next_day)
        assert grm.get_failed_cycles("BTC-EUR") == 0
        assert not grm.is_coin_cycle_locked("BTC-EUR")


class TestPerSymbolIsolation:
    def test_failures_are_per_symbol(self):
        grm = make_grm(max_failures=2)
        grm.note_failed_cycle("BTC-EUR")
        grm.note_failed_cycle("BTC-EUR")
        # ETH should be unaffected
        assert not grm.is_coin_cycle_locked("ETH-EUR")
        assert grm.get_failed_cycles("ETH-EUR") == 0
