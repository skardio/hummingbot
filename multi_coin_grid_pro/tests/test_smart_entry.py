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


class TestRSIHysteresisAndSmoothing(unittest.TestCase):
    """
    Regression tests for post-mortem 2026-05-12.

    Story 3.2: RSI hysteresis — block at rsi_buy_max, only unblock after RSI drops
               rsi_hysteresis_gap points below buy_max AND stays there for recovery_min.
    Story 3.1: Threshold smoothing — median of last N samples prevents single-candle
               threshold swings from opening entries.
    Story 8.1: INJ-USD regression — bot must NOT buy when RSI drops rapidly after
               being overbought for an extended period.
    """

    def _make_cfg(self, rsi_buy_max=75.0, rsi_block_min=77.0,
                  hysteresis_enabled=True, hysteresis_gap=4.0, recovery_min=5.0,
                  smoothing_enabled=True, smoothing_window=20,
                  exhausted_momentum_enabled=False):
        return SmartEntryBaseConfig(
            rsi_buy_max=rsi_buy_max,
            rsi_extreme_low=20.0,
            rsi_block_min=rsi_block_min,
            vwap_max_deviation_pct=20.0,   # wide — not under test
            min_wick_ratio=0.0,            # disabled — not under test
            max_atr_pct_for_grid=99.0,
            min_atr_pct_for_grid=0.0,
            max_5m_spike_pct=99.0,
            max_down_accel_pct=-99.0,
            max_up_accel_pct=99.0,
            max_trend_24h_pct=99.0,
            min_trend_24h_pct=-99.0,
            slippage_check_enabled=False,
            depth_check_enabled=False,
            require_price=False,
            require_orderbook=False,
            rsi_hysteresis_enabled=hysteresis_enabled,
            rsi_hysteresis_gap=hysteresis_gap,
            rsi_hysteresis_recovery_min=recovery_min,
            rsi_smoothing_enabled=smoothing_enabled,
            rsi_smoothing_window=smoothing_window,
            exhausted_momentum_enabled=exhausted_momentum_enabled,
            exhausted_momentum_24h_min_pct=8.0,
            exhausted_momentum_1h_max_pct=1.0,
        )

    def _make_ind(self, rsi, trend_1h=1.0, trend_4h=0.5, trend_24h=3.0, price=5.0):
        from decimal import Decimal
        return CandleIndicators(
            price=Decimal(str(price)),
            rsi_14=rsi,
            vwap=Decimal(str(price)),
            atr_pct=1.0,
            wick_ratio=0.5,
            trend_1h_pct=trend_1h,
            trend_4h_pct=trend_4h,
            trend_24h_pct=trend_24h,
            change_5m_pct=0.1,
        )

    def test_story_8_1_inj_regression_overbought_then_rapid_drop(self):
        """
        Story 8.1 — INJ-USD regression case 2026-05-12 16:05-16:15.

        Scenario: RSI stays above 77 for ~70 minutes (correctly blocked), then
        crashes to 63.7 within 90 seconds. Without hysteresis the bot would have
        entered immediately. With hysteresis + recovery_min, the entry must stay
        blocked for at least recovery_min minutes after RSI drops below the unlock
        threshold.
        """
        logger = logging.getLogger("test_inj")
        logger.setLevel(logging.CRITICAL)
        cfg = self._make_cfg(rsi_buy_max=75.0, rsi_block_min=77.0,
                             hysteresis_enabled=True, hysteresis_gap=4.0, recovery_min=5.0,
                             smoothing_enabled=False)  # smoothing off to isolate hysteresis
        f = SmartEntryFilter(cfg, {}, logger)

        # Step 1: RSI at 78.5 (above block_min=77) → blocked
        ind_overbought = self._make_ind(rsi=78.5)
        allowed, reason, _ = f.allows_entry("INJ-USD", ind_overbought)
        self.assertFalse(allowed, "RSI 78.5 >= block_min 77 must be blocked")
        self.assertTrue(f._rsi_blocked.get("INJ-USD", False), "Symbol must be marked blocked")

        # Step 2: RSI drops to 63.7 (< unlock threshold 75-4=71) — entry must still be blocked
        # because recovery_min (5 min) has not elapsed yet (we call it immediately after step 1)
        ind_crashed = self._make_ind(rsi=63.7)
        allowed2, reason2, _ = f.allows_entry("INJ-USD", ind_crashed)
        self.assertFalse(allowed2,
                         f"Entry must be blocked in recovery cooldown, got: {reason2}")
        self.assertIn("recovery cooldown", reason2,
                      f"Reason must mention recovery cooldown, got: {reason2}")

    def test_hysteresis_no_flip_flop_at_threshold_boundary(self):
        """
        Story 3.2 — once blocked, RSI oscillating just below buy_max must not
        open entry until it drops below (buy_max - gap).

        buy_max=75, gap=4, unlock=71.
        RSI at 73.5 (< buy_max=75 but > unlock=71) must NOT unblock.
        """
        logger = logging.getLogger("test_hysteresis")
        logger.setLevel(logging.CRITICAL)
        cfg = self._make_cfg(rsi_buy_max=75.0, rsi_block_min=77.0,
                             hysteresis_enabled=True, hysteresis_gap=4.0, recovery_min=0.0,
                             smoothing_enabled=False)
        f = SmartEntryFilter(cfg, {}, logger)

        # Get blocked first
        f.allows_entry("ATOM-USD", self._make_ind(rsi=76.0))   # above buy_max → blocked
        self.assertTrue(f._rsi_blocked.get("ATOM-USD", False))

        # RSI at 73.5 — below buy_max but above unlock threshold (71) → still blocked
        allowed, reason, _ = f.allows_entry("ATOM-USD", self._make_ind(rsi=73.5))
        self.assertFalse(allowed, f"RSI 73.5 in hysteresis zone must stay blocked: {reason}")
        self.assertIn("hysteresis", reason.lower(),
                      f"Reason must mention hysteresis, got: {reason}")

    def test_hysteresis_unblocks_after_sufficient_drop_and_recovery(self):
        """
        Story 3.2 — when recovery_min=0, entry is allowed as soon as RSI drops
        below unlock threshold. Tests the clean unblock path.
        """
        logger = logging.getLogger("test_unblock")
        logger.setLevel(logging.CRITICAL)
        cfg = self._make_cfg(rsi_buy_max=75.0, rsi_block_min=77.0,
                             hysteresis_enabled=True, hysteresis_gap=4.0, recovery_min=0.0,
                             smoothing_enabled=False)
        f = SmartEntryFilter(cfg, {}, logger)

        # Block
        f.allows_entry("BTC-USD", self._make_ind(rsi=76.0))
        self.assertTrue(f._rsi_blocked.get("BTC-USD", False))

        # RSI drops to 68 (< unlock=71), recovery_min=0 → should unblock immediately
        allowed, reason, _ = f.allows_entry("BTC-USD", self._make_ind(rsi=68.0))
        self.assertTrue(allowed, f"After sufficient drop with recovery_min=0, entry should be allowed: {reason}")
        self.assertFalse(f._rsi_blocked.get("BTC-USD", False), "Block state must be cleared")

    def test_story_3_1_smoothing_prevents_single_candle_threshold_drop(self):
        """
        Story 3.1 — a single candle where rsi_buy_max drops from 75 to 63
        must not open entry when previous samples were at 75.

        Without smoothing: threshold=63, RSI=62 → allowed.
        With smoothing (median of 10 samples at 75 + 1 at 63): median≈75 → blocked.
        """
        logger = logging.getLogger("test_smooth")
        logger.setLevel(logging.CRITICAL)
        # Config: rsi_buy_max=75, hysteresis off to isolate smoothing effect
        cfg = self._make_cfg(rsi_buy_max=75.0, rsi_block_min=90.0,
                             hysteresis_enabled=False,
                             smoothing_enabled=True, smoothing_window=10)
        f = SmartEntryFilter(cfg, {}, logger)

        # Prime history with 9 samples at threshold=75
        for _ in range(9):
            f._get_smoothed_rsi_buy_max("SOL-USD", 75.0)

        # One outlier sample at 63 (simulates a coin-profile override dropping threshold)
        smoothed = f._get_smoothed_rsi_buy_max("SOL-USD", 63.0)

        # Median of [63, 75, 75, 75, 75, 75, 75, 75, 75, 75] = 75.0
        self.assertGreater(smoothed, 70.0,
                           f"Smoothed threshold must be near 75, not {smoothed} (single outlier must not dominate)")

    def test_story_4_1_exhausted_momentum_blocks_inj_profile(self):
        """
        Story 4.1 — INJ profile: 24h=+11.71%, 1h=+1.90%.
        With threshold 24h>=8% AND 1h<1%: 1h=1.90 is NOT < 1%, so this specific
        case does NOT block (by design — requires both conditions).

        Separately test the exact blocking condition: 24h=+10%, 1h=+0.5%.
        """
        logger = logging.getLogger("test_exhausted")
        logger.setLevel(logging.CRITICAL)
        cfg = self._make_cfg(exhausted_momentum_enabled=True,
                             rsi_block_min=90.0,    # disable hard RSI block
                             hysteresis_enabled=False,
                             smoothing_enabled=False)
        f = SmartEntryFilter(cfg, {}, logger)

        # Case 1: 24h=10%, 1h=0.5% → SHOULD block (exhausted)
        ind_exhausted = self._make_ind(rsi=50.0, trend_1h=0.5, trend_24h=10.0)
        allowed, reason, _ = f.allows_entry("INJ-USD", ind_exhausted)
        self.assertFalse(allowed, f"Exhausted momentum must block: {reason}")
        self.assertIn("EXHAUSTED_MOMENTUM", reason)

        # Case 2: 24h=10%, 1h=1.5% (strong 1h) → must NOT block
        ind_still_running = self._make_ind(rsi=50.0, trend_1h=1.5, trend_24h=10.0)
        allowed2, reason2, _ = f.allows_entry("INJ-USD", ind_still_running)
        self.assertTrue(allowed2,
                        f"Strong 1h should not be blocked by exhausted filter: {reason2}")

        # Case 3: 24h=5% (below 8% threshold) + 1h=0.5% → must NOT block
        ind_small_move = self._make_ind(rsi=50.0, trend_1h=0.5, trend_24h=5.0)
        allowed3, reason3, _ = f.allows_entry("INJ-USD", ind_small_move)
        self.assertTrue(allowed3,
                        f"Small 24h move must not trigger exhausted filter: {reason3}")

    def test_hysteresis_disabled_is_backward_compatible(self):
        """Story 3.2 — when hysteresis disabled, simple threshold check applies (old behaviour)."""
        logger = logging.getLogger("test_disabled")
        logger.setLevel(logging.CRITICAL)
        cfg = self._make_cfg(rsi_buy_max=75.0, rsi_block_min=90.0,
                             hysteresis_enabled=False, smoothing_enabled=False)
        f = SmartEntryFilter(cfg, {}, logger)

        # RSI just above buy_max → blocked
        allowed, _, _ = f.allows_entry("BTC-USD", self._make_ind(rsi=75.5))
        self.assertFalse(allowed)

        # RSI just below buy_max → allowed (no hysteresis, no prior block state)
        allowed2, _, _ = f.allows_entry("BTC-USD", self._make_ind(rsi=74.9))
        self.assertTrue(allowed2)


class TestConfigValidation(unittest.TestCase):
    """Story 7.1 — SmartEntryBaseConfig.validate() fails fast on bad config."""

    def _base_cfg(self, **overrides):
        defaults = dict(
            rsi_buy_max=60.0, rsi_extreme_low=25.0, rsi_block_min=70.0,
            vwap_max_deviation_pct=3.0, min_wick_ratio=0.25,
            max_atr_pct_for_grid=6.0, min_atr_pct_for_grid=0.5,
            max_5m_spike_pct=2.5, max_down_accel_pct=-1.0, max_up_accel_pct=1.5,
            max_trend_24h_pct=8.0, min_trend_24h_pct=-12.0,
            slippage_check_enabled=False, depth_check_enabled=False,
            require_price=False, require_orderbook=False,
        )
        defaults.update(overrides)
        return SmartEntryBaseConfig(**defaults)

    def test_valid_config_does_not_raise(self):
        """A correct config passes validation without error."""
        cfg = self._base_cfg()
        cfg.validate()  # must not raise

    def test_rsi_buy_max_must_be_below_block_min(self):
        """rsi_buy_max >= rsi_block_min is invalid."""
        cfg = self._base_cfg(rsi_buy_max=70.0, rsi_block_min=70.0)
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        self.assertIn("rsi_buy_max", str(ctx.exception))

    def test_rsi_extreme_low_must_be_below_buy_max(self):
        """rsi_extreme_low >= rsi_buy_max is invalid."""
        cfg = self._base_cfg(rsi_extreme_low=65.0, rsi_buy_max=60.0)
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        self.assertIn("rsi_extreme_low", str(ctx.exception))

    def test_hysteresis_gap_must_be_positive(self):
        """rsi_hysteresis_gap <= 0 is invalid."""
        cfg = self._base_cfg()
        cfg.rsi_hysteresis_gap = 0.0
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        self.assertIn("rsi_hysteresis_gap", str(ctx.exception))

    def test_atr_range_must_be_ordered(self):
        """max_atr must be > min_atr."""
        cfg = self._base_cfg(min_atr_pct_for_grid=5.0, max_atr_pct_for_grid=3.0)
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        self.assertIn("max_atr_pct_for_grid", str(ctx.exception))

    def test_multiple_errors_reported_together(self):
        """All validation errors are collected and reported at once."""
        cfg = self._base_cfg(rsi_extreme_low=72.0, rsi_buy_max=70.0, rsi_block_min=70.0)
        with self.assertRaises(ValueError) as ctx:
            cfg.validate()
        msg = str(ctx.exception)
        self.assertIn("rsi_buy_max", msg)
        self.assertIn("rsi_extreme_low", msg)

    def test_invalid_config_raises_on_filter_init(self):
        """SmartEntryFilter.__init__ must reject an invalid config."""
        logger = logging.getLogger("test_val")
        logger.setLevel(logging.CRITICAL)
        cfg = self._base_cfg(rsi_buy_max=70.0, rsi_block_min=70.0)
        with self.assertRaises(ValueError):
            SmartEntryFilter(cfg, {}, logger)


class TestEntryContextLogging(unittest.TestCase):
    """Story 6.1 — allows_entry logs structured entry context for every decision."""

    def _make_cfg(self):
        return SmartEntryBaseConfig(
            rsi_buy_max=60.0, rsi_extreme_low=25.0, rsi_block_min=70.0,
            vwap_max_deviation_pct=3.0, min_wick_ratio=0.25,
            max_atr_pct_for_grid=6.0, min_atr_pct_for_grid=0.5,
            max_5m_spike_pct=2.5, max_down_accel_pct=-1.0, max_up_accel_pct=1.5,
            max_trend_24h_pct=8.0, min_trend_24h_pct=-12.0,
            slippage_check_enabled=False, depth_check_enabled=False,
            require_price=False, require_orderbook=False,
        )

    def _make_ind(self, rsi=50.0):
        return CandleIndicators(
            price=Decimal("10.0"), rsi_14=rsi, vwap=Decimal("9.9"),
            atr_pct=2.5, wick_ratio=0.5,
            trend_1h_pct=0.3, trend_4h_pct=0.2, trend_24h_pct=1.0,
            change_5m_pct=0.1,
        )

    def test_approved_decision_is_logged(self):
        """BUY_APPROVED must emit a log record containing ENTRY_DECISION."""
        logger = logging.getLogger("test_log_approved")
        with self.assertLogs(logger, level="INFO") as cm:
            f = SmartEntryFilter(self._make_cfg(), {}, logger)
            f.allows_entry("ETH-EUR", self._make_ind(rsi=50.0))
        messages = "\n".join(cm.output)
        self.assertIn("ENTRY_DECISION", messages)
        self.assertIn("ETH-EUR", messages)
        self.assertIn("APPROVED", messages)

    def test_rejected_decision_is_logged(self):
        """BUY_REJECTED must emit a log record containing ENTRY_DECISION."""
        logger = logging.getLogger("test_log_rejected")
        with self.assertLogs(logger, level="INFO") as cm:
            f = SmartEntryFilter(self._make_cfg(), {}, logger)
            f.allows_entry("ETH-EUR", self._make_ind(rsi=68.0))  # above buy_max → reject
        messages = "\n".join(cm.output)
        self.assertIn("ENTRY_DECISION", messages)
        self.assertIn("REJECTED", messages)

    def test_log_contains_rsi_and_trend_fields(self):
        """Log must contain RSI value and trend percentages."""
        logger = logging.getLogger("test_log_fields")
        with self.assertLogs(logger, level="INFO") as cm:
            f = SmartEntryFilter(self._make_cfg(), {}, logger)
            f.allows_entry("SOL-EUR", self._make_ind(rsi=45.0))
        messages = "\n".join(cm.output)
        self.assertIn("rsi=", messages)
        self.assertIn("threshold=", messages)
        self.assertIn("trends:", messages)
        self.assertIn("vwap_dev=", messages)
        self.assertIn("atr=", messages)

    def test_evaluate_entry_is_internal(self):
        """_evaluate_entry should not be called directly by callers — only via allows_entry."""
        f = SmartEntryFilter(self._make_cfg(), {})
        self.assertTrue(hasattr(f, "_evaluate_entry"), "_evaluate_entry must exist")
        self.assertTrue(hasattr(f, "allows_entry"), "allows_entry must exist")


if __name__ == "__main__":
    unittest.main()
