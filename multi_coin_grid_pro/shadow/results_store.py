"""Isolated SQLite persistence for the A/B shadow sandbox.

Writes exclusively to ``data/shadow_ab_results.db`` (configurable path for
tests) — never touches ``data/multi_coin_grid_v2_usd.sqlite`` or
``data/realised_pnl_ledger_usd.db``, which remain the live bot's exclusive
files.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from multi_coin_grid_pro.shadow.virtual_grid_position import VirtualExitReason, VirtualGridPosition

SCHEMA = """
CREATE TABLE IF NOT EXISTS shadow_selections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    variant TEXT NOT NULL,
    symbol TEXT NOT NULL,
    rank INTEGER,
    trend_pct REAL,
    grid_score REAL
);

CREATE TABLE IF NOT EXISTS shadow_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    variant TEXT NOT NULL,
    symbol TEXT NOT NULL,
    created_at REAL NOT NULL,
    entry_time REAL,
    entry_price TEXT,
    exit_time REAL,
    exit_price TEXT,
    exit_reason TEXT,
    notional_quote TEXT,
    gross_pnl_quote TEXT,
    fees_quote TEXT,
    net_pnl_quote TEXT,
    annotated_fee_quote_at_empirical_rate TEXT,
    annotated_net_pnl_quote_at_empirical_rate TEXT,
    status TEXT NOT NULL
);
"""


class ShadowResultsStore:
    """Thin, dependency-free SQLite writer. Safe to construct repeatedly;
    schema creation is idempotent (CREATE TABLE IF NOT EXISTS)."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record_selection(
        self, ts: float, variant: str, symbol: str, rank: Optional[int],
        trend_pct: Optional[float], grid_score: Optional[float],
    ) -> None:
        self._conn.execute(
            "INSERT INTO shadow_selections (ts, variant, symbol, rank, trend_pct, grid_score) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, variant, symbol, rank, trend_pct, grid_score),
        )
        self._conn.commit()

    def record_position_open(self, variant: str, position: VirtualGridPosition) -> int:
        cur = self._conn.execute(
            "INSERT INTO shadow_positions "
            "(variant, symbol, created_at, entry_time, entry_price, notional_quote, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'OPEN')",
            (
                variant, position.symbol, position.created_at,
                position.entry_time, str(position.entry_price), str(position.notional_quote),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def record_position_close(self, row_id: int, position: VirtualGridPosition) -> None:
        self._conn.execute(
            "UPDATE shadow_positions SET exit_time=?, exit_price=?, exit_reason=?, "
            "gross_pnl_quote=?, fees_quote=?, net_pnl_quote=?, "
            "annotated_fee_quote_at_empirical_rate=?, annotated_net_pnl_quote_at_empirical_rate=?, "
            "status='CLOSED' WHERE id=?",
            (
                position.exit_time, str(position.exit_price),
                position.exit_reason.value if isinstance(position.exit_reason, VirtualExitReason) else position.exit_reason,
                str(position.gross_pnl_quote), str(position.fees_quote), str(position.net_pnl_quote),
                str(position.annotated_fee_quote_at_empirical_rate),
                str(position.annotated_net_pnl_quote_at_empirical_rate), row_id,
            ),
        )
        self._conn.commit()

    def fetch_closed_positions(self, variant: Optional[str] = None):
        q = "SELECT * FROM shadow_positions WHERE status='CLOSED'"
        params = ()
        if variant:
            q += " AND variant=?"
            params = (variant,)
        return self._conn.execute(q, params).fetchall()

    def mark_all_open_as_orphaned(self) -> int:
        """Safety-first restart handling: a row still `status='OPEN'` after a
        process restart belonged to an in-memory portfolio that no longer
        exists (virtual positions are not persisted with enough fields to
        safely reconstruct a ticking position — see
        ABShadowRunner.handle_restart_orphans()). Mark it with an explicit,
        queryable terminal status rather than silently resuming it (risk of
        wrong future exits with stale/guessed thresholds) or silently
        dropping it (risk of looking like it never happened).

        Returns the number of rows marked."""
        cur = self._conn.execute(
            "UPDATE shadow_positions SET status='ORPHANED_ON_RESTART' WHERE status='OPEN'"
        )
        self._conn.commit()
        return cur.rowcount
