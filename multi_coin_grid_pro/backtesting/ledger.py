"""Currency-safe FIFO P&L accounting for offline research.

The ledger deliberately has no connector or strategy dependency. Exchange fills
and manual fills use the same immutable input model, which makes reconciliation
and golden-value tests deterministic.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Deque, Dict, List, Optional, Set

ZERO = Decimal("0")


@dataclass(frozen=True)
class Fill:
    trade_id: str
    order_id: str
    timestamp: float
    side: str
    price: Decimal
    base_amount: Decimal
    fee_amount: Decimal = ZERO
    fee_asset: str = ""
    fee_quote_rate: Optional[Decimal] = None
    liquidity: str = "unknown"
    source: str = "bot"
    exit_reason: str = "unspecified"

    def __post_init__(self):
        side = self.side.upper()
        if side not in {"BUY", "SELL"}:
            raise ValueError(f"Unsupported fill side: {self.side}")
        if self.price <= ZERO or self.base_amount <= ZERO:
            raise ValueError("Fill price and base amount must be positive")
        if self.fee_amount < ZERO:
            raise ValueError("Fee amount must not be negative")
        object.__setattr__(self, "side", side)


@dataclass
class InventoryLot:
    remaining_base: Decimal
    remaining_cost_quote: Decimal
    remaining_entry_fee_quote: Decimal
    trade_id: str


@dataclass(frozen=True)
class RealizedMatch:
    trade_id: str
    timestamp: float
    base_amount: Decimal
    gross_pnl_quote: Decimal
    entry_fees_quote: Decimal
    exit_fees_quote: Decimal
    net_pnl_quote: Decimal
    exit_reason: str
    source: str


@dataclass(frozen=True)
class EquityPoint:
    timestamp: float
    equity_quote: Decimal


@dataclass(frozen=True)
class PnLReport:
    initial_cash_quote: Decimal
    cash_quote: Decimal
    inventory_base: Decimal
    mark_price: Decimal
    inventory_mark_value_quote: Decimal
    remaining_cost_basis_quote: Decimal
    realized_gross_pnl_quote: Decimal
    realized_fees_quote: Decimal
    realized_net_pnl_quote: Decimal
    unrealized_gross_pnl_quote: Decimal
    remaining_entry_fees_quote: Decimal
    estimated_exit_cost_quote: Decimal
    unrealized_net_pnl_quote: Decimal
    total_equity_quote: Decimal
    total_net_pnl_quote: Decimal
    projected_total_net_pnl_quote: Decimal
    total_return_pct: Decimal
    max_drawdown_pct: Decimal
    win_rate_pct: Optional[Decimal]
    profit_factor: Optional[Decimal]
    fee_impact_quote: Decimal
    fill_count: int
    duplicate_fill_count: int
    cancel_count: int
    open_position_count: int
    pnl_by_exit_reason: Dict[str, Decimal]
    data_quality_warnings: List[str] = field(default_factory=list)


class PortfolioLedger:
    """FIFO ledger with explicit base/quote fee conversion.

    FIFO is used because it is deterministic, handles partial sells naturally,
    and preserves the acquisition cost of every remaining grid lot. Actual
    entry fees are allocated pro rata when a lot is sold. Estimated future exit
    cost is reported separately and never deducted from cash or realized P&L.
    """

    def __init__(self, base_asset: str, quote_asset: str, initial_cash_quote: Decimal):
        if initial_cash_quote < ZERO:
            raise ValueError("Initial cash must not be negative")
        self.base_asset = base_asset.upper()
        self.quote_asset = quote_asset.upper()
        self.initial_cash_quote = initial_cash_quote
        self.cash_quote = initial_cash_quote
        self._lots: Deque[InventoryLot] = deque()
        self._seen_trade_ids: Set[str] = set()
        self.realized_matches: List[RealizedMatch] = []
        self.equity_curve: List[EquityPoint] = []
        self.data_quality_warnings: List[str] = []
        self.fill_count = 0
        self.duplicate_fill_count = 0
        self.cancel_count = 0

    @property
    def inventory_base(self) -> Decimal:
        return sum((lot.remaining_base for lot in self._lots), ZERO)

    @property
    def remaining_cost_basis_quote(self) -> Decimal:
        return sum((lot.remaining_cost_quote for lot in self._lots), ZERO)

    @property
    def remaining_entry_fees_quote(self) -> Decimal:
        return sum((lot.remaining_entry_fee_quote for lot in self._lots), ZERO)

    def record_cancel(self, order_id: str, reason: str = "cancelled") -> None:
        self.cancel_count += 1
        if not order_id:
            self.data_quality_warnings.append(f"Cancellation without order id: {reason}")

    def apply_fill(self, fill: Fill) -> bool:
        """Apply one fill; return False when a duplicate trade id is ignored."""
        if fill.trade_id in self._seen_trade_ids:
            self.duplicate_fill_count += 1
            return False

        if fill.side == "BUY":
            self._apply_buy(fill)
        else:
            self._apply_sell(fill)
        self._seen_trade_ids.add(fill.trade_id)
        self.fill_count += 1
        return True

    def _fee_in_quote(self, fill: Fill) -> Decimal:
        if fill.fee_amount == ZERO:
            return ZERO
        fee_asset = fill.fee_asset.upper()
        if fee_asset == self.quote_asset:
            return fill.fee_amount
        if fee_asset == self.base_asset:
            return fill.fee_amount * fill.price
        if fill.fee_quote_rate is None:
            raise ValueError(
                f"Fee conversion rate required for {fill.fee_asset} fee on trade {fill.trade_id}"
            )
        return fill.fee_amount * fill.fee_quote_rate

    def _apply_buy(self, fill: Fill) -> None:
        notional = fill.base_amount * fill.price
        fee_quote = self._fee_in_quote(fill)
        fee_asset = fill.fee_asset.upper()

        if fee_asset == self.base_asset:
            received_base = fill.base_amount - fill.fee_amount
            if received_base <= ZERO:
                raise ValueError("Base-denominated BUY fee consumes the complete fill")
            retained_cost = received_base * fill.price
            self.cash_quote -= notional
        else:
            received_base = fill.base_amount
            retained_cost = notional
            # A third-token fee is represented as its quote-equivalent equity cost.
            self.cash_quote -= notional + fee_quote

        self._lots.append(InventoryLot(
            remaining_base=received_base,
            remaining_cost_quote=retained_cost,
            remaining_entry_fee_quote=fee_quote,
            trade_id=fill.trade_id,
        ))

    def _apply_sell(self, fill: Fill) -> None:
        available = self.inventory_base
        matched_base = min(fill.base_amount, available)
        if matched_base <= ZERO:
            self.data_quality_warnings.append(
                f"SELL {fill.trade_id} has no tracked inventory and was not attributed to bot P&L"
            )
            return
        if fill.base_amount > available:
            self.data_quality_warnings.append(
                f"SELL {fill.trade_id} exceeds tracked inventory by {fill.base_amount - available}; "
                f"only the tracked amount was attributed"
            )

        fee_quote = self._fee_in_quote(fill) * matched_base / fill.base_amount
        proceeds = matched_base * fill.price
        matched_cost = ZERO
        matched_entry_fees = ZERO
        remaining_to_match = matched_base

        while remaining_to_match > ZERO:
            lot = self._lots[0]
            lot_before = lot.remaining_base
            take = min(remaining_to_match, lot_before)
            ratio = take / lot_before
            cost = lot.remaining_cost_quote * ratio
            entry_fee = lot.remaining_entry_fee_quote * ratio
            matched_cost += cost
            matched_entry_fees += entry_fee
            lot.remaining_base -= take
            lot.remaining_cost_quote -= cost
            lot.remaining_entry_fee_quote -= entry_fee
            remaining_to_match -= take
            if lot.remaining_base == ZERO:
                self._lots.popleft()

        if fill.fee_asset.upper() == self.quote_asset:
            self.cash_quote += proceeds - fee_quote
        elif fill.fee_asset.upper() == self.base_asset:
            # Kraken/Bitget spot normally report SELL fees in quote. Keep unusual base-fee
            # data visible and value it explicitly rather than silently changing units.
            self.cash_quote += proceeds - fee_quote
            self.data_quality_warnings.append(
                f"SELL {fill.trade_id} fee was paid in base; valued at fill price for P&L"
            )
        else:
            self.cash_quote += proceeds - fee_quote

        gross_pnl = proceeds - matched_cost
        net_pnl = gross_pnl - matched_entry_fees - fee_quote
        self.realized_matches.append(RealizedMatch(
            trade_id=fill.trade_id,
            timestamp=fill.timestamp,
            base_amount=matched_base,
            gross_pnl_quote=gross_pnl,
            entry_fees_quote=matched_entry_fees,
            exit_fees_quote=fee_quote,
            net_pnl_quote=net_pnl,
            exit_reason=fill.exit_reason,
            source=fill.source,
        ))

    def mark(self, timestamp: float, mark_price: Decimal) -> EquityPoint:
        if mark_price <= ZERO:
            raise ValueError("Mark price must be positive")
        point = EquityPoint(
            timestamp=timestamp,
            equity_quote=self.cash_quote + self.inventory_base * mark_price,
        )
        self.equity_curve.append(point)
        return point

    def report(
        self,
        mark_price: Decimal,
        estimated_exit_fee_rate: Decimal = ZERO,
        estimated_exit_slippage_rate: Decimal = ZERO,
    ) -> PnLReport:
        if mark_price <= ZERO:
            raise ValueError("Mark price must be positive")
        inventory_value = self.inventory_base * mark_price
        realized_gross = sum((match.gross_pnl_quote for match in self.realized_matches), ZERO)
        realized_fees = sum(
            (match.entry_fees_quote + match.exit_fees_quote for match in self.realized_matches), ZERO
        )
        realized_net = realized_gross - realized_fees
        unrealized_gross = inventory_value - self.remaining_cost_basis_quote
        exit_cost = inventory_value * (estimated_exit_fee_rate + estimated_exit_slippage_rate)
        unrealized_net = unrealized_gross - self.remaining_entry_fees_quote - exit_cost
        equity = self.cash_quote + inventory_value
        total_net = equity - self.initial_cash_quote
        projected_total_net = realized_net + unrealized_net
        return_pct = (
            total_net / self.initial_cash_quote * Decimal("100")
            if self.initial_cash_quote != ZERO else ZERO
        )

        positive = sum((m.net_pnl_quote for m in self.realized_matches if m.net_pnl_quote > ZERO), ZERO)
        negative = -sum((m.net_pnl_quote for m in self.realized_matches if m.net_pnl_quote < ZERO), ZERO)
        profit_factor = positive / negative if negative > ZERO else (None if positive == ZERO else Decimal("Infinity"))
        win_rate = None
        if self.realized_matches:
            wins = sum(1 for match in self.realized_matches if match.net_pnl_quote > ZERO)
            win_rate = Decimal(wins) / Decimal(len(self.realized_matches)) * Decimal("100")

        pnl_by_reason: Dict[str, Decimal] = defaultdict(lambda: ZERO)
        for match in self.realized_matches:
            pnl_by_reason[match.exit_reason] += match.net_pnl_quote

        return PnLReport(
            initial_cash_quote=self.initial_cash_quote,
            cash_quote=self.cash_quote,
            inventory_base=self.inventory_base,
            mark_price=mark_price,
            inventory_mark_value_quote=inventory_value,
            remaining_cost_basis_quote=self.remaining_cost_basis_quote,
            realized_gross_pnl_quote=realized_gross,
            realized_fees_quote=realized_fees,
            realized_net_pnl_quote=realized_net,
            unrealized_gross_pnl_quote=unrealized_gross,
            remaining_entry_fees_quote=self.remaining_entry_fees_quote,
            estimated_exit_cost_quote=exit_cost,
            unrealized_net_pnl_quote=unrealized_net,
            total_equity_quote=equity,
            total_net_pnl_quote=total_net,
            projected_total_net_pnl_quote=projected_total_net,
            total_return_pct=return_pct,
            max_drawdown_pct=self._max_drawdown_pct(),
            win_rate_pct=win_rate,
            profit_factor=profit_factor,
            fee_impact_quote=realized_fees + self.remaining_entry_fees_quote + exit_cost,
            fill_count=self.fill_count,
            duplicate_fill_count=self.duplicate_fill_count,
            cancel_count=self.cancel_count,
            open_position_count=1 if self.inventory_base > ZERO else 0,
            pnl_by_exit_reason=dict(pnl_by_reason),
            data_quality_warnings=list(self.data_quality_warnings),
        )

    def _max_drawdown_pct(self) -> Decimal:
        peak = ZERO
        max_drawdown = ZERO
        for point in self.equity_curve:
            if point.equity_quote > peak:
                peak = point.equity_quote
            if peak > ZERO:
                drawdown = (peak - point.equity_quote) / peak * Decimal("100")
                max_drawdown = max(max_drawdown, drawdown)
        return max_drawdown
