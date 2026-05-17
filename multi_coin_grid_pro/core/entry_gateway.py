"""
Entry Gateway Facade — single entry point for all pre-trade checks.

Wraps GlobalRiskManager calls into a single ``can_enter()`` call,
applying checks in a deterministic order.

Order of checks:
  1. Cycle lock (consecutive failures today)
  2. Daily kill switch (coin >= -2R today)
  3. Risk manager (exposure, cooldowns, daily loss)
  4. Quality floor (optional minimum quality score)

Part of the 17-upgrade trading bot roadmap:
  Item 1 — Entry Gateway Facade
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class EntryDecision:
    """Result of an entry-gateway evaluation."""

    allowed: bool
    approved_notional: Optional[Decimal]
    blocked_by: str    # "none" | "cycle_lock" | "kill_switch" | "risk_manager" | "quality"
    reason: str
    quality_score: int  # 0-100; 0 if scorer was not invoked


class EntryGateway:
    """
    Single authoritative entry point for all pre-trade admission checks.

    Parameters
    ----------
    risk_manager : GlobalRiskManager
        The shared risk-manager instance for this bot session.
    min_quality_score : int
        Minimum quality score required to allow entry (0 = no floor).
    """

    def __init__(self, risk_manager, min_quality_score: int = 0):
        self.risk_manager = risk_manager
        self.min_quality_score = min_quality_score

    def can_enter(
        self,
        *,
        symbol: str,
        requested_notional: Decimal,
        now: float,
        quality_score: int = 100,
        logger=None,
    ) -> EntryDecision:
        """
        Evaluate whether a new position may be opened.

        Parameters
        ----------
        symbol : str
            Trading pair (e.g. "BTC-EUR").
        requested_notional : Decimal
            Desired position size in quote currency.
        now : float
            Current timestamp (unix seconds).  Must be injected — never use
            ``time.time()`` in callers.
        quality_score : int
            Pre-computed quality score (0-100).  Defaults to 100 when no
            scorer is active.
        logger : optional
            Logger passed to the risk manager for structured log output.

        Returns
        -------
        EntryDecision
        """
        _log = logger or log

        # 1. Consecutive failure lock
        cycle_state_getter = getattr(self.risk_manager, "get_coin_cycle_state", None)
        if cycle_state_getter is not None:
            cycle_state = cycle_state_getter(symbol)
            cycle_state_value = getattr(cycle_state, "value", cycle_state)
            if cycle_state_value == "TWO_FAILED_CYCLES":
                n = self.risk_manager.get_failed_cycles(symbol)
                reason = f"state=TWO_FAILED_CYCLES ({n} consecutive losses today)"
                _log.info(f"🔒 ENTRY_BLOCKED {symbol} [cycle_lock]: {reason}")
                return EntryDecision(False, None, "cycle_lock", reason, quality_score)

        if self.risk_manager.is_coin_cycle_locked(symbol):
            n = self.risk_manager.get_failed_cycles(symbol)
            reason = f"{n} consecutive losses today"
            _log.info(f"🔒 ENTRY_BLOCKED {symbol} [cycle_lock]: {reason}")
            return EntryDecision(False, None, "cycle_lock", reason, quality_score)

        # 2. Daily coin kill switch
        if self.risk_manager.is_coin_disabled_today(symbol):
            reason = "coin >= -2R today"
            _log.info(f"🚫 ENTRY_BLOCKED {symbol} [kill_switch]: {reason}")
            return EntryDecision(False, None, "kill_switch", reason, quality_score)

        # 3. Risk manager (exposure, cooldowns, daily portfolio loss)
        approved = self.risk_manager.can_open_trade(
            symbol=symbol,
            requested_notional=requested_notional,
            now=now,
            logger=logger,
        )
        if approved is None:
            reason = "blocked by risk limits"
            return EntryDecision(False, None, "risk_manager", reason, quality_score)

        # 4. Quality floor
        if quality_score < self.min_quality_score:
            reason = f"score {quality_score} < min {self.min_quality_score}"
            _log.info(f"📉 ENTRY_BLOCKED {symbol} [quality]: {reason}")
            return EntryDecision(False, None, "quality", reason, quality_score)

        _log.info(
            f"✅ ENTRY_ALLOWED {symbol}: notional={approved} quality={quality_score}"
        )
        return EntryDecision(True, approved, "none", "ok", quality_score)
