"""
Global risk management utilities shared across multi-asset controllers.

This module centralizes risk-limit evaluation for strategies that allocate
capital dynamically across symbols (e.g., multi-coin grid and arbitrage).

The risk manager tracks:
  * Daily realised PnL against a configurable loss cap
  * Aggregate open capital utilisation
  * Per-trade sizing caps expressed as % of account balance
  * Cooldowns following exits or streaks of consecutive losses
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, MutableMapping, Optional

DecimalZero = Decimal("0")
DecimalHundred = Decimal("100")


@dataclass(frozen=True)
class RiskLimits:
    """
    Container for configurable risk tolerances (expressed as percentages
    unless otherwise noted).
    """

    max_daily_loss_pct: Decimal
    max_balance_risk_per_trade_pct: Decimal
    max_total_open_risk_pct: Decimal
    min_hold_seconds: int
    exit_cooldown_seconds: int
    symbol_switch_cooldown_seconds: int
    consecutive_loss_cooldown_seconds: int


@dataclass
class AllocationRecord:
    symbol: str
    notional_quote: Decimal
    opened_at: float
    unrealised_pnl_quote: Decimal = DecimalZero


class GlobalRiskManager:
    """
    Lightweight risk governor that sits in front of strategy execution.

    It exposes helpers that strategies can query before creating new
    positions and update when orders close.  The manager does not perform
    any I/O; callers are responsible for providing timestamps and realised
    PnL figures.
    """

    def __init__(self, reference_balance_quote: Decimal, limits: RiskLimits):
        if reference_balance_quote <= DecimalZero:
            raise ValueError("reference_balance_quote must be positive")
        self._reference_balance_quote = reference_balance_quote
        self._limits = limits

        # Rolling daily metrics
        self._daily_loss_quote: Decimal = DecimalZero
        self._daily_realised_pnl_quote: Decimal = DecimalZero
        self._last_reset_date: _dt.date = _dt.datetime.utcnow().date()

        # Open exposure per symbol and total
        self._open_allocations: MutableMapping[str, AllocationRecord] = {}
        self._total_open_notional: Decimal = DecimalZero

        # Cooldown tracking
        self._last_exit_time: Dict[str, float] = {}
        self._last_switch_time: float = 0.0
        self._last_loss_time: Optional[float] = None
        self._consecutive_losses: int = 0

    # ------------------------------------------------------------------#
    # Helpers
    # ------------------------------------------------------------------#
    def _reset_if_new_day(self, now: float) -> None:
        current_date = _dt.datetime.utcfromtimestamp(now).date()
        if current_date != self._last_reset_date:
            self._daily_loss_quote = DecimalZero
            self._daily_realised_pnl_quote = DecimalZero
            self._last_reset_date = current_date
            self._consecutive_losses = 0
            self._last_loss_time = None

    def _max_trade_notional(self) -> Decimal:
        per_trade_cap = (
            self._reference_balance_quote
            * self._limits.max_balance_risk_per_trade_pct
            / DecimalHundred
        )
        return max(per_trade_cap, DecimalZero)

    def _max_total_notional(self) -> Decimal:
        return (
            self._reference_balance_quote
            * self._limits.max_total_open_risk_pct
            / DecimalHundred
        )

    # ------------------------------------------------------------------#
    # Public API
    # ------------------------------------------------------------------#
    def can_open_trade(self, *, symbol: str, requested_notional: Decimal, now: float, logger=None) -> Optional[Decimal]:
        """
        Determine whether a trade of the requested notional can be opened.

        Returns
        -------
        Optional[Decimal]
            The approved notional (may be smaller than requested)
            or ``None`` if trading must be blocked.
        """
        if requested_notional <= DecimalZero:
            if logger:
                logger.info(f"🛑 RISK BLOCKED {symbol}: requested_notional <= 0 ({requested_notional})")
            return None

        self._reset_if_new_day(now)

        if self._daily_loss_quote <= DecimalZero:
            pass
        else:
            daily_loss_pct = (self._daily_loss_quote / self._reference_balance_quote) * DecimalHundred
            if daily_loss_pct >= self._limits.max_daily_loss_pct:
                if logger:
                    logger.info(
                        f"🛑 RISK BLOCKED {symbol}: daily loss {
                            daily_loss_pct:.2f}% >= {
                            self._limits.max_daily_loss_pct}%")
                return None

        # Cooldown following consecutive losses
        if self._last_loss_time is not None and self._consecutive_losses > 0:
            elapsed = now - self._last_loss_time
            if elapsed < self._limits.consecutive_loss_cooldown_seconds:
                if logger:
                    logger.info(
                        f"🛑 RISK BLOCKED {symbol}: consecutive loss cooldown ({elapsed:.0f}s / {self._limits.consecutive_loss_cooldown_seconds}s)")  # noqa: E501
                return None

        # Exit cooldown per symbol
        last_exit = self._last_exit_time.get(symbol)
        if last_exit is not None:
            elapsed = now - last_exit
            if elapsed < self._limits.exit_cooldown_seconds:
                if logger:
                    logger.info(
                        f"🛑 RISK BLOCKED {symbol}: exit cooldown ({elapsed:.0f}s / {self._limits.exit_cooldown_seconds}s)")  # noqa: E501
                return None

        # Switch cooldown (global)
        if self._last_switch_time > 0 and (now - self._last_switch_time) < self._limits.symbol_switch_cooldown_seconds:
            if logger:
                logger.info(
                    f"🛑 RISK BLOCKED {symbol}: switch cooldown "
                    f"({(now - self._last_switch_time):.0f}s / {self._limits.symbol_switch_cooldown_seconds}s)"
                )
            return None

        capped_notional = min(requested_notional, self._max_trade_notional())
        if capped_notional <= DecimalZero:
            if logger:
                logger.info(
                    f"🛑 RISK BLOCKED {symbol}: capped_notional <= 0 (requested={requested_notional}, max_per_trade={
                        self._max_trade_notional()})")
            return None

        projected_total = self._total_open_notional + \
            (capped_notional if symbol not in self._open_allocations else DecimalZero)
        if projected_total > self._max_total_notional():
            if logger:
                logger.info(
                    f"🛑 RISK BLOCKED {symbol}: projected total {projected_total} > max {
                        self._max_total_notional()}")
            return None

        if logger:
            logger.info(f"✅ RISK APPROVED {symbol}: notional €{capped_notional}")
        return capped_notional

    def register_open_trade(self, *, symbol: str, notional: Decimal, now: float) -> None:
        """
        Record a new open allocation.  Call only after orders are accepted.
        """
        if notional <= DecimalZero:
            return

        self._reset_if_new_day(now)
        self.note_switch(now)
        existing = self._open_allocations.get(symbol)
        if existing:
            self._total_open_notional -= existing.notional_quote

        allocation = AllocationRecord(symbol=symbol, notional_quote=notional, opened_at=now)
        self._open_allocations[symbol] = allocation
        self._total_open_notional += notional

    def register_close_trade(
        self,
        *,
        symbol: str,
        realised_pnl_quote: Decimal,
        now: float,
    ) -> None:
        """
        Update realised PnL statistics and remove exposure for the symbol.
        """
        self._reset_if_new_day(now)
        self._last_exit_time[symbol] = now

        allocation = self._open_allocations.pop(symbol, None)
        if allocation is not None:
            self._total_open_notional = max(
                DecimalZero, self._total_open_notional - allocation.notional_quote
            )

        self._daily_realised_pnl_quote += realised_pnl_quote
        if realised_pnl_quote < DecimalZero:
            self._daily_loss_quote += abs(realised_pnl_quote)
            self._consecutive_losses += 1
            self._last_loss_time = now
        else:
            self._consecutive_losses = 0
            self._last_loss_time = None

    def update_unrealised(self, *, symbol: str, unrealised_quote: Decimal) -> None:
        """
        Optional helper to store unrealised PnL for monitoring dashboards.
        """
        allocation = self._open_allocations.get(symbol)
        if allocation:
            allocation.unrealised_pnl_quote = unrealised_quote

    def coins_in_exit_cooldown(self, now: float) -> Dict[str, float]:
        """
        Return coins that are still cooling down along with remaining seconds.
        """
        self._reset_if_new_day(now)
        remaining: Dict[str, float] = {}
        for symbol, timestamp in list(self._last_exit_time.items()):
            elapsed = now - timestamp
            remaining_seconds = self._limits.exit_cooldown_seconds - elapsed
            if remaining_seconds > 0:
                remaining[symbol] = remaining_seconds
            else:
                # Cooldown expired, drop record to keep structure tidy
                del self._last_exit_time[symbol]
        return remaining

    def switch_cooldown_remaining(self, now: float) -> float:
        """
        Return remaining seconds on the global switch cooldown (0 if inactive).
        """
        if self._last_switch_time <= 0:
            return 0.0
        elapsed = now - self._last_switch_time
        remaining = self._limits.symbol_switch_cooldown_seconds - elapsed
        return remaining if remaining > 0 else 0.0

    def note_switch(self, now: float) -> None:
        self._last_switch_time = now

    def note_exit(self, symbol: str, now: float) -> None:
        """
        Record an exit event without affecting realised PnL
        (used when a stop is requested but fills not yet known).
        """
        self._last_exit_time[symbol] = now

    @property
    def min_hold_seconds(self) -> int:
        return self._limits.min_hold_seconds

    @property
    def exit_cooldown_seconds(self) -> int:
        return self._limits.exit_cooldown_seconds

    @property
    def switch_cooldown_seconds(self) -> int:
        return self._limits.symbol_switch_cooldown_seconds

    @property
    def cumulative_daily_loss_quote(self) -> Decimal:
        return self._daily_loss_quote

    @property
    def daily_loss_pct(self) -> Decimal:
        if self._reference_balance_quote == DecimalZero:
            return DecimalZero
        return (self._daily_loss_quote / self._reference_balance_quote) * DecimalHundred

    @property
    def total_open_notional(self) -> Decimal:
        return self._total_open_notional
