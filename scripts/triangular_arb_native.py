import logging
import math
import os
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from pydantic import Field

from hummingbot.client.config.config_data_types import BaseClientModel
from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.connector.utils import split_hb_trading_pair
from hummingbot.core.data_type.common import TradeType
from hummingbot.core.data_type.order_candidate import OrderCandidate
from hummingbot.core.event.events import (
    BuyOrderCompletedEvent,
    BuyOrderCreatedEvent,
    MarketOrderFailureEvent,
    SellOrderCompletedEvent,
    SellOrderCreatedEvent,
)
from hummingbot.strategy.script_strategy_base import OrderType, ScriptStrategyBase


def parse_triples(triples_csv: str) -> List[Tuple[str, str, str]]:
    """Parse semicolon-separated triples, each with three comma-separated pairs."""
    triples: List[Tuple[str, str, str]] = []
    for raw_triple in triples_csv.split(";"):
        cleaned = raw_triple.strip()
        if not cleaned:
            continue
        pairs = [p.strip().upper() for p in cleaned.split(",") if p.strip()]
        if len(pairs) != 3:
            continue
        triples.append((pairs[0], pairs[1], pairs[2]))
    return triples


def reorder_triple_for_holding(
    triple: Tuple[str, str, str],
    holding_asset: str,
) -> Optional[Tuple[Tuple[str, str, str], Tuple[str, str, str]]]:
    """
    Returns (direct_route, reverse_route) with direct route starting from holding asset when possible.
    """
    p1, p2, p3 = triple
    if holding_asset not in p1:
        ordered = (p2, p1, p3)
    elif holding_asset not in p2:
        ordered = (p1, p2, p3)
    else:
        ordered = (p1, p3, p2)

    return ordered, ordered[::-1]


def infer_order_sides(route: Tuple[str, str, str], holding_asset: str) -> Tuple[int, int, int]:
    """Return order sides for route where 1=buy and 0=sell."""
    base_1, _ = split_hb_trading_pair(route[0])
    base_2, _ = split_hb_trading_pair(route[1])
    base_3, _ = split_hb_trading_pair(route[2])

    order_side_1 = 0 if base_1 == holding_asset else 1
    order_side_2 = 0 if base_1 == base_2 else 1
    order_side_3 = 1 if base_3 == holding_asset else 0

    return order_side_1, order_side_2, order_side_3


class TriangularArbNativeConfig(BaseClientModel):
    script_file_name: str = os.path.basename(__file__)
    connector_name: str = Field(
        "bitget",
        json_schema_extra={
            "prompt": lambda mi: "Exchange connector name (bitget first, kraken later)",
            "prompt_on_new": True,
        },
    )
    triples_csv: str = Field(
        "ETH-USDT,ETH-BTC,BTC-USDT;SOL-USDT,SOL-BTC,BTC-USDT",
        json_schema_extra={
            "prompt": lambda mi: "Triangular routes as A-B,B-C,A-C;...",
            "prompt_on_new": True,
        },
    )
    holding_asset: str = Field(
        "USDT",
        json_schema_extra={
            "prompt": lambda mi: "Holding/start asset (USDT for Bitget)",
            "prompt_on_new": True,
        },
    )
    order_amount_in_holding_asset: Decimal = Field(
        Decimal("20"),
        json_schema_extra={
            "prompt": lambda mi: "Order amount per arbitrage cycle in holding asset",
            "prompt_on_new": True,
        },
    )
    min_profitability_pct: Decimal = Field(
        Decimal("0.20"),
        json_schema_extra={
            "prompt": lambda mi: "Minimum profitability percent to start arbitrage",
            "prompt_on_new": True,
        },
    )
    taker_fee_pct: Decimal = Field(
        Decimal("0.10"),
        json_schema_extra={
            "prompt": lambda mi: "Estimated taker fee percent per leg",
            "prompt_on_new": True,
        },
    )
    poll_interval: int = Field(
        5,
        json_schema_extra={
            "prompt": lambda mi: "Polling interval in seconds",
            "prompt_on_new": True,
        },
    )
    execute_trades: bool = Field(
        False,
        json_schema_extra={
            "prompt": lambda mi: "Enable real order placement? (False recommended first)",
            "prompt_on_new": True,
        },
    )
    max_trades_per_day: int = Field(
        50,
        json_schema_extra={
            "prompt": lambda mi: "Maximum arbitrage cycles per day",
            "prompt_on_new": True,
        },
    )


class TriangularArbNative(ScriptStrategyBase):
    """
    Native Hummingbot triangular arbitrage script.

    Bitget-first, config-driven, and structured for future Kraken use by only changing connector and routes.
    """

    @classmethod
    def init_markets(cls, config: TriangularArbNativeConfig):
        triples = parse_triples(config.triples_csv)
        pairs = {p for triple in triples for p in triple}
        cls.markets = {config.connector_name: pairs}

    def __init__(self, connectors: Dict[str, ConnectorBase], config: TriangularArbNativeConfig):
        super().__init__(connectors)
        self.config = config
        self.connector = self.connectors[self.config.connector_name]
        self.logger().setLevel(logging.INFO)

        self.status = "NOT_INIT"
        self.last_scan_ts = 0
        self.trades_today = 0

        self.order_candidate: Optional[OrderCandidate] = None
        self.place_order_trials_count = 0
        self.place_order_trials_limit = 5
        self.place_order_failure = False

        self.active_route: Optional[Tuple[str, str, str]] = None
        self.active_sides: Optional[Tuple[int, int, int]] = None
        self.active_amounts: Optional[List[Decimal]] = None
        self.active_leg_idx: int = 0
        self.initial_spent_amount = Decimal("0")

        self.total_profit = Decimal("0")
        self.total_profit_pct = Decimal("0")

        self.triples = parse_triples(self.config.triples_csv)
        self.required_pairs = {pair for triple in self.triples for pair in triple}
        self._last_warmup_log_ts = 0

    def on_tick(self):
        if self.status == "NOT_INIT":
            self.init_strategy()

        if self.arbitrage_started():
            return

        if self.current_timestamp - self.last_scan_ts < self.config.poll_interval:
            return
        self.last_scan_ts = self.current_timestamp

        if not self.all_required_order_books_ready():
            if self.current_timestamp - self._last_warmup_log_ts >= 15:
                self.log_with_clock(
                    logging.INFO,
                    "Waiting for all required order books to initialize before scanning.",
                )
                self._last_warmup_log_ts = self.current_timestamp
            return

        if not self.ready_for_new_orders():
            return

        best = self.find_best_opportunity()
        if best is None:
            return

        triple, route, sides, amounts, profit_pct, alt_route, alt_profit_pct = best
        self.log_with_clock(
            logging.INFO,
            f"Best triangle {triple} best_route={route} best_profit={profit_pct:.4f}% "
            f"alt_route={alt_route} alt_profit={alt_profit_pct:.4f}%",
        )

        if profit_pct < self.config.min_profitability_pct:
            return

        if not self.config.execute_trades:
            self.log_with_clock(
                logging.INFO,
                f"DRY-RUN candidate above threshold {self.config.min_profitability_pct}%: {route} profit={profit_pct:.4f}%",
            )
            return

        self.active_route = route
        self.active_sides = sides
        self.active_amounts = amounts
        self.active_leg_idx = 0
        self.start_arbitrage(route, sides, amounts)

    def init_strategy(self):
        if len(self.triples) == 0:
            self.status = "NOT_ACTIVE"
            self.log_with_clock(logging.WARNING, "No valid triangular routes configured.")
            return
        self.status = "ACTIVE"
        self.log_with_clock(
            logging.INFO,
            f"TriangularArbNative initialized for connector={self.config.connector_name} routes={len(self.triples)}",
        )

    def ready_for_new_orders(self) -> bool:
        if self.status == "NOT_ACTIVE":
            return False

        if self.trades_today >= self.config.max_trades_per_day:
            self.log_with_clock(logging.INFO, "Daily trade limit reached, stopping new cycles.")
            return False

        balance = self.connector.get_available_balance(self.config.holding_asset)
        if balance < self.config.order_amount_in_holding_asset:
            self.log_with_clock(
                logging.INFO,
                f"{self.config.connector_name} {self.config.holding_asset} balance too low ({balance})",
            )
            return False
        return True

    def find_best_opportunity(self):
        best = None
        for triple in self.triples:
            reordered = reorder_triple_for_holding(triple, self.config.holding_asset)
            if reordered is None:
                continue
            direct_route, reverse_route = reordered

            direct_sides = infer_order_sides(direct_route, self.config.holding_asset)
            reverse_sides = tuple(1 - s for s in direct_sides[::-1])

            try:
                direct_profit, direct_amounts = self.calculate_profit(direct_route, direct_sides)
                reverse_profit, reverse_amounts = self.calculate_profit(reverse_route, reverse_sides)
            except ValueError:
                # An order book can disappear briefly during startup or reconnect; skip this route for now.
                continue

            candidate = (triple, direct_route, direct_sides, direct_amounts, direct_profit, reverse_route, reverse_profit)
            if reverse_profit > direct_profit:
                candidate = (triple, reverse_route, reverse_sides, reverse_amounts, reverse_profit, direct_route, direct_profit)

            if best is None or candidate[4] > best[4]:
                best = candidate

        return best

    def all_required_order_books_ready(self) -> bool:
        for pair in self.required_pairs:
            try:
                self.connector.get_order_book(pair)
            except ValueError:
                return False
        return True

    def calculate_profit(self, route: Tuple[str, str, str], sides: Tuple[int, int, int]):
        exchanged_amount = self.config.order_amount_in_holding_asset
        order_amounts = [Decimal("0"), Decimal("0"), Decimal("0")]

        for i in range(3):
            order_amounts[i] = self.get_order_amount_from_exchanged_amount(route[i], sides[i], exchanged_amount)
            if order_amounts[i] <= 0:
                return Decimal("-100"), order_amounts

            if sides[i] == 1:
                exchanged_amount = order_amounts[i]
            else:
                quote_result = self.connector.get_quote_volume_for_base_amount(route[i], False, order_amounts[i])
                exchanged_amount = Decimal(str(quote_result.result_volume))

            exchanged_amount *= (Decimal("1") - self.config.taker_fee_pct / Decimal("100"))

        start_amount = self.config.order_amount_in_holding_asset
        if start_amount <= 0:
            return Decimal("-100"), order_amounts

        profit_pct = (exchanged_amount / start_amount - Decimal("1")) * Decimal("100")
        return profit_pct, order_amounts

    def get_order_amount_from_exchanged_amount(self, pair: str, side: int, exchanged_amount: Decimal) -> Decimal:
        if side == 1:
            orderbook = self.connector.get_order_book(pair)
            return self.get_base_amount_for_quote_volume(orderbook.ask_entries(), exchanged_amount)
        return exchanged_amount

    def get_base_amount_for_quote_volume(self, orderbook_entries, quote_volume: Decimal) -> Decimal:
        cumulative_volume = Decimal("0")
        cumulative_base_amount = Decimal("0")

        for row in orderbook_entries:
            row_amount = Decimal(str(row.amount))
            row_price = Decimal(str(row.price))
            row_volume = row_amount * row_price
            if row_volume + cumulative_volume >= quote_volume:
                row_volume = quote_volume - cumulative_volume
                row_amount = row_volume / row_price
            cumulative_volume += row_volume
            cumulative_base_amount += row_amount
            if cumulative_volume >= quote_volume:
                break

        return cumulative_base_amount

    def start_arbitrage(self, route, sides, amounts):
        self.log_with_clock(logging.INFO, f"Starting arbitrage route={route} sides={sides}")
        first_candidate = self.create_order_candidate(route[0], sides[0], amounts[0])
        if first_candidate and self.process_candidate(first_candidate, False):
            self.status = "ARBITRAGE_STARTED"

    def create_order_candidate(self, pair: str, side: int, amount: Decimal):
        trade_side = TradeType.BUY if side == 1 else TradeType.SELL
        price = self.connector.get_price_for_volume(pair, trade_side, amount).result_price
        price_quantized = self.connector.quantize_order_price(pair, Decimal(str(price)))
        amount_quantized = self.connector.quantize_order_amount(pair, amount)

        if amount_quantized <= Decimal("0"):
            self.log_with_clock(logging.INFO, f"Order amount too low for {pair}")
            return None

        return OrderCandidate(
            trading_pair=pair,
            is_maker=False,
            order_type=OrderType.MARKET,
            order_side=trade_side,
            amount=amount_quantized,
            price=price_quantized,
        )

    def process_candidate(self, order_candidate: OrderCandidate, multiple_trials_enabled: bool) -> bool:
        adjusted = self.connector.budget_checker.adjust_candidate(order_candidate, all_or_none=True)
        if math.isclose(float(adjusted.amount), 0.0, rel_tol=1e-6):
            self.log_with_clock(logging.INFO, f"Adjusted amount too low for {order_candidate.trading_pair}")
            if multiple_trials_enabled:
                self.place_order_trials_count += 1
                self.place_order_failure = True
            return False

        is_buy = order_candidate.order_side == TradeType.BUY
        self.place_order(
            connector_name=self.config.connector_name,
            trading_pair=order_candidate.trading_pair,
            is_buy=is_buy,
            amount=adjusted.amount,
            order_type=order_candidate.order_type,
            price=adjusted.price,
        )
        return True

    def place_order(
        self,
        connector_name: str,
        trading_pair: str,
        is_buy: bool,
        amount: Decimal,
        order_type: OrderType,
        price=Decimal("NaN"),
    ):
        if is_buy:
            self.buy(connector_name, trading_pair, amount, order_type, price)
        else:
            self.sell(connector_name, trading_pair, amount, order_type, price)

    def arbitrage_started(self) -> bool:
        if self.status != "ARBITRAGE_STARTED":
            return False

        if self.order_candidate and self.place_order_failure:
            if self.place_order_trials_count <= self.place_order_trials_limit:
                self.log_with_clock(logging.INFO, "Retrying failed order placement.")
                self.process_candidate(self.order_candidate, True)
            else:
                self.log_with_clock(logging.WARNING, "Too many order placement retries. Pausing strategy.")
                self.status = "NOT_ACTIVE"
        return True

    def did_create_buy_order(self, event: BuyOrderCreatedEvent):
        self.log_with_clock(logging.INFO, f"Buy order created on {event.trading_pair}")
        self._reset_order_candidate_if_matching(event.trading_pair)

    def did_create_sell_order(self, event: SellOrderCreatedEvent):
        self.log_with_clock(logging.INFO, f"Sell order created on {event.trading_pair}")
        self._reset_order_candidate_if_matching(event.trading_pair)

    def _reset_order_candidate_if_matching(self, trading_pair: str):
        if self.order_candidate and self.order_candidate.trading_pair == trading_pair:
            self.order_candidate = None
            self.place_order_trials_count = 0
            self.place_order_failure = False

    def did_fail_order(self, event: MarketOrderFailureEvent):
        if self.order_candidate:
            self.place_order_failure = True

    def did_complete_buy_order(self, event: BuyOrderCompletedEvent):
        self.log_with_clock(
            logging.INFO,
            f"Buy completed: {event.base_asset_amount} {event.base_asset} for {event.quote_asset_amount} {event.quote_asset}",
        )
        self.process_next_leg(event)

    def did_complete_sell_order(self, event: SellOrderCompletedEvent):
        self.log_with_clock(
            logging.INFO,
            f"Sell completed: {event.base_asset_amount} {event.base_asset} for {event.quote_asset_amount} {event.quote_asset}",
        )
        self.process_next_leg(event)

    def process_next_leg(self, order_event):
        if self.active_route is None or self.active_sides is None:
            self.status = "ACTIVE"
            return

        event_pair = f"{order_event.base_asset}-{order_event.quote_asset}"
        if event_pair not in self.active_route:
            return

        leg_idx = self.active_route.index(event_pair)
        side = self.active_sides[leg_idx]

        if side == 1:
            exchanged_amount = Decimal(str(order_event.base_asset_amount))
            spent_amount = Decimal(str(order_event.quote_asset_amount))
        else:
            exchanged_amount = Decimal(str(order_event.quote_asset_amount))
            spent_amount = Decimal(str(order_event.base_asset_amount))

        if leg_idx == 0:
            self.initial_spent_amount = spent_amount

        if leg_idx < 2:
            next_pair = self.active_route[leg_idx + 1]
            next_side = self.active_sides[leg_idx + 1]
            next_amount = self.get_order_amount_from_exchanged_amount(next_pair, next_side, exchanged_amount)
            self.order_candidate = self.create_order_candidate(next_pair, next_side, next_amount)
            if self.order_candidate:
                self.process_candidate(self.order_candidate, True)
            return

        self.finalize_arbitrage(exchanged_amount)

    def finalize_arbitrage(self, final_amount: Decimal):
        if self.initial_spent_amount <= 0:
            self.status = "ACTIVE"
            return

        order_profit = final_amount - self.initial_spent_amount
        order_profit_pct = (order_profit / self.initial_spent_amount) * Decimal("100")

        self.total_profit += order_profit
        self.total_profit_pct = (self.total_profit / self.config.order_amount_in_holding_asset) * Decimal("100")
        self.trades_today += 1

        self.log_with_clock(
            logging.INFO,
            f"Arbitrage completed profit={order_profit:.6f} {self.config.holding_asset} ({order_profit_pct:.4f}%) "
            f"total_profit={self.total_profit:.6f}",
        )

        self.active_route = None
        self.active_sides = None
        self.active_amounts = None
        self.active_leg_idx = 0
        self.initial_spent_amount = Decimal("0")
        self.status = "ACTIVE"

    def format_status(self) -> str:
        if not self.ready_to_trade:
            return "Market connectors are not ready."

        lines: List[str] = []
        warning_lines: List[str] = []

        lines.extend(["", "  Strategy status:", f"    {self.status}"])
        lines.extend(["", "  Connector:", f"    {self.config.connector_name}"])
        lines.extend(["", "  Routes monitored:", f"    {len(self.triples)}"])
        lines.extend(["", "  Trades today:", f"    {self.trades_today}/{self.config.max_trades_per_day}"])
        lines.extend(
            [
                "",
                "  Profit:",
                f"    {self.total_profit:.6f} {self.config.holding_asset} ({self.total_profit_pct:.4f}%)",
            ]
        )

        try:
            df = self.active_orders_df()
            lines.extend(["", "  Active Orders:"] + ["    " + line for line in df.to_string(index=False).split("\n")])
        except ValueError:
            lines.extend(["", "  No active orders."])

        balance = self.connector.get_available_balance(self.config.holding_asset)
        if balance < self.config.order_amount_in_holding_asset:
            warning_lines.append(
                f"{self.config.connector_name} {self.config.holding_asset} balance too low to open new cycles."
            )

        if warning_lines:
            lines.extend(["", "*** WARNINGS ***"] + warning_lines)

        return "\n".join(lines)
