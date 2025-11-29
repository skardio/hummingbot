# integrations/telegram_notifier.py

from typing import Optional

import requests

from multi_coin_grid_pro.core.risk_scanner import RiskResult, TradeStatus


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
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            # hier kun je logging gebruiken ipv print
            print(f"[TelegramNotifier] Failed to send message: {e}")

    def handle_risk_result(self, result: RiskResult) -> None:
        status = result.status

        # Altijd bij DO_NOT_TRADE als enabled
        if self.notify_on_do_not_trade and status == TradeStatus.DO_NOT_TRADE:
            self._send_message(
                "⛔ *DO NOT TRADE*\n"
                f"Score: {result.score}/100\n"
                f"{result.explanation}"
            )
            self._last_status = status
            return

        # Alleen bij status change
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

            self._send_message(
                f"{emoji} Risk status changed to: *{status.value}*\n"
                f"Score: {result.score}/100"
            )

        self._last_status = status
