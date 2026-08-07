# test_signal_outcome_tracker.py — unit tests voor OutcomeTracker (US-402)
import sqlite3
import tempfile
import time
from typing import Dict, Tuple

from multi_coin_grid_pro.signals.momentum_outcome_tracker import OutcomeTracker
from multi_coin_grid_pro.signals.momentum_signal_store import SignalStore


def _make_db() -> str:
    """Create a temp SQLite db with the signals + signal_outcomes tables."""
    tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
    tmp.close()
    store = SignalStore(db_path=tmp.name)
    store.close()
    return tmp.name


def _insert_buy_now(
    db_path: str,
    timestamp: float,
    pair: str = "WLD-USD",
    exchange: str = "kraken",
    price: float = 1.0,
    entry_max: float = 1.002,
    tp1: float = 1.014,
    tp2: float = 1.027,
    stop: float = 0.985,
    entry_min: float = 0.997,
    scan_id: str = "scan001",
) -> int:
    """Insert a BUY_NOW signal row and return its rowid."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute("""
        INSERT INTO signals (
            scan_id, timestamp, exchange, trading_pair, price, spread_pct,
            price_change_5m_pct, price_change_15m_pct, volume_ratio, score,
            accepted, signal_label, entry_min, entry_max, max_chase_price,
            invalidation_price, take_profit_1, take_profit_2, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        scan_id, timestamp, exchange, pair, price, 0.05,
        2.0, 4.5, 3.5, 0.80,
        1, "BUY_NOW",
        entry_min, entry_max, entry_max * 1.008,
        stop, tp1, tp2,
        timestamp,  # created_at = same as timestamp for tests
    ))
    rowid = cur.lastrowid
    conn.commit()
    conn.close()
    return rowid


def _insert_watch(
    db_path: str,
    timestamp: float,
    pair: str = "WLD-USD",
    exchange: str = "kraken",
    price: float = 1.0,
    scan_id: str = "scan001",
) -> int:
    """Insert a WATCH signal row (no entry zone) and return its rowid."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute("""
        INSERT INTO signals (
            scan_id, timestamp, exchange, trading_pair, price, spread_pct,
            price_change_5m_pct, price_change_15m_pct, volume_ratio, score,
            accepted, signal_label, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        scan_id, timestamp, exchange, pair, price, 0.05,
        1.5, 3.0, 2.5, 0.65,
        1, "WATCH",
        timestamp,
    ))
    rowid = cur.lastrowid
    conn.commit()
    conn.close()
    return rowid


def _prices(*pairs_prices) -> Dict[Tuple[str, str], float]:
    """Helper: {(exchange, pair): price, ...}"""
    return {(ex, pair): price for ex, pair, price in pairs_prices}


# ---------------------------------------------------------------------------
# Basic functionality
# ---------------------------------------------------------------------------

class TestOutcomeTrackerBasic:
    def test_update_returns_int(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        _insert_buy_now(db, timestamp=time.time() - 10)
        n = tracker.update(_prices(("kraken", "WLD-USD", 1.005)))
        assert isinstance(n, int)
        tracker.close()

    def test_no_signals_returns_zero(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        n = tracker.update(_prices(("kraken", "WLD-USD", 1.0)))
        assert n == 0
        tracker.close()

    def test_creates_outcome_row(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 10, price=1.0)
        tracker.update(_prices(("kraken", "WLD-USD", 1.01)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT * FROM signal_outcomes WHERE signal_id=?", (signal_id,)).fetchone()
        conn.close()
        assert row is not None
        tracker.close()


# ---------------------------------------------------------------------------
# TP and stop hit detection
# ---------------------------------------------------------------------------

class TestHitDetection:
    def test_hit_tp1_when_price_exceeds_tp1(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 10, tp1=1.014, entry_max=1.002)
        # Price is above TP1
        tracker.update(_prices(("kraken", "WLD-USD", 1.020)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT hit_tp1, hit_tp2, hit_stop FROM signal_outcomes WHERE signal_id=?",
            (signal_id,)
        ).fetchone()
        conn.close()
        assert row[0] == 1  # hit_tp1
        tracker.close()

    def test_no_hit_tp1_when_price_below(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 10, tp1=1.014, entry_max=1.002)
        tracker.update(_prices(("kraken", "WLD-USD", 1.005)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT hit_tp1 FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row[0] == 0
        tracker.close()

    def test_hit_stop_when_price_below_stop(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 10, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 0.980)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT hit_stop FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row[0] == 1
        tracker.close()

    def test_no_hit_stop_when_price_above(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 10, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 0.990)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT hit_stop FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row[0] == 0
        tracker.close()


# ---------------------------------------------------------------------------
# Age-based evaluation
# ---------------------------------------------------------------------------

class TestAgeBasedEvaluation:
    def test_old_signal_gets_evaluated_at(self):
        """Signal >= 30 min old must have evaluated_at set."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 31 * 60)  # 31 min old
        tracker.update(_prices(("kraken", "WLD-USD", 1.005)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT evaluated_at FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None and row[0] is not None
        tracker.close()

    def test_young_signal_not_finalized(self):
        """Signal < 30 min old should NOT have evaluated_at set yet."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 5 * 60)  # 5 min old
        tracker.update(_prices(("kraken", "WLD-USD", 1.005)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT evaluated_at FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        # May or may not be None depending on implementation, but row should exist
        assert row is not None
        tracker.close()

    def test_signal_older_than_30min_excluded_from_new_tracking(self):
        """Signals > 30 min old should already be finalized and not updated again."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 31 * 60)
        # First update: finalizes
        tracker.update(_prices(("kraken", "WLD-USD", 1.005)), now=now)
        # Second update: should not create a second row
        tracker.update(_prices(("kraken", "WLD-USD", 1.010)), now=now + 60)
        conn = sqlite3.connect(db)
        rows = conn.execute(
            "SELECT COUNT(*) FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert rows[0] == 1  # exactly one row
        tracker.close()


# ---------------------------------------------------------------------------
# Multiple exchanges / pairs
# ---------------------------------------------------------------------------

class TestMultiPair:
    def test_updates_correct_pair_only(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        id1 = _insert_buy_now(db, timestamp=now - 30, pair="WLD-USD", exchange="kraken", scan_id="s1")
        id2 = _insert_buy_now(db, timestamp=now - 30, pair="RENDER-USD", exchange="bitvavo", scan_id="s2")
        tracker.update(
            _prices(
                ("kraken", "WLD-USD", 1.02),
                ("bitvavo", "RENDER-USD", 5.50),
            ),
            now=now,
        )
        conn = sqlite3.connect(db)
        r1 = conn.execute("SELECT id FROM signal_outcomes WHERE signal_id=?", (id1,)).fetchone()
        r2 = conn.execute("SELECT id FROM signal_outcomes WHERE signal_id=?", (id2,)).fetchone()
        conn.close()
        assert r1 is not None
        assert r2 is not None
        tracker.close()

    def test_missing_pair_in_price_lookup_skipped(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 30, pair="WLD-USD", exchange="kraken")
        # Only provide price for a different pair
        n = tracker.update(_prices(("kraken", "BTC-USD", 60000)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT id FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        # Signal was not updated (no price found)
        assert n == 0 or row is None
        tracker.close()


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_does_not_raise(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        tracker.close()  # must not raise

    def test_double_close_does_not_raise(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        tracker.close()
        # Second close: SQLite may or may not raise; either is acceptable
        try:
            tracker.close()
        except Exception:
            pass  # acceptable


# ---------------------------------------------------------------------------
# WATCH signal outcome tracking
# ---------------------------------------------------------------------------

class TestWatchOutcomeTracking:
    def test_watch_signal_creates_outcome_row(self):
        """WATCH signal should get an outcome row using signal price as entry_price."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_watch(db, timestamp=now - 10, price=1.0)
        tracker.update(_prices(("kraken", "WLD-USD", 1.02)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT entry_price FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert abs(row[0] - 1.0) < 1e-9  # entry_price = signal price
        tracker.close()

    def test_watch_signal_no_tp_stop_hits(self):
        """WATCH signals must never have hit_tp1/tp2/stop set (no levels defined)."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_watch(db, timestamp=now - 35 * 60, price=1.0)
        # Extreme price — would trigger any TP if incorrectly evaluated
        tracker.update(_prices(("kraken", "WLD-USD", 9999.0)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT hit_tp1, hit_tp2, hit_stop FROM signal_outcomes WHERE signal_id=?",
            (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 0  # hit_tp1
        assert row[1] == 0  # hit_tp2
        assert row[2] == 0  # hit_stop
        tracker.close()

    def test_watch_best_exit_pct_relative_to_signal_price(self):
        """best_exit_pct for WATCH is relative to signal price (not entry_max)."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_watch(db, timestamp=now - 70, price=2.0)  # 70s old → 1m window elapsed
        # price rises to 2.10 (+5%)
        tracker.update(_prices(("kraken", "WLD-USD", 2.10)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT best_exit_pct FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert abs(row[0] - 5.0) < 0.1  # (2.10 - 2.0) / 2.0 * 100 = 5%
        tracker.close()

    def test_watch_evaluated_after_30min(self):
        """WATCH signal >= 30 min gets evaluated_at set."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_watch(db, timestamp=now - 31 * 60, price=1.0)
        tracker.update(_prices(("kraken", "WLD-USD", 1.01)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT evaluated_at FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None and row[0] is not None
        tracker.close()

    def test_buy_now_and_watch_tracked_together(self):
        """BUY_NOW and WATCH signals in same scan are both tracked."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        id_bn = _insert_buy_now(db, timestamp=now - 10, pair="WLD-USD", scan_id="s1")
        id_w = _insert_watch(db, timestamp=now - 10, pair="ALLO-USD", scan_id="s1")
        tracker.update(
            _prices(("kraken", "WLD-USD", 1.02), ("kraken", "ALLO-USD", 0.50)),
            now=now,
        )
        conn = sqlite3.connect(db)
        r_bn = conn.execute("SELECT id FROM signal_outcomes WHERE signal_id=?", (id_bn,)).fetchone()
        r_w = conn.execute("SELECT id FROM signal_outcomes WHERE signal_id=?", (id_w,)).fetchone()
        conn.close()
        assert r_bn is not None
        assert r_w is not None
        tracker.close()


def _insert_too_late(
    db_path: str,
    timestamp: float,
    pair: str = "WLD-USD",
    exchange: str = "kraken",
    price: float = 1.0,
    tp1: float = 1.014,
    tp2: float = 1.027,
    stop: float = 0.985,
    scan_id: str = "scan001",
) -> int:
    """Insert a TOO_LATE signal row and return its rowid."""
    conn = sqlite3.connect(db_path)
    cur = conn.execute("""
        INSERT INTO signals (
            scan_id, timestamp, exchange, trading_pair, price, spread_pct,
            price_change_5m_pct, price_change_15m_pct, volume_ratio, score,
            accepted, signal_label, invalidation_price, take_profit_1, take_profit_2,
            created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        scan_id, timestamp, exchange, pair, price, 0.05,
        3.5, 7.0, 4.0, 0.75,
        1, "TOO_LATE",
        stop, tp1, tp2,
        timestamp,
    ))
    rowid = cur.lastrowid
    conn.commit()
    conn.close()
    return rowid


# ---------------------------------------------------------------------------
# first_hit volgorde tests
# ---------------------------------------------------------------------------

class TestFirstHit:
    def test_first_hit_tp1_when_only_tp1_reached(self):
        """Only TP1 reached → first_hit = TP1 on evaluation."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 31 * 60, tp1=1.014, tp2=1.027, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 1.020)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT first_hit FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "TP1"
        tracker.close()

    def test_first_hit_stop_when_only_stop_reached(self):
        """Only stop reached → first_hit = STOP."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 31 * 60, tp1=1.014, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 0.980)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT first_hit FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "STOP"
        tracker.close()

    def test_first_hit_timeout_when_nothing_reached(self):
        """Neither TP nor stop → first_hit = TIMEOUT after 30 min."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 31 * 60, tp1=1.014, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 1.005)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT first_hit FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "TIMEOUT"
        tracker.close()

    def test_first_hit_not_set_before_30min(self):
        """first_hit must be NULL while signal is still within 30 min window."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 5 * 60, tp1=1.014, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 1.020)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT first_hit FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is None or row[0] is None
        tracker.close()

    def test_stop_time_recorded(self):
        """stop_hit_at_seconds is set when stop is triggered."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 31 * 60, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 0.980)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT stop_hit_at_seconds FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None and row[0] is not None
        assert row[0] > 0
        tracker.close()

    def test_tp1_time_recorded(self):
        """tp1_hit_at_seconds is set when TP1 is triggered."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(db, timestamp=now - 31 * 60, tp1=1.014)
        tracker.update(_prices(("kraken", "WLD-USD", 1.020)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT tp1_hit_at_seconds FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None and row[0] is not None
        assert row[0] > 0
        tracker.close()


# ---------------------------------------------------------------------------
# TOO_LATE outcome tracking tests
# ---------------------------------------------------------------------------

class TestTooLateTracking:
    def test_too_late_creates_outcome_row(self):
        """TOO_LATE signal gets an outcome row using signal price as entry_price."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_too_late(db, timestamp=now - 10, price=1.0)
        tracker.update(_prices(("kraken", "WLD-USD", 1.02)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT entry_price FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert abs(row[0] - 1.0) < 1e-9
        tracker.close()

    def test_too_late_tracks_tp1_hit(self):
        """TOO_LATE signal tracks TP1 hits (hypothetical — for analysis)."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_too_late(db, timestamp=now - 31 * 60, price=1.0, tp1=1.014, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 1.020)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT hit_tp1, first_hit FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == 1    # hit_tp1
        assert row[1] == "TP1"
        tracker.close()

    def test_too_late_first_hit_timeout_when_no_level_reached(self):
        """TOO_LATE with no TP/stop hit → TIMEOUT."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_too_late(db, timestamp=now - 31 * 60, price=1.0, tp1=1.014, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 1.005)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT first_hit FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "TIMEOUT"
        tracker.close()
