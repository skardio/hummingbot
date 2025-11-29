"""
Paper Trading Mode

Simulates bot execution without placing real orders.
Logs everything as-if live for comparison.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PaperTrade:
    """Represents a simulated trade"""
    timestamp: datetime
    symbol: str
    side: str  # "BUY" or "SELL"
    order_type: str
    price: Decimal
    amount: Decimal
    fee: Decimal
    filled: bool = False
    fill_time: Optional[datetime] = None


@dataclass
class PaperPosition:
    """Represents a simulated position"""
    symbol: str
    entry_price: Decimal
    amount: Decimal
    current_price: Decimal
    unrealized_pnl: Decimal
    unrealized_pnl_pct: float


class PaperTradingMode:
    """
    Paper trading mode - simulates trades without real money

    Tracks:
    - Simulated orders
    - Simulated positions
    - P&L (realized and unrealized)
    - All logs as-if live
    """

    def __init__(self, initial_capital: Decimal, config: Dict):
        """
        Initialize paper trading mode

        Args:
            initial_capital: Starting capital
            config: Bot configuration
        """
        self.initial_capital = initial_capital
        self.config = config
        self.current_capital = initial_capital

        # Track positions and orders
        self.positions: Dict[str, PaperPosition] = {}
        self.open_orders: List[PaperTrade] = []
        self.closed_trades: List[PaperTrade] = []

        # Statistics
        self.total_realized_pnl = Decimal("0")
        self.total_fees_paid = Decimal("0")

        logger.info(f"📝 Paper Trading Mode initialized with €{initial_capital}")

    def simulate_buy_order(
        self,
        symbol: str,
        price: Decimal,
        amount: Decimal,
        order_type: str = "LIMIT"
    ) -> PaperTrade:
        """
        Simulate a buy order

        Args:
            symbol: Trading pair
            price: Order price
            amount: Order amount (in base asset)
            order_type: Order type (LIMIT/MARKET)

        Returns:
            PaperTrade object
        """
        cost = amount * price
        fee = cost * Decimal(str(self.config.get("maker_fee_pct", 0.0016)))
        total_cost = cost + fee

        # Check if we have enough capital
        if total_cost > self.current_capital:
            logger.warning(f"⚠️  Insufficient capital for buy: need €{total_cost:.2f}, have €{self.current_capital:.2f}")
            return None

        trade = PaperTrade(
            timestamp=datetime.now(),
            symbol=symbol,
            side="BUY",
            order_type=order_type,
            price=price,
            amount=amount,
            fee=fee
        )

        # For LIMIT orders, add to open orders (simulate fill later)
        # For MARKET orders, fill immediately
        if order_type == "MARKET":
            self._fill_order(trade)
        else:
            self.open_orders.append(trade)
            logger.info(f"📝 Paper BUY order placed: {amount} {symbol} @ €{price} (LIMIT)")

        return trade

    def simulate_sell_order(
        self,
        symbol: str,
        price: Decimal,
        amount: Decimal,
        order_type: str = "LIMIT"
    ) -> PaperTrade:
        """
        Simulate a sell order

        Args:
            symbol: Trading pair
            price: Order price
            amount: Order amount (in base asset)
            order_type: Order type (LIMIT/MARKET)

        Returns:
            PaperTrade object
        """
        # Check if we have the position
        if symbol not in self.positions or self.positions[symbol].amount < amount:
            logger.warning(f"⚠️  Insufficient position for sell: need {amount} {symbol}")
            return None

        revenue = amount * price
        fee = revenue * Decimal(str(self.config.get("maker_fee_pct", 0.0016)))

        trade = PaperTrade(
            timestamp=datetime.now(),
            symbol=symbol,
            side="SELL",
            order_type=order_type,
            price=price,
            amount=amount,
            fee=fee
        )

        # For LIMIT orders, add to open orders
        # For MARKET orders, fill immediately
        if order_type == "MARKET":
            self._fill_order(trade)
        else:
            self.open_orders.append(trade)
            logger.info(f"📝 Paper SELL order placed: {amount} {symbol} @ €{price} (LIMIT)")

        return trade

    def _fill_order(self, trade: PaperTrade) -> None:
        """Fill a simulated order"""
        trade.filled = True
        trade.fill_time = datetime.now()

        if trade.side == "BUY":
            cost = trade.amount * trade.price
            self.current_capital -= (cost + trade.fee)

            # Update or create position
            if trade.symbol in self.positions:
                # Average entry price
                pos = self.positions[trade.symbol]
                total_cost = (pos.entry_price * pos.amount) + cost
                total_amount = pos.amount + trade.amount
                pos.entry_price = total_cost / total_amount
                pos.amount = total_amount
            else:
                self.positions[trade.symbol] = PaperPosition(
                    symbol=trade.symbol,
                    entry_price=trade.price,
                    amount=trade.amount,
                    current_price=trade.price,
                    unrealized_pnl=Decimal("0"),
                    unrealized_pnl_pct=0.0
                )

            logger.info(
                f"✅ Paper BUY filled: {trade.amount} {trade.symbol} @ €{trade.price} "
                f"(fee: €{trade.fee:.4f}, capital: €{self.current_capital:.2f})"
            )

        else:  # SELL
            if trade.symbol in self.positions:
                pos = self.positions[trade.symbol]
                revenue = trade.amount * trade.price
                self.current_capital += (revenue - trade.fee)

                # Calculate realized P&L
                cost_basis = pos.entry_price * trade.amount
                realized_pnl = revenue - cost_basis - trade.fee
                self.total_realized_pnl += realized_pnl

                # Update position
                pos.amount -= trade.amount
                if pos.amount <= 0:
                    del self.positions[trade.symbol]

                logger.info(
                    f"✅ Paper SELL filled: {trade.amount} {trade.symbol} @ €{trade.price} "
                    f"(P&L: €{realized_pnl:.2f}, capital: €{self.current_capital:.2f})"
                )

        self.total_fees_paid += trade.fee
        self.closed_trades.append(trade)

        # Remove from open orders if present
        if trade in self.open_orders:
            self.open_orders.remove(trade)

    def update_prices(self, prices: Dict[str, Decimal]) -> None:
        """
        Update current prices for positions (for unrealized P&L)

        Args:
            prices: Dict of {symbol: current_price}
        """
        for symbol, position in self.positions.items():
            if symbol in prices:
                position.current_price = prices[symbol]
                current_value = position.amount * position.current_price
                cost_basis = position.amount * position.entry_price
                position.unrealized_pnl = current_value - cost_basis
                position.unrealized_pnl_pct = float(
                    (position.current_price - position.entry_price) / position.entry_price * 100
                )

    def check_limit_orders(self, current_prices: Dict[str, Decimal]) -> None:
        """
        Check if any limit orders should be filled

        Args:
            current_prices: Current market prices
        """
        filled_orders = []

        for order in self.open_orders:
            if order.symbol not in current_prices:
                continue

            current_price = current_prices[order.symbol]

            # Check if limit order should fill
            if order.side == "BUY" and current_price <= order.price:
                filled_orders.append(order)
            elif order.side == "SELL" and current_price >= order.price:
                filled_orders.append(order)

        for order in filled_orders:
            order.price = current_prices[order.symbol]  # Fill at current price
            self._fill_order(order)

    def get_portfolio_value(self, current_prices: Dict[str, Decimal]) -> Decimal:
        """
        Calculate total portfolio value

        Args:
            current_prices: Current market prices

        Returns:
            Total portfolio value
        """
        value = self.current_capital

        for symbol, position in self.positions.items():
            if symbol in current_prices:
                value += position.amount * current_prices[symbol]
            else:
                value += position.amount * position.current_price

        return value

    def get_statistics(self, current_prices: Dict[str, Decimal]) -> Dict:
        """
        Get paper trading statistics

        Args:
            current_prices: Current market prices

        Returns:
            Dict with statistics
        """
        portfolio_value = self.get_portfolio_value(current_prices)
        total_unrealized_pnl = sum(
            pos.unrealized_pnl for pos in self.positions.values()
        )

        total_pnl = self.total_realized_pnl + total_unrealized_pnl
        total_pnl_pct = float(total_pnl / self.initial_capital * 100)

        return {
            "initial_capital": float(self.initial_capital),
            "current_capital": float(self.current_capital),
            "portfolio_value": float(portfolio_value),
            "realized_pnl": float(self.total_realized_pnl),
            "unrealized_pnl": float(total_unrealized_pnl),
            "total_pnl": float(total_pnl),
            "total_pnl_pct": total_pnl_pct,
            "total_fees": float(self.total_fees_paid),
            "num_trades": len(self.closed_trades),
            "open_positions": len(self.positions),
            "open_orders": len(self.open_orders),
        }
