"""
Unit tests for US-001: Fail-Closed Market Data Gate

Tests that the SmartEntry filter correctly DENIES entries when:
- Orderbook data is unavailable
- Price data is unavailable

These tests verify the fail-closed behavior that prevents "blind" entries.
"""
import logging
import unittest

# Import SmartEntry components
from multi_coin_grid_pro.logic.smart_entry import SmartEntryBaseConfig, SmartEntryFilter


def create_test_config(**overrides) -> SmartEntryBaseConfig:
    """
    Create a SmartEntryBaseConfig with default test values.

    SmartEntryBaseConfig has 12 required positional arguments.
    This helper provides sensible defaults for all of them.
    """
    defaults = {
        # Required positional arguments (in order)
        'rsi_buy_max': 45.0,
        'rsi_extreme_low': 25.0,
        'rsi_block_min': 70.0,
        'vwap_max_deviation_pct': 3.0,
        'min_wick_ratio': 0.15,
        'max_atr_pct_for_grid': 8.0,
        'min_atr_pct_for_grid': 0.5,
        'max_5m_spike_pct': 3.0,
        'max_down_accel_pct': -4.0,
        'max_up_accel_pct': 4.0,
        'max_trend_24h_pct': 15.0,
        'min_trend_24h_pct': -15.0,
        # Optional fields with defaults
        'require_orderbook': True,
        'require_price': True,
    }
    defaults.update(overrides)
    return SmartEntryBaseConfig(**defaults)


class MockCandleIndicators:
    """Mock indicators for testing."""

    def __init__(self):
        self.rsi_14 = 30.0  # Oversold
        self.atr_pct = 2.0  # Normal volatility
        self.wick_ratio = 0.5
        self.prev_rsi = 35.0
        self.rsi_slope = -0.5
        self.close = 100.0
        self.ema_21 = 99.0


class TestFailClosedConfig(unittest.TestCase):
    """Tests for US-001: Config flags for fail-closed behavior."""

    def test_config_defaults_to_require_data(self):
        """Default config should require orderbook and price data."""
        config = create_test_config()
        self.assertTrue(config.require_orderbook)
        self.assertTrue(config.require_price)

    def test_config_can_disable_requirements(self):
        """Config should allow disabling requirements (for testing/backtest)."""
        config = create_test_config(
            require_orderbook=False,
            require_price=False,
        )
        self.assertFalse(config.require_orderbook)
        self.assertFalse(config.require_price)


class TestSmartEntrySpreadCheck(unittest.TestCase):
    """Tests for spread check fail-closed behavior."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = create_test_config(
            require_price=True,
        )
        self.logger = logging.getLogger("test")

    def test_spread_check_fails_when_no_price(self):
        """US-001: Spread check should DENY entry when bid/ask unavailable."""
        filter_instance = SmartEntryFilter(
            base_cfg=self.config,
            coin_profiles={},
            logger=self.logger,
            exchange_connector=None,
            connector_name=None,
        )

        # Call with None prices
        passed, reason, spread = filter_instance._check_spread(
            symbol="BTC-USDT",
            bid_price=None,
            ask_price=None,
            max_spread_pct=0.5,
        )

        # With US-001 fix and require_price=True, this should FAIL
        self.assertFalse(passed)
        # Reason should mention price
        self.assertTrue(
            "price" in reason.lower() or
            "no_price" in reason.lower() or
            "bid" in reason.lower() or
            "ask" in reason.lower()
        )

    def test_spread_check_fails_when_price_is_zero(self):
        """US-001: Spread check should DENY entry when bid/ask is zero."""
        filter_instance = SmartEntryFilter(
            base_cfg=self.config,
            coin_profiles={},
            logger=self.logger,
        )

        passed, reason, spread = filter_instance._check_spread(
            symbol="BTC-USDT",
            bid_price=0.0,
            ask_price=0.0,
            max_spread_pct=0.5,
        )

        # Zero prices should fail
        self.assertFalse(passed)

    def test_spread_check_passes_with_valid_prices(self):
        """Spread check should PASS when valid prices and spread is OK."""
        filter_instance = SmartEntryFilter(
            base_cfg=self.config,
            coin_profiles={},
            logger=self.logger,
        )

        passed, reason, spread = filter_instance._check_spread(
            symbol="BTC-USDT",
            bid_price=100.0,
            ask_price=100.2,  # 0.2% spread
            max_spread_pct=0.5,  # Max 0.5%
        )

        self.assertTrue(passed)
        self.assertLess(spread, 0.5)

    def test_spread_check_fails_when_spread_too_wide(self):
        """Spread check should DENY when spread exceeds max."""
        filter_instance = SmartEntryFilter(
            base_cfg=self.config,
            coin_profiles={},
            logger=self.logger,
        )

        passed, reason, spread = filter_instance._check_spread(
            symbol="BTC-USDT",
            bid_price=100.0,
            ask_price=101.0,  # 1% spread
            max_spread_pct=0.5,  # Max 0.5%
        )

        self.assertFalse(passed)
        self.assertIn("too wide", reason.lower())


class TestKrakenFailClosed(unittest.TestCase):
    """Tests for Kraken-specific fail-closed scenarios."""

    def setUp(self):
        """Set up Kraken test fixtures."""
        self.config = create_test_config(
            require_orderbook=True,
            require_price=True,
        )
        self.logger = logging.getLogger("test_kraken")

    def test_kraken_eur_pair_no_prices(self):
        """Kraken EUR pair: should fail closed without prices."""
        filter_instance = SmartEntryFilter(
            base_cfg=self.config,
            coin_profiles={},
            logger=self.logger,
            connector_name="kraken",
        )

        passed, reason, spread = filter_instance._check_spread(
            symbol="ETH-EUR",
            bid_price=None,
            ask_price=None,
            max_spread_pct=0.5,
        )

        self.assertFalse(passed)


if __name__ == "__main__":
    unittest.main()
