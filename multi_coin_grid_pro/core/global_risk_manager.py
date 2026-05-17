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
import time
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Dict, MutableMapping, Optional

from multi_coin_grid_pro.core.exit_types import ExitType, cooldown_for_exit
from multi_coin_grid_pro.utils.log_throttle import should_log

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
    max_hold_seconds: int = 0  # 0 = unlimited (backwards compatible) - STORY A1


@dataclass
class AllocationRecord:
    symbol: str
    notional_quote: Decimal
    opened_at: float
    unrealised_pnl_quote: Decimal = DecimalZero


class CoinCycleState(str, Enum):
    """Explicit per-coin re-entry state after the last completed cycle."""

    READY = "READY"
    WIN_EXIT = "WIN_EXIT"
    LOSS_EXIT = "LOSS_EXIT"
    TWO_FAILED_CYCLES = "TWO_FAILED_CYCLES"


@dataclass(frozen=True)
class CoinCycleStatus:
    """Observable state-machine snapshot for one coin."""

    symbol: str
    state: CoinCycleState
    failed_cycles: int
    last_pnl_quote: Decimal = DecimalZero
    last_exit_type: ExitType = ExitType.UNKNOWN


class GlobalRiskManager:
    """
    Lightweight risk governor that sits in front of strategy execution.

    It exposes helpers that strategies can query before creating new
    positions and update when orders close.  The manager does not perform
    any I/O; callers are responsible for providing timestamps and realised
    PnL figures.
    """

    def __init__(self, reference_balance_quote: Decimal, limits: RiskLimits,
                 max_consecutive_failures: int = 2):
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
        self._exit_cooldown_override: Dict[str, int] = {}   # per-symbol cooldown (seconds)
        self._exit_type_per_symbol: Dict[str, ExitType] = {}
        self._last_switch_time: float = 0.0
        self._last_loss_time: Dict[str, float] = {}       # per-coin
        self._consecutive_losses: Dict[str, int] = {}     # per-coin

        # Daily coin kill switch (item 4)
        self._daily_coin_pnl: Dict[str, float] = {}      # cumulative PnL per coin today
        self._coin_r_unit: float = 5.0                    # configurable via set_r_unit()

        # Item 3: Consecutive failed-cycle lock
        self._max_consecutive_failures: int = max_consecutive_failures
        self._failed_cycles: Dict[str, int] = {}          # consecutive losses per coin today
        self._cycle_state: Dict[str, CoinCycleState] = {}
        self._last_cycle_pnl: Dict[str, Decimal] = {}

    # ------------------------------------------------------------------#
    # Helpers
    # ------------------------------------------------------------------#
    def _reset_if_new_day(self, now: float) -> None:
        current_date = _dt.datetime.utcfromtimestamp(now).date()
        if current_date != self._last_reset_date:
            self._daily_loss_quote = DecimalZero
            self._daily_realised_pnl_quote = DecimalZero
            self._last_reset_date = current_date
            self._consecutive_losses.clear()
            self._last_loss_time.clear()
            self._daily_coin_pnl.clear()        # daily coin kill switch reset
            self._failed_cycles.clear()         # item 3: reset failed cycle counter
            self._cycle_state.clear()
            self._last_cycle_pnl.clear()

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

        # Cooldown following consecutive losses (per-coin)
        symbol_loss_time = self._last_loss_time.get(symbol)
        symbol_consec = self._consecutive_losses.get(symbol, 0)
        if symbol_loss_time is not None and symbol_consec > 0:
            elapsed = now - symbol_loss_time
            if elapsed < self._limits.consecutive_loss_cooldown_seconds:
                if logger and should_log(f"risk_blocked_loss_{symbol}", interval_sec=300):
                    logger.info(
                        f"🛑 RISK BLOCKED {symbol}: consecutive loss cooldown ({elapsed:.0f}s / {self._limits.consecutive_loss_cooldown_seconds}s)")  # noqa: E501
                return None

        # Item 3: Cycle lock — block if coin has >= max_consecutive_failures losses
        if self.is_coin_cycle_locked(symbol):
            n = self._failed_cycles.get(symbol, 0)
            if logger and should_log(f"risk_blocked_cycle_{symbol}", interval_sec=300):
                logger.info(
                    f"🔒 COIN_CYCLE_LOCKED {symbol}: "
                    f"{n} consecutive losses today (max {self._max_consecutive_failures})"
                )
            return None

        # Daily coin kill switch — block if >= -2R today
        if self.is_coin_disabled_today(symbol):
            if logger and should_log(f"risk_blocked_kill_{symbol}", interval_sec=300):
                logger.info(
                    f"🚫 COIN_DISABLED_TODAY {symbol}: "
                    f"daily_pnl={self._daily_coin_pnl.get(symbol, 0.0):.2f} < -2R"
                )
            return None

        # Exit cooldown per symbol (duration depends on exit type)
        last_exit = self._last_exit_time.get(symbol)
        if last_exit is not None:
            elapsed = now - last_exit
            cooldown = self._exit_cooldown_override.get(
                symbol, self._limits.exit_cooldown_seconds
            )
            if elapsed < cooldown:
                exit_type = self._exit_type_per_symbol.get(symbol, ExitType.UNKNOWN)
                if logger and should_log(f"risk_blocked_exit_{symbol}", interval_sec=300):
                    logger.info(
                        f"🛑 RISK BLOCKED {symbol}: exit cooldown "
                        f"[{exit_type.value}] ({elapsed:.0f}s / {cooldown}s)"
                    )
                return None

        # Switch cooldown (global)
        if self._last_switch_time > 0 and (now - self._last_switch_time) < self._limits.symbol_switch_cooldown_seconds:
            if logger and should_log(f"risk_blocked_switch_{symbol}", interval_sec=300):
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

        if symbol not in self._open_allocations:
            remaining = self._max_total_notional() - self._total_open_notional
            if remaining <= DecimalZero:
                if logger:
                    logger.info(
                        f"🛑 RISK BLOCKED {symbol}: no room left "
                        f"(open={self._total_open_notional}, max={self._max_total_notional()})")
                return None
            if capped_notional > remaining:
                if logger:
                    logger.info(
                        f"📉 RISK CAPPED {symbol}: €{capped_notional} → €{remaining} "
                        f"(open={self._total_open_notional}, max={self._max_total_notional()})")
                capped_notional = remaining

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
        exit_type: ExitType = ExitType.UNKNOWN,
    ) -> None:
        """
        Update realised PnL statistics and remove exposure for the symbol.

        Parameters
        ----------
        exit_type : ExitType
            Classification of why the position was closed.  Determines the
            cooldown duration applied to this symbol before a new entry.
        """
        self._reset_if_new_day(now)
        # Apply exit-type-specific cooldown
        self._last_exit_time[symbol] = now
        self._exit_type_per_symbol[symbol] = exit_type
        self._exit_cooldown_override[symbol] = cooldown_for_exit(exit_type, now)
        # Daily coin PnL tracking for kill switch
        self._daily_coin_pnl[symbol] = (
            self._daily_coin_pnl.get(symbol, 0.0) + float(realised_pnl_quote)
        )

        allocation = self._open_allocations.pop(symbol, None)
        if allocation is not None:
            self._total_open_notional = max(
                DecimalZero, self._total_open_notional - allocation.notional_quote
            )

        self._daily_realised_pnl_quote += realised_pnl_quote
        if realised_pnl_quote < DecimalZero:
            self._daily_loss_quote += abs(realised_pnl_quote)
            self._consecutive_losses[symbol] = self._consecutive_losses.get(symbol, 0) + 1
            self._last_loss_time[symbol] = now
            self.note_failed_cycle(symbol)      # item 3
        else:
            self._consecutive_losses.pop(symbol, None)
            self._last_loss_time.pop(symbol, None)
            self.note_successful_cycle(symbol)  # item 3
        self._last_cycle_pnl[symbol] = realised_pnl_quote

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
            cooldown = self._exit_cooldown_override.get(
                symbol, self._limits.exit_cooldown_seconds
            )
            remaining_seconds = cooldown - elapsed
            if remaining_seconds > 0:
                remaining[symbol] = remaining_seconds
            else:
                # Cooldown expired, drop record to keep structure tidy
                del self._last_exit_time[symbol]
                self._exit_cooldown_override.pop(symbol, None)
                self._exit_type_per_symbol.pop(symbol, None)
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

    def note_exit(
        self,
        symbol: str,
        now: float,
        exit_type: ExitType = ExitType.UNKNOWN,
    ) -> None:
        """
        Record an exit event without affecting realised PnL.

        Used when a stop is requested but fills are not yet known.
        Applies the exit-type-specific cooldown immediately.
        """
        self._last_exit_time[symbol] = now
        self._exit_type_per_symbol[symbol] = exit_type
        self._exit_cooldown_override[symbol] = cooldown_for_exit(exit_type, now)

    def get_exit_type(self, symbol: str) -> Optional[ExitType]:
        """Return the exit type recorded for a symbol (or None if not set)."""
        return self._exit_type_per_symbol.get(symbol)

    # ------------------------------------------------------------------#
    # Item 3: Consecutive failed-cycle lock helpers
    # ------------------------------------------------------------------#

    def note_failed_cycle(self, symbol: str) -> None:
        """Increment consecutive failure count for this coin."""
        self._failed_cycles[symbol] = self._failed_cycles.get(symbol, 0) + 1
        self._cycle_state[symbol] = (
            CoinCycleState.TWO_FAILED_CYCLES
            if self.is_coin_cycle_locked(symbol)
            else CoinCycleState.LOSS_EXIT
        )

    def note_successful_cycle(self, symbol: str) -> None:
        """Reset consecutive failure count on success."""
        self._failed_cycles.pop(symbol, None)
        self._cycle_state[symbol] = CoinCycleState.WIN_EXIT

    def is_coin_cycle_locked(self, symbol: str, max_failures: int = -1) -> bool:
        """True if coin has >= max_consecutive_failures consecutive losses today."""
        limit = max_failures if max_failures >= 0 else self._max_consecutive_failures
        return self._failed_cycles.get(symbol, 0) >= limit

    def get_failed_cycles(self, symbol: str) -> int:
        """Return the current consecutive failure count for this coin."""
        return self._failed_cycles.get(symbol, 0)

    def get_coin_cycle_state(self, symbol: str) -> CoinCycleState:
        """Return explicit WIN/LOSS/2_FAILED state for re-entry decisions."""
        if self.is_coin_cycle_locked(symbol):
            return CoinCycleState.TWO_FAILED_CYCLES
        return self._cycle_state.get(symbol, CoinCycleState.READY)

    def get_coin_cycle_status(self, symbol: str) -> CoinCycleStatus:
        """Return a structured state-machine snapshot for logs/tests."""
        return CoinCycleStatus(
            symbol=symbol,
            state=self.get_coin_cycle_state(symbol),
            failed_cycles=self.get_failed_cycles(symbol),
            last_pnl_quote=self._last_cycle_pnl.get(symbol, DecimalZero),
            last_exit_type=self._exit_type_per_symbol.get(symbol, ExitType.UNKNOWN),
        )

    # ------------------------------------------------------------------#
    # Daily coin kill switch helpers (item 4)
    # ------------------------------------------------------------------#

    def set_r_unit(self, r_unit_quote: float) -> None:
        """Configure the R unit size (1R in quote currency)."""
        self._coin_r_unit = max(0.01, float(r_unit_quote))

    def record_coin_pnl(self, symbol: str, pnl_quote: float) -> None:
        """Record additional realised PnL for daily coin kill switch tracking."""
        self._daily_coin_pnl[symbol] = (
            self._daily_coin_pnl.get(symbol, 0.0) + pnl_quote
        )

    def get_coin_daily_pnl(self, symbol: str) -> float:
        """Return cumulative daily PnL for a symbol in quote currency."""
        return self._daily_coin_pnl.get(symbol, 0.0)

    def is_coin_halved_today(self, symbol: str) -> bool:
        """True when coin's daily loss exceeds -1R (position size should be halved)."""
        return self._daily_coin_pnl.get(symbol, 0.0) < -self._coin_r_unit

    def is_coin_disabled_today(self, symbol: str) -> bool:
        """True when coin's daily loss exceeds -2R (disabled for rest of day)."""
        return self._daily_coin_pnl.get(symbol, 0.0) < -2.0 * self._coin_r_unit

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
        # Auto-reset on new day when accessed
        self._reset_if_new_day(time.time())
        return self._daily_loss_quote

    @property
    def daily_loss_pct(self) -> Decimal:
        # Auto-reset on new day when accessed
        self._reset_if_new_day(time.time())
        if self._reference_balance_quote == DecimalZero:
            return DecimalZero
        return (self._daily_loss_quote / self._reference_balance_quote) * DecimalHundred

    @property
    def total_open_notional(self) -> Decimal:
        return self._total_open_notional

    @property
    def daily_realised_pnl(self) -> Decimal:
        """Daily realised PnL in quote currency"""
        # Auto-reset on new day when accessed
        self._reset_if_new_day(time.time())
        return self._daily_realised_pnl_quote

    def get_deployable_balance(self, total_balance: Decimal, reserve_pct: float = 0.0) -> Decimal:
        """
        Return deployable balance after keeping *reserve_pct* % back as an
        opportunistic reserve.

        Parameters
        ----------
        total_balance : Decimal
            Full available balance in quote currency.
        reserve_pct : float
            Percentage to hold back (0.0 = no reserve, fully deployed).

        Returns
        -------
        Decimal
            Deployable balance (≥ 0).
        """
        if reserve_pct <= 0:
            return total_balance
        reserve = total_balance * Decimal(str(reserve_pct / 100.0))
        return max(DecimalZero, total_balance - reserve)

    def reset_daily_loss(self, reason: str = "manual") -> None:
        """
        Reset daily loss tracking. Used for:
        - External fill reconciliation (fills detected outside bot)
        - Manual reset after false positive loss detection

        Args:
            reason: Why the reset is being performed (for logging)
        """
        old_loss = self._daily_loss_quote
        self._daily_loss_quote = DecimalZero
        self._daily_realised_pnl_quote = DecimalZero
        self._consecutive_losses.clear()
        self._last_loss_time.clear()
        # Log for audit trail
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"🔄 DAILY_LOSS_RESET: reason={reason} | "
            f"old_loss={float(old_loss):.2f} | new_loss=0.00"
        )

    def adjust_daily_loss(self, adjustment_quote: Decimal, reason: str = "reconciliation") -> None:
        """
        Adjust daily loss by a specific amount. Used when reconciling
        external fills that were tracked incorrectly.

        Args:
            adjustment_quote: Amount to subtract from daily loss (positive = reduce loss)
            reason: Why adjustment is being made
        """
        old_loss = self._daily_loss_quote
        self._daily_loss_quote = max(DecimalZero, self._daily_loss_quote - adjustment_quote)
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            f"🔄 DAILY_LOSS_ADJUST: reason={reason} | "
            f"adjustment={float(adjustment_quote):+.2f} | "
            f"old_loss={float(old_loss):.2f} | new_loss={float(self._daily_loss_quote):.2f}"
        )
