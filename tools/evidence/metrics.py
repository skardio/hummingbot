"""Metric computation over classified executors.

Strictly separated into the three mandated views:

* **A - ALL-IN**     every closed executor, unfiltered
* **B - STRATEGY**   the three ``MATCHED_*`` classes
* **C - OPERATIONAL** everything else

``pnl(A) == pnl(B) + pnl(C)`` holds by construction because the views partition
the same record set.

Only metrics proven measurable in ``docs/EVIDENCE_SCHEMA.md`` are produced here.
All functions are pure.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .classify import HEURISTIC_CLASSES, PHANTOM_PROFIT_CLASSES, VIEW_B_CLASSES, VIEW_C_CLASSES, Classification

ZERO = Decimal(0)


def safe_div(numerator: Decimal, denominator: Decimal) -> Optional[Decimal]:
    """Divide, returning None instead of raising when the denominator is zero."""
    if denominator == 0:
        return None
    return numerator / denominator


@dataclass(frozen=True)
class ExecutorRecord:
    """One closed executor, already classified and fingerprinted."""

    executor_id: str
    close_timestamp: int
    trading_pair: str
    close_type: Optional[int]
    net_pnl_quote: Decimal
    cum_fees_quote: Decimal
    filled_amount_quote: Decimal
    realized_buy_size_quote: Decimal
    realized_sell_size_quote: Decimal
    position_size_quote: Decimal
    classification: Classification
    fingerprint: str

    @property
    def cls(self) -> str:
        return self.classification.cls

    @property
    def deployed_capital(self) -> Decimal:
        """Capital actually put at risk. Never ``filled_amount_quote``."""
        return self.realized_buy_size_quote + self.position_size_quote

    @property
    def is_winner(self) -> bool:
        """Profit only counts when it did not originate in another executor."""
        if self.cls in PHANTOM_PROFIT_CLASSES:
            return False
        return self.net_pnl_quote > 0

    @property
    def day(self) -> str:
        return datetime.fromtimestamp(self.close_timestamp, tz=timezone.utc).strftime("%Y-%m-%d")


@dataclass(frozen=True)
class ViewMetrics:
    """Metrics for one view. Monetary values are Decimal."""

    view: str
    n: int
    net_pnl: Decimal
    fees: Decimal
    gross_pnl: Decimal
    deployed_capital: Decimal
    expectancy_per_trade: Optional[Decimal]
    return_on_deployed: Optional[Decimal]
    win_rate: Optional[Decimal]
    n_winners: int
    n_losers: int
    avg_win: Optional[Decimal]
    avg_loss: Optional[Decimal]
    payoff_ratio: Optional[Decimal]
    profit_factor: Optional[Decimal]
    worst_trade: Optional[Decimal]
    best_trade: Optional[Decimal]
    max_consecutive_losses: int
    pnl_sequence_drawdown: Decimal
    trading_days: int
    distinct_pairs: int


@dataclass(frozen=True)
class MetricsBundle:
    """Everything the gate engine needs. Contains no decisions."""

    views: Mapping[str, ViewMetrics]
    class_distribution: Mapping[str, int]
    class_pnl: Mapping[str, Decimal]
    close_type_distribution: Mapping[int, int]
    pair_pnl_share: Mapping[str, Decimal]
    max_pair_pnl_share: Optional[Decimal]
    max_single_trade_pnl_share: Optional[Decimal]
    operational_share_of_total: Optional[Decimal]
    unmatched_buy_rate: Optional[Decimal]
    heuristic_share_of_b: Optional[Decimal]
    daily_pnl_matched: Mapping[str, List[Decimal]]
    totals: Mapping[str, Decimal]
    warnings: Tuple[str, ...] = field(default_factory=tuple)


def _max_consecutive_losses(records: Sequence[ExecutorRecord]) -> int:
    current = best = 0
    for record in sorted(records, key=lambda r: r.close_timestamp):
        if record.net_pnl_quote < 0:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _pnl_sequence_drawdown(records: Sequence[ExecutorRecord]) -> Decimal:
    """Drawdown of the cumulative realised PnL sequence.

    This is explicitly NOT an equity drawdown: concurrent and unrealised
    positions are absent from the data.
    """
    peak = cumulative = ZERO
    drawdown = ZERO
    for record in sorted(records, key=lambda r: r.close_timestamp):
        cumulative += record.net_pnl_quote
        peak = max(peak, cumulative)
        drawdown = min(drawdown, cumulative - peak)
    return drawdown


def compute_view(view: str, records: Sequence[ExecutorRecord]) -> ViewMetrics:
    """Compute all measurable metrics for a single view."""
    n = len(records)
    net_pnl = sum((r.net_pnl_quote for r in records), ZERO)
    fees = sum((r.cum_fees_quote for r in records), ZERO)
    deployed = sum((r.deployed_capital for r in records), ZERO)

    winners = [r for r in records if r.is_winner]
    losers = [r for r in records if not r.is_winner and r.net_pnl_quote <= 0]

    win_sum = sum((r.net_pnl_quote for r in winners), ZERO)
    loss_sum = sum((r.net_pnl_quote for r in losers), ZERO)

    avg_win = safe_div(win_sum, Decimal(len(winners)))
    avg_loss = safe_div(loss_sum, Decimal(len(losers)))
    payoff = safe_div(avg_win, abs(avg_loss)) if avg_win is not None and avg_loss not in (None, ZERO) else None

    return ViewMetrics(
        view=view,
        n=n,
        net_pnl=net_pnl,
        fees=fees,
        gross_pnl=net_pnl + fees,
        deployed_capital=deployed,
        expectancy_per_trade=safe_div(net_pnl, Decimal(n)),
        return_on_deployed=safe_div(net_pnl, deployed),
        win_rate=safe_div(Decimal(len(winners)), Decimal(n)),
        n_winners=len(winners),
        n_losers=len(losers),
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=payoff,
        profit_factor=safe_div(win_sum, abs(loss_sum)) if loss_sum != 0 else None,
        worst_trade=min((r.net_pnl_quote for r in records), default=None),
        best_trade=max((r.net_pnl_quote for r in records), default=None),
        max_consecutive_losses=_max_consecutive_losses(records),
        pnl_sequence_drawdown=_pnl_sequence_drawdown(records),
        trading_days=len({r.day for r in records}),
        distinct_pairs=len({r.trading_pair for r in records}),
    )


def compute_metrics(records: Sequence[ExecutorRecord]) -> MetricsBundle:
    """Partition into views A/B/C and compute every measurable metric."""
    view_a = list(records)
    view_b = [r for r in records if r.cls in VIEW_B_CLASSES]
    view_c = [r for r in records if r.cls in VIEW_C_CLASSES]

    metrics_a = compute_view("A", view_a)
    metrics_b = compute_view("B", view_b)
    metrics_c = compute_view("C", view_c)

    class_distribution = Counter(r.cls for r in records)
    class_pnl: Dict[str, Decimal] = defaultdict(lambda: ZERO)
    for record in records:
        class_pnl[record.cls] += record.net_pnl_quote

    close_types = Counter(r.close_type for r in records if r.close_type is not None)

    # Concentration is measured on view B only. The verdict rests on view B, so
    # mixing view-C losses in here would let an operational problem (gate G5)
    # mask itself as a sample problem (gate G3) and break gate orthogonality.
    pair_pnl: Dict[str, Decimal] = defaultdict(lambda: ZERO)
    for record in view_b:
        pair_pnl[record.trading_pair] += record.net_pnl_quote

    total_abs_b = sum((abs(r.net_pnl_quote) for r in view_b), ZERO)
    pair_share = {
        pair: (abs(value) / total_abs_b if total_abs_b else ZERO) for pair, value in pair_pnl.items()
    }
    max_pair_share = max(pair_share.values(), default=None)
    max_trade_share = (
        max((abs(r.net_pnl_quote) / total_abs_b for r in view_b), default=None) if total_abs_b else None
    )

    abs_a = abs(metrics_a.net_pnl)
    operational_share = (abs(metrics_c.net_pnl) / abs_a) if abs_a > 0 else None

    n_unmatched_buy = class_distribution.get("UNMATCHED_BUY", 0)
    unmatched_buy_rate = safe_div(Decimal(n_unmatched_buy), Decimal(len(records))) if records else None

    n_heuristic = sum(class_distribution.get(cls, 0) for cls in HEURISTIC_CLASSES if cls in VIEW_B_CLASSES)
    heuristic_share = safe_div(Decimal(n_heuristic), Decimal(len(view_b))) if view_b else None

    daily: Dict[str, List[Decimal]] = defaultdict(list)
    for record in view_b:
        daily[record.day].append(record.net_pnl_quote)

    totals = {
        "net_pnl": metrics_a.net_pnl,
        "fees": metrics_a.fees,
        "buy_quote": sum((r.realized_buy_size_quote for r in records), ZERO),
        "sell_quote": sum((r.realized_sell_size_quote for r in records), ZERO),
        "deployed_capital": metrics_a.deployed_capital,
    }

    return MetricsBundle(
        views={"A": metrics_a, "B": metrics_b, "C": metrics_c},
        class_distribution=dict(class_distribution),
        class_pnl=dict(class_pnl),
        close_type_distribution=dict(close_types),
        pair_pnl_share=pair_share,
        max_pair_pnl_share=max_pair_share,
        max_single_trade_pnl_share=max_trade_share,
        operational_share_of_total=operational_share,
        unmatched_buy_rate=unmatched_buy_rate,
        heuristic_share_of_b=heuristic_share,
        daily_pnl_matched=dict(daily),
        totals=totals,
    )
