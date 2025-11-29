"""
Telegram Bot for Bot Monitoring Alerts

Sends alerts for important events and handles commands.
"""

import logging
from typing import Optional

import requests

from .config import MonitoringConfig
from .database import MonitoringDatabase


class TelegramBot:
    """Telegram bot for alerts and commands"""

    def __init__(self, bot_token: str, chat_id: str, db: MonitoringDatabase):
        """
        Initialize Telegram bot

        Args:
            bot_token: Telegram bot token
            chat_id: Chat ID to send messages to
            db: MonitoringDatabase instance
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.db = db
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.logger = logging.getLogger(__name__)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Send a message to Telegram

        Args:
            text: Message text
            parse_mode: Parse mode (HTML or Markdown)

        Returns:
            True if successful, False otherwise
        """
        if not self.bot_token or not self.chat_id:
            self.logger.warning("Telegram bot not configured - skipping message")
            return False

        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode
            }

            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        except Exception as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False

    def send_alert(self, event_type: str, message: str, coin: Optional[str] = None):
        """
        Send an alert for an important event

        Args:
            event_type: Type of event
            message: Event message
            coin: Coin symbol (optional)
        """
        emoji_map = {
            "stop_loss": "🛑",
            "circuit_breaker": "⚡",
            "error": "❌",
            "api_error": "⚠️",
            "trend_switch": "🔄",
            "executor_created": "✅",
            "executor_stopped": "⏹️",
        }

        emoji = emoji_map.get(event_type, "📢")
        coin_text = f"<b>{coin}</b>: " if coin else ""

        alert_text = f"{emoji} <b>Bot Alert</b>\n\n{coin_text}{message}"
        self.send_message(alert_text)

    def send_status(self) -> bool:
        """Send current bot status"""
        status = self.db.get_latest_status()
        if not status:
            return self.send_message("❌ No status data available")

        status_text = f"""
🤖 <b>Bot Status</b>

💰 Active Coin: <b>{status.get('active_coin', 'None')}</b>
📊 P&L: <b>€{status.get('pnl', 0):.2f}</b>
💵 Exposure: <b>€{status.get('exposure', 0):.2f}</b>
⚙️ Mode: <b>{status.get('mode', 'unknown')}</b>
⏱️ Latency: <b>{status.get('heartbeat_latency', 0):.0f}ms</b>
🔌 Connection: <b>{status.get('connection_status', 'unknown')}</b>
"""
        return self.send_message(status_text)

    def send_recent_events(self, limit: int = 5) -> bool:
        """Send recent events"""
        events = self.db.get_recent_events(limit=limit)
        if not events:
            return self.send_message("📋 No recent events")

        events_text = f"📋 <b>Recent Events</b> (last {limit})\n\n"
        for event in events:
            coin_str = f"{event.get('coin', '')}: " if event.get('coin') else ""
            msg = event.get('message', '')[:50]
            events_text += f"• <b>{event.get('event_type', 'unknown')}</b> - {coin_str}{msg}...\n"

        return self.send_message(events_text)

    def check_and_alert(self, event_type: str, message: str, coin: Optional[str] = None):
        """
        Check if event should trigger alert and send if needed

        Args:
            event_type: Type of event
            message: Event message
            coin: Coin symbol (optional)
        """
        # Always alert for critical events
        critical_events = ["stop_loss", "circuit_breaker", "error", "api_error"]

        if event_type in critical_events:
            self.send_alert(event_type, message, coin)

        # Alert for trend switches (only if coin is valid)
        if event_type == "trend_switch" and coin:
            self.send_alert(event_type, f"Switched to {coin}", coin)

        # Check P&L swings
        if event_type == "status_update":
            status = self.db.get_latest_status()
            if status:
                pnl = status.get('pnl', 0)
                if abs(pnl) > MonitoringConfig.PNL_ALERT_THRESHOLD:
                    self.send_alert(
                        "pnl_swing",
                        f"Large P&L swing detected: €{pnl:.2f}",
                        coin
                    )


def main():
    """Main entry point for Telegram bot (command handler)"""
    import argparse

    parser = argparse.ArgumentParser(description="Telegram Bot for Bot Monitoring")
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
        "command",
        nargs="?",
        choices=["status", "events"],
        help="Command to execute"
    )

    args = parser.parse_args()

    if not args.token or not args.chat_id:
        print("❌ Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        return

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Initialize database and bot
    db = MonitoringDatabase(db_path=args.db_path)
    bot = TelegramBot(args.token, args.chat_id, db)

    # Execute command
    if args.command == "status":
        bot.send_status()
    elif args.command == "events":
        bot.send_recent_events()
    else:
        print("Usage: telegram_bot.py [status|events]")
        print("Or use as library: from monitoring.telegram_bot import TelegramBot")


if __name__ == "__main__":
    main()
