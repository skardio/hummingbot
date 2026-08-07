# momentum_entry_levels.py — Pure entry zone and stop/TP computations (US-204, US-205).
# No I/O, no exchange calls. All functions are deterministic given the same inputs.
from dataclasses import dataclass
from typing import Optional

from multi_coin_grid_pro.signals.momentum_config import EntryConfig


@dataclass
class EntryLevels:
    """Computed entry zone and trade management levels for a BUY_NOW signal."""
    entry_min: float           # bid × (1 − entry_below_bid_pct/100)
    entry_max: float           # ask × (1 + entry_above_ask_pct/100)
    max_chase_price: float     # entry_max × (1 + max_chase_above_entry_max_pct/100)
    invalidation_price: float  # entry_min × (1 − stop_below_entry_min_pct/100)
    take_profit_1: float       # entry_max × (1 + tp1_above_entry_max_pct/100)
    take_profit_2: float       # entry_max × (1 + tp2_above_entry_max_pct/100)


def compute_entry_levels(
    bid: float,
    ask: float,
    cfg: EntryConfig,
) -> Optional[EntryLevels]:
    """Compute entry zone + stop/TP from bid/ask and config.

    Returns None if bid or ask is zero or negative (invalid price data).
    """
    if bid <= 0 or ask <= 0:
        return None
    entry_min = bid * (1.0 - cfg.entry_below_bid_pct / 100.0)
    entry_max = ask * (1.0 + cfg.entry_above_ask_pct / 100.0)
    max_chase_price = entry_max * (1.0 + cfg.max_chase_above_entry_max_pct / 100.0)
    invalidation_price = entry_min * (1.0 - cfg.stop_below_entry_min_pct / 100.0)
    take_profit_1 = entry_max * (1.0 + cfg.tp1_above_entry_max_pct / 100.0)
    take_profit_2 = entry_max * (1.0 + cfg.tp2_above_entry_max_pct / 100.0)
    return EntryLevels(
        entry_min=entry_min,
        entry_max=entry_max,
        max_chase_price=max_chase_price,
        invalidation_price=invalidation_price,
        take_profit_1=take_profit_1,
        take_profit_2=take_profit_2,
    )
