"""
Trade Analyzer - Comprehensive bot analysis for Telegram reporting

Reads trade data directly from SQLite database for accurate real-time data.
Also parses log files for status information (trends, blocks, errors).
"""

import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .config import MonitoringConfig


@dataclass
class Trade:
    """Represents a single trade (buy/sell pair)"""
    coin: str
    buy_price: Decimal
    buy_amount: Decimal
    buy_time: datetime
    sell_price: Optional[Decimal] = None
    sell_amount: Optional[Decimal] = None
    sell_time: Optional[datetime] = None
    buy_fee: Decimal = Decimal("0")
    sell_fee: Decimal = Decimal("0")

    @property
    def is_closed(self) -> bool:
        return self.sell_price is not None

    @property
    def buy_value(self) -> Decimal:
        return self.buy_price * self.buy_amount

    @property
    def sell_value(self) -> Decimal:
        if self.sell_price and self.sell_amount:
            return self.sell_price * self.sell_amount
        return Decimal("0")

    @property
    def profit(self) -> Decimal:
        """Net profit after fees"""
        if not self.is_closed:
            return Decimal("0")
        return self.sell_value - self.buy_value - self.buy_fee - self.sell_fee

    @property
    def profit_pct(self) -> float:
        """Profit as percentage"""
        if not self.is_closed or self.buy_value == 0:
            return 0.0
        return float((self.profit / self.buy_value) * 100)


@dataclass
class BotStatus:
    """Current bot status"""
    is_running: bool = False
    active_coin: Optional[str] = None
    current_position: Optional[Decimal] = None
    entry_price: Optional[Decimal] = None
    target_price: Optional[Decimal] = None
    is_blocked: bool = False
    block_reason: Optional[str] = None
    best_trend_coin: Optional[str] = None
    best_trend_pct: float = 0.0
    top_trends: List[Tuple[str, float]] = field(default_factory=list)
    last_update: Optional[datetime] = None


@dataclass
class AnalysisReport:
    """Complete analysis report"""
    trades: List[Trade]
    status: BotStatus
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_pnl: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    win_count: int = 0
    loss_count: int = 0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class TradeAnalyzer:
    """
    Analyzes bot data from SQLite database and log files.

    Reads trades directly from database for accuracy.
    Uses log files for status information (trends, blocks, etc.)
    """

    # Database path - prices and amounts stored as integers (multiply by divisor)
    DB_PATH = "/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite"
    PRICE_DIVISOR = Decimal("1000000")  # Prices stored as micro-EUR

    def __init__(self, log_path: Optional[str] = None, db_path: Optional[str] = None):
        """
        Initialize analyzer

        Args:
            log_path: Path to log file (default: from config)
            db_path: Path to SQLite database (default: standard path)
        """
        self.log_path = Path(log_path or MonitoringConfig.LOG_FILE)
        self.db_path = db_path or self.DB_PATH
        self.logger = logging.getLogger(__name__)

        # Regex patterns for parsing log files (status info only)
        self.patterns = {
            'top_trends': re.compile(
                r'(\d+)\. (\w+-EUR): ([+-]?[\d.]+)%.*24h: ([+-]?[\d.]+)%'
            ),
            'best_coin': re.compile(
                r'BEST: (\w+-EUR) with ([+-]?[\d.]+)% trend'
            ),
            'active_coin': re.compile(
                r'Active Coin: (\w+-EUR)'
            ),
            'active_coin_alt': re.compile(
                r'🎯 Active: (\w+-EUR)'
            ),
            'risk_blocked': re.compile(
                r'Risk manager blocked.*\(([^)]+)\)'
            ),
            'drawdown_blocked': re.compile(
                r'DRAWDOWN LIMIT|Trading paused'
            ),
            'error': re.compile(
                r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*ERROR.*-\s*(.+)'
            ),
            'warning': re.compile(
                r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*CRITICAL.*-\s*(.+)'
            ),
        }

    def analyze(self, hours: int = 24) -> AnalysisReport:
        """
        Perform comprehensive analysis

        Reads trades from SQLite database (accurate, real-time data).
        Reads status from log files (trends, blocks, etc.)

        Args:
            hours: Number of hours to analyze (default: 24)

        Returns:
            AnalysisReport with all findings
        """
        # Read trades from database (primary source)
        trades = self._read_trades_from_db(hours)

        # Read status from log file
        status = BotStatus()
        errors = []
        warnings = []

        if self.log_path.exists():
            cutoff_time = datetime.now() - timedelta(hours=hours)
            lines = self._read_recent_lines(cutoff_time)
            status = self._parse_status(lines)
            errors, warnings = self._parse_issues(lines)

        # Calculate statistics
        report = self._build_report(trades, status, errors, warnings)

        return report

    def _read_trades_from_db(self, hours: int = 24) -> List[Trade]:
        """
        Read trades directly from SQLite database

        This is more accurate than parsing logs.

        Args:
            hours: Number of hours to look back

        Returns:
            List of Trade objects
        """
        trades = []

        if not Path(self.db_path).exists():
            self.logger.warning(f"Database not found: {self.db_path}")
            return trades

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get trades from last N hours
            cutoff_ms = int((datetime.now() - timedelta(hours=hours)).timestamp() * 1000)

            cursor.execute('''
                SELECT symbol, trade_type, price, amount, trade_fee_in_quote, timestamp
                FROM TradeFill
                WHERE timestamp > ?
                ORDER BY timestamp ASC
            ''', (cutoff_ms,))

            rows = cursor.fetchall()
            conn.close()

            # Use FIFO matching for grid trading
            open_buys: Dict[str, List[Tuple]] = {}  # coin -> [(amount, price, fee, timestamp)]

            for symbol, trade_type, price, amount, fee, ts in rows:
                # Convert from database format
                ts_dt = datetime.fromtimestamp(ts / 1000)
                price_dec = Decimal(str(price)) / self.PRICE_DIVISOR
                amount_dec = Decimal(str(amount)) / self.PRICE_DIVISOR
                fee_dec = Decimal(str(fee)) / self.PRICE_DIVISOR if fee else Decimal("0")

                coin = symbol.replace("-EUR", "")

                if trade_type == 'BUY':
                    # Add to FIFO queue
                    if coin not in open_buys:
                        open_buys[coin] = []
                    open_buys[coin].append((amount_dec, price_dec, fee_dec, ts_dt, symbol))

                elif trade_type == 'SELL':
                    # Match with oldest buys (FIFO)
                    if coin not in open_buys or not open_buys[coin]:
                        self.logger.debug(f"Sell without matching buy for {symbol}")
                        continue

                    remaining_sell = amount_dec
                    remaining_fee = fee_dec

                    while remaining_sell > Decimal("0.0001") and open_buys[coin]:
                        buy_amt, buy_price, buy_fee, buy_time, buy_symbol = open_buys[coin][0]
                        match_amt = min(buy_amt, remaining_sell)

                        # Proportional fees
                        buy_fee_portion = (match_amt / buy_amt) * buy_fee
                        sell_fee_portion = (match_amt / amount_dec) * remaining_fee

                        # Create matched trade
                        matched_trade = Trade(
                            coin=symbol,
                            buy_price=buy_price,
                            buy_amount=match_amt,
                            buy_time=buy_time,
                            buy_fee=buy_fee_portion,
                            sell_price=price_dec,
                            sell_amount=match_amt,
                            sell_time=ts_dt,
                            sell_fee=sell_fee_portion
                        )
                        trades.append(matched_trade)

                        # Update remaining
                        remaining_sell -= match_amt
                        remaining_fee -= sell_fee_portion

                        # Update or remove buy
                        new_buy_amt = buy_amt - match_amt
                        if new_buy_amt <= Decimal("0.0001"):
                            open_buys[coin].pop(0)
                        else:
                            open_buys[coin][0] = (new_buy_amt, buy_price, buy_fee - buy_fee_portion, buy_time, buy_symbol)

            # Add remaining open buy positions
            for coin, buy_list in open_buys.items():
                for buy_amt, buy_price, buy_fee, buy_time, buy_symbol in buy_list:
                    if buy_amt > Decimal("0.0001"):
                        open_trade = Trade(
                            coin=buy_symbol,
                            buy_price=buy_price,
                            buy_amount=buy_amt,
                            buy_time=buy_time,
                            buy_fee=buy_fee
                        )
                        trades.append(open_trade)

        except Exception as e:
            self.logger.error(f"Error reading trades from database: {e}")

        # If database is empty, parse from log file
        if not trades:
            self.logger.info("Database empty, parsing trades from log file...")
            trades = self._parse_trades_from_log(hours)

        return trades

    def _parse_trades_from_log(self, hours: int) -> List[Trade]:
        """Parse trades from log file using FIFO matching for grid trading"""
        trades = []
        cutoff_time = datetime.now() - timedelta(hours=hours)

        # Pattern to match trade fills
        trade_pattern = re.compile(
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?(BUY|SELL) order.*?(\d+\.\d+)/[\d.]+ (\w+) has been filled at ([\d.]+) EUR'
        )

        open_buys: Dict[str, List[Trade]] = {}  # coin -> list of open buy orders (FIFO queue)

        try:
            with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    match = trade_pattern.search(line)
                    if not match:
                        continue

                    timestamp_str, side, amount_str, coin_symbol, price_str = match.groups()
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')

                    if timestamp < cutoff_time:
                        continue

                    symbol = f"{coin_symbol}-EUR"
                    price = Decimal(price_str)
                    amount = Decimal(amount_str)
                    fee = amount * price * Decimal("0.0026")  # Kraken 0.26% fee estimate

                    if side == 'BUY':
                        trade = Trade(
                            coin=symbol,
                            buy_price=price,
                            buy_amount=amount,
                            buy_time=timestamp,
                            buy_fee=fee
                        )
                        if coin_symbol not in open_buys:
                            open_buys[coin_symbol] = []
                        open_buys[coin_symbol].append(trade)

                    elif side == 'SELL':
                        if coin_symbol not in open_buys or not open_buys[coin_symbol]:
                            self.logger.debug(f"Sell without matching buy for {coin_symbol}")
                            continue

                        remaining_sell = amount
                        remaining_fee = fee

                        # Match with oldest buys first (FIFO)
                        while remaining_sell > Decimal("0.0001") and open_buys[coin_symbol]:
                            buy_trade = open_buys[coin_symbol][0]
                            match_amount = min(buy_trade.buy_amount, remaining_sell)

                            # Proportional fees
                            buy_fee_portion = (match_amount / buy_trade.buy_amount) * buy_trade.buy_fee
                            sell_fee_portion = (match_amount / amount) * remaining_fee

                            # Create matched trade
                            closed_trade = Trade(
                                coin=symbol,
                                buy_price=buy_trade.buy_price,
                                buy_amount=match_amount,
                                buy_time=buy_trade.buy_time,
                                buy_fee=buy_fee_portion,
                                sell_price=price,
                                sell_amount=match_amount,
                                sell_time=timestamp,
                                sell_fee=sell_fee_portion
                            )
                            trades.append(closed_trade)

                            # Update remaining amounts
                            remaining_sell -= match_amount
                            remaining_fee -= sell_fee_portion
                            buy_trade.buy_amount -= match_amount
                            buy_trade.buy_fee -= buy_fee_portion

                            # Remove buy if fully consumed
                            if buy_trade.buy_amount <= Decimal("0.0001"):
                                open_buys[coin_symbol].pop(0)

            # Add remaining open positions
            for coin, buy_list in open_buys.items():
                for buy_trade in buy_list:
                    if buy_trade.buy_amount > Decimal("0.0001"):
                        trades.append(buy_trade)

        except Exception as e:
            self.logger.error(f"Error parsing trades from log: {e}")

        return trades

    def _read_recent_lines(self, cutoff_time: datetime) -> List[str]:
        """Read lines from log file after cutoff time"""
        relevant_lines = []

        try:
            with open(self.log_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    # Quick check for timestamp
                    if len(line) > 19:
                        try:
                            timestamp_str = line[:19]
                            timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                            if timestamp >= cutoff_time:
                                relevant_lines.append(line)
                        except ValueError:
                            # Not a timestamped line, include if we're past cutoff
                            if relevant_lines:
                                relevant_lines.append(line)
        except Exception as e:
            self.logger.error(f"Error reading log file: {e}")

        return relevant_lines

    def _parse_status(self, lines: List[str]) -> BotStatus:
        """Parse current status from recent log lines"""
        status = BotStatus()

        # Scan last 1000 lines for current status
        recent_lines = lines[-1000:] if len(lines) > 1000 else lines

        for line in reversed(recent_lines):
            # Check for active coin (multiple patterns)
            if status.active_coin is None:
                match = self.patterns['active_coin'].search(line)
                if match:
                    status.active_coin = match.group(1)
                    status.is_running = True
                else:
                    match = self.patterns['active_coin_alt'].search(line)
                    if match:
                        status.active_coin = match.group(1)
                        status.is_running = True

            # Check for best trend
            if status.best_trend_coin is None:
                match = self.patterns['best_coin'].search(line)
                if match:
                    status.best_trend_coin = match.group(1)
                    status.best_trend_pct = float(match.group(2))

            # Check for risk blocked
            if not status.is_blocked:
                match = self.patterns['risk_blocked'].search(line)
                if match:
                    status.is_blocked = True
                    status.block_reason = match.group(1)
                elif self.patterns['drawdown_blocked'].search(line):
                    status.is_blocked = True
                    status.block_reason = "Drawdown limit"

            # Get timestamp for last update
            if status.last_update is None and len(line) > 19:
                try:
                    status.last_update = datetime.strptime(line[:19], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    pass

        # Parse top trends from last occurrence
        for line in reversed(recent_lines):
            if "Top 10 trends" in line or "Top Trends" in line:
                # Get next 10 lines for trends
                try:
                    idx = recent_lines.index(line)
                    trend_lines = recent_lines[idx:idx + 12]
                    for trend_line in trend_lines:
                        match = self.patterns['top_trends'].search(trend_line)
                        if match:
                            rank = int(match.group(1))
                            coin = match.group(2)
                            trend = float(match.group(3))
                            if rank <= 5:
                                status.top_trends.append((coin, trend))
                except (ValueError, IndexError):
                    pass
                break

        return status

    def _parse_issues(self, lines: List[str]) -> Tuple[List[str], List[str]]:
        """Parse errors and critical warnings"""
        errors = []
        warnings = []

        for line in lines[-1000:]:  # Last 1000 lines
            # Check for errors
            if 'ERROR' in line:
                match = self.patterns['error'].search(line)
                if match:
                    errors.append(f"{match.group(1)}: {match.group(2)[:100]}")

            # Check for critical warnings
            if 'CRITICAL' in line:
                match = self.patterns['warning'].search(line)
                if match:
                    warnings.append(f"{match.group(1)}: {match.group(2)[:100]}")

        return errors[-5:], warnings[-5:]  # Last 5 of each

    def _build_report(
        self,
        trades: List[Trade],
        status: BotStatus,
        errors: List[str],
        warnings: List[str]
    ) -> AnalysisReport:
        """Build complete analysis report"""

        # Calculate P&L
        realized_pnl = Decimal("0")
        win_count = 0
        loss_count = 0

        for trade in trades:
            if trade.is_closed:
                realized_pnl += trade.profit
                if trade.profit > 0:
                    win_count += 1
                else:
                    loss_count += 1

        # Get time range
        start_time = min((t.buy_time for t in trades), default=None)
        end_time = max(
            (t.sell_time or t.buy_time for t in trades),
            default=None
        )

        return AnalysisReport(
            trades=trades,
            status=status,
            start_time=start_time,
            end_time=end_time,
            total_pnl=realized_pnl,
            realized_pnl=realized_pnl,
            win_count=win_count,
            loss_count=loss_count,
            errors=errors,
            warnings=warnings
        )

    def format_telegram_report(self, report: AnalysisReport) -> str:
        """
        Format report for Telegram message

        Args:
            report: AnalysisReport to format

        Returns:
            Formatted HTML string for Telegram
        """
        lines = []

        # Header
        lines.append("📊 <b>BOT ANALYSE RAPPORT</b>")
        lines.append("")

        # Status
        lines.append("━━━ <b>STATUS</b> ━━━")
        if report.status.is_running:
            lines.append(f"✅ Bot draait")
        else:
            lines.append(f"❌ Bot status onbekend")

        if report.status.active_coin:
            lines.append(f"📍 Actieve coin: <b>{report.status.active_coin}</b>")

        if report.status.is_blocked:
            lines.append(f"🛑 GEBLOKKEERD: {report.status.block_reason}")

        lines.append("")

        # P&L Summary
        lines.append("━━━ <b>P&L OVERZICHT</b> ━━━")
        pnl_emoji = "✅" if report.realized_pnl >= 0 else "❌"
        lines.append(f"{pnl_emoji} Gerealiseerd: <b>€{report.realized_pnl:.2f}</b>")
        lines.append(f"📈 Winst trades: {report.win_count}")
        lines.append(f"📉 Verlies trades: {report.loss_count}")

        if report.win_count + report.loss_count > 0:
            win_rate = report.win_count / (report.win_count + report.loss_count) * 100
            lines.append(f"🎯 Win rate: {win_rate:.0f}%")

        lines.append("")

        # Trade History
        lines.append("━━━ <b>TRADE GESCHIEDENIS</b> ━━━")
        if not report.trades:
            lines.append("Geen trades gevonden")
        else:
            for i, trade in enumerate(report.trades[-6:], 1):  # Last 6 trades
                status_emoji = "✅" if trade.is_closed else "⏳"
                if trade.is_closed:
                    profit_emoji = "📈" if trade.profit > 0 else "📉"
                    lines.append(
                        f"{i}. {trade.coin} {profit_emoji} "
                        f"€{trade.profit:+.2f} ({trade.profit_pct:+.1f}%)"
                    )
                else:
                    lines.append(
                        f"{i}. {trade.coin} ⏳ OPEN "
                        f"@ €{trade.buy_price:.5f}"
                    )

        lines.append("")

        # Top Trends
        if report.status.top_trends:
            lines.append("━━━ <b>TOP TRENDS</b> ━━━")
            for coin, trend in report.status.top_trends[:5]:
                trend_emoji = "🚀" if trend > 5 else "📈" if trend > 0 else "📉"
                lines.append(f"{trend_emoji} {coin}: <b>{trend:+.2f}%</b>")
            lines.append("")

        # Issues
        if report.errors or report.warnings:
            lines.append("━━━ <b>PROBLEMEN</b> ━━━")
            for err in report.errors[:3]:
                lines.append(f"❌ {err[:60]}...")
            for warn in report.warnings[:3]:
                lines.append(f"⚠️ {warn[:60]}...")
            lines.append("")

        # Footer with current time (shows when analysis was done)
        lines.append(f"<i>📅 Analyse: {datetime.now().strftime('%d-%m %H:%M:%S')}</i>")
        if report.end_time:
            lines.append(f"<i>📈 Laatste trade: {report.end_time.strftime('%d-%m %H:%M')}</i>")

        return "\n".join(lines)

    def format_short_report(self, report: AnalysisReport) -> str:
        """Format a shorter summary for quick status"""
        pnl_emoji = "✅" if report.realized_pnl >= 0 else "❌"
        status_emoji = "🟢" if report.status.is_running and not report.status.is_blocked else "🔴"

        lines = [
            f"{status_emoji} <b>Quick Status</b>",
            f"💰 P&L: <b>€{report.realized_pnl:.2f}</b>",
            f"📊 Trades: {report.win_count}W / {report.loss_count}L",
        ]

        if report.status.active_coin:
            lines.append(f"📍 {report.status.active_coin}")

        if report.status.is_blocked:
            lines.append(f"🛑 Blocked!")

        return "\n".join(lines)


def main():
    """CLI for testing analyzer"""
    import argparse

    parser = argparse.ArgumentParser(description="Trade Analyzer")
    parser.add_argument("--hours", type=int, default=24, help="Hours to analyze")
    parser.add_argument("--log", type=str, default=None, help="Log file path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    analyzer = TradeAnalyzer(log_path=args.log)
    report = analyzer.analyze(hours=args.hours)

    print(analyzer.format_telegram_report(report))


if __name__ == "__main__":
    main()
