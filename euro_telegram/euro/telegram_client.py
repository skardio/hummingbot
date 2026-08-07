from __future__ import annotations

import logging
from typing import Any

import requests

LOGGER = logging.getLogger(__name__)


class TelegramConfigError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, bot_token: str | None, chat_id: str | None, timeout_seconds: int = 20) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds

    def send_message(self, text: str) -> None:
        if not self.chat_id:
            raise TelegramConfigError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env"
            )
        self.send_message_to(self.chat_id, text)

    def send_message_to(self, chat_id: str | int, text: str) -> None:
        if not self.bot_token:
            raise TelegramConfigError("TELEGRAM_BOT_TOKEN must be set in .env")

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": True,
        }
        try:
            response = requests.post(url, json=payload, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise RuntimeError(f"Telegram sendMessage request failed: {exc.__class__.__name__}") from None
        try:
            response.raise_for_status()
        except requests.HTTPError:
            raise RuntimeError(f"Telegram sendMessage failed: {response.text}") from None
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API returned non-ok response: {result}")
        LOGGER.info("Telegram message sent to chat_id=%s", chat_id)

    def get_updates(self, offset: int | None = None, timeout_seconds: int = 30) -> list[dict[str, Any]]:
        if not self.bot_token:
            raise TelegramConfigError("TELEGRAM_BOT_TOKEN must be set in .env")

        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        payload: dict[str, Any] = {
            "timeout": timeout_seconds,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=timeout_seconds + self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Telegram getUpdates request failed: {exc.__class__.__name__}") from None
        try:
            response.raise_for_status()
        except requests.HTTPError:
            raise RuntimeError(f"Telegram getUpdates failed: {response.text}") from None

        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API returned non-ok response: {result}")
        return result["result"]

    def delete_webhook(self, drop_pending_updates: bool = False) -> None:
        if not self.bot_token:
            raise TelegramConfigError("TELEGRAM_BOT_TOKEN must be set in .env")

        url = f"https://api.telegram.org/bot{self.bot_token}/deleteWebhook"
        payload = {"drop_pending_updates": drop_pending_updates}
        try:
            response = requests.post(url, json=payload, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise RuntimeError(f"Telegram deleteWebhook request failed: {exc.__class__.__name__}") from None
        try:
            response.raise_for_status()
        except requests.HTTPError:
            raise RuntimeError(f"Telegram deleteWebhook failed: {response.text}") from None

        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API returned non-ok response: {result}")

    def check_connection(self) -> dict:
        if not self.bot_token:
            raise TelegramConfigError("TELEGRAM_BOT_TOKEN must be set in .env")

        url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
        try:
            response = requests.get(url, timeout=self.timeout_seconds)
        except requests.RequestException as exc:
            raise RuntimeError(f"Telegram getMe request failed: {exc.__class__.__name__}") from None
        try:
            response.raise_for_status()
        except requests.HTTPError:
            raise RuntimeError(f"Telegram getMe failed: {response.text}") from None

        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API returned non-ok response: {result}")
        return result["result"]
