"""
Telegram Alerter v2.0

Sends critical notifications via Telegram bot:
- Kill switch activations
- Large losses/gains
- Position entries/exits
- System errors

Setup:
1. Create bot with @BotFather
2. Get bot token
3. Get chat_id (send message to bot, check https://api.telegram.org/bot<TOKEN>/getUpdates)
4. Add to config:
   telegram:
     bot_token: "123456:ABC-DEF..."
     chat_id: "123456789"
"""
import logging
from typing import Optional

import requests


class TelegramAlerter:
    """
    Send Telegram notifications for critical events

    Usage:
        alerter = TelegramAlerter(bot_token="...", chat_id="...")
        alerter.critical("Kill switch activated!")
        alerter.info("New grid started for BTC-EUR")
    """

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Telegram alerter

        Args:
            bot_token: Telegram bot token from @BotFather
            chat_id: Chat ID to send messages to
            logger: Optional logger instance
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.logger = logger or logging.getLogger(__name__)
        self.enabled = bool(bot_token and chat_id)

        if self.enabled:
            self.logger.info("=" * 80)
            self.logger.info("📱 TelegramAlerter v2.0 initialized")
            self.logger.info(f"   Bot token: {bot_token[:10]}...")
            self.logger.info(f"   Chat ID: {chat_id}")
            self.logger.info("=" * 80)
            # Send test message
            self._send("✅ Telegram alerts activated - Hybrid Grid Bot v2.0")
        else:
            self.logger.warning("⚠️  TelegramAlerter disabled (no bot_token or chat_id)")

    def _send(self, text: str) -> bool:
        """
        Send message to Telegram

        Args:
            text: Message text

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            response = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                },
                timeout=5
            )

            if response.status_code == 200:
                self.logger.debug(f"📱 Telegram sent: {text[:50]}...")
                return True
            else:
                self.logger.warning(f"⚠️  Telegram send failed: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            self.logger.error(f"❌ Telegram error: {e}")
            return False

    def critical(self, msg: str):
        """
        Send critical alert (🚨 emoji)

        Args:
            msg: Alert message
        """
        self._send(f"🚨 <b>CRITICAL</b>: {msg}")

    def warning(self, msg: str):
        """
        Send warning (⚠️ emoji)

        Args:
            msg: Warning message
        """
        self._send(f"⚠️ <b>WARNING</b>: {msg}")

    def info(self, msg: str):
        """
        Send info message (✅ emoji)

        Args:
            msg: Info message
        """
        self._send(f"✅ {msg}")

    def trade(self, msg: str):
        """
        Send trade notification (💰 emoji)

        Args:
            msg: Trade message
        """
        self._send(f"💰 <b>TRADE</b>: {msg}")

    def pnl_update(self, equity: float, daily_pct: float, realized: float, unrealized: float):
        """
        Send P&L summary

        Args:
            equity: Total equity
            daily_pct: Daily P&L percentage
            realized: Realized P&L
            unrealized: Unrealized P&L
        """
        emoji = "📈" if daily_pct >= 0 else "📉"
        msg = (
            f"{emoji} <b>P&L Update</b>\n"
            f"Equity: €{equity:.2f}\n"
            f"Daily: {daily_pct:+.2f}%\n"
            f"Realized: €{realized:+.2f}\n"
            f"Unrealized: €{unrealized:+.2f}"
        )
        self._send(msg)
