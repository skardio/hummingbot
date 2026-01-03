"""
SQLite Cooldown Persistence Store.

Provides restart-safe cooldown storage for parabolic detector and other
blacklist systems. Cooldowns persist across bot restarts and crashes.

Part of EPIC v3.4 - Story 10: Cooldown Persistence
"""

import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple


class CooldownStore:
    """
    SQLite-based cooldown persistence with automatic cleanup.

    Stores symbol cooldowns with expiry timestamps, allowing them to survive
    bot restarts. Includes automatic cleanup of expired cooldowns and
    shadow mode safety (no writes in shadow mode).

    Thread-safe for single-bot usage (not multi-process safe).
    """

    DEFAULT_DB_PATH = "data/cooldowns.db"

    def __init__(self, db_path: Optional[str] = None, logger: Optional[logging.Logger] = None):
        """
        Initialize cooldown store.

        Args:
            db_path: Path to SQLite database file (creates if not exists)
            logger: Optional logger instance (creates default if None)
        """
        self.db_path = db_path or self.DEFAULT_DB_PATH
        self.logger = logger or logging.getLogger(__name__)

        # Ensure directory exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        # Connect and create table
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Enable dict-like access
        self._create_table()

        self.logger.info(f"Initialized cooldown store at {self.db_path}")

    def _create_table(self):
        """Create cooldowns table if not exists."""
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS symbol_cooldowns (
                    connector TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    PRIMARY KEY (connector, symbol)
                )
            """)

            # Index for efficient cleanup queries
            self.conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at
                ON symbol_cooldowns(expires_at)
            """)

    def set_cooldown(
        self,
        connector: str,
        symbol: str,
        reason: str,
        cooldown_sec: int,
        shadow_mode: bool = False
    ) -> bool:
        """
        Add or update cooldown (upsert).

        Args:
            connector: Exchange connector name ("kraken", "bitget")
            symbol: Trading pair symbol
            reason: Reason for cooldown (e.g., "PARABOLIC_DETECTED")
            cooldown_sec: Cooldown duration in seconds
            shadow_mode: If True, skip database write (shadow mode safety)

        Returns:
            True if cooldown was set, False if shadow mode skip
        """
        if shadow_mode:
            self.logger.info(
                f"[SHADOW] Would persist cooldown for {symbol} ({cooldown_sec}s) - "
                f"reason: {reason}"
            )
            return False

        now = int(time.time())
        expires_at = now + cooldown_sec

        try:
            with self.conn:
                self.conn.execute("""
                    INSERT INTO symbol_cooldowns (connector, symbol, reason, expires_at, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(connector, symbol) DO UPDATE SET
                        reason = excluded.reason,
                        expires_at = excluded.expires_at,
                        created_at = excluded.created_at
                """, (connector, symbol, reason, expires_at, now))

            self.logger.info(
                f"Persisted cooldown: {connector}:{symbol} expires at "
                f"{datetime.fromtimestamp(expires_at).strftime('%Y-%m-%d %H:%M:%S')} "
                f"({cooldown_sec}s) - reason: {reason}"
            )
            return True

        except sqlite3.Error as e:
            self.logger.error(f"Failed to persist cooldown for {symbol}: {e}")
            return False

    def get_remaining(self, connector: str, symbol: str) -> Optional[int]:
        """
        Get remaining cooldown time in seconds.

        Args:
            connector: Exchange connector name
            symbol: Trading pair symbol

        Returns:
            Remaining seconds if on cooldown, None if not on cooldown or expired
        """
        now = int(time.time())

        try:
            cursor = self.conn.execute("""
                SELECT expires_at FROM symbol_cooldowns
                WHERE connector = ? AND symbol = ? AND expires_at > ?
            """, (connector, symbol, now))

            row = cursor.fetchone()
            if row:
                remaining = row["expires_at"] - now
                return max(0, remaining)

            return None

        except sqlite3.Error as e:
            self.logger.error(f"Failed to get cooldown for {symbol}: {e}")
            return None

    def is_on_cooldown(self, connector: str, symbol: str) -> Tuple[bool, Optional[int]]:
        """
        Check if symbol is on cooldown.

        Args:
            connector: Exchange connector name
            symbol: Trading pair symbol

        Returns:
            Tuple of (is_blocked, remaining_seconds)
        """
        remaining = self.get_remaining(connector, symbol)
        if remaining is not None and remaining > 0:
            return True, remaining
        return False, None

    def cleanup_expired(self) -> int:
        """
        Remove expired cooldowns from database.

        Returns:
            Number of cooldowns deleted
        """
        now = int(time.time())

        try:
            with self.conn:
                cursor = self.conn.execute("""
                    DELETE FROM symbol_cooldowns
                    WHERE expires_at <= ?
                """, (now,))
                deleted = cursor.rowcount

            if deleted > 0:
                self.logger.debug(f"Cleaned up {deleted} expired cooldowns")

            return deleted

        except sqlite3.Error as e:
            self.logger.error(f"Failed to cleanup expired cooldowns: {e}")
            return 0

    def load_active(self, connector: Optional[str] = None) -> Dict[str, float]:
        """
        Load all active cooldowns on startup.

        Args:
            connector: Optional connector filter (loads all if None)

        Returns:
            Dict mapping symbol to expiry timestamp
        """
        now = int(time.time())

        try:
            if connector:
                cursor = self.conn.execute("""
                    SELECT symbol, expires_at FROM symbol_cooldowns
                    WHERE connector = ? AND expires_at > ?
                """, (connector, now))
            else:
                cursor = self.conn.execute("""
                    SELECT symbol, expires_at FROM symbol_cooldowns
                    WHERE expires_at > ?
                """, (now,))

            cooldowns = {row["symbol"]: row["expires_at"] for row in cursor.fetchall()}

            if cooldowns:
                self.logger.info(f"Loaded {len(cooldowns)} active cooldowns from persistence")
                for symbol, expires_at in cooldowns.items():
                    remaining = expires_at - now
                    expiry_time = datetime.fromtimestamp(expires_at).strftime('%Y-%m-%d %H:%M:%S')
                    self.logger.info(f"  - {symbol}: {remaining}s remaining (expires {expiry_time})")

            return cooldowns

        except sqlite3.Error as e:
            self.logger.error(f"Failed to load active cooldowns: {e}")
            return {}

    def get_all_cooldowns(self, connector: Optional[str] = None) -> List[Dict]:
        """
        Get all cooldowns (active and expired) for debugging.

        Args:
            connector: Optional connector filter

        Returns:
            List of cooldown dicts with all fields
        """
        try:
            if connector:
                cursor = self.conn.execute("""
                    SELECT * FROM symbol_cooldowns
                    WHERE connector = ?
                    ORDER BY expires_at DESC
                """, (connector,))
            else:
                cursor = self.conn.execute("""
                    SELECT * FROM symbol_cooldowns
                    ORDER BY expires_at DESC
                """)

            return [dict(row) for row in cursor.fetchall()]

        except sqlite3.Error as e:
            self.logger.error(f"Failed to get all cooldowns: {e}")
            return []

    def clear_all(self, connector: Optional[str] = None) -> int:
        """
        Clear all cooldowns (for testing/debugging).

        Args:
            connector: Optional connector filter (clears all if None)

        Returns:
            Number of cooldowns deleted
        """
        try:
            with self.conn:
                if connector:
                    cursor = self.conn.execute("""
                        DELETE FROM symbol_cooldowns WHERE connector = ?
                    """, (connector,))
                else:
                    cursor = self.conn.execute("DELETE FROM symbol_cooldowns")

                deleted = cursor.rowcount

            self.logger.info(f"Cleared {deleted} cooldowns")
            return deleted

        except sqlite3.Error as e:
            self.logger.error(f"Failed to clear cooldowns: {e}")
            return 0

    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.logger.info("Closed cooldown store connection")

    def __del__(self):
        """Cleanup on destruction."""
        try:
            self.close()
        except Exception:
            pass
