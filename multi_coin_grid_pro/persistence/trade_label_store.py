"""
Trade label persistence for post-hoc analysis.

Records per-trade context (regime, session, quality, MFE/MAE) to SQLite.
Enables session edge detection, meta-ranking, and Monte Carlo simulation.

Part of the 17-upgrade trading bot roadmap:
  Item 12 — Learn from Logs Engine
"""
from __future__ import annotations

import csv
import datetime as _dt
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import List, Optional

log = logging.getLogger(__name__)


def session_from_utc(utc_ts: float) -> str:
    """Classify trade timestamp into session: Asia / EU / US / weekend."""
    dt = _dt.datetime.utcfromtimestamp(utc_ts)
    if dt.weekday() >= 5:
        return "weekend"
    hour = dt.hour
    if 0 <= hour < 8:
        return "Asia"
    if 8 <= hour < 16:
        return "EU"
    return "US"


@dataclass
class TradeLabel:
    """Full context record for a completed trade."""

    coin: str
    timestamp_open: int           # unix seconds
    timestamp_close: int          # unix seconds
    session: str                  # Asia | EU | US | weekend
    regime: str                   # e.g. BULL / BEAR / NEUTRAL
    volatility_state: str         # low | normal | high | extreme
    spread_at_entry: float
    depth_at_entry: float
    quality_score: int            # 0–100; 0 if scorer not yet active
    entry_reason: str
    exit_reason: str
    exit_type: str                # TP | SL | SMALL_LOSS | TREND | UNKNOWN
    pnl_quote: float
    mfe_pct: float                # max favorable excursion %
    mae_pct: float                # max adverse excursion %
    reentry: bool                 # True if re-entry on same coin same session
    cycle_number: int             # nth trade on this coin today
    connector: str = "kraken"
    id: Optional[int] = field(default=None)   # DB auto-increment


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS trade_labels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    coin            TEXT    NOT NULL,
    timestamp_open  INTEGER NOT NULL,
    timestamp_close INTEGER NOT NULL,
    session         TEXT    NOT NULL,
    regime          TEXT    NOT NULL DEFAULT '',
    volatility_state TEXT   NOT NULL DEFAULT 'normal',
    spread_at_entry  REAL   NOT NULL DEFAULT 0,
    depth_at_entry   REAL   NOT NULL DEFAULT 0,
    quality_score    INTEGER NOT NULL DEFAULT 0,
    entry_reason    TEXT    NOT NULL DEFAULT '',
    exit_reason     TEXT    NOT NULL DEFAULT '',
    exit_type       TEXT    NOT NULL DEFAULT 'UNKNOWN',
    pnl_quote       REAL    NOT NULL DEFAULT 0,
    mfe_pct         REAL    NOT NULL DEFAULT 0,
    mae_pct         REAL    NOT NULL DEFAULT 0,
    reentry         INTEGER NOT NULL DEFAULT 0,
    cycle_number    INTEGER NOT NULL DEFAULT 1,
    connector       TEXT    NOT NULL DEFAULT 'kraken'
)
"""


class TradeLabelStore:
    """
    Thread-safe SQLite store for trade labels.

    All writes are fail-safe: errors are logged but never propagated
    to the caller so trading is never disrupted.
    """

    def __init__(self, db_path: str = "data/trade_labels.db"):
        self._lock = threading.Lock()
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        try:
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(_CREATE_SQL)
            self._conn.commit()
            log.info("TradeLabelStore initialised at %s", db_path)
        except Exception as exc:
            log.error("TradeLabelStore init failed: %s", exc)
            self._conn = None

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def record(self, label: TradeLabel) -> None:
        """Persist a trade label. Silently swallows errors to protect trading."""
        if self._conn is None:
            return
        try:
            with self._lock:
                self._conn.execute(
                    """INSERT INTO trade_labels
                       (coin, timestamp_open, timestamp_close, session, regime,
                        volatility_state, spread_at_entry, depth_at_entry, quality_score,
                        entry_reason, exit_reason, exit_type, pnl_quote,
                        mfe_pct, mae_pct, reentry, cycle_number, connector)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        label.coin, label.timestamp_open, label.timestamp_close,
                        label.session, label.regime, label.volatility_state,
                        label.spread_at_entry, label.depth_at_entry, label.quality_score,
                        label.entry_reason, label.exit_reason, label.exit_type,
                        label.pnl_quote, label.mfe_pct, label.mae_pct,
                        int(label.reentry), label.cycle_number, label.connector,
                    ),
                )
                self._conn.commit()
        except Exception as exc:
            log.error("TradeLabelStore.record failed for %s: %s", label.coin, exc)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query_recent(self, days: int = 30) -> List[TradeLabel]:
        """Return trade labels from the last N days, newest first."""
        if self._conn is None:
            return []
        cutoff = int(_dt.datetime.utcnow().timestamp()) - days * 86400
        try:
            with self._lock:
                cur = self._conn.execute(
                    "SELECT * FROM trade_labels"
                    " WHERE timestamp_close >= ?"
                    " ORDER BY timestamp_close DESC",
                    (cutoff,),
                )
                rows = cur.fetchall()
            return [self._row_to_label(r) for r in rows]
        except Exception as exc:
            log.error("TradeLabelStore.query_recent failed: %s", exc)
            return []

    def export_csv(self, path: str) -> int:
        """Export all labels to CSV. Returns number of rows written."""
        labels = self.query_recent(days=3650)
        if not labels:
            return 0
        try:
            with open(path, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow([
                    "id", "coin", "timestamp_open", "timestamp_close", "session",
                    "regime", "volatility_state", "spread_at_entry", "depth_at_entry",
                    "quality_score", "entry_reason", "exit_reason", "exit_type",
                    "pnl_quote", "mfe_pct", "mae_pct", "reentry",
                    "cycle_number", "connector",
                ])
                for lbl in labels:
                    writer.writerow([
                        lbl.id, lbl.coin, lbl.timestamp_open, lbl.timestamp_close,
                        lbl.session, lbl.regime, lbl.volatility_state,
                        lbl.spread_at_entry, lbl.depth_at_entry, lbl.quality_score,
                        lbl.entry_reason, lbl.exit_reason, lbl.exit_type,
                        lbl.pnl_quote, lbl.mfe_pct, lbl.mae_pct,
                        int(lbl.reentry), lbl.cycle_number, lbl.connector,
                    ])
            return len(labels)
        except Exception as exc:
            log.error("TradeLabelStore.export_csv failed: %s", exc)
            return 0

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_label(row: tuple) -> TradeLabel:
        return TradeLabel(
            id=row[0],
            coin=row[1],
            timestamp_open=row[2],
            timestamp_close=row[3],
            session=row[4],
            regime=row[5],
            volatility_state=row[6],
            spread_at_entry=row[7],
            depth_at_entry=row[8],
            quality_score=row[9],
            entry_reason=row[10],
            exit_reason=row[11],
            exit_type=row[12],
            pnl_quote=row[13],
            mfe_pct=row[14],
            mae_pct=row[15],
            reentry=bool(row[16]),
            cycle_number=row[17],
            connector=row[18],
        )
