"""
Backtesting Engine for Multi-Coin Grid Bot

Simulates bot decisions on historical data to calculate would-be P&L.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class BacktestTrade:
    """Represents a single trade in backtest"""
    timestamp: float
    symbol: str
    side: str  # "BUY" or "SELL"
    price: Decimal
    amount: Decimal
    fee: Decimal
    pnl: Decimal = Decimal("0")


@dataclass
class BacktestResult:
    """Results from a backtest run"""
    start_date: datetime
    end_date: datetime
    initial_capital: Decimal
    final_capital: Decimal
    total_pnl: Decimal
    total_pnl_pct: float
    num_trades: int
    win_rate: float
    max_drawdown: float
    sharpe_ratio: float
    trades: List[BacktestTrade] = field(default_factory=list)

    @property
    def roi(self) -> float:
        """Return on investment"""
        return float((self.final_capital - self.initial_capital) / self.initial_capital * 100)


class BacktestEngine:
    """
    Backtesting engine for multi-coin grid bot

    Simulates bot decisions on historical price data.
    """

    def __init__(
        self,
        initial_capital: Decimal,
        config: Dict,
        historical_data: Dict[str, List[Tuple[float, Decimal]]]  # {symbol: [(timestamp, price), ...]}
    ):
        """
        Initialize backtest engine

        Args:
            initial_capital: Starting capital
            config: Bot configuration dict
            historical_data: Historical price data per symbol
        """
        self.initial_capital = initial_capital
        self.config = config
        self.historical_data = historical_data

        self.current_capital = initial_capital
        self.positions: Dict[str, Decimal] = {}  # {symbol: amount}
        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[Tuple[float, Decimal]] = []

    def run(
        self,
        start_date: datetime,
        end_date: datetime,
        interval_minutes: int = 10
    ) -> BacktestResult:
        """
        Run backtest simulation

        Args:
            start_date: Start of backtest period
            end_date: End of backtest period
            interval_minutes: How often to check for decisions (minutes)

        Returns:
            BacktestResult with P&L and statistics
        """
        logger.info(f"Starting backtest: {start_date} to {end_date}")
        logger.info(f"Initial capital: €{self.initial_capital}")

        current_time = start_date
        last_decision_time = start_date

        while current_time <= end_date:
            # Check if it's time for a decision (every interval_minutes)
            if (current_time - last_decision_time).total_seconds() >= interval_minutes * 60:
                self._make_decision(current_time)
                last_decision_time = current_time

            # Update equity curve
            current_value = self._calculate_portfolio_value(current_time)
            self.equity_curve.append((current_time.timestamp(), current_value))

            # Move to next interval
            current_time += timedelta(minutes=1)

        # Calculate final results
        final_value = self._calculate_portfolio_value(end_date)
        return self._calculate_results(start_date, end_date, final_value)

    def _make_decision(self, timestamp: datetime) -> None:
        """
        Simulate bot decision at given timestamp

        This is a simplified version - in production, would use actual bot logic
        """
        # Get current prices for all symbols
        current_prices = {}
        for symbol, price_history in self.historical_data.items():
            price = self._get_price_at_time(symbol, timestamp)
            if price:
                current_prices[symbol] = price

        # Simplified decision logic:
        # 1. Find best trending coin (highest price increase)
        # 2. If no position, buy best coin
        # 3. If position exists, check if should switch

        if not self.positions:
            # No positions - buy best coin
            if current_prices:
                best_symbol = max(current_prices.keys(), key=lambda s: current_prices[s])
                self._execute_buy(best_symbol, current_prices[best_symbol], timestamp)
        else:
            # Has position - check if should switch
            # Simplified: switch if another coin is 2% better
            active_symbol = list(self.positions.keys())[0]
            active_price = current_prices.get(active_symbol)

            if active_price:
                for symbol, price in current_prices.items():
                    if symbol != active_symbol:
                        improvement = float((price - active_price) / active_price * 100)
                        if improvement > 2.0:  # 2% better
                            # Switch coins
                            self._execute_sell(active_symbol, active_price, timestamp)
                            self._execute_buy(symbol, price, timestamp)
                            break

    def _get_price_at_time(self, symbol: str, timestamp: datetime) -> Optional[Decimal]:
        """Get price for symbol at given timestamp"""
        if symbol not in self.historical_data:
            return None

        price_history = self.historical_data[symbol]
        target_ts = timestamp.timestamp()

        # Find closest price (before or at timestamp)
        closest_price = None
        for ts, price in price_history:
            if ts <= target_ts:
                closest_price = price
            else:
                break

        return closest_price

    def _execute_buy(self, symbol: str, price: Decimal, timestamp: datetime) -> None:
        """Execute buy order"""
        amount = self.current_capital / price
        fee = amount * Decimal(str(self.config.get("maker_fee_pct", 0.0016)))
        cost = amount * price + fee

        if cost <= self.current_capital:
            self.current_capital -= cost
            self.positions[symbol] = amount

            trade = BacktestTrade(
                timestamp=timestamp.timestamp(),
                symbol=symbol,
                side="BUY",
                price=price,
                amount=amount,
                fee=fee
            )
            self.trades.append(trade)
            logger.debug(f"BUY {symbol} @ €{price} for €{cost:.2f}")

    def _execute_sell(self, symbol: str, price: Decimal, timestamp: datetime) -> None:
        """Execute sell order"""
        if symbol not in self.positions:
            return

        amount = self.positions[symbol]
        revenue = amount * price
        fee = revenue * Decimal(str(self.config.get("maker_fee_pct", 0.0016)))
        net_revenue = revenue - fee

        self.current_capital += net_revenue
        del self.positions[symbol]

        trade = BacktestTrade(
            timestamp=timestamp.timestamp(),
            symbol=symbol,
            side="SELL",
            price=price,
            amount=amount,
            fee=fee
        )
        self.trades.append(trade)
        logger.debug(f"SELL {symbol} @ €{price} for €{net_revenue:.2f}")

    def _calculate_portfolio_value(self, timestamp: datetime) -> Decimal:
        """Calculate total portfolio value at given timestamp"""
        value = self.current_capital

        for symbol, amount in self.positions.items():
            price = self._get_price_at_time(symbol, timestamp)
            if price:
                value += amount * price

        return value

    def _calculate_results(
        self,
        start_date: datetime,
        end_date: datetime,
        final_value: Decimal
    ) -> BacktestResult:
        """Calculate backtest results and statistics"""
        total_pnl = final_value - self.initial_capital
        total_pnl_pct = float(total_pnl / self.initial_capital * 100)

        # Calculate win rate
        winning_trades = sum(1 for t in self.trades if t.pnl > 0)
        win_rate = (winning_trades / len(self.trades) * 100) if self.trades else 0

        # Calculate max drawdown
        max_drawdown = self._calculate_max_drawdown()

        # Calculate Sharpe ratio (simplified)
        sharpe_ratio = self._calculate_sharpe_ratio()

        return BacktestResult(
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_capital=final_value,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            num_trades=len(self.trades),
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            trades=self.trades
        )

    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown from equity curve"""
        if not self.equity_curve:
            return 0.0

        peak = float(self.equity_curve[0][1])
        max_dd = 0.0

        for _, value in self.equity_curve:
            val = float(value)
            if val > peak:
                peak = val
            dd = (peak - val) / peak * 100
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _calculate_sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio (simplified)"""
        if len(self.equity_curve) < 2:
            return 0.0

        # Calculate returns
        returns = []
        for i in range(1, len(self.equity_curve)):
            prev_val = float(self.equity_curve[i - 1][1])
            curr_val = float(self.equity_curve[i][1])
            ret = (curr_val - prev_val) / prev_val if prev_val > 0 else 0
            returns.append(ret)

        if not returns:
            return 0.0

        # Simple Sharpe: mean return / std dev
        import statistics
        mean_return = statistics.mean(returns)
        std_return = statistics.stdev(returns) if len(returns) > 1 else 0

        if std_return == 0:
            return 0.0

        # Annualized Sharpe (assuming daily returns)
        sharpe = (mean_return / std_return) * (252 ** 0.5)  # 252 trading days
        return sharpe
