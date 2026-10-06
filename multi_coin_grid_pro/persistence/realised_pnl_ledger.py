"""Durable, idempotent claim ledger for realised executor PnL.

The kill switch, the drawdown tracker and the phantom-loss correction must each
see a closed executor's realised PnL **exactly once**: never zero times (the
FIX-002 defect) and never twice (double counting).

This store provides the atomic claim that makes that guarantee. A claim is taken
on the executor id, which is stable across restarts, so a second attempt - in
the same tick, a later tick, or after a restart - is refused.

Follows the established pattern of ``cooldown_store`` and ``entry_price_store``.
"""
from __future__ import annotations

import logging
import sqlite3
import time
from decimal import Decimal
from pathlib import Path
from typing import Optional

DEFAULT_DB_PATH = "data/realised_pnl_ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS realised_pnl_processed (
    executor_id     TEXT PRIMARY KEY,
    controller_id   TEXT,
    trading_pair    TEXT,
    close_timestamp INTEGER,
    realised_pnl    TEXT,
    processed_at    INTEGER
)
"""

_INDEX = """
CREATE INDEX IF NOT EXISTS idx_realised_pnl_close_ts
    ON realised_pnl_processed (close_timestamp)
"""


class RealisedPnlLedger:
    """Records which executors have had their realised PnL propagated."""

    def __init__(self, db_path: Optional[str] = None, logger: Optional[logging.Logger] = None):
        self.db_path = str(db_path or DEFAULT_DB_PATH)
        self.logger = logger or logging.getLogger(__name__)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        parent = Path(self.db_path).parent
        if str(parent) and not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _ensure_schema(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute(_SCHEMA)
                connection.execute(_INDEX)
        except sqlite3.Error as exc:
            self.logger.error(f"RealisedPnlLedger: schema init failed for {self.db_path}: {exc}")
            raise

    def claim(
        self,
        executor_id: str,
        *,
        controller_id: Optional[str] = None,
        trading_pair: Optional[str] = None,
        close_timestamp: Optional[int] = None,
        realised_pnl: Optional[Decimal] = None,
    ) -> bool:
        """Atomically claim an executor for realised-PnL processing.

        Returns True only for the first caller, ever. Any later caller gets
        False, including after a process restart.

        On a database error this returns **False** - fail closed. Skipping a
        PnL update is recoverable; double counting a loss into the kill switch
        is not.
        """
        if not executor_id:
            return False
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "INSERT OR IGNORE INTO realised_pnl_processed "
                    "(executor_id, controller_id, trading_pair, close_timestamp, realised_pnl, processed_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        str(executor_id),
                        str(controller_id) if controller_id else None,
                        str(trading_pair) if trading_pair else None,
                        int(close_timestamp) if close_timestamp else None,
                        str(realised_pnl) if realised_pnl is not None else None,
                        int(time.time()),
                    ),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as exc:
            self.logger.error(
                f"RealisedPnlLedger: claim failed for {executor_id}: {exc} - skipping to avoid double counting"
            )
            return False

    def is_processed(self, executor_id: str) -> bool:
        """True when this executor has already been claimed."""
        if not executor_id:
            return False
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT 1 FROM realised_pnl_processed WHERE executor_id = ?",
                    (str(executor_id),),
                ).fetchone()
                return row is not None
        except sqlite3.Error as exc:
            self.logger.error(f"RealisedPnlLedger: lookup failed for {executor_id}: {exc}")
            return False

    def count(self) -> int:
        """Number of executors recorded. Diagnostics only."""
        try:
            with self._connect() as connection:
                row = connection.execute("SELECT COUNT(*) FROM realised_pnl_processed").fetchone()
                return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0
