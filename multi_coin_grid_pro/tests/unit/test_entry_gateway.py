"""
Unit tests for EntryGateway facade.

Item 1 — Entry Gateway Facade
"""
from decimal import Decimal
from unittest.mock import MagicMock

from multi_coin_grid_pro.core.entry_gateway import EntryGateway
from multi_coin_grid_pro.core.global_risk_manager import CoinCycleState

NOW = 1_700_000_000.0
NOTIONAL = Decimal("100")


def make_gateway(
    cycle_locked: bool = False,
    cycle_state=None,
    disabled_today: bool = False,
    can_open_result=Decimal("100"),
    min_quality: int = 0,
) -> EntryGateway:
    risk = MagicMock()
    risk.is_coin_cycle_locked.return_value = cycle_locked
    risk.get_coin_cycle_state.return_value = cycle_state
    risk.is_coin_disabled_today.return_value = disabled_today
    risk.can_open_trade.return_value = can_open_result
    risk.get_failed_cycles.return_value = 2
    return EntryGateway(risk_manager=risk, min_quality_score=min_quality)


class TestEntryGatewayAllowed:
    def test_clean_path_returns_allowed(self):
        gw = make_gateway()
        decision = gw.can_enter(symbol="BTC-EUR", requested_notional=NOTIONAL, now=NOW)
        assert decision.allowed is True
        assert decision.approved_notional == Decimal("100")
        assert decision.blocked_by == "none"
        assert decision.quality_score == 100  # default

    def test_quality_score_passed_through(self):
        gw = make_gateway()
        decision = gw.can_enter(
            symbol="BTC-EUR", requested_notional=NOTIONAL, now=NOW, quality_score=75
        )
        assert decision.allowed is True
        assert decision.quality_score == 75


class TestEntryGatewayCycleLock:
    def test_two_failed_cycles_state_blocks(self):
        gw = make_gateway(cycle_locked=False, cycle_state=CoinCycleState.TWO_FAILED_CYCLES)
        decision = gw.can_enter(symbol="ETH-EUR", requested_notional=NOTIONAL, now=NOW)
        assert decision.allowed is False
        assert decision.blocked_by == "cycle_lock"
        assert "TWO_FAILED_CYCLES" in decision.reason

    def test_cycle_lock_blocks(self):
        gw = make_gateway(cycle_locked=True)
        decision = gw.can_enter(symbol="ETH-EUR", requested_notional=NOTIONAL, now=NOW)
        assert decision.allowed is False
        assert decision.blocked_by == "cycle_lock"
        assert "consecutive" in decision.reason

    def test_cycle_lock_approved_notional_is_none(self):
        gw = make_gateway(cycle_locked=True)
        decision = gw.can_enter(symbol="ETH-EUR", requested_notional=NOTIONAL, now=NOW)
        assert decision.approved_notional is None


class TestEntryGatewayKillSwitch:
    def test_kill_switch_blocks(self):
        gw = make_gateway(disabled_today=True)
        decision = gw.can_enter(symbol="SOL-EUR", requested_notional=NOTIONAL, now=NOW)
        assert decision.allowed is False
        assert decision.blocked_by == "kill_switch"

    def test_cycle_lock_takes_priority_over_kill_switch(self):
        gw = make_gateway(cycle_locked=True, disabled_today=True)
        decision = gw.can_enter(symbol="SOL-EUR", requested_notional=NOTIONAL, now=NOW)
        assert decision.blocked_by == "cycle_lock"


class TestEntryGatewayRiskManager:
    def test_risk_manager_none_blocks(self):
        gw = make_gateway(can_open_result=None)
        decision = gw.can_enter(symbol="ADA-EUR", requested_notional=NOTIONAL, now=NOW)
        assert decision.allowed is False
        assert decision.blocked_by == "risk_manager"

    def test_approved_notional_from_risk_manager(self):
        gw = make_gateway(can_open_result=Decimal("75"))
        decision = gw.can_enter(symbol="BTC-EUR", requested_notional=NOTIONAL, now=NOW)
        assert decision.allowed is True
        assert decision.approved_notional == Decimal("75")


class TestEntryGatewayQualityFloor:
    def test_score_below_floor_blocked(self):
        gw = make_gateway(min_quality=60)
        decision = gw.can_enter(
            symbol="BTC-EUR", requested_notional=NOTIONAL, now=NOW, quality_score=50
        )
        assert decision.allowed is False
        assert decision.blocked_by == "quality"

    def test_score_at_floor_allowed(self):
        gw = make_gateway(min_quality=60)
        decision = gw.can_enter(
            symbol="BTC-EUR", requested_notional=NOTIONAL, now=NOW, quality_score=60
        )
        assert decision.allowed is True

    def test_zero_floor_allows_any_score(self):
        gw = make_gateway(min_quality=0)
        decision = gw.can_enter(
            symbol="BTC-EUR", requested_notional=NOTIONAL, now=NOW, quality_score=0
        )
        assert decision.allowed is True
