"""
Telegram Bot Command Handler

Listens for incoming Telegram messages and handles commands.
Runs as a separate service that polls Telegram for new messages.

Commands:
- /vertel - Full analysis report (Dutch: "tell me")
- /status - Quick status
- /trades - Recent trades
- /trends - Current trends
- /events - Recent events
- /help - Show commands
"""

import logging
import time
from typing import Any, Dict

import requests

from .config import MonitoringConfig
from .database import MonitoringDatabase
from .telegram_bot import TelegramBot
from .trade_analyzer import TradeAnalyzer


class TelegramBotHandler:
    """Handles incoming Telegram commands via polling"""

    def __init__(self, bot: TelegramBot, log_path: str = None):
        """
        Initialize command handler

        Args:
            bot: TelegramBot instance
            log_path: Path to bot log file (optional)
        """
        self.bot = bot
        self.base_url = bot.base_url
        self.logger = logging.getLogger(__name__)
        self.last_update_id = 0

        # Initialize analyzer
        self.analyzer = TradeAnalyzer(log_path=log_path)

        # Command handlers
        self.commands = {
            "/start": self._handle_start,
            "/status": self._handle_status,
            "/events": self._handle_events,
            "/help": self._handle_help,
            "/vertel": self._handle_vertel,
            "/analyse": self._handle_vertel,  # Alias
            "/analyze": self._handle_vertel,  # English alias
            "/trades": self._handle_trades,
            "/trends": self._handle_trends,
            "/quick": self._handle_quick,
            "/pnl": self._handle_pnl,
        }

    def get_updates(self, timeout: int = 10) -> list:
        """
        Get new updates from Telegram

        Args:
            timeout: Long polling timeout in seconds

        Returns:
            List of updates
        """
        try:
            url = f"{self.base_url}/getUpdates"
            params = {
                "offset": self.last_update_id + 1,
                "timeout": timeout,
                "allowed_updates": ["message"]
            }

            response = requests.get(url, params=params, timeout=timeout + 5)
            response.raise_for_status()
            data = response.json()

            if data.get("ok"):
                return data.get("result", [])
            return []
        except Exception as e:
            self.logger.error(f"Error getting updates: {e}")
            return []

    def process_update(self, update: Dict[str, Any]):
        """Process a single update"""
        message = update.get("message", {})
        if not message:
            return

        text = message.get("text", "").strip()
        chat_id = str(message.get("chat", {}).get("id"))

        # Only respond to messages from configured chat ID
        if chat_id != self.bot.chat_id:
            self.logger.debug(f"Ignoring message from chat {chat_id} (not configured)")
            return

        # Check if it's a command
        if text.startswith("/"):
            command = text.split()[0].lower()
            handler = self.commands.get(command)
            if handler:
                try:
                    handler(message)
                except Exception as e:
                    self.logger.error(f"Error handling command {command}: {e}")
                    self.bot.send_message(f"❌ Error processing command: {e}")
            else:
                self.bot.send_message(f"❓ Unknown command: {command}\n\nType /help for available commands")
        else:
            # Regular message - send help
            self.bot.send_message("👋 Hi! Send /help to see available commands.")

    def _handle_start(self, message: Dict[str, Any]):
        """Handle /start command"""
        help_text = """
🤖 <b>Multi-Coin Grid Bot Monitor</b>

<b>Belangrijkste commands:</b>
/vertel - 📊 Uitgebreide analyse rapport
/quick - ⚡ Snelle status
/trades - 📈 Recente trades
/trends - 📊 Top trending coins
/pnl - 💰 P&L overzicht

Type /help voor alle commands.

<b>Automatische alerts:</b>
🛑 Stop-loss | ⚡ Circuit breaker | ❌ Errors
"""
        self.bot.send_message(help_text)

    def _handle_status(self, message: Dict[str, Any]):
        """Handle /status command"""
        self.bot.send_status()

    def _handle_events(self, message: Dict[str, Any]):
        """Handle /events command"""
        # Parse optional limit from command: /events 10
        text = message.get("text", "")
        parts = text.split()
        limit = 5
        if len(parts) > 1:
            try:
                limit = int(parts[1])
                limit = min(limit, 20)  # Max 20 events
            except ValueError:
                pass

        self.bot.send_recent_events(limit=limit)

    def _handle_help(self, message: Dict[str, Any]):
        """Handle /help command"""
        help_text = """
📋 <b>Beschikbare Commands:</b>

<b>📊 Analyse:</b>
/vertel - Uitgebreide analyse (trades, P&L, trends)
/quick - Snelle status samenvatting
/pnl - Alleen P&L overzicht

<b>📈 Trading:</b>
/trades [N] - Laatste N trades (default: 5)
/trends - Huidige top trends
/status - Bot status

<b>📋 Logs:</b>
/events [N] - Laatste N events (default: 5)

<b>ℹ️ Info:</b>
/help - Dit menu

<b>Automatische Alerts:</b>
🛑 Stop-loss triggers
⚡ Circuit breaker
❌ Kritieke errors
🔄 Coin switches
"""
        self.bot.send_message(help_text)

    def _handle_vertel(self, message: Dict[str, Any]):
        """Handle /vertel command - Full analysis report"""
        self.bot.send_message("🔍 <i>Analyseren... even geduld...</i>")

        try:
            # Parse optional hours parameter
            text = message.get("text", "")
            parts = text.split()
            hours = 24
            if len(parts) > 1:
                try:
                    hours = int(parts[1])
                    hours = min(hours, 72)  # Max 72 hours
                except ValueError:
                    pass

            # Run analysis
            report = self.analyzer.analyze(hours=hours)

            # Format and send
            formatted = self.analyzer.format_telegram_report(report)
            self.bot.send_message(formatted)

        except Exception as e:
            self.logger.error(f"Error in /vertel: {e}")
            self.bot.send_message(f"❌ Analyse fout: {e}")

    def _handle_trades(self, message: Dict[str, Any]):
        """Handle /trades command - Show recent trades"""
        try:
            text = message.get("text", "")
            parts = text.split()
            limit = 5
            if len(parts) > 1:
                try:
                    limit = int(parts[1])
                    limit = min(limit, 15)
                except ValueError:
                    pass

            report = self.analyzer.analyze(hours=24)

            if not report.trades:
                self.bot.send_message("📭 Geen trades gevonden in de laatste 24 uur")
                return

            lines = [f"📈 <b>Laatste {min(limit, len(report.trades))} Trades:</b>", ""]

            for i, trade in enumerate(report.trades[-limit:], 1):
                if trade.is_closed:
                    profit_emoji = "✅" if trade.profit > 0 else "❌"
                    lines.append(
                        f"{i}. <b>{trade.coin}</b> {profit_emoji}\n"
                        f"   Buy: €{trade.buy_price:.5f} → Sell: €{trade.sell_price:.5f}\n"
                        f"   P&L: <b>€{trade.profit:+.2f}</b> ({trade.profit_pct:+.1f}%)\n"
                        f"   {trade.buy_time.strftime('%H:%M')} - {trade.sell_time.strftime('%H:%M')}"
                    )
                else:
                    lines.append(
                        f"{i}. <b>{trade.coin}</b> ⏳ OPEN\n"
                        f"   Entry: €{trade.buy_price:.5f}\n"
                        f"   Amount: {trade.buy_amount:.2f}\n"
                        f"   Since: {trade.buy_time.strftime('%H:%M')}"
                    )
                lines.append("")

            self.bot.send_message("\n".join(lines))

        except Exception as e:
            self.logger.error(f"Error in /trades: {e}")
            self.bot.send_message(f"❌ Error: {e}")

    def _handle_trends(self, message: Dict[str, Any]):
        """Handle /trends command - Show current trends"""
        try:
            report = self.analyzer.analyze(hours=1)  # Just need current status

            if not report.status.top_trends:
                self.bot.send_message("📊 Geen trend data beschikbaar")
                return

            lines = ["📊 <b>Top Trends (24h)</b>", ""]

            for i, (coin, trend) in enumerate(report.status.top_trends, 1):
                if trend > 10:
                    emoji = "🚀"
                elif trend > 5:
                    emoji = "📈"
                elif trend > 0:
                    emoji = "📊"
                else:
                    emoji = "📉"

                lines.append(f"{i}. {emoji} <b>{coin}</b>: {trend:+.2f}%")

            if report.status.best_trend_coin:
                lines.append("")
                lines.append(f"🏆 Best: <b>{report.status.best_trend_coin}</b> ({report.status.best_trend_pct:+.2f}%)")

            if report.status.is_blocked:
                lines.append("")
                lines.append(f"🛑 <b>GEBLOKKEERD:</b> {report.status.block_reason}")

            self.bot.send_message("\n".join(lines))

        except Exception as e:
            self.logger.error(f"Error in /trends: {e}")
            self.bot.send_message(f"❌ Error: {e}")

    def _handle_quick(self, message: Dict[str, Any]):
        """Handle /quick command - Quick status summary"""
        try:
            report = self.analyzer.analyze(hours=24)
            formatted = self.analyzer.format_short_report(report)
            self.bot.send_message(formatted)
        except Exception as e:
            self.logger.error(f"Error in /quick: {e}")
            self.bot.send_message(f"❌ Error: {e}")

    def _handle_pnl(self, message: Dict[str, Any]):
        """Handle /pnl command - P&L summary"""
        try:
            report = self.analyzer.analyze(hours=24)

            pnl_emoji = "✅" if report.realized_pnl >= 0 else "❌"

            lines = [
                "💰 <b>P&L Overzicht (24h)</b>",
                "",
                f"{pnl_emoji} Gerealiseerd: <b>€{report.realized_pnl:.2f}</b>",
                "",
                f"📈 Winstgevende trades: {report.win_count}",
                f"📉 Verliesgevende trades: {report.loss_count}",
            ]

            if report.win_count + report.loss_count > 0:
                win_rate = report.win_count / (report.win_count + report.loss_count) * 100
                lines.append(f"🎯 Win rate: <b>{win_rate:.0f}%</b>")

                # Calculate average win/loss
                wins = [t.profit for t in report.trades if t.is_closed and t.profit > 0]
                losses = [t.profit for t in report.trades if t.is_closed and t.profit < 0]

                if wins:
                    avg_win = sum(wins) / len(wins)
                    lines.append(f"📈 Gem. winst: €{avg_win:.2f}")
                if losses:
                    avg_loss = sum(losses) / len(losses)
                    lines.append(f"📉 Gem. verlies: €{avg_loss:.2f}")

            self.bot.send_message("\n".join(lines))

        except Exception as e:
            self.logger.error(f"Error in /pnl: {e}")
            self.bot.send_message(f"❌ Error: {e}")

    def run_polling(self, poll_interval: int = 1):
        """
        Run command handler with polling

        Args:
            poll_interval: Seconds between polls (when no updates)
        """
        self.logger.info("🤖 Starting Telegram command handler (polling mode)")
        self.logger.info(f"📱 Listening for commands in chat {self.bot.chat_id}")

        try:
            while True:
                updates = self.get_updates(timeout=10)

                for update in updates:
                    update_id = update.get("update_id")
                    if update_id > self.last_update_id:
                        self.last_update_id = update_id
                        self.process_update(update)

                # Small sleep to avoid busy waiting
                if not updates:
                    time.sleep(poll_interval)

        except KeyboardInterrupt:
            self.logger.info("🛑 Telegram command handler stopped by user")
        except Exception as e:
            self.logger.error(f"Error in polling loop: {e}")
            raise


def main():
    """Main entry point for command handler"""
    import argparse

    parser = argparse.ArgumentParser(description="Telegram Bot Command Handler")
    parser.add_argument(
        "--token",
        type=str,
        default=MonitoringConfig.TELEGRAM_BOT_TOKEN,
        help="Telegram bot token"
    )
    parser.add_argument(
        "--chat-id",
        type=str,
        default=MonitoringConfig.TELEGRAM_CHAT_ID,
        help="Telegram chat ID"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to SQLite database (default: auto)"
    )
    parser.add_argument(
        "--log-path",
        type=str,
        default=MonitoringConfig.LOG_FILE,
        help="Path to bot log file for analysis"
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=1,
        help="Poll interval in seconds (default: 1)"
    )

    args = parser.parse_args()

    if not args.token or not args.chat_id:
        print("❌ Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        return

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    print("=" * 50)
    print("🤖 TELEGRAM BOT COMMAND HANDLER")
    print("=" * 50)
    print(f"📱 Chat ID: {args.chat_id}")
    print(f"📁 Log file: {args.log_path}")
    print("")
    print("📋 Available commands:")
    print("  /vertel  - Full analysis report")
    print("  /quick   - Quick status")
    print("  /trades  - Recent trades")
    print("  /trends  - Top trends")
    print("  /pnl     - P&L overview")
    print("  /help    - All commands")
    print("")
    print("🚀 Starting polling...")
    print("=" * 50)

    # Initialize database and bot
    db = MonitoringDatabase(db_path=args.db_path)
    bot = TelegramBot(args.token, args.chat_id, db)

    # Initialize command handler with log path
    handler = TelegramBotHandler(bot, log_path=args.log_path)

    # Run polling
    handler.run_polling(poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()
