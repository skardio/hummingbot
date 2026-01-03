"""
Unit tests for Cooldown Persistence Store (Story 10).

Tests SQLite cooldown persistence including:
- Basic CRUD operations
- Restart simulation (load active)
- Expiry and cleanup
- Shadow mode safety
- Multi-connector support
"""

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from multi_coin_grid_pro.persistence.cooldown_store import CooldownStore


class TestCooldownPersistence(unittest.TestCase):
    """Test suite for CooldownStore persistence layer."""

    def setUp(self):
        """Create temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_cooldowns.db")
        self.logger = MagicMock()
        self.store = CooldownStore(db_path=self.db_path, logger=self.logger)

    def tearDown(self):
        """Cleanup after each test."""
        try:
            self.store.close()
        except Exception:
            pass

        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    def test_basic_set_and_get_cooldown(self):
        """Test setting and retrieving a cooldown."""
        # Set cooldown
        success = self.store.set_cooldown(
            connector="kraken",
            symbol="PEPE-EUR",
            reason="PARABOLIC_DETECTED",
            cooldown_sec=1800
        )
        self.assertTrue(success)

        # Get remaining time
        remaining = self.store.get_remaining("kraken", "PEPE-EUR")
        self.assertIsNotNone(remaining)
        self.assertGreater(remaining, 1700)  # Should be close to 1800
        self.assertLessEqual(remaining, 1800)

        # Check if blocked
        is_blocked, rem_time = self.store.is_on_cooldown("kraken", "PEPE-EUR")
        self.assertTrue(is_blocked)
        self.assertEqual(remaining, rem_time)

    def test_cooldown_expiry(self):
        """Test that cooldowns expire correctly."""
        # Set short cooldown (2 seconds)
        self.store.set_cooldown(
            connector="kraken",
            symbol="SUI-EUR",
            reason="PARABOLIC_DETECTED",
            cooldown_sec=2
        )

        # Should be blocked immediately
        is_blocked, _ = self.store.is_on_cooldown("kraken", "SUI-EUR")
        self.assertTrue(is_blocked)

        # Wait for expiry
        time.sleep(2.5)

        # Should no longer be blocked
        is_blocked, _ = self.store.is_on_cooldown("kraken", "SUI-EUR")
        self.assertFalse(is_blocked)

    def test_cooldown_cleanup(self):
        """Test automatic cleanup of expired cooldowns."""
        # Set multiple cooldowns with different expiries
        self.store.set_cooldown("kraken", "PEPE-EUR", "TEST", 1)
        self.store.set_cooldown("kraken", "SUI-EUR", "TEST", 1)
        self.store.set_cooldown("kraken", "DOT-EUR", "TEST", 3600)  # Long cooldown

        # Wait for first two to expire
        time.sleep(1.5)

        # Cleanup
        deleted = self.store.cleanup_expired()
        self.assertEqual(deleted, 2)

        # DOT should still be blocked
        is_blocked, _ = self.store.is_on_cooldown("kraken", "DOT-EUR")
        self.assertTrue(is_blocked)

        # PEPE and SUI should not
        is_blocked, _ = self.store.is_on_cooldown("kraken", "PEPE-EUR")
        self.assertFalse(is_blocked)
        is_blocked, _ = self.store.is_on_cooldown("kraken", "SUI-EUR")
        self.assertFalse(is_blocked)

    def test_restart_simulation_load_active(self):
        """Test loading active cooldowns simulates bot restart."""
        # Set cooldowns
        self.store.set_cooldown("kraken", "PEPE-EUR", "PARABOLIC", 1800)
        self.store.set_cooldown("kraken", "SUI-EUR", "PARABOLIC", 3600)
        self.store.set_cooldown("bitget", "BTC-USDT", "PARABOLIC", 1200)

        # Simulate restart: close and reopen
        self.store.close()
        self.store = CooldownStore(db_path=self.db_path, logger=self.logger)

        # Load active cooldowns (all connectors)
        cooldowns_all = self.store.load_active()
        self.assertEqual(len(cooldowns_all), 3)
        self.assertIn("PEPE-EUR", cooldowns_all)
        self.assertIn("SUI-EUR", cooldowns_all)
        self.assertIn("BTC-USDT", cooldowns_all)

        # Load for specific connector
        cooldowns_kraken = self.store.load_active(connector="kraken")
        self.assertEqual(len(cooldowns_kraken), 2)
        self.assertIn("PEPE-EUR", cooldowns_kraken)
        self.assertIn("SUI-EUR", cooldowns_kraken)
        self.assertNotIn("BTC-USDT", cooldowns_kraken)

        # Verify cooldowns still work
        is_blocked, remaining = self.store.is_on_cooldown("kraken", "PEPE-EUR")
        self.assertTrue(is_blocked)
        self.assertGreater(remaining, 1700)

    def test_shadow_mode_no_db_writes(self):
        """Test that shadow mode prevents database writes."""
        # Attempt to set cooldown in shadow mode
        success = self.store.set_cooldown(
            connector="kraken",
            symbol="PEPE-EUR",
            reason="PARABOLIC_DETECTED",
            cooldown_sec=1800,
            shadow_mode=True
        )
        self.assertFalse(success)

        # Verify no cooldown was written
        remaining = self.store.get_remaining("kraken", "PEPE-EUR")
        self.assertIsNone(remaining)

        # Verify shadow mode log message
        self.logger.info.assert_any_call(
            "[SHADOW] Would persist cooldown for PEPE-EUR (1800s) - reason: PARABOLIC_DETECTED"
        )

    def test_upsert_behavior(self):
        """Test that setting cooldown twice updates (upserts) the entry."""
        # Set initial cooldown
        self.store.set_cooldown("kraken", "PEPE-EUR", "REASON_1", 1800)
        remaining_1 = self.store.get_remaining("kraken", "PEPE-EUR")

        # Wait a bit
        time.sleep(1)

        # Update cooldown (extend with new reason)
        self.store.set_cooldown("kraken", "PEPE-EUR", "REASON_2", 3600)
        remaining_2 = self.store.get_remaining("kraken", "PEPE-EUR")

        # Should have more time remaining now
        self.assertGreater(remaining_2, remaining_1)
        self.assertGreater(remaining_2, 3500)

        # Verify only one entry in DB
        all_cooldowns = self.store.get_all_cooldowns()
        pepe_cooldowns = [c for c in all_cooldowns if c["symbol"] == "PEPE-EUR"]
        self.assertEqual(len(pepe_cooldowns), 1)
        self.assertEqual(pepe_cooldowns[0]["reason"], "REASON_2")

    def test_multi_connector_isolation(self):
        """Test that cooldowns are isolated per connector."""
        # Set same symbol on different connectors
        self.store.set_cooldown("kraken", "PEPE-EUR", "PARABOLIC", 1800)
        self.store.set_cooldown("bitget", "PEPE-EUR", "PARABOLIC", 1800)

        # Both should be blocked
        is_blocked_kraken, _ = self.store.is_on_cooldown("kraken", "PEPE-EUR")
        is_blocked_bitget, _ = self.store.is_on_cooldown("bitget", "PEPE-EUR")
        self.assertTrue(is_blocked_kraken)
        self.assertTrue(is_blocked_bitget)

        # Load per connector
        kraken_cooldowns = self.store.load_active(connector="kraken")
        bitget_cooldowns = self.store.load_active(connector="bitget")

        self.assertEqual(len(kraken_cooldowns), 1)
        self.assertEqual(len(bitget_cooldowns), 1)

        # Clear only kraken
        deleted = self.store.clear_all(connector="kraken")
        self.assertEqual(deleted, 1)

        # Kraken should not be blocked, bitget still blocked
        is_blocked_kraken, _ = self.store.is_on_cooldown("kraken", "PEPE-EUR")
        is_blocked_bitget, _ = self.store.is_on_cooldown("bitget", "PEPE-EUR")
        self.assertFalse(is_blocked_kraken)
        self.assertTrue(is_blocked_bitget)

    def test_get_all_cooldowns_debugging(self):
        """Test get_all_cooldowns for debugging/monitoring."""
        # Set multiple cooldowns
        self.store.set_cooldown("kraken", "PEPE-EUR", "PARABOLIC", 1800)
        self.store.set_cooldown("kraken", "SUI-EUR", "VWAP_SLOPE", 1200)
        self.store.set_cooldown("bitget", "BTC-USDT", "PARABOLIC", 3600)

        # Get all
        all_cooldowns = self.store.get_all_cooldowns()
        self.assertEqual(len(all_cooldowns), 3)

        # Verify structure
        for cooldown in all_cooldowns:
            self.assertIn("connector", cooldown)
            self.assertIn("symbol", cooldown)
            self.assertIn("reason", cooldown)
            self.assertIn("expires_at", cooldown)
            self.assertIn("created_at", cooldown)

        # Get for specific connector
        kraken_cooldowns = self.store.get_all_cooldowns(connector="kraken")
        self.assertEqual(len(kraken_cooldowns), 2)

    def test_clear_all_cooldowns(self):
        """Test clearing all cooldowns."""
        # Set multiple cooldowns
        self.store.set_cooldown("kraken", "PEPE-EUR", "PARABOLIC", 1800)
        self.store.set_cooldown("kraken", "SUI-EUR", "PARABOLIC", 1800)
        self.store.set_cooldown("bitget", "BTC-USDT", "PARABOLIC", 1800)

        # Clear all
        deleted = self.store.clear_all()
        self.assertEqual(deleted, 3)

        # Verify all cleared
        cooldowns = self.store.load_active()
        self.assertEqual(len(cooldowns), 0)

    def test_expired_cooldown_returns_none(self):
        """Test that expired cooldowns return None for remaining time."""
        # Set very short cooldown
        self.store.set_cooldown("kraken", "PEPE-EUR", "TEST", 1)

        # Wait for expiry
        time.sleep(1.5)

        # Should return None
        remaining = self.store.get_remaining("kraken", "PEPE-EUR")
        self.assertIsNone(remaining)

        # is_on_cooldown should also return False
        is_blocked, rem = self.store.is_on_cooldown("kraken", "PEPE-EUR")
        self.assertFalse(is_blocked)
        self.assertIsNone(rem)

    def test_database_persistence_across_instances(self):
        """Test that cooldowns persist across CooldownStore instances."""
        # Set cooldown with first instance
        self.store.set_cooldown("kraken", "PEPE-EUR", "PARABOLIC", 1800)
        self.store.close()

        # Create new instance with same DB
        store2 = CooldownStore(db_path=self.db_path, logger=self.logger)

        # Should still be blocked
        is_blocked, remaining = store2.is_on_cooldown("kraken", "PEPE-EUR")
        self.assertTrue(is_blocked)
        self.assertGreater(remaining, 1700)

        store2.close()


if __name__ == "__main__":
    unittest.main()
