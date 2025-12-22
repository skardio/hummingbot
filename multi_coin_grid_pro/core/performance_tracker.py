"""
Performance Tracker v1.0

Real-time tracking van trading performance metrics:
- Win rate (rolling window)
- Profit factor (gross profit / gross loss)
- Sharpe ratio
- Max drawdown
- Average hold time
- Fee efficiency

Gebruikt voor:
1. Performance monitoring (dashboards, alerts)
2. Auto-adjustment van strategy parameters
3. Trade analytics en reporting
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class TradeOutcome(Enum):
    """Trade result classification"""
    WIN = "win"           # Profitable trade
    LOSS = "loss"         # Losing trade
    BREAKEVEN = "breakeven"  # No gain/loss (within fee margin)


@dataclass
class TradeRecord:
    """Single trade execution record"""
    symbol: str
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    position_size_eur: Decimal
    realized_pnl_eur: Decimal  # After fees
    fees_eur: Decimal
    outcome: TradeOutcome
    hold_time_hours: float
    exit_reason: str  # "profit_target", "stop_loss", "trend_reversal", etc.

    def __post_init__(self):
        """Calculate derived fields"""
        if self.hold_time_hours == 0:
            self.hold_time_hours = (self.exit_time - self.entry_time).total_seconds() / 3600


@dataclass
class PerformanceMetrics:
    """Aggregated performance metrics"""
    # Time period
    period_start: datetime
    period_end: datetime

    # Trade statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0

    # P&L metrics
    total_pnl_eur: Decimal = Decimal("0")
    gross_profit_eur: Decimal = Decimal("0")
    gross_loss_eur: Decimal = Decimal("0")
    total_fees_eur: Decimal = Decimal("0")
    net_pnl_eur: Decimal = Decimal("0")  # After fees

    # Performance ratios
    win_rate: float = 0.0  # Percentage of winning trades
    profit_factor: float = 0.0  # Gross profit / Gross loss
    sharpe_ratio: float = 0.0  # Risk-adjusted returns

    # Risk metrics
    max_drawdown_pct: float = 0.0
    current_drawdown_pct: float = 0.0

    # Efficiency metrics
    avg_win_eur: Decimal = Decimal("0")
    avg_loss_eur: Decimal = Decimal("0")
    avg_hold_time_hours: float = 0.0
    fee_to_profit_ratio: float = 0.0  # Fees / Gross profit

    # Per-symbol breakdown
    symbol_breakdown: Dict[str, Dict] = field(default_factory=dict)


@dataclass
class PerformanceConfig:
    """Configuration for performance tracking"""
    enabled: bool = True

    # Lookback windows
    win_rate_lookback_trades: int = 20  # Last N trades
    sharpe_lookback_days: int = 7
    profit_factor_lookback_days: int = 7

    # Thresholds
    min_acceptable_win_rate: float = 0.45  # 45%
    min_acceptable_sharpe: float = 0.5
    min_acceptable_profit_factor: float = 1.2
    max_acceptable_drawdown_pct: float = 5.0
    max_fee_to_profit_ratio: float = 0.30  # 30%

    # Risk-free rate for Sharpe calculation
    risk_free_rate_annual: float = 0.03  # 3%

    # Reporting
    report_interval_hours: int = 4
    save_to_db: bool = True


class PerformanceTracker:
    """
    Track and analyze trading performance in real-time.

    Usage:
        config = PerformanceConfig(win_rate_lookback_trades=20)
        tracker = PerformanceTracker(config)

        # Record trades
        tracker.record_trade(
            symbol="BTC-EUR",
            entry_time=datetime.now(timezone.utc),
            exit_time=datetime.now(timezone.utc),
            entry_price=Decimal("50000"),
            exit_price=Decimal("50500"),
            position_size_eur=Decimal("100"),
            realized_pnl_eur=Decimal("0.95"),
            fees_eur=Decimal("0.05"),
            exit_reason="profit_target"
        )

        # Get metrics
        metrics = tracker.get_current_metrics()
        print(f"Win rate: {metrics.win_rate:.1%}")
        print(f"Profit factor: {metrics.profit_factor:.2f}")
        print(f"Sharpe ratio: {metrics.sharpe_ratio:.2f}")
    """

    def __init__(self, config: PerformanceConfig):
        self.config = config
        self.trade_history: List[TradeRecord] = []
        self._peak_balance: Decimal = Decimal("0")
        self._current_balance: Decimal = Decimal("0")
        self._last_report_time: Optional[datetime] = None

        logger.info("📊 PerformanceTracker initialized")
        logger.info(f"   Win rate threshold: {config.min_acceptable_win_rate:.0%}")
        logger.info(f"   Sharpe threshold: {config.min_acceptable_sharpe:.2f}")
        logger.info(f"   Profit factor threshold: {config.min_acceptable_profit_factor:.2f}")

    def record_trade(
        self,
        symbol: str,
        entry_time: datetime,
        exit_time: datetime,
        entry_price: Decimal,
        exit_price: Decimal,
        position_size_eur: Decimal,
        realized_pnl_eur: Decimal,
        fees_eur: Decimal,
        exit_reason: str = "unknown"
    ) -> TradeRecord:
        """
        Record a completed trade.

        Args:
            symbol: Trading pair
            entry_time: Entry timestamp
            exit_time: Exit timestamp
            entry_price: Entry price
            exit_price: Exit price
            position_size_eur: Position size in EUR
            realized_pnl_eur: Realized P&L after fees
            fees_eur: Total fees paid
            exit_reason: Why trade was closed

        Returns:
            TradeRecord object
        """
        # Classify outcome
        if realized_pnl_eur > Decimal("0.001"):  # >€0.001 = win
            outcome = TradeOutcome.WIN
        elif realized_pnl_eur < Decimal("-0.001"):  # <-€0.001 = loss
            outcome = TradeOutcome.LOSS
        else:
            outcome = TradeOutcome.BREAKEVEN

        # Calculate hold time
        hold_time_hours = (exit_time - entry_time).total_seconds() / 3600

        # Create record
        trade = TradeRecord(
            symbol=symbol,
            entry_time=entry_time,
            exit_time=exit_time,
            entry_price=entry_price,
            exit_price=exit_price,
            position_size_eur=position_size_eur,
            realized_pnl_eur=realized_pnl_eur,
            fees_eur=fees_eur,
            outcome=outcome,
            hold_time_hours=hold_time_hours,
            exit_reason=exit_reason
        )

        self.trade_history.append(trade)

        # Update balance tracking for drawdown
        self._current_balance += realized_pnl_eur
        if self._current_balance > self._peak_balance:
            self._peak_balance = self._current_balance

        # Log trade
        emoji = "✅" if outcome == TradeOutcome.WIN else "❌" if outcome == TradeOutcome.LOSS else "➖"
        logger.info(
            f"{emoji} Trade closed: {symbol} | P&L: €{realized_pnl_eur:.2f} | "
            f"Hold: {hold_time_hours:.1f}h | Reason: {exit_reason}"
        )

        return trade

    def get_current_metrics(
        self,
        lookback_days: Optional[int] = None
    ) -> PerformanceMetrics:
        """
        Calculate current performance metrics.

        Args:
            lookback_days: Optional lookback period (defaults to config)

        Returns:
            PerformanceMetrics with all calculated values
        """
        if not self.trade_history:
            # Return empty metrics if no trades
            now = datetime.now(timezone.utc)
            return PerformanceMetrics(
                period_start=now,
                period_end=now
            )

        # Determine time window
        if lookback_days:
            cutoff_time = datetime.now(timezone.utc) - timedelta(days=lookback_days)
            trades = [t for t in self.trade_history if t.exit_time >= cutoff_time]
        else:
            trades = self.trade_history

        if not trades:
            now = datetime.now(timezone.utc)
            return PerformanceMetrics(period_start=now, period_end=now)

        # Time period
        period_start = trades[0].entry_time
        period_end = trades[-1].exit_time

        # Basic counts
        total_trades = len(trades)
        winning_trades = sum(1 for t in trades if t.outcome == TradeOutcome.WIN)
        losing_trades = sum(1 for t in trades if t.outcome == TradeOutcome.LOSS)
        breakeven_trades = sum(1 for t in trades if t.outcome == TradeOutcome.BREAKEVEN)

        # P&L aggregation
        total_pnl = sum(t.realized_pnl_eur for t in trades)
        total_fees = sum(t.fees_eur for t in trades)
        gross_profit = sum(t.realized_pnl_eur + t.fees_eur for t in trades if t.outcome == TradeOutcome.WIN)
        gross_loss = abs(sum(t.realized_pnl_eur + t.fees_eur for t in trades if t.outcome == TradeOutcome.LOSS))
        net_pnl = total_pnl  # Already includes fees

        # Win rate
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        # Profit factor
        profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else 0.0

        # Sharpe ratio
        sharpe_ratio = self._calculate_sharpe_ratio(trades)

        # Drawdown
        max_drawdown_pct = self._calculate_max_drawdown(trades)
        current_drawdown_pct = float(
            (self._peak_balance - self._current_balance) / self._peak_balance * 100
        ) if self._peak_balance > 0 else 0.0

        # Averages
        avg_win = gross_profit / winning_trades if winning_trades > 0 else Decimal("0")
        avg_loss = gross_loss / losing_trades if losing_trades > 0 else Decimal("0")
        avg_hold_time = statistics.mean([t.hold_time_hours for t in trades]) if trades else 0.0

        # Fee efficiency
        fee_to_profit_ratio = float(total_fees / gross_profit) if gross_profit > 0 else 0.0

        # Per-symbol breakdown
        symbol_breakdown = self._calculate_symbol_breakdown(trades)

        return PerformanceMetrics(
            period_start=period_start,
            period_end=period_end,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            breakeven_trades=breakeven_trades,
            total_pnl_eur=total_pnl,
            gross_profit_eur=gross_profit,
            gross_loss_eur=gross_loss,
            total_fees_eur=total_fees,
            net_pnl_eur=net_pnl,
            win_rate=win_rate,
            profit_factor=profit_factor,
            sharpe_ratio=sharpe_ratio,
            max_drawdown_pct=max_drawdown_pct,
            current_drawdown_pct=current_drawdown_pct,
            avg_win_eur=avg_win,
            avg_loss_eur=avg_loss,
            avg_hold_time_hours=avg_hold_time,
            fee_to_profit_ratio=fee_to_profit_ratio,
            symbol_breakdown=symbol_breakdown
        )

    def _calculate_sharpe_ratio(self, trades: List[TradeRecord]) -> float:
        """Calculate Sharpe ratio (risk-adjusted returns)"""
        if len(trades) < 2:
            return 0.0

        # Calculate returns (P&L as percentage of position size)
        returns = [
            float(t.realized_pnl_eur / t.position_size_eur * 100)
            for t in trades if t.position_size_eur > 0
        ]

        if not returns:
            return 0.0

        # Mean and std dev of returns
        mean_return = statistics.mean(returns)
        std_dev = statistics.stdev(returns) if len(returns) > 1 else 0.0

        if std_dev == 0:
            return 0.0

        # Annualized Sharpe ratio
        # Assuming ~250 trading days per year, ~6 trades per day average
        periods_per_year = 250 * 6
        risk_free_rate_per_period = self.config.risk_free_rate_annual / periods_per_year

        sharpe = (mean_return - risk_free_rate_per_period) / std_dev * (periods_per_year ** 0.5)

        return sharpe

    def _calculate_max_drawdown(self, trades: List[TradeRecord]) -> float:
        """Calculate maximum drawdown percentage"""
        if not trades:
            return 0.0

        # Build cumulative P&L series
        cumulative_pnl = Decimal("0")
        peak = Decimal("0")
        max_dd = Decimal("0")

        for trade in trades:
            cumulative_pnl += trade.realized_pnl_eur
            if cumulative_pnl > peak:
                peak = cumulative_pnl
            drawdown = peak - cumulative_pnl
            if drawdown > max_dd:
                max_dd = drawdown

        # Convert to percentage
        max_dd_pct = float(max_dd / peak * 100) if peak > 0 else 0.0

        return max_dd_pct

    def _calculate_symbol_breakdown(self, trades: List[TradeRecord]) -> Dict[str, Dict]:
        """Calculate per-symbol performance metrics"""
        breakdown = {}

        # Group trades by symbol
        symbols = set(t.symbol for t in trades)

        for symbol in symbols:
            symbol_trades = [t for t in trades if t.symbol == symbol]

            wins = sum(1 for t in symbol_trades if t.outcome == TradeOutcome.WIN)
            losses = sum(1 for t in symbol_trades if t.outcome == TradeOutcome.LOSS)
            total = len(symbol_trades)
            # Fix: Convert Decimal to float to avoid type mismatch
            pnl = sum(float(t.realized_pnl_eur) for t in symbol_trades)

            breakdown[symbol] = {
                "total_trades": total,
                "wins": wins,
                "losses": losses,
                "win_rate": wins / total if total > 0 else 0.0,
                "total_pnl_eur": float(pnl),
                "avg_pnl_eur": float(pnl / total) if total > 0 else 0.0,
            }

        return breakdown

    def get_recent_performance(self, last_n_trades: int = 20) -> PerformanceMetrics:
        """
        Get metrics for recent trades only.

        Args:
            last_n_trades: Number of recent trades to analyze

        Returns:
            PerformanceMetrics for recent window
        """
        recent_trades = self.trade_history[-last_n_trades:] if len(self.trade_history) >= last_n_trades else self.trade_history

        if not recent_trades:
            now = datetime.now(timezone.utc)
            return PerformanceMetrics(period_start=now, period_end=now)

        # Reuse main calculation logic
        old_history = self.trade_history
        self.trade_history = recent_trades
        metrics = self.get_current_metrics()
        self.trade_history = old_history

        return metrics

    def is_performance_acceptable(self) -> Tuple[bool, List[str]]:
        """
        Check if current performance meets minimum thresholds.

        Returns:
            Tuple of (acceptable: bool, reasons: List[str])
        """
        metrics = self.get_recent_performance(self.config.win_rate_lookback_trades)

        issues = []

        # Check win rate
        if metrics.total_trades >= 10 and metrics.win_rate < self.config.min_acceptable_win_rate:
            issues.append(f"Win rate {metrics.win_rate:.1%} < {self.config.min_acceptable_win_rate:.1%}")

        # Check Sharpe ratio
        if metrics.total_trades >= 10 and metrics.sharpe_ratio < self.config.min_acceptable_sharpe:
            issues.append(f"Sharpe {metrics.sharpe_ratio:.2f} < {self.config.min_acceptable_sharpe:.2f}")

        # Check profit factor
        if metrics.total_trades >= 10 and metrics.profit_factor < self.config.min_acceptable_profit_factor:
            issues.append(f"Profit factor {metrics.profit_factor:.2f} < {self.config.min_acceptable_profit_factor:.2f}")

        # Check drawdown
        if metrics.max_drawdown_pct > self.config.max_acceptable_drawdown_pct:
            issues.append(f"Drawdown {metrics.max_drawdown_pct:.1f}% > {self.config.max_acceptable_drawdown_pct:.1f}%")

        # Check fee efficiency
        if metrics.total_trades >= 5 and metrics.fee_to_profit_ratio > self.config.max_fee_to_profit_ratio:
            issues.append(f"Fee ratio {metrics.fee_to_profit_ratio:.1%} > {self.config.max_fee_to_profit_ratio:.1%}")

        acceptable = len(issues) == 0

        return acceptable, issues

    def generate_report(self) -> str:
        """
        Generate human-readable performance report.

        Returns:
            Formatted string with performance summary
        """
        metrics = self.get_current_metrics()

        report = []
        report.append("=" * 80)
        report.append("📊 PERFORMANCE REPORT")
        report.append("=" * 80)
        report.append(f"Period: {metrics.period_start.strftime('%Y-%m-%d %H:%M')} → {metrics.period_end.strftime('%Y-%m-%d %H:%M')}")
        report.append("")

        # Trade statistics
        report.append("📈 TRADE STATISTICS")
        report.append(f"   Total trades: {metrics.total_trades}")
        report.append(f"   Wins: {metrics.winning_trades} ({metrics.win_rate:.1%})")
        report.append(f"   Losses: {metrics.losing_trades}")
        report.append(f"   Breakeven: {metrics.breakeven_trades}")
        report.append("")

        # P&L summary
        report.append("💰 P&L SUMMARY")
        report.append(f"   Net P&L: €{metrics.net_pnl_eur:.2f}")
        report.append(f"   Gross profit: €{metrics.gross_profit_eur:.2f}")
        report.append(f"   Gross loss: €{metrics.gross_loss_eur:.2f}")
        report.append(f"   Total fees: €{metrics.total_fees_eur:.2f}")
        report.append("")

        # Performance ratios
        report.append("📊 PERFORMANCE RATIOS")
        report.append(f"   Win rate: {metrics.win_rate:.1%}")
        report.append(f"   Profit factor: {metrics.profit_factor:.2f}")
        report.append(f"   Sharpe ratio: {metrics.sharpe_ratio:.2f}")
        report.append(f"   Max drawdown: {metrics.max_drawdown_pct:.2f}%")
        report.append("")

        # Efficiency
        report.append("⚡ EFFICIENCY")
        report.append(f"   Avg win: €{metrics.avg_win_eur:.2f}")
        report.append(f"   Avg loss: €{metrics.avg_loss_eur:.2f}")
        report.append(f"   Avg hold time: {metrics.avg_hold_time_hours:.1f}h")
        report.append(f"   Fee/profit ratio: {metrics.fee_to_profit_ratio:.1%}")
        report.append("")

        # Per-symbol breakdown
        if metrics.symbol_breakdown:
            report.append("🪙 TOP PERFORMERS")
            sorted_symbols = sorted(
                metrics.symbol_breakdown.items(),
                key=lambda x: x[1]["total_pnl_eur"],
                reverse=True
            )[:5]
            for symbol, data in sorted_symbols:
                report.append(
                    f"   {symbol}: €{data['total_pnl_eur']:.2f} "
                    f"({data['wins']}/{data['total_trades']} wins, {data['win_rate']:.0%})"
                )

        report.append("=" * 80)

        return "\n".join(report)
