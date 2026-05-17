from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FeeAwareExitDecision:
    avg_entry: Decimal
    break_even: Decimal
    expected_exit_fee: Decimal
    expected_exit_fee_rate: Decimal
    current_price: Decimal
    allowed: bool


def realized_net_pnl(
    realized_sell_quote: Decimal,
    realized_buy_quote: Decimal,
    realized_buy_fees_quote: Decimal,
    realized_sell_fees_quote: Decimal,
) -> Decimal:
    """Canonical Kraken-style realized net P&L formula."""
    return (
        realized_sell_quote
        - realized_buy_quote
        - realized_buy_fees_quote
        - realized_sell_fees_quote
    )


def stop_allowed_after_preclose(can_close: bool, emergency: bool) -> bool:
    """Non-emergency stops must respect failed pre-close validation."""
    return can_close or emergency


def position_tracking_cleanup_allowed(status_name: str, is_active: bool) -> bool:
    """Position tracking may only be cleared after confirmed executor closure."""
    return status_name == "TERMINATED" and not is_active


def fee_aware_timeout_bypass_allowed(
    close_reason: str,
    blocked_for_sec: float,
    bypass_after_sec: float,
) -> bool:
    """Allow stale no-progress exits to break fee-aware limbo after a max wait."""
    return (
        close_reason == "NO_PROGRESS_TIMEOUT"
        and bypass_after_sec > 0
        and blocked_for_sec >= bypass_after_sec
    )


def fee_aware_exit_decision(
    side: str,
    avg_entry: Decimal,
    position_size_base: Decimal,
    buy_fees_quote: Decimal,
    current_price: Decimal,
    expected_exit_fee_rate: Decimal,
) -> FeeAwareExitDecision:
    """Return fee-aware break-even and whether the proposed exit is allowed."""
    if position_size_base <= Decimal("0") or avg_entry <= Decimal("0"):
        return FeeAwareExitDecision(
            avg_entry=avg_entry,
            break_even=Decimal("0"),
            expected_exit_fee=Decimal("0"),
            expected_exit_fee_rate=expected_exit_fee_rate,
            current_price=current_price,
            allowed=True,
        )

    expected_exit_fee = position_size_base * current_price * expected_exit_fee_rate
    side_name = side.upper()

    if side_name == "BUY":
        buy_cost_quote = position_size_base * avg_entry
        required_quote = buy_cost_quote + buy_fees_quote
        break_even = required_quote / (position_size_base * (Decimal("1") - expected_exit_fee_rate))
        allowed = current_price >= break_even
    else:
        sell_proceeds_quote = position_size_base * avg_entry
        available_quote = sell_proceeds_quote - buy_fees_quote
        break_even = available_quote / (position_size_base * (Decimal("1") + expected_exit_fee_rate))
        allowed = current_price <= break_even

    return FeeAwareExitDecision(
        avg_entry=avg_entry,
        break_even=break_even,
        expected_exit_fee=expected_exit_fee,
        expected_exit_fee_rate=expected_exit_fee_rate,
        current_price=current_price,
        allowed=allowed,
    )
