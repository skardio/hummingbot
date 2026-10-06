"""Accounting classification of closed executors.

Layers 1-3 are exact. Layer 4 is an explicit heuristic, needed only because the
exchange ``min_order_size`` is not persisted per executor. Every classification
result records which layer produced it and whether that layer is exact.

Rows are reclassified, never discarded: ``pnl(A) == pnl(B) + pnl(C)`` must hold.

All functions in this module are pure.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional, Sequence

BUY = "BUY"
SELL = "SELL"

# --- classes ---------------------------------------------------------------
NO_FILL = "NO_FILL"
HELD_ONLY = "HELD_ONLY"
UNMATCHED_BUY = "UNMATCHED_BUY"
UNMATCHED_SELL = "UNMATCHED_SELL"
OVERSOLD = "OVERSOLD"
MATCHED_EXACT = "MATCHED_EXACT"
MATCHED_DUST_CONFIRMED = "MATCHED_DUST_CONFIRMED"
MATCHED_DUST_HEURISTIC = "MATCHED_DUST_HEURISTIC"
PARTIAL_OPEN = "PARTIAL_OPEN"

ALL_CLASSES = (
    NO_FILL,
    HELD_ONLY,
    UNMATCHED_BUY,
    UNMATCHED_SELL,
    OVERSOLD,
    MATCHED_EXACT,
    MATCHED_DUST_CONFIRMED,
    MATCHED_DUST_HEURISTIC,
    PARTIAL_OPEN,
)

#: View B - the strategy view.
VIEW_B_CLASSES = (MATCHED_EXACT, MATCHED_DUST_CONFIRMED, MATCHED_DUST_HEURISTIC)

#: View C - operational cost. Everything that is not view B.
VIEW_C_CLASSES = tuple(cls for cls in ALL_CLASSES if cls not in VIEW_B_CLASSES)

#: Classes whose profit originates from a purchase booked in another executor.
#: They must never be counted as winners in any win rate.
PHANTOM_PROFIT_CLASSES = (UNMATCHED_SELL, OVERSOLD)

#: Only layer 4 is heuristic.
HEURISTIC_CLASSES = (MATCHED_DUST_HEURISTIC, PARTIAL_OPEN)


def to_decimal(value: Any, default: Decimal = Decimal(0)) -> Decimal:
    """Parse a value to Decimal via str, returning ``default`` when impossible."""
    if value is None:
        return default
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default
    return parsed if parsed.is_finite() else default


@dataclass(frozen=True)
class ExecutorFacts:
    """Accounting facts derived from one executor's ``custom_info``."""

    buy_base: Decimal
    sell_base: Decimal
    buy_quote: Decimal
    sell_quote: Decimal
    buy_fees_quote: Decimal
    sell_fees_quote: Decimal
    stored_realized_buy_quote: Optional[Decimal]
    n_regular_orders: int
    n_held_orders: int

    @property
    def residual_base(self) -> Decimal:
        return self.buy_base - self.sell_base

    @property
    def avg_entry(self) -> Decimal:
        if self.buy_base <= 0:
            return Decimal(0)
        return self.buy_quote / self.buy_base

    @property
    def residual_value_quote(self) -> Decimal:
        return abs(self.residual_base) * self.avg_entry

    @property
    def residual_rel(self) -> Decimal:
        if self.buy_base <= 0:
            return Decimal(0)
        return abs(self.residual_base) / self.buy_base


@dataclass(frozen=True)
class Classification:
    """Outcome of classifying one executor."""

    cls: str
    layer: int
    exact: bool
    residual_base: Decimal
    residual_value_quote: Decimal
    residual_rel: Decimal
    dust_signature: bool

    @property
    def in_view_b(self) -> bool:
        return self.cls in VIEW_B_CLASSES


def _held_order_ids(held_orders: Sequence[Any]) -> set:
    ids = set()
    for entry in held_orders or []:
        if isinstance(entry, Mapping):
            value = entry.get("client_order_id")
            if value is not None:
                ids.add(str(value))
        elif entry is not None:
            ids.add(str(entry))
    return ids


def _sum_orders(orders: Iterable[Mapping[str, Any]], field: str, side: str) -> Decimal:
    total = Decimal(0)
    for order in orders:
        if str(order.get("trade_type")) == side:
            total += to_decimal(order.get(field))
    return total


def extract_facts(custom_info: Mapping[str, Any]) -> ExecutorFacts:
    """Derive accounting facts from an executor's ``custom_info`` mapping.

    Held position orders are excluded, mirroring the executor's own
    ``update_realized_pnl_metrics`` which operates on ``regular_filled_orders``.
    """
    filled = custom_info.get("filled_orders") or []
    held = custom_info.get("held_position_orders") or []
    held_ids = _held_order_ids(held)

    regular = [
        order
        for order in filled
        if isinstance(order, Mapping) and str(order.get("client_order_id")) not in held_ids
    ]

    stored_raw = custom_info.get("realized_buy_size_quote")
    stored = to_decimal(stored_raw) if stored_raw is not None else None

    return ExecutorFacts(
        buy_base=_sum_orders(regular, "executed_amount_base", BUY),
        sell_base=_sum_orders(regular, "executed_amount_base", SELL),
        buy_quote=_sum_orders(regular, "executed_amount_quote", BUY),
        sell_quote=_sum_orders(regular, "executed_amount_quote", SELL),
        buy_fees_quote=_sum_orders(regular, "cumulative_fee_paid_quote", BUY),
        sell_fees_quote=_sum_orders(regular, "cumulative_fee_paid_quote", SELL),
        stored_realized_buy_quote=stored,
        n_regular_orders=len(regular),
        n_held_orders=len(held_ids),
    )


def has_dust_signature(facts: ExecutorFacts, signature_epsilon: Decimal) -> bool:
    """True when the executor applied its own residual-dust correction.

    The correction subtracts ``residual_base * avg_entry`` from
    ``realized_buy_size_quote``. It only fires when the residual is below the
    exchange ``min_order_size``, so its presence is authoritative proof that the
    residual was unsellable.
    """
    if facts.stored_realized_buy_quote is None:
        return False
    if facts.buy_quote <= 0:
        return False
    return (facts.buy_quote - facts.stored_realized_buy_quote) > signature_epsilon


def classify(
    facts: ExecutorFacts,
    dust_abs_quote: Decimal,
    dust_rel_pct: Decimal,
    zero_residual_epsilon_base: Decimal,
    dust_signature_epsilon_quote: Decimal,
) -> Classification:
    """Assign an executor to exactly one class.

    Thresholds are supplied by the caller from the policy; none are defined here.
    """
    residual = facts.residual_base
    signature = has_dust_signature(facts, dust_signature_epsilon_quote)

    def result(cls: str, layer: int, exact: bool) -> Classification:
        return Classification(
            cls=cls,
            layer=layer,
            exact=exact,
            residual_base=residual,
            residual_value_quote=facts.residual_value_quote,
            residual_rel=facts.residual_rel,
            dust_signature=signature,
        )

    # --- layer 1: structural, exact ---
    if facts.n_regular_orders == 0:
        return result(HELD_ONLY if facts.n_held_orders > 0 else NO_FILL, 1, True)
    if facts.buy_base > 0 and facts.sell_base == 0:
        return result(UNMATCHED_BUY, 1, True)
    if facts.sell_base > 0 and facts.buy_base == 0:
        return result(UNMATCHED_SELL, 1, True)
    if facts.buy_base == 0 and facts.sell_base == 0:
        return result(NO_FILL, 1, True)
    if residual < -zero_residual_epsilon_base:
        return result(OVERSOLD, 1, True)

    # --- layer 2: exact ---
    if abs(residual) <= zero_residual_epsilon_base:
        return result(MATCHED_EXACT, 2, True)

    # --- layer 3: exact, on the executor's own authority ---
    if signature:
        return result(MATCHED_DUST_CONFIRMED, 3, True)

    # --- layer 4: heuristic ---
    if facts.residual_value_quote < dust_abs_quote and facts.residual_rel < dust_rel_pct:
        return result(MATCHED_DUST_HEURISTIC, 4, False)
    return result(PARTIAL_OPEN, 4, False)
