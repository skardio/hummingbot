"""Unit tests for TradeLabelStore (Item 12)."""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from multi_coin_grid_pro.persistence.trade_label_store import TradeLabel, TradeLabelStore, session_from_utc

_NOW = int(time.time())


def _make_label(**kwargs) -> TradeLabel:
    defaults = dict(
        coin="ETH-USD",
        timestamp_open=_NOW - 3600,
        timestamp_close=_NOW,
        session="EU",
        regime="BULL",
        volatility_state="normal",
        spread_at_entry=0.05,
        depth_at_entry=1000.0,
        quality_score=65,
        entry_reason="trend_up",
        exit_reason="take_profit",
        exit_type="TP",
        pnl_quote=2.50,
        mfe_pct=1.2,
        mae_pct=-0.4,
        reentry=False,
        cycle_number=1,
    )
    defaults.update(kwargs)
    return TradeLabel(**defaults)


class TestSessionFromUtc(unittest.TestCase):

    def test_asia_session(self):
        # UTC 02:00 on a Wednesday
        ts = 1_745_028_000   # 2025-04-19 02:00 UTC (Saturday actually... let's use known value)
        import datetime as _dt

        # Build a known weekday + hour
        dt = _dt.datetime(2025, 4, 21, 3, 0, 0)   # Monday 03:00 UTC
        ts = dt.timestamp()
        self.assertEqual(session_from_utc(ts), "Asia")

    def test_eu_session(self):
        import datetime as _dt
        dt = _dt.datetime(2025, 4, 21, 10, 0, 0)   # Monday 10:00 UTC
        self.assertEqual(session_from_utc(dt.timestamp()), "EU")

    def test_us_session(self):
        import datetime as _dt
        dt = _dt.datetime(2025, 4, 21, 20, 0, 0)   # Monday 20:00 UTC
        self.assertEqual(session_from_utc(dt.timestamp()), "US")

    def test_weekend(self):
        import datetime as _dt
        dt = _dt.datetime(2025, 4, 19, 12, 0, 0)   # Saturday
        self.assertEqual(session_from_utc(dt.timestamp()), "weekend")

    def test_accepts_datetime_for_backward_compatibility(self):
        import datetime as _dt
        dt = _dt.datetime(2025, 4, 21, 10, 0, 0)   # Monday 10:00 UTC
        self.assertEqual(session_from_utc(dt), "EU")


class TestTradeLabelStore(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = TradeLabelStore(db_path=self.tmp.name)

    def tearDown(self):
        self.store.close()
        os.unlink(self.tmp.name)

    def test_record_and_query(self):
        label = _make_label()
        self.store.record(label)
        results = self.store.query_recent(days=30)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].coin, "ETH-USD")

    def test_query_returns_newest_first(self):
        label1 = _make_label(timestamp_close=_NOW - 3600, pnl_quote=1.0)
        label2 = _make_label(timestamp_close=_NOW, pnl_quote=2.0)
        self.store.record(label1)
        self.store.record(label2)
        results = self.store.query_recent(days=30)
        self.assertEqual(results[0].pnl_quote, 2.0, "Newest first")

    def test_query_respects_days_limit(self):
        # Record with old timestamp (more than 10 days ago)
        old_ts = int(time.time()) - 11 * 86400
        old_label = _make_label(timestamp_close=old_ts)
        new_label = _make_label(timestamp_close=int(time.time()))
        self.store.record(old_label)
        self.store.record(new_label)
        results = self.store.query_recent(days=10)
        self.assertEqual(len(results), 1, "Only recent label should be returned")

    def test_export_csv(self):
        self.store.record(_make_label(pnl_quote=1.5))
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            csv_path = f.name
        try:
            n = self.store.export_csv(csv_path)
            self.assertEqual(n, 1)
            with open(csv_path) as fh:
                lines = fh.readlines()
            # header + 1 data row
            self.assertEqual(len(lines), 2)
        finally:
            os.unlink(csv_path)

    def test_query_empty_store(self):
        results = self.store.query_recent(days=30)
        self.assertEqual(results, [])

    def test_reentry_flag_preserved(self):
        self.store.record(_make_label(reentry=True, cycle_number=2))
        results = self.store.query_recent(days=30)
        self.assertTrue(results[0].reentry)
        self.assertEqual(results[0].cycle_number, 2)

    def test_multiple_coins_stored(self):
        self.store.record(_make_label(coin="ETH-USD"))
        self.store.record(_make_label(coin="BTC-USD"))
        self.store.record(_make_label(coin="SOL-USD"))
        results = self.store.query_recent(days=30)
        coins = {r.coin for r in results}
        self.assertEqual(coins, {"ETH-USD", "BTC-USD", "SOL-USD"})

    def test_creates_parent_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = Path(tmpdir) / "nested" / "labels.db"
            store = TradeLabelStore(db_path=str(nested))
            try:
                store.record(_make_label())
                self.assertTrue(nested.exists())
                self.assertEqual(len(store.query_recent(days=30)), 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
