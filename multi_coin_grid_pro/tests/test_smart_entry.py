"""
Unit tests for SmartEntryFilter v2.0
"""
import logging
import sys
import unittest
from decimal import Decimal
from pathlib import Path

from hummingbot.core.data_type.order_book_row import OrderBookRow
from multi_coin_grid_pro.core.models import CandleIndicators  # noqa: E402
from multi_coin_grid_pro.logic.smart_entry import SmartEntryBaseConfig, SmartEntryFilter  # noqa: E402

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestSmartEntryFilter(unittest.TestCase):
    """Test SmartEntry v2.0 filtering logic"""

    def setUp(self):
        """Set up test fixtures"""
        self.logger = logging.getLogger("test")
        self.logger.setLevel(logging.CRITICAL)  # Suppress logs during tests

        # Base configuration (matches config.prod.yaml v3.0)
        self.base_cfg = SmartEntryBaseConfig(
            rsi_buy_max=60.0,
            rsi_extreme_low=25.0,
            rsi_block_min=70.0,
            vwap_max_deviation_pct=3.0,
            min_wick_ratio=0.25,  # Updated to match v3.0 config
            max_atr_pct_for_grid=6.0,
            min_atr_pct_for_grid=0.5,
            max_5m_spike_pct=2.5,
            max_down_accel_pct=-1.0,
            max_up_accel_pct=1.5,
            max_trend_24h_pct=8.0,
            min_trend_24h_pct=-12.0,
            # Phase 2: Slippage Protection
            slippage_check_enabled=True,
            max_entry_spread_pct=0.5,
            # Phase 2: Order Book Depth
            depth_check_enabled=True,
            min_depth_multiplier=3.0,
            # Disable fail-closed for indicator tests (tested separately)
            require_price=False,
            require_orderbook=False,
        )

        # Coin profiles with overrides
        self.coin_profiles = {
            "ATOM-EUR": {
                "min_wick_ratio": 0.20,  # More lenient for ATOM
            },
            "SOL-EUR": {
                "max_atr_pct_for_grid": 5.0,  # More strict for SOL
            }
        }

        self.filter = SmartEntryFilter(self.base_cfg, self.coin_profiles, self.logger)

    def test_good_entry_conditions(self):
        """Test entry allowed with good conditions"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,  # Good RSI
            vwap=Decimal("10.4"),  # Close to VWAP
            atr_pct=2.5,  # Good volatility
            wick_ratio=0.50,  # Good structure
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,  # Reasonable trend
            change_5m_pct=0.2,  # Small move
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertTrue(allowed, f"Entry should be allowed: {reason}")
        self.assertIn("BUY ALLOWED", reason)

    def test_rsi_overbought_block(self):
        """Test RSI overbought blocking"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=75.0,  # Too high
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("RSI", reason)
        self.assertIn("overbought", reason.lower())

    def test_rsi_oversold_block(self):
        """Test RSI oversold blocking (falling knife)"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=20.0,  # Too low
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("RSI", reason)
        self.assertIn("falling knife", reason.lower())

    def test_vwap_deviation_block(self):
        """Test VWAP deviation blocking"""
        indicators = CandleIndicators(
            price=Decimal("11.0"),
            rsi_14=50.0,
            vwap=Decimal("10.0"),  # 10% deviation
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("VWAP", reason)

    def test_wick_ratio_block(self):
        """Test wick ratio blocking (poor structure)"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.20,  # Too low (below 0.25 threshold)
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("wick_ratio", reason)
        self.assertIn("poor structure", reason.lower())

    def test_coin_profile_override(self):
        """Test coin-specific profile overrides"""
        # ATOM has min_wick_ratio=0.20 vs base 0.25
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.22,  # Between ATOM override (0.20) and base (0.25)
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        # Should fail for BTC (uses base config with 0.25 threshold)
        allowed_btc, _, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed_btc)

        # Should pass for ATOM (has override)
        allowed_atom, reason_atom, _ = self.filter.allows_entry("ATOM-EUR", indicators)
        self.assertTrue(allowed_atom, f"ATOM should be allowed with profile override: {reason_atom}")

    def test_atr_too_low(self):
        """Test ATR too low blocking"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=0.3,  # Too low
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("ATR", reason)
        self.assertIn("too low", reason.lower())

    def test_atr_too_high(self):
        """Test ATR too high blocking (chaos)"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=8.0,  # Too high
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("ATR", reason)
        self.assertIn("chaotic", reason.lower())

    def test_5m_spike_detection(self):
        """Test 5-minute spike blocking"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=5.0,  # Large spike
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("5m move", reason)
        self.assertIn("spike", reason.lower())

    def test_downside_acceleration_block(self):
        """Test downside acceleration blocking (falling knife)"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=-2.0,  # 1h much worse than 4h
            trend_4h_pct=0.5,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("accel", reason)

    def test_24h_trend_extended(self):
        """Test 24h trend too extended blocking"""
        indicators = CandleIndicators(
            price=Decimal("10.5"),
            rsi_14=50.0,
            vwap=Decimal("10.4"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=15.0,  # Too high
            change_5m_pct=0.2,
        )

        allowed, reason, _ = self.filter.allows_entry("BTC-EUR", indicators)
        self.assertFalse(allowed)
        self.assertIn("24h trend", reason)
        self.assertIn("extended", reason.lower())

    def test_spread_check_with_mock_exchange(self):
        """Test spread check with mock exchange connector"""
        from unittest.mock import Mock

        # Create mock exchange with order book that has snapshot property
        mock_orderbook = Mock()
        mock_orderbook.snapshot = (
            [[10.0, 100.0]],  # bids: [price, volume]
            [[10.10, 100.0]]  # asks: 1% spread
        )

        class MockExchange:
            def get_order_book(self, connector_name, trading_pair):
                return mock_orderbook

        # Create filter with mock exchange
        filter_with_exchange = SmartEntryFilter(
            self.base_cfg,
            self.coin_profiles,
            self.logger,
            exchange_connector=MockExchange(),
            connector_name="mock_exchange"
        )

        indicators = CandleIndicators(
            price=Decimal("10.05"),
            rsi_14=50.0,
            vwap=Decimal("10.0"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        # Spread is 1%, which exceeds max_entry_spread_pct (0.5%)
        allowed, reason, trace = filter_with_exchange.allows_entry("BTC-EUR", indicators, trace_enabled=True)
        self.assertFalse(allowed)
        self.assertIn("Spread", reason)
        self.assertIn("wide", reason.lower())

    def test_spread_check_passed(self):
        """Test spread check passes with acceptable spread"""
        from unittest.mock import Mock

        # Create mock exchange with order book that has snapshot property
        mock_orderbook = Mock()
        mock_orderbook.snapshot = (
            [[10.0, 100.0]],  # bids
            [[10.02, 100.0]]  # asks: 0.2% spread - OK
        )

        class MockExchange:
            def get_order_book(self, connector_name, trading_pair):
                return mock_orderbook

        filter_with_exchange = SmartEntryFilter(
            self.base_cfg,
            self.coin_profiles,
            self.logger,
            exchange_connector=MockExchange(),
            connector_name="mock_exchange"
        )

        indicators = CandleIndicators(
            price=Decimal("10.01"),
            rsi_14=50.0,
            vwap=Decimal("10.0"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, _ = filter_with_exchange.allows_entry("BTC-EUR", indicators)
        self.assertTrue(allowed)

    def test_depth_check_insufficient(self):
        """Test order book depth check rejects insufficient liquidity

        Verifies that orderbook depth calculation uses price×amount (quote currency)
        and correctly rejects orders when depth is insufficient.
        """
        from unittest.mock import Mock

        # Create mock that returns proper OrderBookRow objects
        mock_connector = Mock()
        mock_orderbook = Mock()

        # Setup orderbook snapshot: 5 BTC @ 10 EUR = 50 EUR depth (INSUFFICIENT for 100 EUR order × 3)
        mock_orderbook.snapshot = (
            [OrderBookRow(10.0, 5.0, 1)],  # bids (already imported at module level)
            [OrderBookRow(10.01, 5.0, 1)]  # asks
        )

        # Mock connector methods
        def get_order_book_side_effect(*args):
            if len(args) == 1:
                # Depth check path: get_order_book(trading_pair)
                return mock_orderbook
            else:
                # Spread check path: get_order_book(connector_name, trading_pair)
                return {
                    'bids': [[10.0, 5.0]],
                    'asks': [[10.01, 5.0]]
                }

        mock_connector.get_order_book = Mock(side_effect=get_order_book_side_effect)

        filter_with_exchange = SmartEntryFilter(
            self.base_cfg,
            self.coin_profiles,
            self.logger,
            exchange_connector=mock_connector,
            connector_name="mock_exchange"
        )

        indicators = CandleIndicators(
            price=Decimal("10.0"),
            rsi_14=50.0,
            vwap=Decimal("10.0"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        # Order size is 100 EUR, needs 3x depth = 300 EUR
        # But order book only has ~50 EUR on each side
        allowed, reason, trace = filter_with_exchange.allows_entry(
            "BTC-EUR",
            indicators,
            order_size_eur=100.0,
            trace_enabled=True
        )
        self.assertFalse(allowed, f"Entry should be blocked: allowed={allowed}, reason={reason}")
        self.assertIn("liquidity", reason.lower())

    def test_depth_check_sufficient(self):
        """Test order book depth check passes with sufficient liquidity

        Verifies that orderbook with 500 EUR depth passes check for 100 EUR order × 3.
        """
        from unittest.mock import Mock

        mock_connector = Mock()
        mock_orderbook = Mock()

        # Setup orderbook snapshot: 50 BTC @ 10 EUR = 500 EUR depth (SUFFICIENT)
        mock_orderbook.snapshot = (
            [OrderBookRow(10.0, 50.0, 1)],
            [OrderBookRow(10.01, 50.0, 1)]
        )

        def get_order_book_side_effect(*args):
            if len(args) == 1:
                return mock_orderbook
            else:
                return {
                    'bids': [[10.0, 50.0]],
                    'asks': [[10.01, 50.0]]
                }

        mock_connector.get_order_book = Mock(side_effect=get_order_book_side_effect)

        filter_with_exchange = SmartEntryFilter(
            self.base_cfg,
            self.coin_profiles,
            self.logger,
            exchange_connector=mock_connector,
            connector_name="mock_exchange"
        )

        indicators = CandleIndicators(
            price=Decimal("10.0"),
            rsi_14=50.0,
            vwap=Decimal("10.0"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        # Order size is 100 EUR, needs 3x depth = 300 EUR
        # Order book has 500 EUR on each side - sufficient
        allowed, reason, _ = filter_with_exchange.allows_entry(
            "BTC-EUR",
            indicators,
            order_size_eur=100.0
        )
        self.assertTrue(allowed)

    def test_depth_check_skipped_without_exchange(self):
        """Test depth check is skipped when no exchange connector is provided"""
        # Filter without exchange connector
        indicators = CandleIndicators(
            price=Decimal("10.0"),
            rsi_14=50.0,
            vwap=Decimal("10.0"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        # Should pass because depth check is skipped
        allowed, reason, _ = self.filter.allows_entry(
            "BTC-EUR",
            indicators,
            order_size_eur=100.0
        )
        self.assertTrue(allowed)

    def test_depth_no_orderbook_does_not_emit_gate_denied(self):
        """When get_orderbook_snapshot returns empty, depth check is skipped (not blocked)
        and NO gate_denied event is emitted — prevents false NO_ORDERBOOK_DATA inflation."""
        from unittest.mock import Mock

        mock_connector = Mock()
        mock_orderbook = Mock()
        # Empty bids/asks → get_orderbook_snapshot returns (None, None, None)
        mock_orderbook.snapshot = ([], [])
        mock_connector.get_order_book = Mock(return_value=mock_orderbook)

        mock_event_logger = Mock()

        filter_with_exchange = SmartEntryFilter(
            self.base_cfg,
            self.coin_profiles,
            self.logger,
            exchange_connector=mock_connector,
            connector_name="mock_exchange"
        )
        filter_with_exchange.event_logger = mock_event_logger

        indicators = CandleIndicators(
            price=Decimal("10.0"),
            rsi_14=50.0,
            vwap=Decimal("10.0"),
            atr_pct=2.5,
            wick_ratio=0.50,
            trend_1h_pct=0.5,
            trend_4h_pct=0.3,
            trend_24h_pct=1.0,
            change_5m_pct=0.2,
        )

        allowed, reason, trace = filter_with_exchange.allows_entry(
            "BTC-EUR", indicators, order_size_eur=100.0, trace_enabled=True
        )

        # Depth check skipped → entry not blocked by depth
        self.assertNotIn("orderbook", reason.lower(), "Depth skip should not block entry")
        # gate_denied must NOT have been called for NO_ORDERBOOK_DATA
        for call in mock_event_logger.emit_gate_denied.call_args_list:
            kwargs = call.kwargs if call.kwargs else {}
            args = call.args if call.args else []
            reason_code = kwargs.get("reason_code") or (args[3] if len(args) > 3 else None)
            self.assertNotEqual(
                str(reason_code), "NO_ORDERBOOK_DATA",
                "emit_gate_denied must not be called with NO_ORDERBOOK_DATA on depth-skip path"
            )


class TestVwapSlopeGuardAndParabolic(unittest.TestCase):
    """Tests for VWAP slope guard and parabolic detector in SmartEntry v2."""

    # Indicators that pass all gates 0–6b when vwap_max_deviation_pct is large.
    # price=1.20, vwap=1.00 → dev = +20.0% (above any 15% threshold)
    _BASE_IND = dict(
        price=Decimal("1.20"),
        rsi_14=50.0,
        vwap=Decimal("1.00"),
        atr_pct=2.5,
        wick_ratio=0.50,
        trend_1h_pct=0.5,
        trend_4h_pct=0.3,
        trend_24h_pct=1.0,
        change_5m_pct=0.2,
    )

    def _make_cfg(self, **overrides):
        defaults = dict(
            rsi_buy_max=60.0,
            rsi_extreme_low=25.0,
            rsi_block_min=70.0,
            vwap_max_deviation_pct=25.0,   # permit 20% dev through gate 2
            min_wick_ratio=0.25,
            max_atr_pct_for_grid=6.0,
            min_atr_pct_for_grid=0.5,
            max_5m_spike_pct=2.5,
            max_down_accel_pct=-1.0,
            max_up_accel_pct=1.5,
            max_trend_24h_pct=8.0,
            min_trend_24h_pct=-12.0,
            slippage_check_enabled=False,
            depth_check_enabled=False,
            require_price=False,
            require_orderbook=False,
            vwap_slope_guard_enabled=False,
            parabolic_detector_enabled=False,
        )
        defaults.update(overrides)
        return SmartEntryBaseConfig(**defaults)

    def _make_filter(self, **cfg_overrides):
        logger = logging.getLogger("test_vwap_parabolic")
        logger.setLevel(logging.CRITICAL)
        cfg = self._make_cfg(**cfg_overrides)
        return SmartEntryFilter(cfg, {}, logger)

    # ── VWAP slope guard ──────────────────────────────────────────────────────

    def test_vwap_slope_guard_blocks_live_when_conditions_met(self):
        """Live mode: high deviation + flat 15m slope → entry blocked."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, reason, _ = f.allows_entry(
            "BTC-EUR", ind, vwap_slope_15m_pct=0.02,  # flat slope
        )
        self.assertFalse(allowed)
        self.assertIn("VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH", reason)

    def test_vwap_slope_guard_shadow_does_not_block(self):
        """Shadow mode: same conditions → entry still allowed."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=True,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind, vwap_slope_15m_pct=0.02,
        )
        self.assertTrue(allowed)

    def test_vwap_slope_guard_passes_when_slope_missing(self):
        """Missing slope data → fail open (entry allowed)."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_deviation_high_pct=15.0,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind, vwap_slope_15m_pct=None,
        )
        self.assertTrue(allowed)

    def test_vwap_slope_guard_passes_when_deviation_low(self):
        """Price close to VWAP → guard not triggered even if slope is flat."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_15m=0.10,
        )
        # price 2% above vwap — well below 15% threshold
        ind = CandleIndicators(**{**self._BASE_IND, "vwap": Decimal("1.176")})
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind, vwap_slope_15m_pct=0.01,
        )
        self.assertTrue(allowed)

    def test_vwap_slope_guard_passes_when_slope_healthy(self):
        """High deviation but healthy slope → entry allowed."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind, vwap_slope_15m_pct=0.50,  # healthy slope
        )
        self.assertTrue(allowed)

    # ── Parabolic detector ────────────────────────────────────────────────────

    def test_parabolic_blocks_live_when_all_conditions_met(self):
        """Live mode: high dev + high accel_5m + high accel_15m → blocked."""
        f = self._make_filter(
            parabolic_detector_enabled=True,
            parabolic_detector_shadow_mode=False,
            parabolic_vwap_dev_min_pct=18.0,
            parabolic_accel_5m_min_pct=2.5,
            parabolic_accel_15m_min_pct=6.0,
            parabolic_cooldown_minutes=30,
        )
        ind = CandleIndicators(**self._BASE_IND)  # dev=20% > 18%
        allowed, reason, _ = f.allows_entry(
            "ETH-EUR", ind, accel_5m_pct=3.0, accel_15m_pct=7.0,
        )
        self.assertFalse(allowed)
        self.assertIn("PARABOLIC_DETECTED", reason)

    def test_parabolic_shadow_does_not_block(self):
        """Shadow mode: parabolic conditions → entry still allowed."""
        f = self._make_filter(
            parabolic_detector_enabled=True,
            parabolic_detector_shadow_mode=True,
            parabolic_vwap_dev_min_pct=18.0,
            parabolic_accel_5m_min_pct=2.5,
            parabolic_accel_15m_min_pct=6.0,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "ETH-EUR", ind, accel_5m_pct=3.0, accel_15m_pct=7.0,
        )
        self.assertTrue(allowed)

    def test_parabolic_cooldown_blocks_subsequent_entry(self):
        """After detection the cooldown blocks the next attempt."""
        f = self._make_filter(
            parabolic_detector_enabled=True,
            parabolic_detector_shadow_mode=False,
            parabolic_vwap_dev_min_pct=18.0,
            parabolic_accel_5m_min_pct=2.5,
            parabolic_accel_15m_min_pct=6.0,
            parabolic_cooldown_minutes=30,
        )
        ind = CandleIndicators(**self._BASE_IND)
        # First call: triggers detection + sets cooldown
        f.allows_entry("SOL-EUR", ind, accel_5m_pct=3.0, accel_15m_pct=7.0)
        # Second call (accel now mild): must still be blocked by cooldown
        allowed, reason, _ = f.allows_entry(
            "SOL-EUR", ind, accel_5m_pct=0.1, accel_15m_pct=0.1,
        )
        self.assertFalse(allowed)
        self.assertIn("PARABOLIC_COOLDOWN_ACTIVE", reason)

    def test_parabolic_passes_when_accel_missing(self):
        """Missing acceleration data → fail open (entry allowed)."""
        f = self._make_filter(
            parabolic_detector_enabled=True,
            parabolic_detector_shadow_mode=False,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "ADA-EUR", ind, accel_5m_pct=None, accel_15m_pct=None,
        )
        self.assertTrue(allowed)

    def test_parabolic_passes_when_only_partial_conditions_met(self):
        """Only two of three conditions → not parabolic, entry allowed."""
        f = self._make_filter(
            parabolic_detector_enabled=True,
            parabolic_detector_shadow_mode=False,
            parabolic_vwap_dev_min_pct=18.0,
            parabolic_accel_5m_min_pct=2.5,
            parabolic_accel_15m_min_pct=6.0,
        )
        ind = CandleIndicators(**self._BASE_IND)  # dev=20% ✓
        # accel_5m ✓ but accel_15m < 6.0 ✗
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind, accel_5m_pct=3.0, accel_15m_pct=4.0,
        )
        self.assertTrue(allowed)


class TestCA3VwapDualWindow(unittest.TestCase):
    """CA3: Dual-window VWAP slope guard tests for SmartEntry v2 live path."""

    # Indicators: price=1.20, vwap=1.00 → dev=+20% (above any 15% threshold).
    _BASE_IND = dict(
        price=Decimal("1.20"),
        rsi_14=50.0,
        vwap=Decimal("1.00"),
        atr_pct=2.5,
        wick_ratio=0.50,
        trend_1h_pct=0.5,
        trend_4h_pct=0.3,
        trend_24h_pct=1.0,
        change_5m_pct=0.2,
    )

    def _make_filter(self, **cfg_overrides):
        defaults = dict(
            rsi_buy_max=60.0,
            rsi_extreme_low=25.0,
            rsi_block_min=70.0,
            vwap_max_deviation_pct=25.0,
            min_wick_ratio=0.25,
            max_atr_pct_for_grid=6.0,
            min_atr_pct_for_grid=0.5,
            max_5m_spike_pct=2.5,
            max_down_accel_pct=-1.0,
            max_up_accel_pct=1.5,
            max_trend_24h_pct=8.0,
            min_trend_24h_pct=-12.0,
            slippage_check_enabled=False,
            depth_check_enabled=False,
            require_price=False,
            require_orderbook=False,
            vwap_slope_guard_enabled=False,
            parabolic_detector_enabled=False,
        )
        defaults.update(cfg_overrides)
        logger = logging.getLogger("test_ca3")
        logger.setLevel(logging.CRITICAL)
        cfg = SmartEntryBaseConfig(**defaults)
        return SmartEntryFilter(cfg, {}, logger)

    # ── Dual-window: both slopes flat → reject ────────────────────────────────

    def test_dual_window_both_flat_live_blocks(self):
        """Both 5m and 15m slopes flat at high deviation → entry blocked (live)."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_dual_confirmation=True,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_5m=0.05,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, reason, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=0.01,   # flat (< 0.05)
            vwap_slope_15m_pct=0.02,  # flat (< 0.10)
        )
        self.assertFalse(allowed)
        self.assertIn("VWAP_GUARD_REJECT", reason)
        self.assertIn("dual-window", reason)

    def test_dual_window_shadow_does_not_block(self):
        """Shadow mode: both slopes flat → entry still allowed."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=True,
            vwap_slope_dual_confirmation=True,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_5m=0.05,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=0.01,
            vwap_slope_15m_pct=0.02,
        )
        self.assertTrue(allowed)

    # ── Dual-window: only one slope flat → allow ──────────────────────────────

    def test_dual_window_only_15m_flat_allows(self):
        """15m flat but 5m healthy → dual confirmation NOT met → allowed."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_dual_confirmation=True,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_5m=0.05,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=0.50,   # healthy 5m slope
            vwap_slope_15m_pct=0.02,  # flat 15m slope
        )
        self.assertTrue(allowed)

    def test_dual_window_only_5m_flat_allows(self):
        """5m flat but 15m healthy → dual confirmation NOT met → allowed."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_dual_confirmation=True,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_5m=0.05,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=0.02,   # flat 5m slope
            vwap_slope_15m_pct=0.50,  # healthy 15m slope
        )
        self.assertTrue(allowed)

    # ── Dual-window: missing 5m data → degrade to single 15m ─────────────────

    def test_dual_window_missing_5m_degrades_to_single_15m(self):
        """Dual mode + 5m data missing → degrades to single 15m check."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_dual_confirmation=True,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        # 5m not available → degrades to single-window on 15m
        allowed, reason, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=None,
            vwap_slope_15m_pct=0.02,  # flat
        )
        self.assertFalse(allowed)
        self.assertIn("VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH", reason)

    def test_dual_window_both_missing_fails_open(self):
        """Both slopes missing in dual mode → guard skipped (fail open)."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_dual_confirmation=True,
            vwap_slope_deviation_high_pct=15.0,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=None,
            vwap_slope_15m_pct=None,
        )
        self.assertTrue(allowed)

    # ── Guard disabled → no reject ────────────────────────────────────────────

    def test_guard_disabled_never_rejects(self):
        """VWAP guard disabled → no rejection even with extreme conditions."""
        f = self._make_filter(
            vwap_slope_guard_enabled=False,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=0.0,
            vwap_slope_15m_pct=0.0,
        )
        self.assertTrue(allowed)

    # ── Single-window mode (dual_confirmation=False) ──────────────────────────

    def test_single_window_mode_uses_15m_only(self):
        """Single window mode: 15m flat → blocked regardless of 5m health."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_dual_confirmation=False,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        # 5m is healthy but 15m flat → single-window rejects on 15m alone
        allowed, reason, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=0.50,   # healthy — ignored in single-window mode
            vwap_slope_15m_pct=0.02,  # flat
        )
        self.assertFalse(allowed)
        self.assertIn("VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH", reason)

    # ── Reject reason visible to why-no-trade system ──────────────────────────

    def test_reject_reason_contains_guard_name(self):
        """VWAP_GUARD_REJECT appears in reject reason for why-no-trade logging."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_dual_confirmation=True,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_5m=0.05,
            vwap_slope_min_pct_15m=0.10,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, reason, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=0.01,
            vwap_slope_15m_pct=0.01,
        )
        self.assertFalse(allowed)
        # The reason returned to the controller ends up in why-no-trade logs
        self.assertIn("VWAP_GUARD_REJECT", reason)

    # ── Parabolic guard disabled → no reject ─────────────────────────────────

    def test_parabolic_guard_disabled_no_reject(self):
        """Parabolic guard disabled → no rejection even with extreme acceleration."""
        f = self._make_filter(
            parabolic_detector_enabled=False,
        )
        ind = CandleIndicators(**self._BASE_IND)
        allowed, _, _ = f.allows_entry(
            "ETH-EUR", ind, accel_5m_pct=10.0, accel_15m_pct=20.0,
        )
        self.assertTrue(allowed)

    # ── Existing gates 0-7 unaffected ─────────────────────────────────────────

    def test_existing_gates_still_reject_independently(self):
        """RSI overbought still rejects even when VWAP guard would pass."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_dual_confirmation=True,
        )
        # RSI overbought → gate 1 should reject before VWAP guard is reached
        ind = CandleIndicators(**{**self._BASE_IND, "rsi_14": 75.0})
        allowed, reason, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=0.50,
            vwap_slope_15m_pct=0.50,
        )
        self.assertFalse(allowed)
        self.assertIn("RSI", reason)

    def test_clean_candidate_with_both_guards_enabled_allowed(self):
        """Clean candidate passes both VWAP and parabolic guards."""
        f = self._make_filter(
            vwap_slope_guard_enabled=True,
            vwap_slope_guard_shadow_mode=False,
            vwap_slope_dual_confirmation=True,
            vwap_slope_deviation_high_pct=15.0,
            vwap_slope_min_pct_5m=0.05,
            vwap_slope_min_pct_15m=0.10,
            parabolic_detector_enabled=True,
            parabolic_detector_shadow_mode=False,
            parabolic_vwap_dev_min_pct=18.0,
            parabolic_accel_5m_min_pct=2.5,
            parabolic_accel_15m_min_pct=6.0,
        )
        # price close to VWAP (dev ~2%) → VWAP guard never triggers at dev < 15%
        ind = CandleIndicators(**{**self._BASE_IND, "vwap": Decimal("1.18")})
        allowed, reason, _ = f.allows_entry(
            "BTC-EUR", ind,
            vwap_slope_5m_pct=0.20,
            vwap_slope_15m_pct=0.15,
            accel_5m_pct=0.5,
            accel_15m_pct=1.0,
        )
        self.assertTrue(allowed)
        self.assertIn("BUY ALLOWED", reason)


if __name__ == "__main__":
    unittest.main()
