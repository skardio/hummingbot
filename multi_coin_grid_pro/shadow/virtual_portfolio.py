"""Virtual, in-memory capital/exposure tracker for one A/B variant.

Deliberately independent from ``multi_coin_grid_pro.utils.budget_allocator``
and ``multi_coin_grid_pro.core.risk_buckets`` — those classes carry live
state references and are not imported here. Variant A and variant B each get
their own fresh ``VirtualPortfolio`` instance; nothing is shared between them
except the read-only market-data snapshot they both observe in the same
tick, which is what makes the comparison fair.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from multi_coin_grid_pro.shadow.virtual_grid_position import VirtualGridPosition


@dataclass
class VirtualPortfolio:
    """One variant's (A or B) isolated virtual capital and open/closed positions."""

    variant_label: str
    capital_quote: Decimal
    max_slots: int
    open_positions: Dict[str, VirtualGridPosition] = field(default_factory=dict)  # symbol -> position
    closed_positions: List[VirtualGridPosition] = field(default_factory=list)
    reserved_quote: Decimal = Decimal("0")

    def available_slots(self) -> int:
        return max(0, self.max_slots - len(self.open_positions))

    def available_capital(self) -> Decimal:
        return max(Decimal("0"), self.capital_quote - self.reserved_quote)

    def can_open(self, symbol: str, notional_quote: Decimal) -> bool:
        if symbol in self.open_positions:
            return False
        if self.available_slots() <= 0:
            return False
        return notional_quote <= self.available_capital()

    def open_position(self, position: VirtualGridPosition) -> None:
        self.open_positions[position.symbol] = position
        self.reserved_quote += position.notional_quote

    def close_position(self, symbol: str) -> Optional[VirtualGridPosition]:
        position = self.open_positions.pop(symbol, None)
        if position is None:
            return None
        self.reserved_quote = max(Decimal("0"), self.reserved_quote - position.notional_quote)
        self.closed_positions.append(position)
        return position

    def realized_pnl_total(self) -> Decimal:
        return sum((p.net_pnl_quote or Decimal("0")) for p in self.closed_positions) or Decimal("0")

    def unrealized_pnl_total(self) -> Decimal:
        return sum((p.unrealized_pnl_quote or Decimal("0")) for p in self.open_positions.values()) or Decimal("0")

    def max_drawdown_quote(self) -> Decimal:
        """Simple peak-to-trough drawdown over the realised-PnL equity curve."""
        equity = Decimal("0")
        peak = Decimal("0")
        max_dd = Decimal("0")
        for position in self.closed_positions:
            equity += position.net_pnl_quote or Decimal("0")
            peak = max(peak, equity)
            max_dd = min(max_dd, equity - peak)
        return max_dd
