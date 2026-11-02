"""Conservative candle replay for precomputed grid order intents.

This is accuracy level A. A candle crossing a limit is only a conservative
proxy for execution; it is not evidence of queue priority or a maker fill.
Level B requires recorded trades/order books and is intentionally not faked.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from multi_coin_grid_pro.backtesting.ledger import ZERO, EquityPoint, Fill, PnLReport, PortfolioLedger


@dataclass(frozen=True)
class Candle:
    timestamp: float
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume_base: Optional[Decimal] = None


@dataclass(frozen=True)
class OrderIntent:
    order_id: str
    placed_timestamp: float
    side: str
    price: Decimal
    base_amount: Decimal
    order_type: str = "LIMIT_MAKER"
    exit_reason: str = "grid"


@dataclass(frozen=True)
class ReplayAssumptions:
    maker_fee_rate: Decimal
    taker_fee_rate: Decimal
    spread_rate: Decimal = ZERO
    market_slippage_rate: Decimal = ZERO
    max_fill_fraction_per_candle: Decimal = Decimal("1")
    candle_volume_participation: Decimal = Decimal("0.01")
    min_notional: Decimal = ZERO
    tick_size: Decimal = ZERO
    strict_limit_penetration: bool = True

    def __post_init__(self):
        rates = (
            self.maker_fee_rate,
            self.taker_fee_rate,
            self.spread_rate,
            self.market_slippage_rate,
            self.max_fill_fraction_per_candle,
            self.candle_volume_participation,
        )
        if any(rate < ZERO for rate in rates):
            raise ValueError("Replay rates must not be negative")
        if self.max_fill_fraction_per_candle > Decimal("1"):
            raise ValueError("max_fill_fraction_per_candle must be <= 1")


@dataclass
class _WorkingOrder:
    intent: OrderIntent
    remaining_base: Decimal
    eligible_candles: int = 0


@dataclass(frozen=True)
class ReplayResult:
    report: PnLReport
    equity_curve: List[EquityPoint]
    filled_order_ids: List[str]
    open_order_ids: List[str]
    cancelled_order_ids: List[str]
    assumptions: ReplayAssumptions
    accuracy_level: str = "A_CONSERVATIVE_CANDLE"
    limitations: List[str] = field(default_factory=list)


class CandleReplay:
    def __init__(
        self,
        base_asset: str,
        quote_asset: str,
        initial_cash_quote: Decimal,
        assumptions: ReplayAssumptions,
    ):
        self.ledger = PortfolioLedger(base_asset, quote_asset, initial_cash_quote)
        self.assumptions = assumptions

    def run(self, candles: Iterable[Candle], order_intents: Iterable[OrderIntent]) -> ReplayResult:
        candle_list = sorted(candles, key=lambda candle: candle.timestamp)
        if not candle_list:
            raise ValueError("At least one candle is required")
        intents = sorted(order_intents, key=lambda order: order.placed_timestamp)
        pending: Dict[str, _WorkingOrder] = {}
        filled_order_ids: List[str] = []
        cancelled_order_ids: List[str] = []
        intent_index = 0

        for candle in candle_list:
            while intent_index < len(intents) and intents[intent_index].placed_timestamp < candle.timestamp:
                intent = intents[intent_index]
                self._validate_intent(intent)
                if intent.order_id in pending:
                    raise ValueError(f"Duplicate order intent id: {intent.order_id}")
                pending[intent.order_id] = _WorkingOrder(intent, intent.base_amount)
                intent_index += 1

            for order_id, working in list(pending.items()):
                working.eligible_candles += 1
                intent = working.intent
                if working.eligible_candles == 1 and self._is_marketable_post_only(intent, candle):
                    self.ledger.record_cancel(order_id, "post_only_would_cross")
                    cancelled_order_ids.append(order_id)
                    del pending[order_id]
                    continue

                fill_amount = self._fill_amount(working, candle)
                if fill_amount <= ZERO:
                    continue
                price, liquidity = self._fill_price_and_liquidity(intent, candle)
                fee_rate = (
                    self.assumptions.maker_fee_rate
                    if liquidity == "maker" else self.assumptions.taker_fee_rate
                )
                self.ledger.apply_fill(Fill(
                    trade_id=f"{order_id}:{working.eligible_candles}:{working.remaining_base}",
                    order_id=order_id,
                    timestamp=candle.timestamp,
                    side=intent.side,
                    price=price,
                    base_amount=fill_amount,
                    fee_amount=fill_amount * price * fee_rate,
                    fee_asset=self.ledger.quote_asset,
                    liquidity=liquidity,
                    exit_reason=intent.exit_reason,
                ))
                working.remaining_base -= fill_amount
                if working.remaining_base == ZERO:
                    filled_order_ids.append(order_id)
                    del pending[order_id]

            # Final-tick fills are included before the final equity snapshot.
            self.ledger.mark(candle.timestamp, candle.close)

        report = self.ledger.report(
            mark_price=candle_list[-1].close,
            estimated_exit_fee_rate=self.assumptions.taker_fee_rate,
            estimated_exit_slippage_rate=self.assumptions.market_slippage_rate,
        )
        return ReplayResult(
            report=report,
            equity_curve=list(self.ledger.equity_curve),
            filled_order_ids=filled_order_ids,
            open_order_ids=list(pending),
            cancelled_order_ids=cancelled_order_ids,
            assumptions=self.assumptions,
            limitations=[
                "Candle high/low penetration is not proof of a maker fill or queue priority.",
                "Latency and order-book depth are assumptions unless supplied by a level-B replay.",
                "Signals/order intents must be produced without future candle information.",
            ],
        )

    def _validate_intent(self, intent: OrderIntent) -> None:
        if intent.side.upper() not in {"BUY", "SELL"}:
            raise ValueError(f"Unsupported side: {intent.side}")
        if intent.price <= ZERO or intent.base_amount <= ZERO:
            raise ValueError("Order price and amount must be positive")
        if intent.price * intent.base_amount < self.assumptions.min_notional:
            raise ValueError(f"Order {intent.order_id} is below min_notional")
        tick = self.assumptions.tick_size
        if tick > ZERO and intent.price % tick != ZERO:
            raise ValueError(f"Order {intent.order_id} is not aligned to tick_size")

    def _is_marketable_post_only(self, intent: OrderIntent, candle: Candle) -> bool:
        if intent.order_type.upper() != "LIMIT_MAKER":
            return False
        half_spread = candle.open * self.assumptions.spread_rate / Decimal("2")
        bid = candle.open - half_spread
        ask = candle.open + half_spread
        return (
            intent.side.upper() == "BUY" and intent.price >= ask
        ) or (
            intent.side.upper() == "SELL" and intent.price <= bid
        )

    def _fill_amount(self, working: _WorkingOrder, candle: Candle) -> Decimal:
        intent = working.intent
        if intent.order_type.upper() == "MARKET":
            touched = True
        elif intent.side.upper() == "BUY":
            touched = candle.low < intent.price if self.assumptions.strict_limit_penetration else candle.low <= intent.price
        else:
            touched = candle.high > intent.price if self.assumptions.strict_limit_penetration else candle.high >= intent.price
        if not touched:
            return ZERO

        amount = working.remaining_base * self.assumptions.max_fill_fraction_per_candle
        if candle.volume_base is not None:
            amount = min(amount, candle.volume_base * self.assumptions.candle_volume_participation)
        return min(amount, working.remaining_base)

    def _fill_price_and_liquidity(self, intent: OrderIntent, candle: Candle):
        if intent.order_type.upper() != "MARKET":
            return intent.price, "maker"
        slippage = self.assumptions.market_slippage_rate
        if intent.side.upper() == "BUY":
            return candle.open * (Decimal("1") + slippage), "taker"
        return candle.open * (Decimal("1") - slippage), "taker"


def split_research_validation(
    candles: Iterable[Candle], validation_start_timestamp: float
) -> Tuple[List[Candle], List[Candle]]:
    """Create a chronological, non-overlapping research/validation split."""
    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    research = [candle for candle in ordered if candle.timestamp < validation_start_timestamp]
    validation = [candle for candle in ordered if candle.timestamp >= validation_start_timestamp]
    if not research or not validation:
        raise ValueError("Research and validation periods must both contain candles")
    return research, validation


def compare_scenarios(
    candles: Iterable[Candle],
    scenario_orders: Dict[str, Iterable[OrderIntent]],
    base_asset: str,
    quote_asset: str,
    initial_cash_quote: Decimal,
    assumptions: ReplayAssumptions,
) -> Dict[str, ReplayResult]:
    """Replay scenarios on one immutable market dataset and cost model."""
    shared_candles = list(candles)
    return {
        name: CandleReplay(
            base_asset=base_asset,
            quote_asset=quote_asset,
            initial_cash_quote=initial_cash_quote,
            assumptions=assumptions,
        ).run(shared_candles, orders)
        for name, orders in scenario_orders.items()
    }
