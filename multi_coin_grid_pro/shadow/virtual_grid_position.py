"""Simplified virtual position model for the A/B shadow sandbox.

IMPORTANT, explicit simplification (documented, not hidden): this is a
**single-level** long-only entry/exit model, not a byte-for-byte clone of
``hummingbot.strategy_v2.executors.grid_executor.GridExecutor``'s multi-level
grid ladder. Reusing the live ``GridExecutor`` class directly was rejected:
it is tightly coupled to ``ConnectorBase``/``StrategyV2Base`` and would
require either a live connector (defeats the isolation goal) or extensive
mocking that risks silently diverging from real behaviour. Instead, this
model reuses the exact same *pure* exit-safety formulas the live executor
uses (``realized_net_pnl``, ``fee_aware_exit_decision`` from
``multi_coin_grid_pro.logic.exit_safety``), so the STOP_LOSS / fee-aware
TAKE_PROFIT math is identical to production, only the multi-level grid
mechanics are not reproduced.

Exit mechanisms simulated: STOP_LOSS (unrealized pnl% <= -stop_loss_pct),
fee-aware TAKE_PROFIT (net pnl% >= required_net_pct AND price confirms
break-even), and a TIME_LIMIT (max hold seconds). EARLY_STOP variants driven
by the controller's five-layer exit stack, US-005, or the kill switch are
*not* reproduced — flagged as an open limitation, not silently approximated.

No look-ahead: ``tick()`` only ever receives the current price; it never
looks at future data. Running this forward in real time (not over a stored
historical series) is what guarantees that property.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from multi_coin_grid_pro.logic.exit_safety import fee_aware_exit_decision, realized_net_pnl


class VirtualPositionStatus(Enum):
    PENDING_ENTRY = "PENDING_ENTRY"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class VirtualExitReason(Enum):
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT_NET = "TAKE_PROFIT_NET"
    TIME_LIMIT = "TIME_LIMIT"


@dataclass
class VirtualGridPosition:
    symbol: str
    notional_quote: Decimal
    stop_loss_pct: Decimal
    required_take_profit_net_pct: Decimal
    maker_fee_pct: Decimal
    taker_fee_pct: Decimal
    max_hold_seconds: float
    limit_price: Decimal                      # the virtual LIMIT_MAKER entry price we are waiting to fill
    created_at: float

    status: VirtualPositionStatus = VirtualPositionStatus.PENDING_ENTRY
    entry_price: Optional[Decimal] = None
    entry_time: Optional[float] = None
    position_size_base: Decimal = Decimal("0")
    entry_fees_quote: Decimal = Decimal("0")
    _consecutive_fill_ticks: int = 0

    unrealized_pnl_quote: Decimal = Decimal("0")
    exit_time: Optional[float] = None
    exit_price: Optional[Decimal] = None
    exit_reason: Optional[VirtualExitReason] = None
    gross_pnl_quote: Optional[Decimal] = None
    fees_quote: Optional[Decimal] = None
    net_pnl_quote: Optional[Decimal] = None

    # Non-production, observability-only: what the fee would have been at the
    # empirically-measured real rate (~0.29%, see FASE B investigation),
    # recorded alongside the primary config-assumed fee for later comparison.
    # Never used in any exit decision.
    _empirical_fee_pct_for_annotation: Decimal = Decimal("0.0029")
    annotated_fee_quote_at_empirical_rate: Optional[Decimal] = None
    # Full secondary bottom line at the empirical fee rate — NOT a
    # replacement for net_pnl_quote (which must stay coupled to the
    # config-assumed fee used by the exit decisions above, for a fair A/B
    # comparison against the live bot's own assumptions). This field exists
    # so analysts are never tempted to quietly substitute the old
    # best-case/config fee for realised trading cost when reading results —
    # both numbers are reported side by side, explicitly labelled.
    annotated_net_pnl_quote_at_empirical_rate: Optional[Decimal] = None

    def try_fill_entry(self, current_price: Decimal, now: float) -> bool:
        """Consider the virtual LIMIT_MAKER buy filled only after the public
        last-traded price has been at/below our limit price for 2 consecutive
        ticks — a conservative approximation that avoids single-tick noise,
        in place of naively filling the instant a candle touches the limit."""
        if self.status != VirtualPositionStatus.PENDING_ENTRY:
            return False
        if current_price <= self.limit_price:
            self._consecutive_fill_ticks += 1
        else:
            self._consecutive_fill_ticks = 0
        if self._consecutive_fill_ticks < 2:
            return False

        self.entry_price = current_price
        self.entry_time = now
        self.position_size_base = self.notional_quote / current_price
        self.entry_fees_quote = self.notional_quote * self.maker_fee_pct
        self.status = VirtualPositionStatus.OPEN
        return True

    def tick(self, current_price: Decimal, now: float) -> Optional[VirtualExitReason]:
        """Update unrealized PnL and check exit conditions. Returns the exit
        reason if this tick should close the position, else None."""
        if self.status != VirtualPositionStatus.OPEN:
            return None

        gross_move_pct = (current_price - self.entry_price) / self.entry_price
        self.unrealized_pnl_quote = (
            gross_move_pct * self.notional_quote - self.entry_fees_quote
        )
        unrealized_pnl_pct = self.unrealized_pnl_quote / self.notional_quote

        # 1) STOP_LOSS — mirrors grid_executor.stop_loss_condition(): fires on
        # mid-price unrealized loss, not fee-aware (matches production exactly,
        # including the known asymmetry documented in the FASE B report).
        if unrealized_pnl_pct <= -self.stop_loss_pct:
            return VirtualExitReason.STOP_LOSS

        # 2) TAKE_PROFIT_NET — mirrors grid_executor.take_profit_condition():
        # fee-aware, requires net pnl (after estimated exit fee) >= configured
        # minimum, using the exact same break-even formula as production.
        decision = fee_aware_exit_decision(
            side="BUY",
            avg_entry=self.entry_price,
            position_size_base=self.position_size_base,
            buy_fees_quote=self.entry_fees_quote,
            current_price=current_price,
            expected_exit_fee_rate=self.taker_fee_pct,
        )
        if decision.allowed:
            expected_exit_fee = self.position_size_base * current_price * self.taker_fee_pct
            net_pnl_after_fees = self.unrealized_pnl_quote - expected_exit_fee
            net_pnl_pct_after_fees = net_pnl_after_fees / self.notional_quote
            if net_pnl_pct_after_fees >= self.required_take_profit_net_pct:
                return VirtualExitReason.TAKE_PROFIT_NET

        # 3) TIME_LIMIT — simple max-hold timeout (approximates the
        # controller's max_hold_time_exit / HARD_CAP_TIME_LIMIT).
        if self.max_hold_seconds > 0 and (now - self.entry_time) >= self.max_hold_seconds:
            return VirtualExitReason.TIME_LIMIT

        return None

    def close(self, current_price: Decimal, now: float, reason: VirtualExitReason) -> None:
        self.status = VirtualPositionStatus.CLOSED
        self.exit_time = now
        self.exit_price = current_price
        self.exit_reason = reason

        sell_quote = self.position_size_base * current_price
        buy_quote = self.position_size_base * self.entry_price
        exit_fees_quote = sell_quote * self.taker_fee_pct

        self.gross_pnl_quote = sell_quote - buy_quote
        self.fees_quote = self.entry_fees_quote + exit_fees_quote
        self.net_pnl_quote = realized_net_pnl(
            realized_sell_quote=sell_quote,
            realized_buy_quote=buy_quote,
            realized_buy_fees_quote=self.entry_fees_quote,
            realized_sell_fees_quote=exit_fees_quote,
        )
        empirical_exit_fee = sell_quote * self._empirical_fee_pct_for_annotation
        empirical_entry_fee = buy_quote * self._empirical_fee_pct_for_annotation
        self.annotated_fee_quote_at_empirical_rate = empirical_entry_fee + empirical_exit_fee
        self.annotated_net_pnl_quote_at_empirical_rate = realized_net_pnl(
            realized_sell_quote=sell_quote,
            realized_buy_quote=buy_quote,
            realized_buy_fees_quote=empirical_entry_fee,
            realized_sell_fees_quote=empirical_exit_fee,
        )
