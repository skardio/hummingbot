# test_momentum_shadow_archive.py — permanente opslag + T+30 capture van BUY_NOW shadow-outcomes.
import re
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest

from multi_coin_grid_pro.signals import momentum_shadow_archive as sa
from multi_coin_grid_pro.signals.momentum_outcome_tracker import OutcomeTracker
from multi_coin_grid_pro.signals.momentum_signal_store import SignalStore

PAIR = ("kraken", "WLD-USD")
ENTRY = 1.0
INV = 0.97863  # -2.137% — echte invalidation, niet -2.0


def _db() -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    SignalStore(db_path=tmp.name).close()
    return tmp.name


def _buy_now(db, ts, regime=0.1, breadth=50.0, created_at=None) -> int:
    conn = sqlite3.connect(db)
    cur = conn.execute("""
        INSERT INTO signals (scan_id, timestamp, exchange, trading_pair, price, spread_pct,
            price_change_5m_pct, price_change_15m_pct, volume_ratio, score, accepted,
            signal_label, entry_min, entry_max, max_chase_price, invalidation_price,
            take_profit_1, take_profit_2, market_regime_at_signal, market_breadth_15m, created_at)
        VALUES ('s', ?, ?, ?, ?, 0.05, 2.0, 4.5, 3.5, 0.8, 1, 'BUY_NOW', ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ts, PAIR[0], PAIR[1], ENTRY, ENTRY * 0.995, ENTRY, ENTRY * 1.008, INV,
          ENTRY * 1.012, ENTRY * 1.025, regime, breadth, ts if created_at is None else created_at))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid


def _rows(db, sql, args=()):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out = [dict(r) for r in conn.execute(sql, args)]
    conn.close()
    return out


def _archive(db):
    return _rows(db, "SELECT * FROM buy_now_shadow_archive ORDER BY signal_id")


def _run(db, ts, ticks):
    """ticks: [(age_seconds, price)] → één tracker, update per tick."""
    tr = OutcomeTracker(db)
    for age, price in ticks:
        tr.update({PAIR: price}, now=ts + age)
    tr.close()


# ── automatische archive-write ────────────────────────────────────────────────

def test_archive_written_automatically_on_final_evaluation():
    db = _db()
    ts = time.time()
    sid = _buy_now(db, ts)
    _run(db, ts, [(600, 1.004), (1830, 0.996)])
    rows = _archive(db)
    assert [r["signal_id"] for r in rows] == [sid]
    r = rows[0]
    assert r["archive_status"] == "EVALUATED"
    assert r["v5_pass"] == 1
    assert r["volume_ratio"] == 3.5 and r["market_breadth_15m"] == 50.0
    assert r["d5_d15_ratio"] == pytest.approx(2.0 / 4.5)
    assert r["wide_tp_price"] == pytest.approx(1.015)
    assert r["invalidation_price"] == INV
    for col in ("exit_30m_price", "exit_30m_pct", "exit_30m_at_seconds", "mfe_at_seconds",
                "mae_at_seconds", "best_exit_pct", "worst_drawdown_pct", "evaluated_at"):
        assert r[col] is not None, col


def test_not_archived_before_final_evaluation():
    db = _db()
    ts = time.time()
    _buy_now(db, ts)
    _run(db, ts, [(600, 1.004), (1700, 1.0)])
    assert _archive(db) == []


def test_v5_pass_uses_frozen_rules():
    db = _db()
    ts = time.time()
    ok = _buy_now(db, ts, regime=0.0, breadth=40.0)
    bad = _buy_now(db, ts + 1, regime=0.1, breadth=39.9)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE signals SET trading_pair='OTHER' WHERE id=?", (bad,))
    conn.commit()
    conn.close()
    tr = OutcomeTracker(db)
    tr.update({PAIR: 1.0, ("kraken", "OTHER"): 1.0}, now=ts + 1850)
    tr.close()
    v5 = {r["signal_id"]: r["v5_pass"] for r in _archive(db)}
    assert v5 == {ok: 1, bad: 0}


def test_v5_sql_identical_to_track_v5_paper():
    src = (Path(__file__).resolve().parents[3] / "track_v5_paper.py").read_text()
    m = re.search(r'V5_WHERE = """(.*?)"""', src, re.S)
    assert m and " ".join(m.group(1).split()) == " ".join(sa.V5_SQL.split())


# ── idempotentie / geen duplicaten ────────────────────────────────────────────

def test_idempotent_no_duplicates():
    db = _db()
    ts = time.time()
    sid = _buy_now(db, ts)
    _run(db, ts, [(1830, 0.996)])
    first = _archive(db)[0]["archived_at"]
    conn = sqlite3.connect(db)
    assert sa.archive_evaluated(conn, sid, time.time()) == 0
    assert sa.backfill(conn, time.time()) == 0
    conn.commit()
    conn.close()
    _run(db, ts, [(1900, 1.5)])  # extra tick na evaluatie
    OutcomeTracker(db).close()   # restart
    rows = _archive(db)
    assert len(rows) == 1 and rows[0]["archived_at"] == first
    assert rows[0]["exit_30m_price"] == 0.996


# ── restart / crash recovery ──────────────────────────────────────────────────

def test_restart_recovers_missing_archive_row(monkeypatch):
    db = _db()
    ts = time.time()
    sid = _buy_now(db, ts)
    monkeypatch.setattr(sa, "archive_evaluated", lambda *a, **k: 0)  # crash/oude code
    tr = OutcomeTracker(db)
    tr.update({PAIR: 0.996}, now=ts + 1830)
    tr.close()
    assert _archive(db) == []
    monkeypatch.undo()
    OutcomeTracker(db).close()  # herstart → backfill
    assert [r["signal_id"] for r in _archive(db)] == [sid]


# ── retention ────────────────────────────────────────────────────────────────

def test_purge_archives_before_deleting_signals(monkeypatch):
    db = _db()
    ts = time.time() - 8 * 86400
    sid = _buy_now(db, ts)
    lost = _buy_now(db, ts + 5)  # nooit geprijsd/geëvalueerd → zichtbaar als gat
    conn = sqlite3.connect(db)
    conn.execute("UPDATE signals SET trading_pair='NOPRICE' WHERE id=?", (lost,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(sa, "archive_evaluated", lambda *a, **k: 0)
    tr = OutcomeTracker.__new__(OutcomeTracker)
    tr._conn = sqlite3.connect(db)
    tr.update({PAIR: 0.996}, now=ts + 1830)
    tr.close()
    monkeypatch.undo()
    store = SignalStore(db_path=db)
    assert store.purge_old(retention_days=7) == 2
    store.close()
    assert _rows(db, "SELECT id FROM signals") == []
    status = {r["signal_id"]: r["archive_status"] for r in _archive(db)}
    assert status == {sid: "EVALUATED", lost: "UNEVALUATED"}
    assert _archive(db)[0]["volume_ratio"] == 3.5  # features overleven retention


def test_purge_fails_closed_when_archive_fails(monkeypatch):
    db = _db()
    _buy_now(db, time.time() - 8 * 86400)

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")

    store = SignalStore(db_path=db)
    monkeypatch.setattr(sa, "backfill", boom)
    assert store.purge_old(retention_days=7) == 0
    store.close()
    assert len(_rows(db, "SELECT id FROM signals")) == 1


# ── T+30 capture ─────────────────────────────────────────────────────────────

def test_exit_30m_is_first_observation_after_30m_not_max():
    db = _db()
    ts = time.time()
    _buy_now(db, ts)
    _run(db, ts, [(300, 1.009), (1790, 1.008), (1835, 1.003), (1900, 1.010)])
    o = _rows(db, "SELECT * FROM signal_outcomes")[0]
    assert o["exit_30m_price"] == 1.003
    assert o["exit_30m_at_seconds"] == pytest.approx(1835)
    assert o["exit_30m_pct"] == pytest.approx(0.3)
    assert o["best_exit_pct"] == pytest.approx(0.9)  # MFE blijft apart
    assert o["first_hit"] == "TIMEOUT"


def test_exit_30m_records_real_elapsed_seconds_when_late():
    db = _db()
    ts = time.time()
    _buy_now(db, ts)
    _run(db, ts, [(2100, 0.99)])  # service-hapering: eerste tick pas na 35 min
    a = _archive(db)[0]
    assert a["exit_30m_at_seconds"] == pytest.approx(2100)
    assert a["exit_30m_pct"] == pytest.approx(-1.0)


def test_max_price_30m_written_once_on_evaluation_tick():
    # Basis van de historische T+30-reconstructie (69 pre-fix trades): het 30m-venster
    # wordt alleen op de finale evaluatietick geschreven (eerste tick >=30 min mét prijs),
    # daarna is het signaal niet meer pending. Dus max_price_30m == exit-prijs en
    # evaluated_at - timestamp == exit_30m_at_seconds.
    db = _db()
    ts = time.time()
    _buy_now(db, ts)
    tr = OutcomeTracker(db)
    tr.update({PAIR: 1.009}, now=ts + 600)
    tr.update({}, now=ts + 1805)               # pair niet gescand: geen geldige observatie
    tr.update({PAIR: 1.002}, now=ts + 1880)    # eerste geldige observatie >= 30 min
    tr.update({PAIR: 1.011}, now=ts + 1950)    # na evaluatie: geen effect meer
    tr.close()
    o = _rows(db, "SELECT * FROM signal_outcomes")[0]
    assert o["max_price_30m"] == o["min_price_30m"] == o["exit_30m_price"] == 1.002
    assert o["exit_30m_at_seconds"] == pytest.approx(1880)
    assert o["evaluated_at"] - ts == pytest.approx(1880)
    assert o["best_exit_pct"] == pytest.approx(0.9)


# ── CURRENT / WIDE ongewijzigd ───────────────────────────────────────────────

@pytest.mark.parametrize("ticks,cur,wide", [
    ([(100, 1.013), (1830, 1.0)], "TP1", "TIMEOUT"),
    ([(100, 1.016), (1830, 1.0)], "TP1", "WIDE_TP"),
    ([(100, 1.013), (200, 0.97), (1830, 0.97)], "TP1", "STOP"),
    ([(100, 0.978), (1830, 1.02)], "STOP", "STOP"),
    ([(1830, 1.005)], "TIMEOUT", "TIMEOUT"),
])
def test_archive_mirrors_current_and_wide_outcomes(ticks, cur, wide):
    db = _db()
    ts = time.time()
    _buy_now(db, ts)
    _run(db, ts, ticks)
    o = _rows(db, "SELECT first_hit, wide_first_hit FROM signal_outcomes")[0]
    a = _archive(db)[0]
    assert (o["first_hit"], o["wide_first_hit"]) == (cur, wide)
    assert (a["current_outcome"], a["wide_outcome"]) == (cur, wide)


# ── payoff-model ─────────────────────────────────────────────────────────────

def test_stop_uses_real_invalidation_distance():
    g = sa.gross_return_pct("CURRENT", "STOP", 1.0, INV, None)
    assert g == pytest.approx(-2.137)
    assert sa.gross_return_pct("WIDE", "STOP", 1.0, INV, None) == g
    assert sa.net_return_pct(g) == pytest.approx(-2.637)


def test_timeout_uses_t30_exit_not_mfe():
    assert sa.gross_return_pct("CURRENT", "TIMEOUT", 1.0, INV, -0.4) == -0.4
    assert sa.gross_return_pct("WIDE", "TIMEOUT", 1.0, INV, -0.4) == -0.4
    assert sa.gross_return_pct("CURRENT", "TIMEOUT", 1.0, INV, None) is None


def test_tp_payoffs_and_uniform_fee():
    assert sa.gross_return_pct("CURRENT", "TP1", 1.0, INV, None, 1.012) == pytest.approx(1.2)
    assert sa.gross_return_pct("CURRENT", "TP2", 1.0, INV, None, None, 1.025) == pytest.approx(2.5)
    assert sa.gross_return_pct("WIDE", "WIDE_TP", 1.0, INV, None) == 1.5
    assert sa.net_return_pct(1.5) == pytest.approx(1.0)


# ── cohort + dekking ─────────────────────────────────────────────────────────

def test_cohort_start_is_set_once_and_coverage_counted():
    db = _db()
    tr = OutcomeTracker(db)
    assert tr.start_shadow_cohort(now=1000.0) == 1000.0
    assert tr.start_shadow_cohort(now=2000.0) == 1000.0
    tr.update({}, now=7200.0)
    tr.update({}, now=7260.0)
    tr.close()
    assert _rows(db, "SELECT * FROM shadow_scan_coverage") == [{"hour_bucket": 2, "scans": 2}]
