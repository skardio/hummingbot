# momentum_signal_store.py — persistent storage for momentum signals.
# SignalStore: own SQLite DB (never the grid DBs).
# JsonSnapshotWriter: atomic JSON snapshot via os.replace.
import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional

from multi_coin_grid_pro.signals.momentum_models import MomentumSignal, ScanResult

# ---------------------------------------------------------------------------
# Guard: these filenames are exclusively grid-bot databases — never write here.
# ---------------------------------------------------------------------------

_GRID_DB_NAMES = frozenset([
    "multi_coin_grid_v2.sqlite",
    "multi_coin_grid_v2_usd.sqlite",
    "spot_grid_bitget.sqlite",
    "spot_grid_okx.sqlite",
])

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id       TEXT    NOT NULL,
    timestamp     REAL    NOT NULL,
    exchange      TEXT    NOT NULL,
    trading_pair  TEXT    NOT NULL,
    price         REAL    NOT NULL,
    spread_pct    REAL,
    price_change_1m_pct  REAL,
    price_change_3m_pct   REAL,
    price_change_5m_pct   REAL,
    price_change_15m_pct  REAL,
    volume_ratio  REAL,
    acceleration_score    REAL,
    slippage_100eur       REAL,
    slippage_250eur       REAL,
    signal_label          TEXT,
    entry_min             REAL,
    entry_max             REAL,
    max_chase_price       REAL,
    invalidation_price    REAL,
    take_profit_1         REAL,
    take_profit_2         REAL,
    score         REAL    NOT NULL,
    accepted      INTEGER NOT NULL,   -- BOOLEAN 0/1
    rank          INTEGER,
    rejection_reason TEXT,
    all_reasons   TEXT,               -- JSON array
    score_breakdown TEXT,             -- JSON object
    preselection_score    REAL,
    preselection_rank     INTEGER,
    preselection_bucket   TEXT,
    preselection_breakdown TEXT,      -- JSON object
    config_version_id     INTEGER,
    market_regime_at_signal REAL,     -- gem. δ15m van alle verrijkte paren deze scan
    market_breadth_15m    REAL,       -- % verrijkte paren met positieve δ15m
    btc_15m_change_pct    REAL,       -- BTC δ15m (NULL als niet in scan)
    eth_15m_change_pct    REAL,       -- ETH δ15m (NULL als niet in scan)
    created_at    REAL    NOT NULL
)
"""

_CREATE_CONFIG_VERSIONS_SQL = """
CREATE TABLE IF NOT EXISTS config_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  REAL    NOT NULL,   -- epoch when service started with this config
    config_hash TEXT    NOT NULL,   -- sha256 of key params (dedup)
    params_json TEXT    NOT NULL    -- full key params as JSON for analysis
)
"""

_CREATE_OUTCOMES_SQL = """
CREATE TABLE IF NOT EXISTS signal_outcomes (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id            INTEGER NOT NULL,
    entry_price          REAL    NOT NULL,
    max_price_1m         REAL,
    max_price_3m         REAL,
    max_price_5m         REAL,
    max_price_10m        REAL,
    max_price_30m        REAL,
    min_price_1m         REAL,
    min_price_3m         REAL,
    min_price_5m         REAL,
    min_price_10m        REAL,
    min_price_30m        REAL,
    hit_tp1              INTEGER DEFAULT 0,
    hit_tp2              INTEGER DEFAULT 0,
    hit_stop             INTEGER DEFAULT 0,
    best_exit_pct        REAL,
    worst_drawdown_pct   REAL,
    evaluated_at         REAL,
    first_hit            TEXT,
    tp1_hit_at_seconds   REAL,
    tp2_hit_at_seconds   REAL,
    stop_hit_at_seconds  REAL,
    time_to_first_hit_minutes REAL,   -- minuten van signaal tot first_hit (NULL bij TIMEOUT)
    entry_zone_reached   INTEGER,     -- 1 als prijs entry_max raakte, 0 als niet, NULL bij WATCH
    FOREIGN KEY (signal_id) REFERENCES signals(id)
)
"""

_INSERT_SQL = """
INSERT INTO signals (
    scan_id, timestamp, exchange, trading_pair, price, spread_pct,
    price_change_1m_pct, price_change_3m_pct, price_change_5m_pct, price_change_15m_pct, volume_ratio,
    acceleration_score, slippage_100eur, slippage_250eur, signal_label,
    entry_min, entry_max, max_chase_price, invalidation_price, take_profit_1, take_profit_2,
    score, accepted, rank, rejection_reason, all_reasons,
    score_breakdown, preselection_score, preselection_rank, preselection_bucket,
    preselection_breakdown, config_version_id,
    market_regime_at_signal, market_breadth_15m, btc_15m_change_pct, eth_15m_change_pct,
    created_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


class SignalStore:
    """Persist :class:`MomentumSignal` objects in a dedicated SQLite database.

    Raises ``ValueError`` on construction if *db_path* points to a known
    grid-bot database filename — those files must never be written by this
    service.
    """

    def __init__(self, db_path: str) -> None:
        basename = Path(db_path).name
        if basename in _GRID_DB_NAMES:
            raise ValueError(
                f"db_path '{db_path}' refers to a grid-bot database ({basename}). "
                "SignalStore requires a dedicated database such as "
                "'data/momentum_signals.sqlite'."
            )
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_CREATE_TABLE_SQL)
        self._conn.execute(_CREATE_OUTCOMES_SQL)
        self._conn.execute(_CREATE_CONFIG_VERSIONS_SQL)
        # Migrations: add columns to existing databases.
        _migrations = [
            "ALTER TABLE signals ADD COLUMN price_change_1m_pct REAL",
            "ALTER TABLE signals ADD COLUMN price_change_3m_pct REAL",
            "ALTER TABLE signals ADD COLUMN acceleration_score REAL",
            "ALTER TABLE signals ADD COLUMN slippage_100eur REAL",
            "ALTER TABLE signals ADD COLUMN slippage_250eur REAL",
            "ALTER TABLE signals ADD COLUMN signal_label TEXT",
            "ALTER TABLE signals ADD COLUMN entry_min REAL",
            "ALTER TABLE signals ADD COLUMN entry_max REAL",
            "ALTER TABLE signals ADD COLUMN max_chase_price REAL",
            "ALTER TABLE signals ADD COLUMN invalidation_price REAL",
            "ALTER TABLE signals ADD COLUMN take_profit_1 REAL",
            "ALTER TABLE signals ADD COLUMN take_profit_2 REAL",
            "ALTER TABLE signals ADD COLUMN preselection_score REAL",
            "ALTER TABLE signals ADD COLUMN preselection_rank INTEGER",
            "ALTER TABLE signals ADD COLUMN preselection_bucket TEXT",
            "ALTER TABLE signals ADD COLUMN preselection_breakdown TEXT",
            "ALTER TABLE signal_outcomes ADD COLUMN first_hit TEXT",
            "ALTER TABLE signal_outcomes ADD COLUMN tp1_hit_at_seconds REAL",
            "ALTER TABLE signal_outcomes ADD COLUMN tp2_hit_at_seconds REAL",
            "ALTER TABLE signal_outcomes ADD COLUMN stop_hit_at_seconds REAL",
            "ALTER TABLE signals ADD COLUMN config_version_id INTEGER",
            "ALTER TABLE signals ADD COLUMN market_regime_at_signal REAL",
            "ALTER TABLE signals ADD COLUMN market_breadth_15m REAL",
            "ALTER TABLE signals ADD COLUMN btc_15m_change_pct REAL",
            "ALTER TABLE signals ADD COLUMN eth_15m_change_pct REAL",
            "ALTER TABLE signal_outcomes ADD COLUMN time_to_first_hit_minutes REAL",
            "ALTER TABLE signal_outcomes ADD COLUMN entry_zone_reached INTEGER",
        ]
        for stmt in _migrations:
            try:
                self._conn.execute(stmt)
            except sqlite3.OperationalError:
                pass  # column already exists
        self._conn.commit()

    def get_or_create_config_version(self, params: Dict) -> int:
        """Return existing config_version id if params unchanged, else insert new row.

        *params* should be a flat dict of the key filter/scoring parameters
        (e.g. min_volume_ratio, min_price_change_1m_pct, …).  A sha256 hash
        of the sorted JSON representation is used for dedup so that identical
        configs across restarts reuse the same version row.
        """
        params_json = json.dumps(params, sort_keys=True)
        config_hash = hashlib.sha256(params_json.encode()).hexdigest()[:16]
        row = self._conn.execute(
            "SELECT id FROM config_versions WHERE config_hash = ?",
            (config_hash,),
        ).fetchone()
        if row:
            return int(row[0])
        cursor = self._conn.execute(
            "INSERT INTO config_versions (started_at, config_hash, params_json) VALUES (?,?,?)",
            (time.time(), config_hash, params_json),
        )
        self._conn.commit()
        return int(cursor.lastrowid)

    def save(self, signal: MomentumSignal) -> int:
        """Insert *signal* and return the new row id. Sets ``signal.id``."""
        cursor = self._conn.execute(
            _INSERT_SQL,
            (
                signal.scan_id,
                signal.timestamp,
                signal.exchange,
                signal.trading_pair,
                signal.price,
                signal.spread_pct,
                signal.price_change_1m_pct,
                signal.price_change_3m_pct,
                signal.price_change_5m_pct,
                signal.price_change_15m_pct,
                signal.volume_ratio,
                signal.acceleration_score,
                signal.slippage_100eur,
                signal.slippage_250eur,
                signal.signal_label,
                signal.entry_min,
                signal.entry_max,
                signal.max_chase_price,
                signal.invalidation_price,
                signal.take_profit_1,
                signal.take_profit_2,
                signal.score,
                1 if signal.accepted else 0,
                signal.rank,
                signal.rejection_reason,
                json.dumps(signal.all_reasons),
                json.dumps(signal.score_breakdown),
                signal.preselection_score,
                signal.preselection_rank,
                signal.preselection_bucket,
                json.dumps(signal.preselection_breakdown, sort_keys=True) if signal.preselection_breakdown else None,
                signal.config_version_id,
                signal.market_regime_at_signal,
                signal.market_breadth_15m,
                signal.btc_15m_change_pct,
                signal.eth_15m_change_pct,
                time.time(),
            ),
        )
        self._conn.commit()
        row_id: int = cursor.lastrowid
        signal.id = row_id
        return row_id

    def save_batch(self, signals: List[MomentumSignal]) -> List[int]:
        """Insert a list of signals in one transaction. Returns list of ids."""
        ids: List[int] = []
        with self._conn:
            for signal in signals:
                cursor = self._conn.execute(
                    _INSERT_SQL,
                    (
                        signal.scan_id,
                        signal.timestamp,
                        signal.exchange,
                        signal.trading_pair,
                        signal.price,
                        signal.spread_pct,
                        signal.price_change_1m_pct,
                        signal.price_change_3m_pct,
                        signal.price_change_5m_pct,
                        signal.price_change_15m_pct,
                        signal.volume_ratio,
                        signal.acceleration_score,
                        signal.slippage_100eur,
                        signal.slippage_250eur,
                        signal.signal_label,
                        signal.entry_min,
                        signal.entry_max,
                        signal.max_chase_price,
                        signal.invalidation_price,
                        signal.take_profit_1,
                        signal.take_profit_2,
                        signal.score,
                        1 if signal.accepted else 0,
                        signal.rank,
                        signal.rejection_reason,
                        json.dumps(signal.all_reasons),
                        json.dumps(signal.score_breakdown),
                        signal.preselection_score,
                        signal.preselection_rank,
                        signal.preselection_bucket,
                        json.dumps(signal.preselection_breakdown, sort_keys=True) if signal.preselection_breakdown else None,
                        signal.config_version_id,
                        signal.market_regime_at_signal,
                        signal.market_breadth_15m,
                        signal.btc_15m_change_pct,
                        signal.eth_15m_change_pct,
                        time.time(),
                    ),
                )
                row_id = cursor.lastrowid
                signal.id = row_id
                ids.append(row_id)
        return ids

    def purge_old(self, retention_days: int) -> int:
        """Delete records older than *retention_days*. Returns deleted count."""
        cutoff = time.time() - retention_days * 86_400
        cursor = self._conn.execute(
            "DELETE FROM signals WHERE created_at < ?", (cutoff,)
        )
        self._conn.commit()
        return cursor.rowcount

    def load_recent(self, limit: int = 100) -> List[Dict]:
        """Return the most recent *limit* rows as plain dicts."""
        cursor = self._conn.execute(
            "SELECT id, scan_id, timestamp, exchange, trading_pair, price, "
            "spread_pct, price_change_3m_pct, price_change_5m_pct, price_change_15m_pct, "
            "volume_ratio, acceleration_score, slippage_100eur, slippage_250eur, "
            "signal_label, score, accepted, rank, rejection_reason, "
            "all_reasons, score_breakdown, created_at "
            "FROM signals ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def count(self) -> int:
        """Return total number of stored signals."""
        row = self._conn.execute("SELECT COUNT(*) FROM signals").fetchone()
        return row[0]

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


# ---------------------------------------------------------------------------
# JSON snapshot writer
# ---------------------------------------------------------------------------

def _signal_to_dict(signal: MomentumSignal) -> dict:
    return {
        "id": signal.id,
        "scan_id": signal.scan_id,
        "timestamp": signal.timestamp,
        "exchange": signal.exchange,
        "trading_pair": signal.trading_pair,
        "price": signal.price,
        "spread_pct": signal.spread_pct,
        "price_change_5m_pct": signal.price_change_5m_pct,
        "price_change_15m_pct": signal.price_change_15m_pct,
        "volume_ratio": signal.volume_ratio,
        "score": signal.score,
        "accepted": signal.accepted,
        "rank": signal.rank,
        "rejection_reason": signal.rejection_reason,
        "all_reasons": signal.all_reasons,
        "score_breakdown": signal.score_breakdown,
    }


class JsonSnapshotWriter:
    """Atomically write a :class:`ScanResult` to a JSON file.

    Uses ``os.replace`` so the reader never sees a half-written file.
    """

    def __init__(self, snapshot_path: str) -> None:
        self._path = snapshot_path

    def write(self, scan_result: ScanResult, disclaimer: Optional[str] = None) -> None:
        """Write *scan_result* to the snapshot path atomically."""
        data: Dict = {
            "disclaimer": disclaimer or "SIGNAL ONLY — GEEN ORDERS WORDEN GEPLAATST",
            "scan_id": scan_result.scan_id,
            "timestamp": scan_result.timestamp,
            "scan_duration_seconds": scan_result.scan_duration_seconds,
            "total_scanned": scan_result.total_scanned,
            "total_accepted": scan_result.total_accepted,
            "total_rejected": scan_result.total_rejected,
            "rejection_breakdown": scan_result.rejection_breakdown,
            "top_signals": [_signal_to_dict(s) for s in scan_result.top_signals],
        }
        tmp = self._path + ".tmp"
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, self._path)
