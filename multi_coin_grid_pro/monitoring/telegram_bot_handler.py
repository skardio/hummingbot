"""
Telegram Bot Command Handler

Listens for incoming Telegram messages and handles commands.
Runs as a separate service that polls Telegram for new messages.
"""

import logging
import time
from typing import Any, Dict

import requests

from .config import MonitoringConfig
from .database import MonitoringDatabase
from .telegram_bot import TelegramBot


class TelegramBotHandler:
    """Handles incoming Telegram commands via polling"""

    def __init__(self, bot: TelegramBot):
        """
        Initialize command handler

        Args:
            bot: TelegramBot instance
        """
        self.bot = bot
        self.base_url = bot.base_url
        self.logger = logging.getLogger(__name__)
        self.last_update_id = 0

        # Command handlers
        self.commands = {
            "/start": self._handle_start,
            "/status": self._handle_status,
            "/events": self._handle_events,
            "/help": self._handle_help,
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
🤖 <b>Bot Monitoring System</b>

Available commands:
/status - Get current bot status
/events - Get recent events
/help - Show this help message

The bot will automatically alert you for:
🛑 Stop-loss triggers
⚡ Circuit breaker activations
❌ Errors
🔄 Coin switches
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
📋 <b>Available Commands:</b>

/status - Get current bot status
  Shows: active coin, P&L, exposure, mode, latency

/events [N] - Get recent events
  Example: /events 10
  Default: 5 events

/help - Show this help message

<b>Automatic Alerts:</b>
The bot automatically sends alerts for:
🛑 Stop-loss triggers
⚡ Circuit breaker activations
❌ Critical errors
🔄 Coin switches (with valid coin)
"""
        self.bot.send_message(help_text)

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

    # Initialize database and bot
    db = MonitoringDatabase(db_path=args.db_path)
    bot = TelegramBot(args.token, args.chat_id, db)

    # Initialize command handler
    handler = TelegramBotHandler(bot)

    # Run polling
    handler.run_polling(poll_interval=args.poll_interval)


if __name__ == "__main__":
    main()
