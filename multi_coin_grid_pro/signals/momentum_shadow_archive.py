# momentum_shadow_archive.py — permanente opslag van geëvalueerde BUY_NOW shadow-outcomes.
#
# Puur meetlaag: leest signals + signal_outcomes en schrijft een onveranderlijke
# kopie naar ``buy_now_shadow_archive`` in DEZELFDE database. Beïnvloedt geen
# signalen, geen CURRENT/WIDE-logica en geen orders.
#
# Waarom: ``SignalStore.purge_old`` verwijdert ``signals`` na 7 dagen; zonder
# archief gaan de entry-features (en dus v5-classificatie) verloren.
import json
import logging
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

ARCHIVE_SCHEMA_VERSION = 1

# Frozen v5-regels — tekstueel identiek aan track_v5_paper.V5_WHERE (test bewaakt dit).
V5_SQL = """
    s.volume_ratio < 15
    AND s.price_change_5m_pct / NULLIF(s.price_change_15m_pct, 0) < 0.75
    AND s.market_regime_at_signal >= 0
    AND s.market_breadth_15m >= 40
"""

# Cohort-definitie (frozen tijdens de meetronde; vastgelegd in archive_meta).
WIDE_TP_PCT = 1.5
FEE_ROUND_TRIP_PCT = 0.50
TIMEOUT_HORIZON_MIN = 30
# Tracker evalueert alleen signalen jonger dan 40 min (grace); daarna nooit meer.
UNEVALUATED_AFTER_SEC = 45 * 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS buy_now_shadow_archive (
    signal_id               INTEGER PRIMARY KEY,
    archive_status          TEXT    NOT NULL,   -- EVALUATED | UNEVALUATED
    archived_at             REAL    NOT NULL,
    schema_version          INTEGER NOT NULL,
    signal_ts               REAL    NOT NULL,
    exchange                TEXT    NOT NULL,
    trading_pair            TEXT    NOT NULL,
    config_version_id       INTEGER,
    signal_price            REAL,
    volume_ratio            REAL,
    price_change_5m_pct     REAL,
    price_change_15m_pct    REAL,
    d5_d15_ratio            REAL,
    market_regime_at_signal REAL,
    market_breadth_15m      REAL,
    btc_15m_change_pct      REAL,
    eth_15m_change_pct      REAL,
    v5_pass                 INTEGER NOT NULL,   -- frozen V5_SQL op moment van archiveren
    entry_price             REAL,               -- entry_ref van tracker (= entry_max)
    entry_min               REAL,
    entry_max               REAL,
    tp1_price               REAL,
    tp2_price               REAL,
    wide_tp_price           REAL,
    invalidation_price      REAL,
    exit_30m_price          REAL,
    exit_30m_pct            REAL,
    exit_30m_at_seconds     REAL,
    current_outcome         TEXT,               -- TP1 | TP2 | STOP | TIMEOUT
    wide_outcome            TEXT,               -- WIDE_TP | STOP | TIMEOUT
    p07_hit_at_seconds      REAL,
    p10_hit_at_seconds      REAL,
    tp1_hit_at_seconds      REAL,
    tp2_hit_at_seconds      REAL,
    wide_tp_hit_at_seconds  REAL,
    m10_hit_at_seconds      REAL,
    m15_hit_at_seconds      REAL,
    stop_hit_at_seconds     REAL,
    mfe_at_seconds          REAL,
    mae_at_seconds          REAL,
    best_exit_pct           REAL,               -- MFE (bruto %, t.o.v. entry_price)
    worst_drawdown_pct      REAL,               -- MAE (bruto %, t.o.v. entry_price)
    evaluated_at            REAL
);
CREATE INDEX IF NOT EXISTS idx_shadow_archive_ts ON buy_now_shadow_archive(signal_ts);
CREATE TABLE IF NOT EXISTS shadow_archive_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shadow_scan_coverage (
    hour_bucket INTEGER PRIMARY KEY,   -- floor(epoch / 3600)
    scans       INTEGER NOT NULL
);
"""

_SELECT_COLUMNS = f"""
    s.id, ?, ?, {ARCHIVE_SCHEMA_VERSION}, s.timestamp, s.exchange, s.trading_pair,
    s.config_version_id, s.price,
    s.volume_ratio, s.price_change_5m_pct, s.price_change_15m_pct,
    s.price_change_5m_pct / NULLIF(s.price_change_15m_pct, 0),
    s.market_regime_at_signal, s.market_breadth_15m,
    s.btc_15m_change_pct, s.eth_15m_change_pct,
    CASE WHEN {V5_SQL} THEN 1 ELSE 0 END,
    o.entry_price, s.entry_min, s.entry_max, s.take_profit_1, s.take_profit_2,
    s.entry_max * (1.0 + {WIDE_TP_PCT} / 100.0), s.invalidation_price,
    o.exit_30m_price, o.exit_30m_pct, o.exit_30m_at_seconds,
    o.first_hit, o.wide_first_hit,
    o.p07_hit_at_seconds, o.p10_hit_at_seconds, o.tp1_hit_at_seconds, o.tp2_hit_at_seconds,
    o.wide_tp_hit_at_seconds, o.m10_hit_at_seconds, o.m15_hit_at_seconds,
    o.stop_hit_at_seconds, o.mfe_at_seconds, o.mae_at_seconds,
    o.best_exit_pct, o.worst_drawdown_pct, o.evaluated_at
"""

_INSERT_HEAD = """
INSERT OR IGNORE INTO buy_now_shadow_archive (
    signal_id, archive_status, archived_at, schema_version, signal_ts, exchange, trading_pair,
    config_version_id, signal_price,
    volume_ratio, price_change_5m_pct, price_change_15m_pct, d5_d15_ratio,
    market_regime_at_signal, market_breadth_15m, btc_15m_change_pct, eth_15m_change_pct,
    v5_pass,
    entry_price, entry_min, entry_max, tp1_price, tp2_price, wide_tp_price, invalidation_price,
    exit_30m_price, exit_30m_pct, exit_30m_at_seconds,
    current_outcome, wide_outcome,
    p07_hit_at_seconds, p10_hit_at_seconds, tp1_hit_at_seconds, tp2_hit_at_seconds,
    wide_tp_hit_at_seconds, m10_hit_at_seconds, m15_hit_at_seconds,
    stop_hit_at_seconds, mfe_at_seconds, mae_at_seconds,
    best_exit_pct, worst_drawdown_pct, evaluated_at
)
"""

_BUY_NOW_BASE = "s.signal_label = 'BUY_NOW' AND s.accepted = 1 AND s.entry_max IS NOT NULL"


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


def archive_evaluated(conn: sqlite3.Connection, signal_id: int, now: float) -> int:
    """Archiveer één geëvalueerd BUY_NOW-signaal. Commit NIET (caller-transactie).

    Idempotent: INSERT OR IGNORE op signal_id; een bestaande archiefrij wordt nooit herschreven.
    """
    cur = conn.execute(
        _INSERT_HEAD + f"SELECT {_SELECT_COLUMNS} "
        "FROM signals s JOIN signal_outcomes o ON o.signal_id = s.id "
        f"WHERE s.id = ? AND o.evaluated_at IS NOT NULL AND {_BUY_NOW_BASE}",
        ("EVALUATED", now, signal_id),
    )
    return cur.rowcount


def backfill(conn: sqlite3.Connection, now: float) -> int:
    """Recovery-sweep: archiveer alles wat nog in ``signals`` staat maar ontbreekt.

    - geëvalueerde BUY_NOW (bv. crash tussen outcome-write en archive-write, of
      signalen geëvalueerd door oudere code) → EVALUATED
    - BUY_NOW die nooit geëvalueerd zijn en dat ook niet meer kunnen worden
      (ouder dan de tracker-grace) → UNEVALUATED, zodat datagaten permanent zichtbaar zijn.
    Commit zelf. Returns aantal nieuwe archiefrijen.
    """
    ensure_schema(conn)
    n = conn.execute(
        _INSERT_HEAD + f"SELECT {_SELECT_COLUMNS} "
        "FROM signal_outcomes o JOIN signals s ON s.id = o.signal_id "
        f"WHERE o.evaluated_at IS NOT NULL AND {_BUY_NOW_BASE} "
        "AND o.signal_id NOT IN (SELECT signal_id FROM buy_now_shadow_archive)",
        ("EVALUATED", now),
    ).rowcount
    n += conn.execute(
        _INSERT_HEAD + f"SELECT {_SELECT_COLUMNS} "
        "FROM signals s LEFT JOIN signal_outcomes o ON o.signal_id = s.id "
        f"WHERE {_BUY_NOW_BASE} AND o.evaluated_at IS NULL AND s.timestamp < ? "
        "AND s.id NOT IN (SELECT signal_id FROM buy_now_shadow_archive)",
        ("UNEVALUATED", now, now - UNEVALUATED_AFTER_SEC),
    ).rowcount
    conn.commit()
    if n:
        logger.info("[SHADOW_ARCHIVE] backfill archived %d rows", n)
    return n


def unarchived_signal_ids(conn: sqlite3.Connection, now: float) -> list:
    """BUY_NOW-signalen die definitief zijn maar nog niet in het archief staan."""
    rows = conn.execute(
        "SELECT s.id FROM signals s LEFT JOIN signal_outcomes o ON o.signal_id = s.id "
        f"WHERE {_BUY_NOW_BASE} AND (o.evaluated_at IS NOT NULL OR s.timestamp < ?) "
        "AND s.id NOT IN (SELECT signal_id FROM buy_now_shadow_archive)",
        (now - UNEVALUATED_AFTER_SEC,),
    ).fetchall()
    return [r[0] for r in rows]


def record_scan(conn: sqlite3.Connection, now: float) -> None:
    """Tel één tracker-update per uur (dekking/downtime-detectie). Commit NIET."""
    conn.execute(
        "INSERT INTO shadow_scan_coverage (hour_bucket, scans) VALUES (?, 1) "
        "ON CONFLICT(hour_bucket) DO UPDATE SET scans = scans + 1",
        (int(now // 3600),),
    )


def start_cohort_if_absent(conn: sqlite3.Connection, now: float) -> float:
    """Leg eenmalig het startmoment + frozen definitie van de schone cohort vast."""
    ensure_schema(conn)
    definition = {
        "v5_sql": " ".join(V5_SQL.split()),
        "current": {"entry": "entry_max", "tp1": "entry_max*1.012", "tp2": "entry_max*1.025",
                    "stop": "signal invalidation_price"},
        "wide": {"tp_pct": WIDE_TP_PCT, "stop": "same invalidation_price"},
        "timeout_horizon_min": TIMEOUT_HORIZON_MIN,
        "timeout_exit": "first observed price at age >= 30 min (tracker grace max 40 min)",
        "fee_round_trip_pct": FEE_ROUND_TRIP_PCT,
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
    }
    conn.execute("INSERT OR IGNORE INTO shadow_archive_meta (key, value) VALUES ('cohort_start_ts', ?)",
                 (repr(now),))
    conn.execute("INSERT OR IGNORE INTO shadow_archive_meta (key, value) VALUES ('cohort_definition', ?)",
                 (json.dumps(definition, sort_keys=True),))
    conn.commit()
    return float(conn.execute(
        "SELECT value FROM shadow_archive_meta WHERE key = 'cohort_start_ts'").fetchone()[0])


# ── Payoff-model (analyse; bruto en netto strikt gescheiden) ──────────────────

def gross_return_pct(variant: str, outcome: Optional[str], entry_price: float,
                     invalidation_price: float, exit_30m_pct: Optional[float],
                     tp1_price: Optional[float] = None,
                     tp2_price: Optional[float] = None) -> Optional[float]:
    """Bruto prijsbeweging (%) bij exit. Geen fees. None = niet waardeerbaar.

    STOP = echte invalidation_price-afstand; TIMEOUT = T+30 exit, nooit MFE.
    """
    if outcome == "STOP":
        return (invalidation_price / entry_price - 1.0) * 100.0
    if outcome == "TIMEOUT":
        return exit_30m_pct
    if variant == "CURRENT":
        if outcome == "TP1":
            return (tp1_price / entry_price - 1.0) * 100.0 if tp1_price else 1.2
        if outcome == "TP2":
            return (tp2_price / entry_price - 1.0) * 100.0 if tp2_price else 2.5
    if variant == "WIDE" and outcome == "WIDE_TP":
        return WIDE_TP_PCT
    return None


def net_return_pct(gross_pct: Optional[float], fee_pct: float = FEE_ROUND_TRIP_PCT) -> Optional[float]:
    """Netto = bruto − round-trip kostenaanname, uniform voor elke uitkomst."""
    return None if gross_pct is None else gross_pct - fee_pct
