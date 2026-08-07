"""
In-memory paper trading manager for the momentum sleeve.

Tracks virtual momentum positions based on MomentumCandidate signals.
Does NOT place real orders and does NOT touch grid executor state.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Exit reasons
_EXIT_STOP_LOSS = "STOP_LOSS"
_EXIT_TAKE_PROFIT = "TAKE_PROFIT"
_EXIT_TRAILING = "TRAILING_STOP"
_EXIT_MAX_HOLD = "MAX_HOLD"


@dataclass
class MomentumPosition:
    trading_pair: str
    entry_time: float
    entry_price: float
    quote_size: float
    base_size: float
    score_at_entry: float
    regime_at_entry: str
    vol_exp_at_entry: float
    stop_loss_price: float
    take_profit_price: float
    trailing_activation_price: float      # price at which trailing stop activates
    trailing_stop_price: Optional[float]  # None until activated
    trailing_distance_pct: float
    peak_price: float
    max_favorable_excursion_pct: float = 0.0
    max_adverse_excursion_pct: float = 0.0
    # Filled on close:
    exit_time: Optional[float] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    paper_pnl_quote: Optional[float] = None
    paper_pnl_pct: Optional[float] = None


class MomentumSleeveManager:
    """
    Paper trading manager for momentum sleeve.

    Config keys (all under momentum_sleeve: in YAML):
      max_positions: int          (default 1)
      max_quote_per_position: float (default 25)
      min_score: float            (default 75)
      stop_loss_pct: float        (default 0.012)
      take_profit_pct: float      (default 0.020)
      trailing_activation_pct: float (default 0.012)
      trailing_distance_pct: float   (default 0.008)
      max_hold_minutes: float     (default 90)
      cooldown_minutes: float     (default 60)
      summary_interval_minutes: float (default 60)
    """

    def __init__(self, config: dict):
        self.config = config
        self.max_positions: int = int(config.get("max_positions", 1))
        self.max_quote: float = float(config.get("max_quote_per_position", 25.0))
        self.min_score: float = float(config.get("min_score", 75.0))
        self.stop_loss_pct: float = float(config.get("stop_loss_pct", 0.012))
        self.take_profit_pct: float = float(config.get("take_profit_pct", 0.020))
        self.trailing_activation_pct: float = float(config.get("trailing_activation_pct", 0.012))
        self.trailing_distance_pct: float = float(config.get("trailing_distance_pct", 0.008))
        self.max_hold_seconds: float = float(config.get("max_hold_minutes", 90)) * 60
        self.cooldown_seconds: float = float(config.get("cooldown_minutes", 60)) * 60
        self.summary_interval: float = float(config.get("summary_interval_minutes", 60)) * 60

        self.open_positions: Dict[str, MomentumPosition] = {}  # pair -> position
        self.closed_positions: List[MomentumPosition] = []
        self._cooldowns: Dict[str, float] = {}   # pair -> cooldown_expiry_timestamp
        self._last_summary_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def maybe_enter(self, candidate, current_price: float, now: float) -> Optional[MomentumPosition]:
        """
        Attempt to open a paper position for the candidate.

        Returns the new MomentumPosition if entry was taken, else None.
        """
        pair = str(candidate.symbol)

        if not candidate.entry_allowed:
            return None
        if candidate.score < self.min_score:
            return None
        if len(self.open_positions) >= self.max_positions:
            return None
        if pair in self.open_positions:
            return None

        cooldown_expiry = self._cooldowns.get(pair, 0.0)
        if now < cooldown_expiry:
            remaining = int(cooldown_expiry - now)
            logger.debug(
                "momentum_paper_entry_blocked pair=%s reason=cooldown remaining_sec=%d",
                pair, remaining,
            )
            return None

        if current_price <= 0.0:
            logger.warning("momentum_paper_entry_skipped pair=%s reason=invalid_price", pair)
            return None

        stop_price = current_price * (1.0 - self.stop_loss_pct)
        tp_price = current_price * (1.0 + self.take_profit_pct)
        activation_price = current_price * (1.0 + self.trailing_activation_pct)
        base_size = self.max_quote / current_price

        pos = MomentumPosition(
            trading_pair=pair,
            entry_time=now,
            entry_price=current_price,
            quote_size=self.max_quote,
            base_size=base_size,
            score_at_entry=candidate.score,
            regime_at_entry=candidate.regime_at_score,
            vol_exp_at_entry=candidate.volume_expansion,
            stop_loss_price=stop_price,
            take_profit_price=tp_price,
            trailing_activation_price=activation_price,
            trailing_stop_price=None,
            trailing_distance_pct=self.trailing_distance_pct,
            peak_price=current_price,
        )
        self.open_positions[pair] = pos

        logger.info(
            "[MOMENTUM_PAPER_ENTRY] pair=%s score=%.1f entry=%.6f "
            "sl=%.6f tp=%.6f trail_act=%.6f size_quote=%.2f "
            "regime=%s vol_exp=%.2f",
            pair, candidate.score, current_price,
            stop_price, tp_price, activation_price, self.max_quote,
            candidate.regime_at_score, candidate.volume_expansion,
        )
        return pos

    def update_positions(self, price_by_pair: Dict[str, float], now: float) -> List[MomentumPosition]:
        """
        Update all open positions with latest prices.

        Returns list of positions that were closed this tick.
        """
        closed: List[MomentumPosition] = []
        for pair, pos in list(self.open_positions.items()):
            price = price_by_pair.get(pair)
            if price is None or price <= 0.0:
                logger.warning(
                    "momentum_paper_update_skipped pair=%s reason=no_price", pair
                )
                continue

            # Update excursions
            move_pct = (price - pos.entry_price) / pos.entry_price * 100.0
            if move_pct > pos.max_favorable_excursion_pct:
                pos.max_favorable_excursion_pct = move_pct
            elif move_pct < -pos.max_adverse_excursion_pct:
                pos.max_adverse_excursion_pct = abs(move_pct)

            # Update peak
            if price > pos.peak_price:
                pos.peak_price = price

            # Activate trailing stop if price reached activation level
            if pos.trailing_stop_price is None and price >= pos.trailing_activation_price:
                pos.trailing_stop_price = price * (1.0 - pos.trailing_distance_pct)
                logger.debug(
                    "momentum_paper_trailing_activated pair=%s price=%.6f trail=%.6f",
                    pair, price, pos.trailing_stop_price,
                )

            # Move trailing stop up if peak moved further
            if pos.trailing_stop_price is not None:
                new_trail = pos.peak_price * (1.0 - pos.trailing_distance_pct)
                if new_trail > pos.trailing_stop_price:
                    pos.trailing_stop_price = new_trail

            # Check exit
            exit_reason = self.maybe_exit(pos, price, now)
            if exit_reason is not None:
                self._close_position(pos, price, now, exit_reason)
                closed.append(pos)

        return closed

    def maybe_exit(self, position: MomentumPosition, current_price: float, now: float) -> Optional[str]:
        """
        Return exit reason if position should be closed, else None.
        """
        # Hard stop
        if current_price <= position.stop_loss_price:
            return _EXIT_STOP_LOSS

        # Take profit
        if current_price >= position.take_profit_price:
            return _EXIT_TAKE_PROFIT

        # Trailing stop (only if activated)
        if (
            position.trailing_stop_price is not None
            and current_price <= position.trailing_stop_price
        ):
            return _EXIT_TRAILING

        # Max hold
        if now - position.entry_time >= self.max_hold_seconds:
            return _EXIT_MAX_HOLD

        return None

    def get_summary(self) -> dict:
        """Return a snapshot dict of paper trading performance."""
        closed = self.closed_positions
        n_closed = len(closed)
        n_open = len(self.open_positions)
        if n_closed == 0:
            return {
                "open_positions": n_open,
                "total_trades": 0,
                "win_rate_pct": None,
                "total_paper_pnl_quote": 0.0,
                "avg_pnl_pct": None,
                "best_trade_pct": None,
                "worst_trade_pct": None,
            }

        wins = [p for p in closed if (p.paper_pnl_pct or 0.0) > 0]
        pnls_pct = [p.paper_pnl_pct or 0.0 for p in closed]
        total_pnl = sum(p.paper_pnl_quote or 0.0 for p in closed)
        return {
            "open_positions": n_open,
            "total_trades": n_closed,
            "win_rate_pct": round(len(wins) / n_closed * 100, 1),
            "total_paper_pnl_quote": round(total_pnl, 4),
            "avg_pnl_pct": round(sum(pnls_pct) / n_closed, 3),
            "best_trade_pct": round(max(pnls_pct), 3),
            "worst_trade_pct": round(min(pnls_pct), 3),
        }

    def log_summary_if_due(self, now: float) -> None:
        """Log a [MOMENTUM_PAPER_SUMMARY] line if the interval has elapsed."""
        if now - self._last_summary_time < self.summary_interval:
            return
        self._last_summary_time = now
        s = self.get_summary()
        open_pairs = list(self.open_positions.keys()) or ["—"]
        logger.info(
            "[MOMENTUM_PAPER_SUMMARY] "
            "open=%d(%s) trades=%d win_rate=%s%% "
            "total_pnl=%.4f avg_pnl=%s%% best=%s%% worst=%s%%",
            s["open_positions"],
            ",".join(open_pairs),
            s["total_trades"],
            s["win_rate_pct"] if s["win_rate_pct"] is not None else "n/a",
            s["total_paper_pnl_quote"],
            s["avg_pnl_pct"] if s["avg_pnl_pct"] is not None else "n/a",
            s["best_trade_pct"] if s["best_trade_pct"] is not None else "n/a",
            s["worst_trade_pct"] if s["worst_trade_pct"] is not None else "n/a",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _close_position(
        self,
        pos: MomentumPosition,
        exit_price: float,
        now: float,
        exit_reason: str,
    ) -> None:
        pnl_quote = (exit_price - pos.entry_price) * pos.base_size
        pnl_pct = (exit_price - pos.entry_price) / pos.entry_price * 100.0
        hold_sec = int(now - pos.entry_time)

        pos.exit_time = now
        pos.exit_price = exit_price
        pos.exit_reason = exit_reason
        pos.paper_pnl_quote = round(pnl_quote, 6)
        pos.paper_pnl_pct = round(pnl_pct, 4)

        del self.open_positions[pos.trading_pair]
        self.closed_positions.append(pos)

        # Set cooldown
        self._cooldowns[pos.trading_pair] = now + self.cooldown_seconds

        logger.info(
            "[MOMENTUM_PAPER_EXIT] pair=%s reason=%s "
            "entry=%.6f exit=%.6f pnl_quote=%.4f pnl_pct=%.3f%% "
            "hold=%ds mfe=%.2f%% mae=%.2f%%",
            pos.trading_pair, exit_reason,
            pos.entry_price, exit_price,
            pnl_quote, pnl_pct,
            hold_sec,
            pos.max_favorable_excursion_pct,
            pos.max_adverse_excursion_pct,
        )


def build_momentum_sleeve_manager(momentum_cfg: dict) -> Optional[MomentumSleeveManager]:
    """
    Factory: return a MomentumSleeveManager if mode == 'paper', else None.
    """
    if not isinstance(momentum_cfg, dict):
        return None
    mode = str(momentum_cfg.get("mode", "detect_only")).lower()
    if mode != "paper":
        return None
    return MomentumSleeveManager(momentum_cfg)
