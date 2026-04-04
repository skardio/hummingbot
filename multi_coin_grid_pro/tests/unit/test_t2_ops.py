"""
T2 Unit Tests — Capital Recovery & Operations
Tests for O1, O3, O5, O7, O8
"""
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from multi_coin_grid_pro.monitoring.database import MonitoringDatabase


# ═══════════════════════════════════════════════════════════════════════════
# O3: SQLite WAL mode
# ═══════════════════════════════════════════════════════════════════════════
class TestWALMode(unittest.TestCase):
    """Verify WAL journal mode on all our SQLite stores."""

    def test_monitoring_db_uses_wal(self):
        with tempfile.TemporaryDirectory() as td:
            db = MonitoringDatabase(db_path=os.path.join(td, "test.db"))
            cur = db.conn.execute("PRAGMA journal_mode")
            mode = cur.fetchone()[0]
            db.close()
            self.assertEqual(mode.lower(), "wal")

    def test_cooldown_store_uses_wal(self):
        from multi_coin_grid_pro.persistence.cooldown_store import CooldownStore
        with tempfile.TemporaryDirectory() as td:
            store = CooldownStore(
                db_path=os.path.join(td, "cool.db"),
            )
            cur = store.conn.execute("PRAGMA journal_mode")
            mode = cur.fetchone()[0]
            store.conn.close()
            self.assertEqual(mode.lower(), "wal")

    def test_entry_price_store_uses_wal(self):
        from multi_coin_grid_pro.persistence.entry_price_store import EntryPriceStore
        with tempfile.TemporaryDirectory() as td:
            store = EntryPriceStore(
                db_path=os.path.join(td, "ep.db"),
            )
            cur = store.conn.execute("PRAGMA journal_mode")
            mode = cur.fetchone()[0]
            store.conn.close()
            self.assertEqual(mode.lower(), "wal")


# ═══════════════════════════════════════════════════════════════════════════
# O5: Monitoring DB retention / prune_old_data
# ═══════════════════════════════════════════════════════════════════════════
class TestMonitoringRetention(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.db = MonitoringDatabase(
            db_path=os.path.join(self.td, "mon.db")
        )

    def tearDown(self):
        self.db.close()

    def _insert_with_age(self, table, days_ago, **kwargs):
        """Insert a row with a timestamp `days_ago` days in the past."""
        ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
        if table == "bot_status":
            self.db.conn.execute(
                "INSERT INTO bot_status (timestamp, pnl) VALUES (?, ?)",
                (ts, kwargs.get("pnl", 0)),
            )
        elif table == "bot_events":
            self.db.conn.execute(
                "INSERT INTO bot_events (timestamp, event_type, message)"
                " VALUES (?, ?, ?)",
                (ts, "test", "msg"),
            )
        elif table == "trades":
            self.db.conn.execute(
                "INSERT INTO trades (timestamp, coin, side, price, amount)"
                " VALUES (?, ?, ?, ?, ?)",
                (ts, "BTC", "buy", 100, 1),
            )
        self.db.conn.commit()

    def test_prune_deletes_old_status(self):
        self._insert_with_age("bot_status", 1)   # keep
        self._insert_with_age("bot_status", 10)   # prune
        result = self.db.prune_old_data(status_days=7)
        self.assertEqual(result["bot_status"], 1)
        rows = self.db.conn.execute(
            "SELECT count(*) FROM bot_status"
        ).fetchone()[0]
        self.assertEqual(rows, 1)

    def test_prune_deletes_old_events(self):
        self._insert_with_age("bot_events", 5)    # keep
        self._insert_with_age("bot_events", 40)   # prune
        result = self.db.prune_old_data(events_days=30)
        self.assertEqual(result["bot_events"], 1)

    def test_prune_keeps_recent_trades(self):
        self._insert_with_age("trades", 10)   # keep
        self._insert_with_age("trades", 100)  # prune
        result = self.db.prune_old_data(trades_days=90)
        self.assertEqual(result["trades"], 1)

    def test_auto_prune_on_init(self):
        """Init should auto-prune (called from _init_database)."""
        # Insert old data manually
        self._insert_with_age("bot_status", 20)
        self.db.conn.commit()
        # Re-init (triggers prune_old_data)
        self.db._init_database()
        rows = self.db.conn.execute(
            "SELECT count(*) FROM bot_status"
        ).fetchone()[0]
        self.assertEqual(rows, 0)


# ═══════════════════════════════════════════════════════════════════════════
# O7: Health check endpoint
# ═══════════════════════════════════════════════════════════════════════════
try:
    import flask  # noqa: F401
    _HAS_FLASK = True
except ImportError:
    _HAS_FLASK = False


@unittest.skipUnless(_HAS_FLASK, "flask not installed")
class TestHealthEndpoint(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.mkdtemp()
        self.mon_db = MonitoringDatabase(
            db_path=os.path.join(self.td, "mon.db")
        )
        from multi_coin_grid_pro.monitoring.dashboard import app, init_dashboard
        init_dashboard(self.mon_db)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        self.mon_db.close()

    def test_health_no_status_rows(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 503)
        data = resp.get_json()
        self.assertEqual(data["status"], "unhealthy")

    def test_health_recent_status(self):
        self.mon_db.add_status(pnl=1.0, mode="running")
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["mode"], "running")

    def test_health_stale_status(self):
        # Insert a status 5 minutes ago
        old_ts = (datetime.now() - timedelta(minutes=5)).isoformat()
        self.mon_db.conn.execute(
            "INSERT INTO bot_status (timestamp, mode) VALUES (?, ?)",
            (old_ts, "running"),
        )
        self.mon_db.conn.commit()
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 503)
        data = resp.get_json()
        self.assertEqual(data["status"], "unhealthy")


# ═══════════════════════════════════════════════════════════════════════════
# O1: Auto-cancel stale orders (unit test with mock connector)
# ═══════════════════════════════════════════════════════════════════════════
class TestAutoCancel(unittest.TestCase):
    """Test stale order auto-cancel logic (mocked connector)."""

    def _make_controller_stub(self, auto_cancel=True):
        """Build a minimal mock of the controller for _cleanup_stale_orders."""
        ctrl = MagicMock()
        ctrl.config = MagicMock()
        ctrl.config.max_hold_time_minutes = 60
        ctrl.config.auto_cancel_stale_orders = auto_cancel
        ctrl.config.market_list = ["BTC-USD", "ETH-USD"]
        ctrl.config.whitelisted_pairs = None
        ctrl.active_coins = {}  # no active executors
        ctrl._stale_orders = []

        # Mock connector with one stale sell order
        order = MagicMock()
        order.trading_pair = "BTC-USD"
        order.is_sell = True
        order.creation_timestamp = time.time() - 9000  # 150 min ago
        order.amount = 0.001
        order.price = 50000

        ctrl.connector = MagicMock()
        ctrl.connector._in_flight_orders = {"order-1": order}

        # Mock telegram
        ctrl.telegram_alerter = MagicMock()
        ctrl.telegram_alerter.enabled = False

        # logger
        ctrl.logger = MagicMock(return_value=MagicMock())

        return ctrl

    def test_auto_cancel_calls_connector_cancel(self):
        import asyncio

        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        ctrl = self._make_controller_stub(auto_cancel=True)
        # Bind the real method
        ctrl._cleanup_stale_orders = (
            MultiCoinGridController._cleanup_stale_orders.__get__(ctrl)
        )
        asyncio.get_event_loop().run_until_complete(
            ctrl._cleanup_stale_orders()
        )
        ctrl.connector.cancel.assert_called_once_with("BTC-USD", "order-1")

    def test_auto_cancel_disabled_no_cancel(self):
        import asyncio

        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        ctrl = self._make_controller_stub(auto_cancel=False)
        ctrl._cleanup_stale_orders = (
            MultiCoinGridController._cleanup_stale_orders.__get__(ctrl)
        )
        asyncio.get_event_loop().run_until_complete(
            ctrl._cleanup_stale_orders()
        )
        ctrl.connector.cancel.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════
# O8: Rotation cooldown after normal close
# ═══════════════════════════════════════════════════════════════════════════
class TestRotationCooldown(unittest.TestCase):
    """Verify _add_to_blacklist supports duration_override for O8."""

    def _make_ctrl_stub(self, cooldown_sec=300, blacklist_sec=1800):
        ctrl = MagicMock()
        ctrl.config = MagicMock()
        ctrl.config.blacklist_after_timeout_sec = blacklist_sec
        ctrl.config.rotation_cooldown_after_close_sec = cooldown_sec
        ctrl.session_blacklist = {}
        ctrl.logger = MagicMock(return_value=MagicMock())
        return ctrl

    def test_duration_override_uses_shorter_cooldown(self):
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        ctrl = self._make_ctrl_stub(cooldown_sec=300, blacklist_sec=1800)
        bound = MultiCoinGridController._add_to_blacklist.__get__(ctrl)
        now = time.time()
        bound("BTC-USD", "T2-O8:ROTATION_COOLDOWN:TAKE_PROFIT", now,
              duration_override=300)

        self.assertIn("BTC-USD", ctrl.session_blacklist)
        expected_expiry = now + 300
        actual_expiry = ctrl.session_blacklist["BTC-USD"]
        self.assertAlmostEqual(actual_expiry, expected_expiry, delta=2)

    def test_default_blacklist_without_override(self):
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

        ctrl = self._make_ctrl_stub(cooldown_sec=300, blacklist_sec=1800)
        bound = MultiCoinGridController._add_to_blacklist.__get__(ctrl)
        now = time.time()
        bound("ETH-USD", "NO_FILL_TIMEOUT", now)

        expected_expiry = now + 1800
        actual_expiry = ctrl.session_blacklist["ETH-USD"]
        self.assertAlmostEqual(actual_expiry, expected_expiry, delta=2)


if __name__ == "__main__":
    unittest.main()
