"""Non-blocking, per-bot SQLite telemetry for trading decisions.

The trading path only performs ``Queue.put_nowait``.  Schema creation,
retention and all SQLite I/O happen on a daemon worker.  Telemetry failures are
therefore observable but can never block or reject an order.
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

EVENT_TYPES = frozenset({
    "BUY_DECISION_ALLOW",
    "BUY_DECISION_BLOCK",
    "BUY_ORDER_SUBMITTED",
    "BUY_ORDER_PARTIAL_FILL",
    "BUY_ORDER_FILLED",
    "BUY_ORDER_CANCEL_REQUESTED",
    "BUY_ORDER_CANCEL_CONFIRMED",
    "BUY_ORDER_CANCEL_FAILED",
    "BUY_CAP_REACHED",
    "EXECUTOR_EXIT",
})


@dataclass(frozen=True)
class DecisionTelemetryEvent:
    event_type: str
    event_timestamp: float
    exchange: str
    strategy: str
    executor_id: str
    trading_pair: str
    event_id: str = ""
    bot_instance_id: Optional[str] = None
    reason_code: Optional[str] = None
    order_id: Optional[str] = None
    side: Optional[str] = None
    order_state: Optional[str] = None
    config_version: Optional[str] = None
    configured_cap: Optional[int] = None
    executed_order_count: Optional[int] = None
    open_order_count: Optional[int] = None
    reserved_order_count: Optional[int] = None
    fill_count: Optional[int] = None
    average_entry_price: Optional[float] = None
    current_price: Optional[float] = None
    position_size_base: Optional[float] = None
    position_size_quote: Optional[float] = None
    unrealized_pnl_quote: Optional[float] = None
    distance_to_stop_pct: Optional[float] = None
    grid_score: Optional[float] = None
    trend_score: Optional[float] = None
    regime: Optional[str] = None
    regime_status: Optional[str] = None

    def normalized(self) -> "DecisionTelemetryEvent":
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"Unsupported decision telemetry event: {self.event_type}")
        return DecisionTelemetryEvent(
            **{**asdict(self), "event_id": self.event_id or str(uuid.uuid4())}
        )


class DecisionTelemetryWriter:
    """Best-effort asynchronous SQLite writer with bounded memory use."""

    _STOP = object()

    def __init__(
        self,
        db_path: str,
        queue_size: int = 1000,
        retention_days: int = 90,
        busy_timeout_ms: int = 1000,
    ):
        self.db_path = Path(db_path)
        self.retention_days = max(1, int(retention_days))
        self.busy_timeout_ms = max(100, int(busy_timeout_ms))
        self._queue: queue.Queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self._lock = threading.Lock()
        self._stats: Dict[str, int] = {
            "enqueued": 0,
            "written": 0,
            "dropped": 0,
            "write_failures": 0,
        }
        self._closed = False
        self._logger = logging.getLogger(__name__)
        self._worker = threading.Thread(
            target=self._run,
            name=f"decision-telemetry-{self.db_path.stem}",
            daemon=True,
        )
        self._worker.start()

    def emit(self, event: DecisionTelemetryEvent) -> bool:
        """Enqueue without waiting. Returns False if disabled/full/invalid."""
        if self._closed:
            return False
        try:
            normalized = event.normalized()
            self._queue.put_nowait(normalized)
            self._increment("enqueued")
            return True
        except queue.Full:
            self._increment("dropped")
            return False
        except Exception as exc:
            self._increment("dropped")
            self._logger.debug("Decision telemetry event rejected (non-fatal): %s", exc)
            return False

    @property
    def stats(self) -> Dict[str, int]:
        with self._lock:
            values = dict(self._stats)
        values["queued"] = self._queue.qsize()
        return values

    def flush(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        while self._queue.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)
        return self._queue.unfinished_tasks == 0

    def close(self, timeout: float = 5.0) -> None:
        if self._closed:
            return
        self.flush(timeout)
        self._closed = True
        try:
            self._queue.put_nowait(self._STOP)
        except queue.Full:
            pass
        self._worker.join(timeout=max(0.0, timeout))

    def _increment(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._stats[key] += amount

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=self.busy_timeout_ms / 1000)
        conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        self._create_schema(conn)
        return conn

    @staticmethod
    def _create_schema(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS DecisionTelemetryEvent (
                event_id TEXT PRIMARY KEY,
                event_timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                exchange TEXT NOT NULL,
                strategy TEXT NOT NULL,
                bot_instance_id TEXT,
                executor_id TEXT NOT NULL,
                trading_pair TEXT NOT NULL,
                reason_code TEXT,
                order_id TEXT,
                side TEXT,
                order_state TEXT,
                config_version TEXT,
                configured_cap INTEGER,
                executed_order_count INTEGER,
                open_order_count INTEGER,
                reserved_order_count INTEGER,
                fill_count INTEGER,
                average_entry_price REAL,
                current_price REAL,
                position_size_base REAL,
                position_size_quote REAL,
                unrealized_pnl_quote REAL,
                distance_to_stop_pct REAL,
                grid_score REAL,
                trend_score REAL,
                regime TEXT,
                regime_status TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_decision_executor_time
                ON DecisionTelemetryEvent(executor_id, event_timestamp);
            CREATE INDEX IF NOT EXISTS idx_decision_type_time
                ON DecisionTelemetryEvent(event_type, event_timestamp);
            CREATE INDEX IF NOT EXISTS idx_decision_pair_time
                ON DecisionTelemetryEvent(trading_pair, event_timestamp);
            CREATE TABLE IF NOT EXISTS DecisionTelemetryHealth (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                updated_at REAL NOT NULL,
                enqueued INTEGER NOT NULL,
                written INTEGER NOT NULL,
                dropped INTEGER NOT NULL,
                write_failures INTEGER NOT NULL
            );
            """
        )
        conn.commit()

    def _run(self) -> None:
        conn: Optional[sqlite3.Connection] = None
        last_retention = 0.0
        while True:
            item = self._queue.get()
            try:
                if item is self._STOP:
                    return
                if conn is None:
                    conn = self._connect()
                self._write_event(conn, item)
                self._increment("written")
                now = time.time()
                if now - last_retention >= 86400:
                    cutoff = now - self.retention_days * 86400
                    conn.execute("DELETE FROM DecisionTelemetryEvent WHERE event_timestamp < ?", (cutoff,))
                    last_retention = now
                self._write_health(conn, now)
                conn.commit()
            except Exception as exc:
                self._increment("write_failures")
                self._logger.warning("Decision telemetry write failed (trading unaffected): %s", exc)
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = None
            finally:
                self._queue.task_done()
        # pragma: no cover - loop exits through return

    @staticmethod
    def _write_event(conn: sqlite3.Connection, event: DecisionTelemetryEvent) -> None:
        data = asdict(event)
        columns = tuple(data.keys())
        placeholders = ",".join("?" for _ in columns)
        conn.execute(
            f"INSERT OR IGNORE INTO DecisionTelemetryEvent ({','.join(columns)}) VALUES ({placeholders})",
            tuple(data[column] for column in columns),
        )

    def _write_health(self, conn: sqlite3.Connection, now: float) -> None:
        stats = self.stats
        conn.execute(
            """INSERT INTO DecisionTelemetryHealth
               (singleton_id, updated_at, enqueued, written, dropped, write_failures)
               VALUES (1, ?, ?, ?, ?, ?)
               ON CONFLICT(singleton_id) DO UPDATE SET
                 updated_at=excluded.updated_at, enqueued=excluded.enqueued,
                 written=excluded.written, dropped=excluded.dropped,
                 write_failures=excluded.write_failures""",
            (now, stats["enqueued"], stats["written"], stats["dropped"], stats["write_failures"]),
        )


_writers: Dict[str, DecisionTelemetryWriter] = {}
_writers_lock = threading.Lock()


def get_decision_telemetry_writer(
    db_path: str,
    queue_size: int = 1000,
    retention_days: int = 90,
) -> DecisionTelemetryWriter:
    """Return one writer per resolved database path within this process."""
    key = str(Path(db_path).resolve())
    with _writers_lock:
        writer = _writers.get(key)
        if writer is None:
            writer = DecisionTelemetryWriter(key, queue_size, retention_days)
            _writers[key] = writer
        return writer
