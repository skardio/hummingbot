"""
Fill-risk telemetry persistence (FASE 1B shadow-mode).

Records one row per BUY fill event, IN ADDITION TO (not instead of) the
[FILL_RISK_LOG] structured log line emitted by grid_executor.py. Purely
observational: never read by any entry/exit decision path.

Shared by all 4 spot bots (Bitget/OKX/Kraken USD/Kraken EUR) via a single
db file (data/fill_risk_snapshots.db) so they can be compared later without
reading logs. Same store pattern as trade_label_store.py/cooldown_store.py:
thread-safe SQLite, WAL mode, fail-safe writes (never disrupt trading).
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from typing import List, Optional

log = logging.getLogger(__name__)


@dataclass
class FillRiskSnapshot:
    """One BUY-fill snapshot. Unique on (executor_id, fill_number)."""

    executor_id: str
    exchange: str
    quote_currency: str
    bot_instance_id: str
    trading_pair: str
    fill_number: int
    timestamp: float
    fill_price: float
    fill_amount_base: float
    fill_amount_quote: float
    avg_entry_price: float
    position_size_quote: float
    unrealized_pnl_quote: float
    unrealized_drawdown_pct: float
    current_price: float
    entry_atr_pct: float
    entry_trend_score: Optional[float]
    effective_stop_pct: float
    risk_state: str
    id: Optional[int] = None


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS FillRiskSnapshot (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    executor_id             TEXT    NOT NULL,
    exchange                TEXT    NOT NULL,
    quote_currency          TEXT    NOT NULL,
    bot_instance_id         TEXT    NOT NULL,
    trading_pair            TEXT    NOT NULL,
    fill_number             INTEGER NOT NULL,
    timestamp               REAL    NOT NULL,
    fill_price              REAL    NOT NULL DEFAULT 0,
    fill_amount_base        REAL    NOT NULL DEFAULT 0,
    fill_amount_quote       REAL    NOT NULL DEFAULT 0,
    avg_entry_price         REAL    NOT NULL DEFAULT 0,
    position_size_quote     REAL    NOT NULL DEFAULT 0,
    unrealized_pnl_quote    REAL    NOT NULL DEFAULT 0,
    unrealized_drawdown_pct REAL    NOT NULL DEFAULT 0,
    current_price           REAL    NOT NULL DEFAULT 0,
    entry_atr_pct           REAL    NOT NULL DEFAULT 0,
    entry_trend_score       REAL,
    effective_stop_pct      REAL    NOT NULL DEFAULT 0,
    risk_state              TEXT    NOT NULL DEFAULT 'NONE',
    UNIQUE(executor_id, fill_number)
)
"""

_CREATE_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_fill_risk_bot_ts "
    "ON FillRiskSnapshot (bot_instance_id, timestamp)"
)

_COLUMNS = (
    "id, executor_id, exchange, quote_currency, bot_instance_id, trading_pair, "
    "fill_number, timestamp, fill_price, fill_amount_base, fill_amount_quote, "
    "avg_entry_price, position_size_quote, unrealized_pnl_quote, unrealized_drawdown_pct, "
    "current_price, entry_atr_pct, entry_trend_score, effective_stop_pct, risk_state"
)


@dataclass
class PostFillRiskSnapshot:
    """One periodic risk sample taken AFTER an executor reaches the soft-risk
    fill threshold (default fill 5), up to and including one final sample at
    close. Separate table from FillRiskSnapshot so fill-events and periodic
    risk-samples never mix."""

    executor_id: str
    exchange: str
    quote_currency: str
    bot_instance_id: str
    trading_pair: str
    timestamp: float
    buy_fill_count: int
    avg_entry_price: float
    current_price: float
    unrealized_pnl_pct: float
    position_size_quote: float
    effective_stop_pct: float
    shadow_stop_mild: float
    shadow_stop_medium: float
    shadow_stop_strong: float
    is_final: bool
    id: Optional[int] = None


_CREATE_POST_FILL_SQL = """
CREATE TABLE IF NOT EXISTS PostFillRiskSnapshot (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    executor_id             TEXT    NOT NULL,
    exchange                TEXT    NOT NULL,
    quote_currency          TEXT    NOT NULL,
    bot_instance_id         TEXT    NOT NULL,
    trading_pair            TEXT    NOT NULL,
    timestamp               REAL    NOT NULL,
    buy_fill_count          INTEGER NOT NULL,
    avg_entry_price         REAL    NOT NULL DEFAULT 0,
    current_price           REAL    NOT NULL DEFAULT 0,
    unrealized_pnl_pct      REAL    NOT NULL DEFAULT 0,
    position_size_quote     REAL    NOT NULL DEFAULT 0,
    effective_stop_pct      REAL    NOT NULL DEFAULT 0,
    shadow_stop_mild        REAL    NOT NULL DEFAULT 0,
    shadow_stop_medium      REAL    NOT NULL DEFAULT 0,
    shadow_stop_strong      REAL    NOT NULL DEFAULT 0,
    is_final                INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_POST_FILL_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_post_fill_risk_executor_ts "
    "ON PostFillRiskSnapshot (executor_id, timestamp)"
)

_POST_FILL_COLUMNS = (
    "id, executor_id, exchange, quote_currency, bot_instance_id, trading_pair, timestamp, "
    "buy_fill_count, avg_entry_price, current_price, unrealized_pnl_pct, position_size_quote, "
    "effective_stop_pct, shadow_stop_mild, shadow_stop_medium, shadow_stop_strong, is_final"
)


class FillRiskSnapshotStore:
    """
    Thread-safe SQLite store for fill-risk telemetry snapshots.

    All writes are fail-safe: errors are logged but never propagated
    to the caller so trading is never disrupted.
    """

    def __init__(self, db_path: str = "data/fill_risk_snapshots.db"):
        self._lock = threading.Lock()
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        try:
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_SQL)
            self._conn.execute(_CREATE_INDEX_SQL)
            self._conn.execute(_CREATE_POST_FILL_SQL)
            self._conn.execute(_CREATE_POST_FILL_INDEX_SQL)
            self._conn.commit()
            log.info("FillRiskSnapshotStore initialised at %s", db_path)
        except Exception as exc:
            log.error("FillRiskSnapshotStore init failed: %s", exc)
            self._conn = None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, snap: FillRiskSnapshot) -> None:
        """Persist one fill-risk snapshot. Dedup on (executor_id, fill_number)
        via INSERT OR IGNORE. Silently swallows errors to protect trading."""
        if self._conn is None:
            return
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT OR IGNORE INTO FillRiskSnapshot
                       (executor_id, exchange, quote_currency, bot_instance_id, trading_pair,
                        fill_number, timestamp, fill_price, fill_amount_base, fill_amount_quote,
                        avg_entry_price, position_size_quote, unrealized_pnl_quote,
                        unrealized_drawdown_pct, current_price, entry_atr_pct, entry_trend_score,
                        effective_stop_pct, risk_state)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        snap.executor_id, snap.exchange, snap.quote_currency, snap.bot_instance_id,
                        snap.trading_pair, snap.fill_number, snap.timestamp, snap.fill_price,
                        snap.fill_amount_base, snap.fill_amount_quote, snap.avg_entry_price,
                        snap.position_size_quote, snap.unrealized_pnl_quote,
                        snap.unrealized_drawdown_pct, snap.current_price, snap.entry_atr_pct,
                        snap.entry_trend_score, snap.effective_stop_pct, snap.risk_state,
                    ),
                )
                self._conn.commit()
        except Exception as exc:
            log.error(
                "FillRiskSnapshotStore.record failed for executor=%s fill=%s: %s",
                snap.executor_id, snap.fill_number, exc,
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query_recent(self, days: int = 30, bot_instance_id: Optional[str] = None) -> List[FillRiskSnapshot]:
        """Return snapshots from the last N days, newest first. Optionally
        filter by bot_instance_id (e.g. to compare bots side by side)."""
        if self._conn is None:
            return []
        import time as _time
        cutoff = _time.time() - days * 86400
        try:
            with self._lock:
                if bot_instance_id:
                    cur = self._conn.execute(
                        f"SELECT {_COLUMNS} FROM FillRiskSnapshot "
                        "WHERE timestamp >= ? AND bot_instance_id = ? ORDER BY timestamp DESC",
                        (cutoff, bot_instance_id),
                    )
                else:
                    cur = self._conn.execute(
                        f"SELECT {_COLUMNS} FROM FillRiskSnapshot "
                        "WHERE timestamp >= ? ORDER BY timestamp DESC",
                        (cutoff,),
                    )
                rows = cur.fetchall()
            return [self._row_to_snapshot(r) for r in rows]
        except Exception as exc:
            log.error("FillRiskSnapshotStore.query_recent failed: %s", exc)
            return []

    @staticmethod
    def _row_to_snapshot(row) -> FillRiskSnapshot:
        return FillRiskSnapshot(
            id=row[0], executor_id=row[1], exchange=row[2], quote_currency=row[3],
            bot_instance_id=row[4], trading_pair=row[5], fill_number=row[6], timestamp=row[7],
            fill_price=row[8], fill_amount_base=row[9], fill_amount_quote=row[10],
            avg_entry_price=row[11], position_size_quote=row[12], unrealized_pnl_quote=row[13],
            unrealized_drawdown_pct=row[14], current_price=row[15], entry_atr_pct=row[16],
            entry_trend_score=row[17], effective_stop_pct=row[18], risk_state=row[19],
        )

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # PostFillRiskSnapshot (periodic post-fill-5 samples) - same connection/lock
    # ------------------------------------------------------------------

    def record_post_fill(self, snap: PostFillRiskSnapshot) -> None:
        """Persist one periodic post-fill-5 risk sample. No dedup key - each
        call is a distinct time-sampled row. Silently swallows errors."""
        if self._conn is None:
            return
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO PostFillRiskSnapshot
                       (executor_id, exchange, quote_currency, bot_instance_id, trading_pair,
                        timestamp, buy_fill_count, avg_entry_price, current_price,
                        unrealized_pnl_pct, position_size_quote, effective_stop_pct,
                        shadow_stop_mild, shadow_stop_medium, shadow_stop_strong, is_final)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        snap.executor_id, snap.exchange, snap.quote_currency, snap.bot_instance_id,
                        snap.trading_pair, snap.timestamp, snap.buy_fill_count, snap.avg_entry_price,
                        snap.current_price, snap.unrealized_pnl_pct, snap.position_size_quote,
                        snap.effective_stop_pct, snap.shadow_stop_mild, snap.shadow_stop_medium,
                        snap.shadow_stop_strong, int(snap.is_final),
                    ),
                )
                self._conn.commit()
        except Exception as exc:
            log.error(
                "FillRiskSnapshotStore.record_post_fill failed for executor=%s: %s",
                snap.executor_id, exc,
            )

    def query_post_fill_recent(self, days: int = 30, executor_id: Optional[str] = None) -> List[PostFillRiskSnapshot]:
        """Return post-fill-5 samples from the last N days, oldest first (natural
        order for MAE/MFE-style time-series analysis). Optionally filter by executor_id."""
        if self._conn is None:
            return []
        import time as _time
        cutoff = _time.time() - days * 86400
        try:
            with self._lock:
                if executor_id:
                    cur = self._conn.execute(
                        f"SELECT {_POST_FILL_COLUMNS} FROM PostFillRiskSnapshot "
                        "WHERE timestamp >= ? AND executor_id = ? ORDER BY timestamp ASC",
                        (cutoff, executor_id),
                    )
                else:
                    cur = self._conn.execute(
                        f"SELECT {_POST_FILL_COLUMNS} FROM PostFillRiskSnapshot "
                        "WHERE timestamp >= ? ORDER BY timestamp ASC",
                        (cutoff,),
                    )
                rows = cur.fetchall()
            return [self._row_to_post_fill_snapshot(r) for r in rows]
        except Exception as exc:
            log.error("FillRiskSnapshotStore.query_post_fill_recent failed: %s", exc)
            return []

    @staticmethod
    def _row_to_post_fill_snapshot(row) -> PostFillRiskSnapshot:
        return PostFillRiskSnapshot(
            id=row[0], executor_id=row[1], exchange=row[2], quote_currency=row[3],
            bot_instance_id=row[4], trading_pair=row[5], timestamp=row[6],
            buy_fill_count=row[7], avg_entry_price=row[8], current_price=row[9],
            unrealized_pnl_pct=row[10], position_size_quote=row[11],
            effective_stop_pct=row[12], shadow_stop_mild=row[13],
            shadow_stop_medium=row[14], shadow_stop_strong=row[15], is_final=bool(row[16]),
        )
