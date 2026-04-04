"""
SQLite Entry Price Persistence Store (T1-K4).

Stores per-symbol entry prices so they survive bot restarts.
Without this, the pro exit system (stop-loss, emergency exit, etc.)
cannot function after a restart because entry prices are lost.

Part of T1: Kill Switch & Critical Safety
"""

import logging
import os
import sqlite3
import time
from decimal import Decimal
from typing import Dict, Optional


class EntryPriceStore:
    """
    SQLite-backed entry price persistence.

    Stores {symbol: (entry_price, entry_timestamp)} so that after a
    restart the bot knows at what price each open position was entered.

    Thread-safe for single-bot usage (not multi-process safe).
    """

    DEFAULT_DB_PATH = "data/entry_prices.db"

    def __init__(
        self,
        db_path: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.db_path = db_path or self.DEFAULT_DB_PATH
        self.logger = logger or logging.getLogger(__name__)

        os.makedirs(os.path.dirname(self.db_path) or ".", exist_ok=True)

        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")  # T2-O3 forward-compat
        self.conn.row_factory = sqlite3.Row
        self._create_table()

        self.logger.info(f"EntryPriceStore initialized at {self.db_path}")

    def _create_table(self):
        """Create entry_prices table if not exists."""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS entry_prices (
                    symbol      TEXT PRIMARY KEY,
                    price       TEXT NOT NULL,
                    timestamp   REAL NOT NULL,
                    executor_id TEXT DEFAULT '',
                    updated_at  REAL NOT NULL
                )
            """)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save(
        self,
        symbol: str,
        price: Decimal,
        executor_id: str = "",
        timestamp: Optional[float] = None,
    ) -> None:
        """
        Upsert entry price for a symbol.

        Args:
            symbol: Trading pair (e.g. 'RENDER-USD')
            price: Entry price as Decimal
            executor_id: Optional executor ID for traceability
            timestamp: Entry timestamp (defaults to now)
        """
        now = timestamp or time.time()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO entry_prices (symbol, price, timestamp, executor_id, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    price = excluded.price,
                    timestamp = excluded.timestamp,
                    executor_id = excluded.executor_id,
                    updated_at = excluded.updated_at
                """,
                (symbol, str(price), now, executor_id, now),
            )

    def delete(self, symbol: str) -> bool:
        """
        Remove entry price for a symbol.

        Returns:
            True if a row was deleted, False if symbol was not found.
        """
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM entry_prices WHERE symbol = ?",
                (symbol,),
            )
            return cursor.rowcount > 0

    def clear_all(self) -> int:
        """Remove all entry prices. Returns number of rows deleted."""
        with self.conn:
            cursor = self.conn.execute("DELETE FROM entry_prices")
            return cursor.rowcount

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def load_all(self) -> Dict[str, Decimal]:
        """
        Load all persisted entry prices.

        Returns:
            Dict mapping symbol -> entry_price (Decimal)
        """
        rows = self.conn.execute(
            "SELECT symbol, price FROM entry_prices"
        ).fetchall()
        return {row["symbol"]: Decimal(row["price"]) for row in rows}

    def get(self, symbol: str) -> Optional[Decimal]:
        """Get entry price for a single symbol, or None."""
        row = self.conn.execute(
            "SELECT price FROM entry_prices WHERE symbol = ?",
            (symbol,),
        ).fetchone()
        return Decimal(row["price"]) if row else None

    def count(self) -> int:
        """Return number of stored entry prices."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM entry_prices").fetchone()
        return row["cnt"]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()
