"""
Market-regime telemetry (observability only, never read by any trading decision).

Two parts, shared by all spot bots:

* ``publish_regime`` / ``observe_regime``: the controller publishes its latest regime detection; executors
  read it at BUY fill, SELL fill and close time. No future information is used: a snapshot older than
  ``max_age_sec`` is reported as STALE, a snapshot stamped in the future as UNKNOWN.
* ``RegimeTelemetryStore``: SQLite store (data/regime_telemetry.db). ``RegimeBuyFill`` has one row per real
  BUY fill, ``RegimeExecutor`` one row per executor (entry, last SELL fill, exit decision, exit).
  Every write is idempotent and fail-safe: errors are logged and never propagate into trading.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1

VALID = "VALID"
UNKNOWN = "UNKNOWN"
STALE = "STALE"
NO_BUY_FILL = "NO_BUY_FILL"
EXIT_OBSERVED = "OBSERVED"
EXIT_NOT_OBSERVED_RESTART = "NOT_OBSERVED_RESTART"


@dataclass(frozen=True)
class RegimeSnapshot:
    """One published regime detection. ``regime`` is None when detection never produced a value."""

    regime: Optional[str]
    source: str
    detected_at: Optional[float]
    published_at: float
    score: Optional[float] = None
    reason: str = ""


@dataclass(frozen=True)
class RegimeObservation:
    """What an executor records at an event moment."""

    regime: str
    status: str
    source: str
    regime_timestamp: Optional[float]
    age_sec: Optional[float]
    reason: str = ""


def headline(obs: "RegimeObservation") -> tuple:
    """(regime, reason) for entry/exit fields: only a VALID observation yields a regime; the last known value
    of a STALE one stays visible in the reason, never in the regime field."""
    if obs.status == VALID:
        return obs.regime, obs.reason
    if obs.status == STALE:
        return UNKNOWN, f"stale (last known {obs.regime}): {obs.reason}"
    return UNKNOWN, obs.reason


DEFAULT_MAX_AGE_SEC = 300.0
_HISTORY_LEN = 64  # newest snapshots kept per bot so a fill is matched to the regime known at fill time

_history: Dict[str, Deque[RegimeSnapshot]] = {}
_lock = threading.Lock()


def publish_regime(bot_key: str, regime: str, source: str, detected_at: float, score: Optional[float] = None) -> None:
    with _lock:
        _history.setdefault(bot_key, deque(maxlen=_HISTORY_LEN)).append(
            RegimeSnapshot(regime, source, detected_at, detected_at, score))


def publish_regime_failure(bot_key: str, source: str, reason: str, now: float) -> None:
    """Keep the last good regime and its detection time (so it ages into STALE); remember why detection failed."""
    with _lock:
        history = _history.setdefault(bot_key, deque(maxlen=_HISTORY_LEN))
        previous = next((s for s in reversed(history) if s.regime is not None), None)
        history.append(RegimeSnapshot(
            previous.regime if previous else None, source, previous.detected_at if previous else None,
            now, previous.score if previous else None, reason))


def clear_regime(bot_key: Optional[str] = None) -> None:
    with _lock:
        if bot_key is None:
            _history.clear()
        else:
            _history.pop(bot_key, None)


def observe_regime(bot_key: str, event_time: float, max_age_sec: float = DEFAULT_MAX_AGE_SEC) -> RegimeObservation:
    """Regime known at ``event_time``: only snapshots published at or before it are eligible (no look-ahead)."""
    with _lock:
        history = list(_history.get(bot_key, ()))
    if not history:
        return RegimeObservation(UNKNOWN, UNKNOWN, "none", None, None, "no_regime_snapshot_published")
    snap = next((s for s in reversed(history) if s.published_at <= event_time), None)
    if snap is None:
        return RegimeObservation(UNKNOWN, UNKNOWN, "none", None, None, "no_regime_detected_before_event")
    if snap.regime is None or snap.detected_at is None:
        return RegimeObservation(UNKNOWN, UNKNOWN, snap.source, None, None, snap.reason or "detector_returned_no_regime")
    age = event_time - snap.detected_at
    if age > max_age_sec:
        reason = f"age {age:.0f}s > max {max_age_sec:.0f}s" + (f"; last failure: {snap.reason}" if snap.reason else "")
        return RegimeObservation(snap.regime, STALE, snap.source, snap.detected_at, age, reason)
    return RegimeObservation(snap.regime, VALID, snap.source, snap.detected_at, age, snap.reason)


_CREATE_BUY_SQL = """
CREATE TABLE IF NOT EXISTS RegimeBuyFill (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    executor_id      TEXT NOT NULL,
    exchange         TEXT NOT NULL,
    bot_instance_id  TEXT NOT NULL,
    trading_pair     TEXT NOT NULL,
    order_id         TEXT NOT NULL,
    fill_key         TEXT NOT NULL,
    buy_sequence     INTEGER NOT NULL,
    fill_timestamp   REAL NOT NULL,
    fill_price       REAL NOT NULL,
    fill_amount      REAL NOT NULL,
    regime           TEXT NOT NULL,
    regime_status    TEXT NOT NULL,
    regime_source    TEXT NOT NULL,
    regime_timestamp REAL,
    regime_age_sec   REAL,
    regime_reason    TEXT NOT NULL DEFAULT '',
    UNIQUE(executor_id, order_id, fill_key)
)
"""

_CREATE_EXECUTOR_SQL = """
CREATE TABLE IF NOT EXISTS RegimeExecutor (
    executor_id               TEXT PRIMARY KEY,
    exchange                  TEXT NOT NULL,
    bot_instance_id           TEXT NOT NULL,
    trading_pair              TEXT NOT NULL,
    entry_regime              TEXT,
    entry_regime_status       TEXT,
    entry_regime_source       TEXT,
    entry_regime_timestamp    REAL,
    entry_regime_reason       TEXT,
    entry_fill_timestamp      REAL,
    entry_order_id            TEXT,
    last_sell_fill_timestamp  REAL,
    last_sell_fill_regime     TEXT,
    last_sell_regime_status   TEXT,
    exit_decision_timestamp   REAL,
    exit_decision_regime      TEXT,
    exit_decision_status      TEXT,
    exit_decision_reason      TEXT,
    exit_state                TEXT,
    exit_timestamp            REAL,
    exit_regime               TEXT,
    exit_regime_status        TEXT,
    exit_regime_source        TEXT,
    exit_regime_timestamp     REAL,
    exit_regime_reason        TEXT,
    exit_close_type           TEXT,
    exit_close_reason         TEXT,
    exit_had_sell_fill        INTEGER,
    exit_realized_sell_quote  REAL
)
"""

_CREATE_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_regime_buy_executor ON RegimeBuyFill (executor_id, fill_timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_regime_exec_bot ON RegimeExecutor (bot_instance_id)",
)


@dataclass(frozen=True)
class ExecutorRef:
    executor_id: str
    exchange: str
    bot_instance_id: str
    trading_pair: str


class RegimeTelemetryStore:
    """Thread-safe SQLite store; every write is idempotent and swallows its own errors."""

    def __init__(self, db_path: str = "data/regime_telemetry.db"):
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        try:
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_BUY_SQL)
            self._conn.execute(_CREATE_EXECUTOR_SQL)
            for sql in _CREATE_INDEXES:
                self._conn.execute(sql)
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._conn.commit()
        except Exception as exc:
            log.error("RegimeTelemetryStore init failed: %s", exc)
            self._conn = None

    def _write(self, label: str, statements) -> bool:
        if self._conn is None:
            return False
        try:
            with self._lock:
                for sql, params in statements:
                    self._conn.execute(sql, params)
                self._conn.commit()
            return True
        except Exception as exc:
            log.error("RegimeTelemetryStore.%s failed: %s", label, exc)
            return False

    @staticmethod
    def _ensure_row(ref: ExecutorRef):
        return (
            "INSERT OR IGNORE INTO RegimeExecutor (executor_id, exchange, bot_instance_id, trading_pair) "
            "VALUES (?,?,?,?)",
            (ref.executor_id, ref.exchange, ref.bot_instance_id, ref.trading_pair),
        )

    def record_buy_fill(
        self, ref: ExecutorRef, order_id: str, fill_key: str, sequence: int, fill_timestamp: float,
        fill_price: float, fill_amount: float, obs: RegimeObservation, is_first_buy: bool,
    ) -> bool:
        statements = [
            self._ensure_row(ref),
            (
                "INSERT OR IGNORE INTO RegimeBuyFill (executor_id, exchange, bot_instance_id, trading_pair, "
                "order_id, fill_key, buy_sequence, fill_timestamp, fill_price, fill_amount, regime, "
                "regime_status, regime_source, regime_timestamp, regime_age_sec, regime_reason) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ref.executor_id, ref.exchange, ref.bot_instance_id, ref.trading_pair, order_id, fill_key,
                 sequence, fill_timestamp, fill_price, fill_amount, obs.regime, obs.status, obs.source,
                 obs.regime_timestamp, obs.age_sec, obs.reason),
            ),
        ]
        entry_regime, entry_reason = headline(obs)
        if is_first_buy:
            statements.append((
                "UPDATE RegimeExecutor SET entry_regime=?, entry_regime_status=?, entry_regime_source=?, "
                "entry_regime_timestamp=?, entry_regime_reason=?, entry_fill_timestamp=?, entry_order_id=? "
                "WHERE executor_id=? AND entry_regime IS NULL",
                (entry_regime, obs.status, obs.source, obs.regime_timestamp, entry_reason, fill_timestamp,
                 order_id, ref.executor_id),
            ))
        return self._write("record_buy_fill", statements)

    def record_sell_fill(self, ref: ExecutorRef, fill_timestamp: float, obs: RegimeObservation) -> bool:
        return self._write("record_sell_fill", [
            self._ensure_row(ref),
            (
                "UPDATE RegimeExecutor SET last_sell_fill_timestamp=?, last_sell_fill_regime=?, "
                "last_sell_regime_status=? WHERE executor_id=? "
                "AND (last_sell_fill_timestamp IS NULL OR last_sell_fill_timestamp<=?)",
                (fill_timestamp, headline(obs)[0], obs.status, ref.executor_id, fill_timestamp),
            ),
        ])

    def record_exit_decision(self, ref: ExecutorRef, timestamp: float, obs: RegimeObservation, reason: str) -> bool:
        return self._write("record_exit_decision", [
            self._ensure_row(ref),
            (
                "UPDATE RegimeExecutor SET exit_decision_timestamp=?, exit_decision_regime=?, "
                "exit_decision_status=?, exit_decision_reason=? "
                "WHERE executor_id=? AND exit_decision_timestamp IS NULL",
                (timestamp, headline(obs)[0], obs.status, reason, ref.executor_id),
            ),
        ])

    def record_exit(
        self, ref: ExecutorRef, timestamp: float, obs: RegimeObservation, close_type: str, close_reason: str,
        had_sell_fill: bool, realized_sell_quote: float,
    ) -> bool:
        return self._write("record_exit", [
            self._ensure_row(ref),
            (
                "UPDATE RegimeExecutor SET exit_state=?, exit_timestamp=?, exit_regime=?, exit_regime_status=?, "
                "exit_regime_source=?, exit_regime_timestamp=?, exit_regime_reason=?, exit_close_type=?, "
                "exit_close_reason=?, exit_had_sell_fill=?, exit_realized_sell_quote=? "
                "WHERE executor_id=? AND exit_state IS NULL",
                (EXIT_OBSERVED, timestamp, headline(obs)[0], obs.status, obs.source, obs.regime_timestamp,
                 headline(obs)[1], close_type, close_reason, int(had_sell_fill), realized_sell_quote, ref.executor_id),
            ),
            (
                "UPDATE RegimeExecutor SET entry_regime_status=? "
                "WHERE executor_id=? AND entry_regime IS NULL AND entry_regime_status IS NULL",
                (NO_BUY_FILL, ref.executor_id),
            ),
        ])

    def mark_unobserved_exits(self, bot_instance_id: str, exchange: str) -> int:
        """At controller start: executors of this bot without an observed exit lost it to a restart."""
        if self._conn is None:
            return 0
        try:
            with self._lock:
                cur = self._conn.execute(
                    "UPDATE RegimeExecutor SET exit_state=? WHERE bot_instance_id=? AND exchange=? "
                    "AND exit_state IS NULL",
                    (EXIT_NOT_OBSERVED_RESTART, bot_instance_id, exchange),
                )
                self._conn.commit()
                return cur.rowcount
        except Exception as exc:
            log.error("RegimeTelemetryStore.mark_unobserved_exits failed: %s", exc)
            return 0

    def get_executor(self, executor_id: str) -> Optional[dict]:
        if self._conn is None:
            return None
        with self._lock:
            cur = self._conn.execute("SELECT * FROM RegimeExecutor WHERE executor_id=?", (executor_id,))
            row = cur.fetchone()
            return dict(zip([c[0] for c in cur.description], row)) if row else None

    def get_buy_fills(self, executor_id: str) -> list:
        if self._conn is None:
            return []
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM RegimeBuyFill WHERE executor_id=? ORDER BY buy_sequence", (executor_id,))
            names = [c[0] for c in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]


_store_singleton = None


def get_regime_store() -> Optional[RegimeTelemetryStore]:
    """Process-wide store; None (never raises) when it cannot be opened."""
    global _store_singleton
    if _store_singleton is None:
        try:
            store = RegimeTelemetryStore()
            _store_singleton = store if store._conn is not None else False
        except Exception:
            _store_singleton = False
    return _store_singleton or None
