"""
Data Collector Service

Background service that collects bot status, parses logs, and stores data in database.
Runs every N seconds (default: 10s).
"""

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from .config import MonitoringConfig
from .database import MonitoringDatabase
from .telegram_bot import TelegramBot


class DataCollector:
    """Collects bot data and stores in database"""

    def __init__(self, db: MonitoringDatabase, log_file: str, telegram_bot: Optional[TelegramBot] = None):
        """
        Initialize data collector

        Args:
            db: MonitoringDatabase instance
            log_file: Path to bot log file
            telegram_bot: Optional TelegramBot instance for alerts
        """
        self.db = db
        self.log_file = Path(log_file)
        self.logger = logging.getLogger(__name__)
        self.telegram_bot = telegram_bot

        # Start from END of file to avoid processing old events
        # Only monitor NEW events from this point forward
        self.last_position = 0
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(0, 2)  # Seek to end of file
                    self.last_position = f.tell()
                self.logger.info(f"📍 Starting from end of log file (position: {self.last_position})")
            except Exception as e:
                self.logger.warning(f"Could not seek to end of log file: {e}")

        # Event patterns to detect
        self.event_patterns = {
            "stop_loss": re.compile(r"STOP LOSS TRIGGERED|stop-loss triggered", re.IGNORECASE),
            "circuit_breaker": re.compile(r"CIRCUIT BREAKER ACTIVE|circuit breaker", re.IGNORECASE),
            "error": re.compile(r"ERROR|CRITICAL|Exception|Traceback", re.IGNORECASE),
            "trend_switch": re.compile(r"SWITCH APPROVED|Selected coin|🔍 Selected coin", re.IGNORECASE),
            "executor_created": re.compile(r"STARTING new grid|Creating grid|CREATING GRID", re.IGNORECASE),
            "executor_stopped": re.compile(r"Stopping executor|executor stopped|STOPPING executor", re.IGNORECASE),
            # Note: API rate limit warnings are normal - don't alert on them
            "api_error": re.compile(r"API.*error|API.*failed", re.IGNORECASE),
        }

        # Events that should NOT trigger alerts (too noisy)
        self.noisy_events = {
            "api_rate_limit",  # Normal rate limit warnings
        }

    def read_new_log_lines(self) -> list:
        """Read new lines from log file since last check"""
        if not self.log_file.exists():
            return []

        try:
            with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                # Seek to last position
                f.seek(self.last_position)
                lines = f.readlines()
                # Update position
                self.last_position = f.tell()
                return lines
        except Exception as e:
            self.logger.error(f"Error reading log file: {e}")
            return []

    def parse_log_line(self, line: str) -> Optional[Dict[str, Any]]:
        """
        Parse a log line and detect events

        Returns:
            Dict with event_type, coin, message if event detected, else None
        """
        # Extract timestamp if present
        timestamp_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)

        # Check for event patterns
        for event_type, pattern in self.event_patterns.items():
            if pattern.search(line):
                # Try to extract coin symbol - FIXED: Better pattern matching
                coin = None

                # First try to find coin in "Selected coin:" pattern
                selected_match = re.search(r'Selected coin:\s*([A-Z0-9]+-EUR)', line, re.IGNORECASE)
                if selected_match:
                    coin = selected_match.group(1)
                else:
                    # Fallback: look for any coin symbol pattern
                    coin_match = re.search(r'([A-Z0-9]+-EUR)', line)
                    coin = coin_match.group(1) if coin_match else None

                # Special handling for "Selected coin" messages
                if event_type == "trend_switch" and "Selected coin" in line:
                    # Extract the coin name or "None" message
                    selected_match = re.search(r'Selected coin:\s*(.+?)(?:\s|$)', line)
                    if selected_match:
                        coin_info = selected_match.group(1).strip()
                        # If coin_info contains a coin symbol, extract it
                        coin_symbol_match = re.search(r'([A-Z0-9]+-EUR)', coin_info)
                        if coin_symbol_match:
                            coin = coin_symbol_match.group(1)
                        # Create a cleaner message
                        message = f"Selected coin: {coin_info}"
                    else:
                        message = line.strip()
                else:
                    # For other events, use full line but clean it up
                    message = line.strip()
                    # Remove excessive whitespace
                    message = re.sub(r'\s+', ' ', message)
                    # Limit message length to prevent database issues (but keep more than dashboard shows)
                    if len(message) > 500:
                        message = message[:497] + "..."

                return {
                    "event_type": event_type,
                    "coin": coin,
                    "message": message,
                    "timestamp": timestamp_match.group(1) if timestamp_match else None
                }

        return None

    def get_bot_status_from_logs(self) -> Dict[str, Any]:
        """
        Extract bot status from recent log lines

        Returns:
            Dict with status information
        """
        status = {
            "active_coin": None,
            "pnl": 0.0,
            "exposure": 0.0,
            "mode": "running",
            "grid_level": None,
            "connection_status": "ok"
        }

        # Read last 500 lines to find status (increased from 100 for better coverage)
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()[-500:]

                    # Look for active coin - FIXED: Search for "Selected coin:" pattern
                    for line in reversed(lines):
                        # Pattern 1: "📊 MONITORING: Active Coin: FET-EUR" (new explicit format)
                        monitoring_coin_match = re.search(r'MONITORING:.*?Active Coin:\s*([A-Z0-9]+-EUR)', line)
                        if monitoring_coin_match:
                            coin = monitoring_coin_match.group(1)
                            if coin.upper() != "NONE":
                                status["active_coin"] = coin
                                break

                        # Pattern 2: "🔍 Selected coin: FET-EUR" or "Selected coin: FET-EUR"
                        selected_match = re.search(r'Selected coin:\s*([A-Z0-9]+-EUR)', line, re.IGNORECASE)
                        if selected_match:
                            coin = selected_match.group(1)
                            # Skip if it says "None"
                            if coin.upper() != "NONE":
                                status["active_coin"] = coin
                                break

                        # Pattern 3: "active_coin.*?([A-Z0-9]+-EUR)" (fallback)
                        coin_match = re.search(r'active_coin.*?([A-Z0-9]+-EUR)', line)
                        if coin_match:
                            status["active_coin"] = coin_match.group(1)
                            break

                        # Pattern 4: "Active Coin: FET-EUR" from status output
                        active_coin_match = re.search(r'Active Coin:\s*([A-Z0-9]+-EUR)', line)
                        if active_coin_match:
                            coin = active_coin_match.group(1)
                            if coin.upper() != "NONE":
                                status["active_coin"] = coin
                                break

                    # Look for P&L - FIXED: Search for P&L patterns in logs
                    for line in reversed(lines):
                        # Pattern 1: "📊 MONITORING: Total P&L: €+1.23" (new explicit format)
                        monitoring_pnl_match = re.search(r'MONITORING:.*?Total P&L:\s*€([+-]?[\d.]+)', line)
                        if monitoring_pnl_match:
                            try:
                                status["pnl"] = float(monitoring_pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 2: "📊 MONITORING: Executor P&L: €+1.23" (executor P&L)
                        executor_pnl_match = re.search(r'MONITORING:.*?Executor P&L:\s*€([+-]?[\d.]+)', line)
                        if executor_pnl_match:
                            try:
                                status["pnl"] = float(executor_pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 3: "💰 P&L: €+1.23 (+2.45%)" or "📉 P&L: €-1.23 (-2.45%)"
                        pnl_match = re.search(r'P&L:\s*€([+-]?[\d.]+)', line)
                        if pnl_match:
                            try:
                                status["pnl"] = float(pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 4: "Total P&L: €+1.23"
                        total_pnl_match = re.search(r'Total P&L:\s*€([+-]?[\d.]+)', line)
                        if total_pnl_match:
                            try:
                                status["pnl"] = float(total_pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 5: "net_pnl_quote.*?([+-]?[\d.]+)"
                        net_pnl_match = re.search(r'net_pnl_quote[:\s]+([+-]?[\d.]+)', line)
                        if net_pnl_match:
                            try:
                                status["pnl"] = float(net_pnl_match.group(1))
                                break
                            except ValueError:
                                pass

                    # Look for exposure - FIXED: Better pattern matching
                    for line in reversed(lines):
                        # Pattern 1: "Total Exposure: €50.00"
                        exposure_match = re.search(r'Total Exposure:\s*€([\d.]+)', line)
                        if exposure_match:
                            try:
                                status["exposure"] = float(exposure_match.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 2: "exposure.*?€([\d.]+)"
                        exposure_match2 = re.search(r'exposure.*?€([\d.]+)', line, re.IGNORECASE)
                        if exposure_match2:
                            try:
                                status["exposure"] = float(exposure_match2.group(1))
                                break
                            except ValueError:
                                pass

                        # Pattern 3: "Reset exposure: FET-EUR (was €50.00)"
                        reset_exposure_match = re.search(r'Reset exposure.*?€([\d.]+)', line)
                        if reset_exposure_match:
                            try:
                                status["exposure"] = float(reset_exposure_match.group(1))
                                break
                            except ValueError:
                                pass

                    # Look for mode (paused, error, etc)
                    for line in reversed(lines):
                        if "CIRCUIT BREAKER" in line or "paused" in line.lower():
                            status["mode"] = "paused"
                            break
                        if "ERROR" in line or "CRITICAL" in line:
                            status["mode"] = "error_safe_mode"
                            break
            except Exception as e:
                self.logger.error(f"Error reading status from logs: {e}")

        return status

    def measure_latency(self) -> float:
        """
        Measure exchange latency (Kraken ping)

        Returns:
            Latency in milliseconds
        """
        try:
            import time
            start = time.time()
            # Simple HTTP request to Kraken public endpoint
            response = requests.get("https://api.kraken.com/0/public/Time", timeout=5)
            elapsed = (time.time() - start) * 1000  # Convert to ms

            if response.status_code == 200:
                return elapsed
            else:
                return 9999.0  # Error indicator
        except Exception as e:
            self.logger.debug(f"Latency measurement failed: {e}")
            return 9999.0

    def collect_and_store(self):
        """Main collection cycle: read logs, detect events, store status"""
        # Read new log lines
        new_lines = self.read_new_log_lines()

        # Parse and store events
        for line in new_lines:
            # Skip API rate limit warnings completely (too noisy)
            if "API rate limit" in line or "rate limit" in line.lower():
                continue

            event = self.parse_log_line(line)
            if event:
                # Skip storing noisy events
                if event["event_type"] in self.noisy_events:
                    continue

                self.db.add_event(
                    event_type=event["event_type"],
                    message=event["message"],
                    coin=event.get("coin"),
                    data={"timestamp": event.get("timestamp")}
                )

                # Log important events
                if event["event_type"] in ["stop_loss", "error", "circuit_breaker"]:
                    self.logger.warning(f"⚠️  Event detected: {event['event_type']} - {event['message'][:100]}")

                # Send Telegram alert for critical events only
                if self.telegram_bot:
                    coin = event.get("coin")
                    event_type = event["event_type"]

                    # Only alert for:
                    # 1. Critical events (always alert, even without coin)
                    # 2. Trend switches (only if coin is valid)
                    if event_type in ["stop_loss", "circuit_breaker", "error"]:
                        # Critical events - always alert
                        self.telegram_bot.check_and_alert(
                            event_type=event_type,
                            message=event["message"][:200],
                            coin=coin
                        )
                    elif event_type == "trend_switch" and coin:
                        # Trend switches - only if coin is valid
                        self.telegram_bot.check_and_alert(
                            event_type=event_type,
                            message=event["message"][:200],
                            coin=coin
                        )

        # Get and store bot status
        status = self.get_bot_status_from_logs()
        latency = self.measure_latency()

        self.db.add_status(
            active_coin=status["active_coin"],
            pnl=status["pnl"],
            exposure=status["exposure"],
            mode=status["mode"],
            grid_level=status["grid_level"],
            heartbeat_latency=latency,
            connection_status="ok" if latency < 5000 else "reconnecting"
        )

    def run_continuous(self, interval: int = 10):
        """
        Run collector continuously

        Args:
            interval: Seconds between collection cycles
        """
        self.logger.info(f"🚀 Starting data collector (interval: {interval}s)")
        self.logger.info(f"📁 Monitoring log file: {self.log_file}")

        try:
            while True:
                try:
                    self.collect_and_store()
                except Exception as e:
                    self.logger.error(f"Error in collection cycle: {e}")

                time.sleep(interval)
        except KeyboardInterrupt:
            self.logger.info("🛑 Data collector stopped by user")


def main():
    """Main entry point for collector"""
    import argparse

    parser = argparse.ArgumentParser(description="Bot Monitoring Data Collector")
    parser.add_argument(
        "--interval",
        type=int,
        default=MonitoringConfig.COLLECTOR_INTERVAL,
        help="Collection interval in seconds (default: 10)"
    )
    parser.add_argument(
        "--log-file",
        type=str,
        default=MonitoringConfig.LOG_FILE,
        help="Path to bot log file"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: auto)"
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize database and collector
    db = MonitoringDatabase(db_path=args.db_path)

    # Initialize Telegram bot if configured
    telegram_bot = None
    if MonitoringConfig.TELEGRAM_BOT_TOKEN and MonitoringConfig.TELEGRAM_CHAT_ID:
        telegram_bot = TelegramBot(
            bot_token=MonitoringConfig.TELEGRAM_BOT_TOKEN,
            chat_id=MonitoringConfig.TELEGRAM_CHAT_ID,
            db=db
        )
        logging.info("✅ Telegram bot initialized")

    collector = DataCollector(db=db, log_file=args.log_file, telegram_bot=telegram_bot)

    # Run collector
    collector.run_continuous(interval=args.interval)


if __name__ == "__main__":
    main()
