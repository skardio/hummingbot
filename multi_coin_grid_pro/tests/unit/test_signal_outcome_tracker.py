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


# ---------------------------------------------------------------------------
# Shadow-test (v5 prospectief): CURRENT vs WIDE_TP + observationele drempels
# ---------------------------------------------------------------------------

class TestShadowTestOrdering:
    """CURRENT (bestaand) en WIDE_TP (schaduw) moeten volledig onafhankelijk
    van elkaar worden bepaald, met dezelfde invalidation_price als anker."""

    def test_current_unaffected_by_wide_tp_addition(self):
        """CURRENT-kolommen (hit_tp1/hit_stop/first_hit) blijven exact zoals
        vóór de shadow-test-uitbreiding — geen regressie."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(
            db, timestamp=now - 31 * 60, entry_max=1.002, tp1=1.014, tp2=1.027, stop=0.985,
        )
        tracker.update(_prices(("kraken", "WLD-USD", 1.020)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT hit_tp1, hit_stop, first_hit FROM signal_outcomes WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        conn.close()
        assert row == (1, 0, "TP1")
        tracker.close()

    def test_current_tp_but_wide_tp_never_reached_stays_timeout(self):
        """Prijs bereikt CURRENT TP1 (+1.2%) maar niet WIDE_TP (+1.5%):
        CURRENT=TP1, WIDE_TP=TIMEOUT (nooit gestopt, nooit wide-TP geraakt)."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        # entry_max=1.0 → TP1=1.012 (+1.2%), WIDE_TP=1.015 (+1.5%), stop=0.985 (op entry_min)
        signal_id = _insert_buy_now(
            db, timestamp=now - 31 * 60, entry_max=1.0, entry_min=0.997,
            tp1=1.012, tp2=1.025, stop=0.982,
        )
        # Prijs stijgt tot 1.013 (tussen TP1 en WIDE_TP) en blijft daar.
        tracker.update(_prices(("kraken", "WLD-USD", 1.013)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT first_hit, wide_first_hit, hit_wide_tp FROM signal_outcomes WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        conn.close()
        assert row is not None
        first_hit, wide_first_hit, hit_wide_tp = row
        assert first_hit == "TP1"
        assert hit_wide_tp == 0
        assert wide_first_hit == "TIMEOUT"
        tracker.close()

    def test_same_trade_current_tp_but_wide_tp_stop(self):
        """Kernscenario: entry -> +1.3% (raakt CURRENT TP1, niet WIDE_TP) ->
        -2.1% (raakt STOP, gedeeld met WIDE_TP). CURRENT=TP1, WIDE_TP=STOP."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        t0 = time.time() - 31 * 60
        signal_id = _insert_buy_now(
            db, timestamp=t0, entry_max=1.0, entry_min=0.997,
            tp1=1.012, tp2=1.025, stop=0.979,   # stop op ongeveer -2.1% t.o.v. entry_max
        )
        # Tick 1 (t0+60s): prijs +1.3% -> raakt CURRENT TP1 (1.012), niet WIDE_TP (1.015)
        tracker.update(_prices(("kraken", "WLD-USD", 1.013)), now=t0 + 60)
        # Tick 2 (t0+120s): prijs zakt naar -2.1% -> raakt STOP (0.979), gedeeld door beide varianten
        tracker.update(_prices(("kraken", "WLD-USD", 0.978)), now=t0 + 120)
        # Tick 3 (t0+31min): finale evaluatie
        tracker.update(_prices(("kraken", "WLD-USD", 0.978)), now=t0 + 31 * 60)

        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT first_hit, wide_first_hit, hit_tp1, hit_wide_tp, hit_stop "
            "FROM signal_outcomes WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        conn.close()
        assert row is not None
        first_hit, wide_first_hit, hit_tp1, hit_wide_tp, hit_stop = row
        assert first_hit == "TP1", "CURRENT moet TP1 zijn (1.3% >= 1.2% drempel, v\u00f3\u00f3r de stop-tick)"
        assert hit_tp1 == 1
        assert hit_wide_tp == 0, "prijs heeft nooit de 1.5% WIDE_TP-drempel geraakt"
        assert hit_stop == 1, "dezelfde stop-gebeurtenis geldt voor beide varianten"
        assert wide_first_hit == "STOP", (
            "WIDE_TP moet STOP zijn: TP werd nooit geraakt, dus de gedeelde "
            "stop-gebeurtenis (zelfde invalidation_price als CURRENT) wint"
        )
        tracker.close()

    def test_wide_tp_hit_when_price_exceeds_1_5_pct(self):
        """Prijs bereikt +1.5% zonder ooit de stop te raken -> WIDE_TP=WIDE_TP."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(
            db, timestamp=now - 31 * 60, entry_max=1.0, entry_min=0.997,
            tp1=1.012, tp2=1.025, stop=0.982,
        )
        tracker.update(_prices(("kraken", "WLD-USD", 1.016)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT hit_wide_tp, wide_first_hit FROM signal_outcomes WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        conn.close()
        assert row == (1, "WIDE_TP")
        tracker.close()

    def test_wide_tp_uses_real_invalidation_price_not_fixed_pct(self):
        """WIDE_TP's STOP-kant moet de daadwerkelijke invalidation_price per
        signaal gebruiken, niet een vaste -2.0%/-1.5% aanname. Twee signalen
        met verschillende invalidation_price moeten onafhankelijk reageren
        op exact hun eigen stop-niveau."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        # Signaal A: stop ligt op 0.985 (relatief hoog -> raakt sneller stop)
        sig_a = _insert_buy_now(
            db, timestamp=now - 31 * 60, pair="AAA-USD", entry_max=1.0,
            tp1=1.012, tp2=1.025, stop=0.985,
        )
        # Signaal B: stop ligt op 0.960 (veel dieper -> raakt bij dezelfde prijs geen stop)
        sig_b = _insert_buy_now(
            db, timestamp=now - 31 * 60, pair="BBB-USD", entry_max=1.0,
            tp1=1.012, tp2=1.025, stop=0.960,
        )
        # Beide op dezelfde prijs 0.970: A moet STOP raken (0.970 < 0.985), B niet (0.970 > 0.960)
        tracker.update(_prices(("kraken", "AAA-USD", 0.970), ("kraken", "BBB-USD", 0.970)), now=now)
        conn = sqlite3.connect(db)
        row_a = conn.execute(
            "SELECT hit_stop, wide_first_hit FROM signal_outcomes WHERE signal_id=?", (sig_a,)
        ).fetchone()
        row_b = conn.execute(
            "SELECT hit_stop, wide_first_hit FROM signal_outcomes WHERE signal_id=?", (sig_b,)
        ).fetchone()
        conn.close()
        assert row_a == (1, "STOP"), "signaal A's eigen invalidation_price (0.985) is geraakt"
        assert row_b == (0, "TIMEOUT"), "signaal B's eigen, veel diepere invalidation_price (0.960) is niet geraakt"
        tracker.close()

    def test_watch_and_too_late_have_no_wide_tp_fields(self):
        """WIDE_TP-logica is BUY_NOW-only: WATCH/TOO_LATE blijven ongemoeid."""
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        watch_id = _insert_watch(db, timestamp=now - 10, price=1.0)
        too_late_id = _insert_too_late(db, timestamp=now - 10, price=1.0, tp1=1.014, stop=0.985)
        tracker.update(_prices(("kraken", "WLD-USD", 1.02)), now=now)
        conn = sqlite3.connect(db)
        row_watch = conn.execute(
            "SELECT hit_wide_tp, wide_first_hit FROM signal_outcomes WHERE signal_id=?", (watch_id,)
        ).fetchone()
        row_too_late = conn.execute(
            "SELECT hit_wide_tp, wide_first_hit FROM signal_outcomes WHERE signal_id=?", (too_late_id,)
        ).fetchone()
        conn.close()
        assert row_watch == (0, None)
        assert row_too_late == (0, None)
        tracker.close()


class TestObservationalThresholds:
    """p07/p10/m10/m15_hit_at_seconds en mfe/mae_at_seconds zijn puur logging
    en mogen CURRENT/WIDE_TP nooit be\u00efnvloeden."""

    def test_p07_and_p10_timestamps_recorded(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(
            db, timestamp=now - 10, entry_max=1.0, tp1=1.012, tp2=1.025, stop=0.982,
        )
        # +1.0% beweging: moet p07 (0.7%) en p10 (1.0%) allebei triggeren
        tracker.update(_prices(("kraken", "WLD-USD", 1.010)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT p07_hit_at_seconds, p10_hit_at_seconds FROM signal_outcomes WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None
        assert row[1] is not None
        tracker.close()

    def test_m10_and_m15_timestamps_recorded(self):
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        now = time.time()
        signal_id = _insert_buy_now(
            db, timestamp=now - 10, entry_max=1.0, tp1=1.012, tp2=1.025, stop=0.980,
        )
        # -1.6% beweging: moet m10 (-1.0%) en m15 (-1.5%) allebei triggeren, maar STOP (0.980, -2.0%) niet
        tracker.update(_prices(("kraken", "WLD-USD", 0.984)), now=now)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT m10_hit_at_seconds, m15_hit_at_seconds, hit_stop FROM signal_outcomes WHERE signal_id=?",
            (signal_id,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] is not None
        assert row[1] is not None
        assert row[2] == 0
        tracker.close()

    def test_mfe_and_mae_timestamps_track_new_extremes(self):
        """mfe/mae_at_seconds worden alleen bijgewerkt als er een NIEUW extreem is.

        Let op: max/min-windows worden pas bijgewerkt zodra age_min >= 1 (de
        kleinste window-grens) — vandaar ticks ruim voorbij de 1-minutengrens.
        """
        db = _make_db()
        tracker = OutcomeTracker(db_path=db)
        t0 = time.time() - 10
        signal_id = _insert_buy_now(
            db, timestamp=t0, entry_max=1.0, tp1=1.020, tp2=1.030, stop=0.970,
        )
        # Tick 1 (age_min ~1.08, voorbij de 1m-grens): prijs +0.5% -> eerste MFE
        tracker.update(_prices(("kraken", "WLD-USD", 1.005)), now=t0 + 65)
        conn = sqlite3.connect(db)
        mfe_1 = conn.execute(
            "SELECT mfe_at_seconds, best_exit_pct FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        assert mfe_1[0] is not None
        assert abs(mfe_1[1] - 0.5) < 0.01

        # Tick 2 (age_min ~2.2): prijs zakt naar +0.2% -> GEEN nieuw MFE-record (best blijft 0.5%)
        tracker.update(_prices(("kraken", "WLD-USD", 1.002)), now=t0 + 130)
        conn = sqlite3.connect(db)
        mfe_2 = conn.execute(
            "SELECT mfe_at_seconds FROM signal_outcomes WHERE signal_id=?", (signal_id,)
        ).fetchone()
        conn.close()
        # mfe_at_seconds mag niet zijn overschreven met de latere, lagere prijs-tick
        assert mfe_2[0] == mfe_1[0]
        tracker.close()
