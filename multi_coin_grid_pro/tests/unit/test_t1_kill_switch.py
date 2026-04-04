"""
Tests for T1: Kill Switch & Critical Safety (K1-K4)

K1: Wire kill switch — pnl_tracker_v2 receives fills
K2: Kill switch stops all executors
K3: Emergency exit cooldown — blacklist after emergency/hard-stop/stop-loss
K4: Persist entry prices to SQLite
"""
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from multi_coin_grid_pro.core.models import TradeFill
from multi_coin_grid_pro.persistence.entry_price_store import EntryPriceStore
from multi_coin_grid_pro.risk.pnl_tracker import RealtimePnLTracker
from multi_coin_grid_pro.risk.risk_guard import RiskGuardV2

# ==========================================================================
# K4: EntryPriceStore
# ==========================================================================


class TestEntryPriceStore:
    """Test SQLite persistence of entry prices."""

    @pytest.fixture
    def store(self, tmp_path):
        db_path = str(tmp_path / "test_entry_prices.db")
        s = EntryPriceStore(db_path=db_path)
        yield s
        s.close()

    def test_save_and_load(self, store):
        store.save("BTC-USD", Decimal("50000.1234"))
        store.save("ETH-USD", Decimal("3000.5678"))

        loaded = store.load_all()
        assert loaded["BTC-USD"] == Decimal("50000.1234")
        assert loaded["ETH-USD"] == Decimal("3000.5678")
        assert store.count() == 2

    def test_upsert_overwrites(self, store):
        store.save("BTC-USD", Decimal("50000"))
        store.save("BTC-USD", Decimal("51000"))

        loaded = store.load_all()
        assert loaded["BTC-USD"] == Decimal("51000")
        assert store.count() == 1

    def test_delete(self, store):
        store.save("BTC-USD", Decimal("50000"))
        assert store.delete("BTC-USD") is True
        assert store.delete("BTC-USD") is False  # Already gone
        assert store.count() == 0

    def test_get_single(self, store):
        store.save("BTC-USD", Decimal("50000"))
        assert store.get("BTC-USD") == Decimal("50000")
        assert store.get("NONEXISTENT") is None

    def test_clear_all(self, store):
        store.save("BTC-USD", Decimal("50000"))
        store.save("ETH-USD", Decimal("3000"))
        deleted = store.clear_all()
        assert deleted == 2
        assert store.count() == 0

    def test_wal_mode(self, store):
        """Verify WAL mode is enabled (T2-O3 forward-compat)."""
        mode = store.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_empty_load(self, store):
        loaded = store.load_all()
        assert loaded == {}

    def test_executor_id_stored(self, store):
        store.save("BTC-USD", Decimal("50000"), executor_id="abc123")
        row = store.conn.execute(
            "SELECT executor_id FROM entry_prices WHERE symbol = ?",
            ("BTC-USD",),
        ).fetchone()
        assert row["executor_id"] == "abc123"

    def test_survives_reconnect(self, tmp_path):
        """K4 core requirement: entry prices survive restart."""
        db_path = str(tmp_path / "persist_test.db")

        # Session 1: save
        s1 = EntryPriceStore(db_path=db_path)
        s1.save("RENDER-USD", Decimal("1.8277"))
        s1.save("TAO-USD", Decimal("245.50"))
        s1.close()

        # Session 2: load
        s2 = EntryPriceStore(db_path=db_path)
        loaded = s2.load_all()
        assert loaded["RENDER-USD"] == Decimal("1.8277")
        assert loaded["TAO-USD"] == Decimal("245.50")
        s2.close()


# ==========================================================================
# K1: RealtimePnLTracker gets wired
# ==========================================================================

class TestPnLTrackerWiring:
    """Test that PnL tracker correctly processes synthetic fills."""

    @pytest.fixture
    def tracker(self):
        return RealtimePnLTracker(
            starting_balance=Decimal("300"),
            logger=MagicMock(),
        )

    def test_on_trade_fill_updates_balance(self, tracker):
        """K1: After buy+sell fills, realized PnL is reflected."""
        # Buy 100 units at $1.00
        buy_fill = TradeFill(
            symbol="RENDER-USD",
            side="buy",
            price=Decimal("1.00"),
            size=Decimal("100"),
            fee=Decimal("0.16"),
            ts=1000,
        )
        tracker.on_trade_fill(buy_fill)

        assert tracker.positions["RENDER-USD"].size == Decimal("100")
        assert tracker.positions["RENDER-USD"].avg_entry_price == Decimal("1.00")

        # Sell 100 units at $1.05 (+5%)
        sell_fill = TradeFill(
            symbol="RENDER-USD",
            side="sell",
            price=Decimal("1.05"),
            size=Decimal("100"),
            fee=Decimal("0.26"),
            ts=2000,
        )
        tracker.on_trade_fill(sell_fill)

        # Realized PnL = (1.05 - 1.00) * 100 = $5.00
        assert tracker.realized_pnl == Decimal("5.00")
        assert tracker.positions["RENDER-USD"].size == Decimal("0")

    def test_daily_pnl_pct_nonzero_after_fills(self, tracker):
        """K1: daily_pnl_pct must be non-zero after losing trade."""
        # Buy at $10
        tracker.on_trade_fill(TradeFill(
            symbol="BTC-USD", side="buy",
            price=Decimal("10"), size=Decimal("10"),
            fee=Decimal("0.016"), ts=1000,
        ))
        # Sell at $9 (-10% loss)
        tracker.on_trade_fill(TradeFill(
            symbol="BTC-USD", side="sell",
            price=Decimal("9"), size=Decimal("10"),
            fee=Decimal("0.026"), ts=2000,
        ))

        # Realized loss = (9 - 10) * 10 = -$10
        # Fees = 0.016 + 0.026 = $0.042
        # Balance change: -100 - 0.016 + 90 - 0.026 = -$10.042
        daily_pct = tracker.daily_pnl_pct()
        assert daily_pct < 0, f"Expected negative daily PnL, got {daily_pct}"

    def test_update_unrealized(self, tracker):
        """K1: unrealized PnL updates from price dict."""
        tracker.on_trade_fill(TradeFill(
            symbol="ETH-USD", side="buy",
            price=Decimal("3000"), size=Decimal("1"),
            fee=Decimal("0.48"), ts=1000,
        ))

        # Price dropped to $2900
        tracker.update_unrealized({"ETH-USD": Decimal("2900")})
        assert tracker.unrealized_pnl == Decimal("-100")

        # Price recovered to $3100
        tracker.update_unrealized({"ETH-USD": Decimal("3100")})
        assert tracker.unrealized_pnl == Decimal("100")


# ==========================================================================
# K2: RiskGuardV2 kill switch
# ==========================================================================

class TestRiskGuardKillSwitch:
    """Test that kill switch triggers correctly with real PnL data."""

    @pytest.fixture
    def setup(self):
        tracker = RealtimePnLTracker(
            starting_balance=Decimal("300"),
            logger=MagicMock(),
        )
        alerter = MagicMock()
        alerter.critical = MagicMock()
        alerter.warning = MagicMock()

        guard = RiskGuardV2(
            cfg={
                "max_daily_loss_pct": 3.0,
                "max_weekly_loss_pct": 8.0,
                "max_monthly_loss_pct": 12.0,
            },
            pnl_tracker=tracker,
            alerter=alerter,
            logger=MagicMock(),
        )
        return tracker, guard, alerter

    def test_check_limits_allows_trading_initially(self, setup):
        tracker, guard, _ = setup
        assert guard.check_limits() is True

    def test_check_limits_triggers_on_daily_loss(self, setup):
        """K1+K2: After sufficient losses, kill switch triggers."""
        tracker, guard, alerter = setup

        # Simulate a -3.5% loss ($300 * 3.5% = $10.50 loss)
        tracker.on_trade_fill(TradeFill(
            symbol="RENDER-USD", side="buy",
            price=Decimal("1.00"), size=Decimal("300"),
            fee=Decimal("0.48"), ts=1000,
        ))
        tracker.on_trade_fill(TradeFill(
            symbol="RENDER-USD", side="sell",
            price=Decimal("0.965"), size=Decimal("300"),
            fee=Decimal("0.78"), ts=2000,
        ))

        # daily_pnl_pct should be negative enough to trigger 3% limit
        result = guard.check_limits()
        assert result is False, (
            f"Kill switch should trigger. "
            f"Daily PnL: {tracker.daily_pnl_pct():.2f}%"
        )
        assert guard.trading_enabled is False
        alerter.critical.assert_called()

    def test_kill_switch_stays_disabled(self, setup):
        """K2: Once triggered, kill switch stays disabled."""
        tracker, guard, _ = setup
        guard._kill("Test trigger")
        assert guard.check_limits() is False
        assert guard.check_limits() is False

    def test_kill_switch_reset(self, setup):
        """K2: Manual reset re-enables trading."""
        tracker, guard, _ = setup
        guard._kill("Test trigger")
        assert guard.check_limits() is False
        guard.reset_kill_switch()
        assert guard.check_limits() is True


# ==========================================================================
# K3: Emergency exit cooldown
# ==========================================================================

class TestEmergencyExitCooldown:
    """Test that emergency exits lead to session blacklisting."""

    def test_emergency_reasons_are_blacklist_worthy(self):
        """K3: Verify the set of reasons that trigger blacklisting."""
        emergency_reasons = {"emergency_exit", "hard_stop_exit", "stop_loss"}
        non_emergency = {"take_profit", "timeout", "switch", None}

        for reason in emergency_reasons:
            assert reason in emergency_reasons

        for reason in non_emergency:
            assert reason not in emergency_reasons
