#!/usr/bin/env python3
"""
Test Multi-Coin Grid Bot V2 - Integration Test

This test requires the full hummingbot environment.
Skip if hummingbot modules are not available.
"""

import sys
import unittest
from pathlib import Path

# Add hummingbot to path
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))


def hummingbot_available():
    """Check if hummingbot modules are available"""
    try:
        from hummingbot.connector.connector_base import ConnectorBase
        return True
    except (ImportError, KeyError):
        return False


# Skip entire module if hummingbot not available
if not hummingbot_available():
    import pytest
    pytest.skip("Hummingbot modules not available", allow_module_level=True)


class TestBotReady(unittest.TestCase):
    """Integration tests that require full hummingbot environment"""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures"""
        if not hummingbot_available():
            raise unittest.SkipTest("Hummingbot modules not available")

    def test_strategy_imports(self):
        """Test that strategy can be imported"""
        from scripts.multi_coin_grid_v2 import MultiCoinGridStrategyConfig, MultiCoinGridStrategyV2
        self.assertIsNotNone(MultiCoinGridStrategyConfig)
        self.assertIsNotNone(MultiCoinGridStrategyV2)

    def test_config_creation(self):
        """Test that config can be created"""
        from scripts.multi_coin_grid_v2 import MultiCoinGridStrategyConfig
        config = MultiCoinGridStrategyConfig()
        self.assertIsNotNone(config)

    def test_markets_loaded(self):
        """Test that markets are loaded from config"""
        from scripts.multi_coin_grid_v2 import MultiCoinGridStrategyV2

        # Markets may be empty dict if dynamic discovery not run yet
        # or if loaded without network access
        markets = MultiCoinGridStrategyV2.markets
        self.assertIsInstance(markets, dict)

        # If markets were loaded, verify structure
        if markets:
            self.assertIn("kraken", markets)
            self.assertGreater(len(markets.get("kraken", set())), 0)


if __name__ == "__main__":
    if hummingbot_available():
        print("\n" + "=" * 70)
        print("  TESTING MULTI-COIN GRID BOT V2")
        print("=" * 70)
        unittest.main()
    else:
        print("⚠️  Skipping tests - hummingbot modules not available")
        print("   Run with full hummingbot environment for integration tests")
