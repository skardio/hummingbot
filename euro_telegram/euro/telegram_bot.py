from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .telegram_client import TelegramClient

LOGGER = logging.getLogger(__name__)


GenerateCallback = Callable[[str | int], str]


class TelegramCommandBot:
    def __init__(
        self,
        client: TelegramClient,
        allowed_chat_id: str,
        state_path: Path,
        generate_callback: GenerateCallback,
        poll_timeout_seconds: int = 30,
        drop_pending_on_first_start: bool = True,
    ) -> None:
        self.client = client
        self.allowed_chat_id = str(allowed_chat_id)
        self.state_path = state_path
        self.generate_callback = generate_callback
        self.poll_timeout_seconds = poll_timeout_seconds
        self.drop_pending_on_first_start = drop_pending_on_first_start

    def run_forever(self) -> None:
        self.client.delete_webhook(drop_pending_updates=False)
        offset = self._load_offset()
        if offset is None and self.drop_pending_on_first_start:
            offset = self._latest_offset()
            if offset is not None:
                self._save_offset(offset)
                LOGGER.info("Dropped pending Telegram updates; starting from offset %s", offset)

        LOGGER.info("Telegram command bot started. Send /generate to chat_id=%s", self.allowed_chat_id)
        while True:
            try:
                updates = self.client.get_updates(offset=offset, timeout_seconds=self.poll_timeout_seconds)
                for update in updates:
                    offset = int(update["update_id"]) + 1
                    self._save_offset(offset)
                    self._handle_update(update)
            except KeyboardInterrupt:
                raise
            except Exception:
                LOGGER.exception("Telegram command polling failed; retrying soon")
                time.sleep(5)

    def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        text = (message.get("text") or "").strip()

        if chat_id != self.allowed_chat_id:
            LOGGER.warning("Ignoring Telegram message from unauthorized chat_id=%s", chat_id)
            return

        command = self._command_name(text)
        if command in {"/generate", "/gen", "generate"}:
            self.client.send_message_to(chat_id, "Ik genereer 10 nieuwe combinaties...")
            try:
                reply = self.generate_callback(chat_id)
            except Exception:
                LOGGER.exception("Could not generate Telegram command reply")
                self.client.send_message_to(chat_id, "Sorry, genereren lukte niet. Check de logs.")
                return
            self.client.send_message_to(chat_id, reply)
            return

        if command in {"/start", "/help", "help"}:
            self.client.send_message_to(
                chat_id,
                "Stuur /generate voor 10 nieuwe Euro-combinaties.",
            )

    @staticmethod
    def _command_name(text: str) -> str:
        if not text:
            return ""
        first = text.split()[0].strip().lower()
        return first.split("@", 1)[0]

    def _latest_offset(self) -> int | None:
        updates = self.client.get_updates(timeout_seconds=0)
        if not updates:
            return None
        return max(int(update["update_id"]) for update in updates) + 1

    def _load_offset(self) -> int | None:
        if not self.state_path.exists():
            return None
        raw = self.state_path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None

    def _save_offset(self, offset: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(str(offset), encoding="utf-8")
