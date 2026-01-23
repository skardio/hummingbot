"""
Tests for US-002: Auto-Quarantine / Pair Health Monitor

Tests the pair health monitor that auto-quarantines unhealthy pairs.
"""
# Direct import to avoid utils/__init__.py heavy dependencies
import importlib.util
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "pair_health_monitor",
    Path(__file__).parent.parent / "utils" / "pair_health_monitor.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

PairHealthMonitor = _module.PairHealthMonitor
FailureType = _module.FailureType
PairHealth = _module.PairHealth
QuarantineInfo = _module.QuarantineInfo


class TestPairHealthMonitor:
    """Test suite for PairHealthMonitor."""

    def test_monitor_initialization(self):
        """Test monitor initializes with correct defaults."""
        monitor = PairHealthMonitor()

        assert monitor.quarantine_threshold == 10
        assert monitor.quarantine_window_sec == 120.0
        assert monitor.quarantine_duration_sec == 900.0
        assert monitor.enabled is True

    def test_monitor_custom_config(self):
        """Test monitor with custom configuration."""
        monitor = PairHealthMonitor(
            quarantine_threshold=5,
            quarantine_window_sec=60.0,
            quarantine_duration_sec=300.0
        )

        assert monitor.quarantine_threshold == 5
        assert monitor.quarantine_window_sec == 60.0
        assert monitor.quarantine_duration_sec == 300.0

    def test_disabled_monitor_never_quarantines(self):
        """Test disabled monitor never quarantines."""
        monitor = PairHealthMonitor(enabled=False, quarantine_threshold=1)

        # Record many failures
        for _ in range(10):
            monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")

        assert monitor.is_quarantined("BTC-USDT") is False

    def test_single_failure_no_quarantine(self):
        """Test single failure doesn't trigger quarantine."""
        monitor = PairHealthMonitor(quarantine_threshold=5)

        was_quarantined = monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")

        assert was_quarantined is False
        assert monitor.is_quarantined("BTC-USDT") is False

    def test_threshold_breach_triggers_quarantine(self):
        """Test breaching threshold triggers quarantine."""
        monitor = PairHealthMonitor(
            quarantine_threshold=3,
            quarantine_window_sec=60.0,
            quarantine_duration_sec=10.0
        )

        # Record failures up to threshold
        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        was_quarantined = monitor.record_failure("BTC-USDT", "NO_ORDERBOOK_DATA")

        assert was_quarantined is True
        assert monitor.is_quarantined("BTC-USDT") is True

    def test_quarantine_expires(self):
        """Test quarantine expires after duration."""
        monitor = PairHealthMonitor(
            quarantine_threshold=1,
            quarantine_window_sec=60.0,
            quarantine_duration_sec=0.1  # 100ms for testing
        )

        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        assert monitor.is_quarantined("BTC-USDT") is True

        # Wait for quarantine to expire
        time.sleep(0.15)

        assert monitor.is_quarantined("BTC-USDT") is False

    def test_multiple_pairs_independent(self):
        """Test different pairs are tracked independently."""
        monitor = PairHealthMonitor(quarantine_threshold=2)

        # Quarantine BTC
        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")

        # ETH has no failures
        assert monitor.is_quarantined("BTC-USDT") is True
        assert monitor.is_quarantined("ETH-USDT") is False

    def test_get_quarantined_pairs(self):
        """Test getting list of quarantined pairs."""
        monitor = PairHealthMonitor(quarantine_threshold=1)

        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        monitor.record_failure("ETH-USDT", "NO_ORDERBOOK_DATA")

        quarantined = monitor.get_quarantined_pairs()

        assert "BTC-USDT" in quarantined
        assert "ETH-USDT" in quarantined
        assert len(quarantined) == 2

    def test_get_quarantine_info(self):
        """Test getting quarantine details."""
        monitor = PairHealthMonitor(
            quarantine_threshold=2,
            quarantine_duration_sec=600
        )

        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        monitor.record_failure("BTC-USDT", "STALE_ORDERBOOK")

        info = monitor.get_quarantine_info("BTC-USDT")

        assert info is not None
        assert info.pair == "BTC-USDT"
        assert info.failure_count == 2
        assert info.release_at > time.time()

    def test_quarantine_info_none_when_not_quarantined(self):
        """Test quarantine info returns None when not quarantined."""
        monitor = PairHealthMonitor()

        info = monitor.get_quarantine_info("BTC-USDT")

        assert info is None

    def test_record_success(self):
        """Test recording successful data fetch."""
        monitor = PairHealthMonitor()

        monitor.record_success("BTC-USDT")

        stats = monitor.get_statistics()
        assert stats["total_pairs_tracked"] == 1

    def test_force_release(self):
        """Test forcing release from quarantine."""
        monitor = PairHealthMonitor(
            quarantine_threshold=1,
            quarantine_duration_sec=3600  # Long duration
        )

        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        assert monitor.is_quarantined("BTC-USDT") is True

        released = monitor.force_release("BTC-USDT")

        assert released is True
        assert monitor.is_quarantined("BTC-USDT") is False

    def test_force_release_not_quarantined(self):
        """Test force release on non-quarantined pair."""
        monitor = PairHealthMonitor()

        released = monitor.force_release("BTC-USDT")

        assert released is False

    def test_reset(self):
        """Test resetting monitor state."""
        monitor = PairHealthMonitor(quarantine_threshold=1)

        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        monitor.record_failure("ETH-USDT", "NO_PRICE_DATA")

        monitor.reset()

        assert monitor.is_quarantined("BTC-USDT") is False
        assert monitor.is_quarantined("ETH-USDT") is False
        assert monitor.get_statistics()["total_pairs_tracked"] == 0

    def test_statistics(self):
        """Test statistics gathering."""
        monitor = PairHealthMonitor(quarantine_threshold=2)

        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")  # Triggers quarantine
        monitor.record_failure("ETH-USDT", "STALE_PRICE")

        stats = monitor.get_statistics()

        assert stats["enabled"] is True
        assert stats["total_pairs_tracked"] == 2
        assert stats["currently_quarantined"] == 1
        assert stats["total_quarantines"] == 1
        assert "BTC-USDT" in stats["quarantined_pairs"]

    def test_failures_expire_outside_window(self):
        """Test failures outside window are not counted."""
        monitor = PairHealthMonitor(
            quarantine_threshold=3,
            quarantine_window_sec=0.1  # 100ms window
        )

        # Record 2 failures
        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")

        # Wait for them to expire
        time.sleep(0.15)

        # This should not trigger quarantine as previous failures expired
        was_quarantined = monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")

        assert was_quarantined is False
        assert monitor.is_quarantined("BTC-USDT") is False

    def test_different_failure_types(self):
        """Test different failure types are all counted."""
        monitor = PairHealthMonitor(quarantine_threshold=4)

        monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
        monitor.record_failure("BTC-USDT", "NO_ORDERBOOK_DATA")
        monitor.record_failure("BTC-USDT", "STALE_PRICE")
        was_quarantined = monitor.record_failure("BTC-USDT", "STALE_ORDERBOOK")

        assert was_quarantined is True
        assert monitor.is_quarantined("BTC-USDT") is True


class TestFailureType:
    """Test FailureType enum."""

    def test_all_types_exist(self):
        """Test all expected failure types exist."""
        assert FailureType.NO_PRICE_DATA is not None
        assert FailureType.NO_ORDERBOOK_DATA is not None
        assert FailureType.STALE_PRICE is not None
        assert FailureType.STALE_ORDERBOOK is not None
        assert FailureType.SPREAD_TOO_WIDE is not None
        assert FailureType.DEPTH_INSUFFICIENT is not None


class TestPairHealth:
    """Test PairHealth dataclass."""

    def test_add_failure(self):
        """Test adding failures to health state."""
        health = PairHealth(pair="BTC-USDT")

        health.add_failure(FailureType.NO_PRICE_DATA)
        health.add_failure(FailureType.STALE_ORDERBOOK)

        assert len(health.failures) == 2

    def test_count_failures_in_window(self):
        """Test counting failures in rolling window."""
        health = PairHealth(pair="BTC-USDT")

        health.add_failure(FailureType.NO_PRICE_DATA)
        health.add_failure(FailureType.NO_PRICE_DATA)

        count = health.count_failures_in_window(60.0)
        assert count == 2

    def test_count_failures_by_type(self):
        """Test counting failures by type."""
        health = PairHealth(pair="BTC-USDT")

        health.add_failure(FailureType.NO_PRICE_DATA)
        health.add_failure(FailureType.NO_PRICE_DATA)
        health.add_failure(FailureType.STALE_ORDERBOOK)

        counts = health.count_failures_by_type(60.0)

        assert counts[FailureType.NO_PRICE_DATA] == 2
        assert counts[FailureType.STALE_ORDERBOOK] == 1


class TestQuarantineInfo:
    """Test QuarantineInfo dataclass."""

    def test_quarantine_info_creation(self):
        """Test creating quarantine info."""
        now = time.time()
        info = QuarantineInfo(
            pair="BTC-USDT",
            quarantined_at=now,
            release_at=now + 600,
            reason="10 failures in 120s",
            failure_count=10
        )

        assert info.pair == "BTC-USDT"
        assert info.failure_count == 10
        assert info.release_at > info.quarantined_at
