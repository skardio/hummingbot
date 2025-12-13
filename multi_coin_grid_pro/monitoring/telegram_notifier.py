# integrations/telegram_notifier.py

import logging
from typing import Optional

import requests

from multi_coin_grid_pro.core.risk_scanner import RiskResult, TradeStatus

LOGGER = logging.getLogger("monitor.telegram")


class TelegramNotifier:
    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        notify_on_status_change: bool = True,
        notify_on_do_not_trade: bool = True,
    ):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.notify_on_status_change = notify_on_status_change
        self.notify_on_do_not_trade = notify_on_do_not_trade
        self._last_status: Optional[TradeStatus] = None

    def _send_message(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            try:
                resp.raise_for_status()
            except Exception:
                # Log HTTP-level failures with response body
                LOGGER.error(
                    "Telegram send failed (http=%s): %s",
                    resp.status_code if resp is not None else "?",
                    (resp.text[:1000] if resp is not None else ""),
                )
                return

            # Check Telegram API-level result
            try:
                data = resp.json()
            except Exception:
                LOGGER.error("Telegram response is not JSON: %s", resp.text)
                return

            if not data.get("ok"):
                LOGGER.error("Telegram API returned error: %s", data)
            else:
                LOGGER.debug("Telegram message sent successfully: %s", data)
        except Exception:
            LOGGER.exception("Failed to send Telegram message")

    def handle_risk_result(self, result: RiskResult) -> None:
        status = result.status

        # Build the message(s) and send via _send_message.
        msg = self.format_risk_message(result)
        if msg:
            self._send_message(msg)
            # Update last status according to what was sent
            self._last_status = status

    def format_risk_message(self, result: RiskResult) -> Optional[str]:
        """Return the message text that would be sent for a given RiskResult.

        This is useful for logging/preview without performing network I/O.
        """
        status = result.status

        # Always on DO_NOT_TRADE if enabled
        if self.notify_on_do_not_trade and status == TradeStatus.DO_NOT_TRADE:
            return (
                "⛔ *DO NOT TRADE*\n"
                f"Score: {result.score}/100\n"
                f"{result.explanation}"
            )

        # Only on status change
        if (
            self.notify_on_status_change
            and self._last_status is not None
            and status != self._last_status
        ):
            emoji = {
                TradeStatus.TRADE: "✅",
                TradeStatus.TRADE_WITH_CAUTION: "⚠️",
                TradeStatus.DO_NOT_TRADE: "⛔",
            }[status]

            return (
                f"{emoji} Risk status changed to: *{status.value}*\n"
                f"Score: {result.score}/100"
            )

        return None
