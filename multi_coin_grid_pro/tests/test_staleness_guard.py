"""
Tests for US-008: StalenessGuard

Tests the staleness guard which rejects entries when market data is stale.
"""
import importlib.util
import time
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "staleness_guard",
    Path(__file__).parent.parent / "utils" / "staleness_guard.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

DataFreshness = _module.DataFreshness
StalenessGuard = _module.StalenessGuard
StaleReason = _module.StaleReason


class TestStalenessGuard:
    """Test suite for StalenessGuard."""

    def test_guard_initialization(self):
        """Test guard initializes with correct defaults."""
        guard = StalenessGuard()

        assert guard.max_price_age_ms == 2000
        assert guard.max_orderbook_age_ms == 5000
        assert guard.enabled is True

    def test_guard_custom_config(self):
        """Test guard with custom configuration."""
        guard = StalenessGuard(
            max_price_age_ms=1000,
            max_orderbook_age_ms=3000,
            enabled=True
        )

        assert guard.max_price_age_ms == 1000
        assert guard.max_orderbook_age_ms == 3000

    def test_disabled_guard_always_fresh(self):
        """Test disabled guard always returns fresh."""
        guard = StalenessGuard(enabled=False)

        # No data updated, but should still pass
        result = guard.is_data_fresh("BTC-USDT")

        assert result.is_fresh is True
        assert result.reason == StaleReason.FRESH

    def test_no_price_data_fails(self):
        """Test fails when no price data is available."""
        guard = StalenessGuard(enabled=True)

        result = guard.is_data_fresh("BTC-USDT", require_price=True)

        assert result.is_fresh is False
        assert result.reason == StaleReason.NO_PRICE_DATA
        assert "No price data" in result.details

    def test_no_orderbook_data_fails(self):
        """Test fails when no orderbook data is available."""
        guard = StalenessGuard(enabled=True)

        # Update price but not orderbook
        guard.update_price("BTC-USDT", 50000.0)

        result = guard.is_data_fresh("BTC-USDT", require_price=True, require_orderbook=True)

        assert result.is_fresh is False
        assert result.reason == StaleReason.NO_ORDERBOOK_DATA

    def test_fresh_data_passes(self):
        """Test fresh data passes all checks."""
        guard = StalenessGuard(
            max_price_age_ms=2000,
            max_orderbook_age_ms=5000,
            enabled=True
        )

        # Update both price and orderbook
        guard.update_price("BTC-USDT", 50000.0)
        guard.update_orderbook("BTC-USDT")

        result = guard.is_data_fresh("BTC-USDT")

        assert result.is_fresh is True
        assert result.reason == StaleReason.FRESH
        assert result.price_age_ms is not None
        assert result.orderbook_age_ms is not None
        assert result.price_age_ms < 100  # Should be very fresh
        assert result.orderbook_age_ms < 100

    def test_stale_price_fails(self):
        """Test stale price data fails."""
        guard = StalenessGuard(
            max_price_age_ms=100,  # Very short for testing
            max_orderbook_age_ms=5000,
            enabled=True
        )

        # Update data
        guard.update_price("BTC-USDT", 50000.0)
        guard.update_orderbook("BTC-USDT")

        # Wait for price to become stale
        time.sleep(0.15)  # 150ms > 100ms threshold

        result = guard.is_data_fresh("BTC-USDT")

        assert result.is_fresh is False
        assert result.reason == StaleReason.STALE_PRICE
        assert "stale" in result.details.lower()

    def test_stale_orderbook_fails(self):
        """Test stale orderbook data fails."""
        guard = StalenessGuard(
            max_price_age_ms=10000,  # Long threshold for price
            max_orderbook_age_ms=100,  # Very short for orderbook
            enabled=True
        )

        # Update data
        guard.update_price("BTC-USDT", 50000.0)
        guard.update_orderbook("BTC-USDT")

        # Wait for orderbook to become stale
        time.sleep(0.15)  # 150ms > 100ms threshold

        result = guard.is_data_fresh("BTC-USDT")

        assert result.is_fresh is False
        assert result.reason == StaleReason.STALE_ORDERBOOK

    def test_multiple_pairs_tracked_independently(self):
        """Test different pairs are tracked independently."""
        guard = StalenessGuard(enabled=True)

        # Update BTC only
        guard.update_price("BTC-USDT", 50000.0)
        guard.update_orderbook("BTC-USDT")

        # ETH should fail
        result_eth = guard.is_data_fresh("ETH-USDT")
        assert result_eth.is_fresh is False

        # BTC should pass
        result_btc = guard.is_data_fresh("BTC-USDT")
        assert result_btc.is_fresh is True

    def test_get_price_age_ms(self):
        """Test getting price age in milliseconds."""
        guard = StalenessGuard(enabled=True)

        # No data - should return None
        assert guard.get_price_age_ms("BTC-USDT") is None

        # Update price
        guard.update_price("BTC-USDT", 50000.0)
        time.sleep(0.1)

        age = guard.get_price_age_ms("BTC-USDT")
        assert age is not None
        assert age >= 100  # At least 100ms

    def test_get_orderbook_age_ms(self):
        """Test getting orderbook age in milliseconds."""
        guard = StalenessGuard(enabled=True)

        # No data - should return None
        assert guard.get_orderbook_age_ms("BTC-USDT") is None

        # Update orderbook
        guard.update_orderbook("BTC-USDT")
        time.sleep(0.1)

        age = guard.get_orderbook_age_ms("BTC-USDT")
        assert age is not None
        assert age >= 100  # At least 100ms

    def test_statistics(self):
        """Test statistics gathering."""
        guard = StalenessGuard(enabled=True)

        # Update some pairs
        guard.update_price("BTC-USDT", 50000.0)
        guard.update_price("ETH-USDT", 3000.0)
        guard.update_orderbook("BTC-USDT")

        stats = guard.get_statistics()

        assert stats["enabled"] is True
        assert stats["tracked_pairs_price"] == 2
        assert stats["tracked_pairs_orderbook"] == 1

    def test_clear_pair(self):
        """Test clearing a single pair."""
        guard = StalenessGuard(enabled=True)

        guard.update_price("BTC-USDT", 50000.0)
        guard.update_orderbook("BTC-USDT")

        # Should be fresh before clearing
        assert guard.is_data_fresh("BTC-USDT").is_fresh is True

        # Clear the pair
        guard.clear_pair("BTC-USDT")

        # Should fail after clearing
        assert guard.is_data_fresh("BTC-USDT").is_fresh is False

    def test_reset(self):
        """Test resetting all data."""
        guard = StalenessGuard(enabled=True)

        guard.update_price("BTC-USDT", 50000.0)
        guard.update_price("ETH-USDT", 3000.0)
        guard.update_orderbook("BTC-USDT")
        guard.update_orderbook("ETH-USDT")

        # Reset all
        guard.reset()

        # Both should fail now
        assert guard.is_data_fresh("BTC-USDT").is_fresh is False
        assert guard.is_data_fresh("ETH-USDT").is_fresh is False

    def test_price_only_check(self):
        """Test checking only price freshness."""
        guard = StalenessGuard(enabled=True)

        # Update only price
        guard.update_price("BTC-USDT", 50000.0)

        # Should pass when only requiring price
        result = guard.is_data_fresh("BTC-USDT", require_price=True, require_orderbook=False)
        assert result.is_fresh is True

    def test_orderbook_only_check(self):
        """Test checking only orderbook freshness."""
        guard = StalenessGuard(enabled=True)

        # Update only orderbook
        guard.update_orderbook("BTC-USDT")

        # Should pass when only requiring orderbook
        result = guard.is_data_fresh("BTC-USDT", require_price=False, require_orderbook=True)
        assert result.is_fresh is True


class TestDataFreshness:
    """Test DataFreshness dataclass."""

    def test_freshness_result_fresh(self):
        """Test fresh result."""
        result = DataFreshness(
            is_fresh=True,
            reason=StaleReason.FRESH,
            price_age_ms=100.0,
            orderbook_age_ms=200.0,
            details="All data fresh"
        )

        assert result.is_fresh is True
        assert result.reason == StaleReason.FRESH
        assert result.price_age_ms == 100.0
        assert result.orderbook_age_ms == 200.0

    def test_freshness_result_stale(self):
        """Test stale result."""
        result = DataFreshness(
            is_fresh=False,
            reason=StaleReason.STALE_PRICE,
            price_age_ms=5000.0,
            orderbook_age_ms=200.0,
            details="Price too old"
        )

        assert result.is_fresh is False
        assert result.reason == StaleReason.STALE_PRICE


class TestStaleReason:
    """Test StaleReason enum."""

    def test_all_reasons_exist(self):
        """Test all expected reasons exist."""
        assert StaleReason.FRESH is not None
        assert StaleReason.STALE_PRICE is not None
        assert StaleReason.STALE_ORDERBOOK is not None
        assert StaleReason.NO_PRICE_DATA is not None
        assert StaleReason.NO_ORDERBOOK_DATA is not None

    def test_reason_values(self):
        """Test reason enum values."""
        assert StaleReason.FRESH.value == "FRESH"
        assert StaleReason.STALE_PRICE.value == "STALE_PRICE"
        assert StaleReason.STALE_ORDERBOOK.value == "STALE_ORDERBOOK"
