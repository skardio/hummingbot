"""
Unit tests for _apply_adaptive_filters method in MultiCoinGridController

Tests that adaptive filters are correctly applied to SmartEntry configuration.
"""

import logging
import unittest
from unittest.mock import MagicMock, Mock

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.logic.smart_entry import SmartEntryBaseConfig


class TestApplyAdaptiveFilters(unittest.TestCase):
    """Test suite for _apply_adaptive_filters method"""

    def setUp(self):
        """Set up test fixtures"""
        self.logger = logging.getLogger("test")
        self.logger.setLevel(logging.DEBUG)

        # Create a mock controller with just the parts we need
        self.controller = Mock()
        self.controller.logger = MagicMock(return_value=self.logger)

        # Create mock SmartEntry with base config
        self.base_cfg = SmartEntryBaseConfig(
            rsi_buy_max=70.0,
            rsi_extreme_low=25.0,
            rsi_block_min=80.0,
            vwap_max_deviation_pct=3.0,
            min_wick_ratio=0.25,
            max_atr_pct_for_grid=6.0,
            min_atr_pct_for_grid=0.5,
            max_5m_spike_pct=2.5,
            max_down_accel_pct=-2.0,
            max_up_accel_pct=1.5,
            max_trend_24h_pct=8.0,
            min_trend_24h_pct=-12.0,
        )

        self.smart_entry_mock = Mock()
        self.smart_entry_mock.base_cfg = self.base_cfg
        self.controller.smart_entry_v2 = self.smart_entry_mock
        # No YAML limits by default (adaptive has free reign)
        self.controller._yaml_smart_entry_limits = {}

    def test_apply_bull_filters(self):
        """Test applying BULL regime filters"""
        bull_filters = {
            'rsi_buy_min': 20.0,
            'rsi_buy_max': 85.0,
            'vwap_max_deviation_pct': 7.0,
            'max_up_accel_pct': 3.0,
            'max_down_accel_pct': -4.0,
            'atr_min_pct': 0.08,
            'atr_max_pct': 6.5,
            'spike_5m_max_pct': 3.5,
            'wick_ratio_min': 0.15,
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, bull_filters)

        self.assertEqual(self.base_cfg.rsi_buy_max, 85.0)
        self.assertEqual(self.base_cfg.rsi_extreme_low, 20.0)
        self.assertEqual(self.base_cfg.vwap_max_deviation_pct, 7.0)
        self.assertEqual(self.base_cfg.max_up_accel_pct, 3.0)
        self.assertEqual(self.base_cfg.max_down_accel_pct, -4.0)
        self.assertEqual(self.base_cfg.min_atr_pct_for_grid, 0.08)
        self.assertEqual(self.base_cfg.max_atr_pct_for_grid, 6.5)
        self.assertEqual(self.base_cfg.max_5m_spike_pct, 3.5)
        self.assertEqual(self.base_cfg.min_wick_ratio, 0.15)

    def test_apply_chop_filters(self):
        """Test applying CHOP regime filters"""
        chop_filters = {
            'rsi_buy_max': 78.0,
            'rsi_buy_min': 25.0,
            'vwap_max_deviation_pct': 4.5,
            'max_up_accel_pct': 1.8,
            'max_down_accel_pct': -2.5,
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, chop_filters)

        self.assertEqual(self.base_cfg.rsi_buy_max, 78.0)
        self.assertEqual(self.base_cfg.rsi_extreme_low, 25.0)
        self.assertEqual(self.base_cfg.vwap_max_deviation_pct, 4.5)
        self.assertEqual(self.base_cfg.max_up_accel_pct, 1.8)
        self.assertEqual(self.base_cfg.max_down_accel_pct, -2.5)

    def test_apply_bear_filters(self):
        """Test applying BEAR regime filters"""
        bear_filters = {
            'rsi_buy_max': 70.0,
            'rsi_buy_min': 20.0,
            'vwap_max_deviation_pct': 3.5,
            'max_up_accel_pct': 1.5,
            'max_down_accel_pct': -2.0,
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, bear_filters)

        self.assertEqual(self.base_cfg.rsi_buy_max, 70.0)
        self.assertEqual(self.base_cfg.rsi_extreme_low, 20.0)
        self.assertEqual(self.base_cfg.vwap_max_deviation_pct, 3.5)

    def test_apply_partial_filters(self):
        """Test applying only some filters (others unchanged)"""
        original_vwap = self.base_cfg.vwap_max_deviation_pct

        partial_filters = {
            'rsi_buy_max': 88.0,
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, partial_filters)

        self.assertEqual(self.base_cfg.rsi_buy_max, 88.0)
        self.assertEqual(self.base_cfg.vwap_max_deviation_pct, original_vwap)

    def test_no_smart_entry_warning(self):
        """Test warning when SmartEntry is not initialized"""
        self.controller.smart_entry_v2 = None

        filters = {'rsi_buy_max': 85.0}

        result = MultiCoinGridController._apply_adaptive_filters(self.controller, filters)

        self.assertIsNone(result)

    def test_non_smartentry_filters_applied_to_controller(self):
        """Test that grid_spacing_mult, max_active_grids, and entry_confidence_min are
        applied to controller-level attributes (not SmartEntry config)."""
        # Set up controller attributes that the method writes to
        self.controller._regime_max_active_grids = None
        self.controller._regime_grid_spacing_mult = 1.0
        self.controller._regime_entry_confidence_min = None
        self.controller.grid_suitability_scorer = None

        filters = {
            'rsi_buy_max': 85.0,
            'grid_spacing_mult': 1.5,
            'max_active_grids': 3,
            'entry_confidence_min': 0.70,
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, filters)

        self.assertEqual(self.base_cfg.rsi_buy_max, 85.0)
        # Non-SmartEntry filters stored on controller
        self.assertEqual(self.controller._regime_max_active_grids, 3)
        self.assertEqual(self.controller._regime_grid_spacing_mult, 1.5)
        self.assertEqual(self.controller._regime_entry_confidence_min, 0.70)

    def test_key_mapping_rsi_buy_min(self):
        """Test that rsi_buy_min correctly maps to rsi_extreme_low"""
        filters = {
            'rsi_buy_min': 15.0,
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, filters)

        self.assertEqual(self.base_cfg.rsi_extreme_low, 15.0)

    def test_key_mapping_atr(self):
        """Test that atr_min/max_pct correctly maps to min/max_atr_pct_for_grid"""
        filters = {
            'atr_min_pct': 0.2,
            'atr_max_pct': 8.0,
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, filters)

        self.assertEqual(self.base_cfg.min_atr_pct_for_grid, 0.2)
        self.assertEqual(self.base_cfg.max_atr_pct_for_grid, 8.0)

    def test_yaml_limits_clamp_adaptive(self):
        """RE-01: Adaptive values clamped so they never loosen YAML limits.

        Note: min_atr_pct_for_grid is intentionally NOT in min_fields — regime is
        allowed to lower it below the YAML baseline (HF-01 fix).
        Note: rsi_buy_max is intentionally NOT clamped — BULL regime must be able to
        raise it above the YAML baseline (e.g. baseline=65, BULL=76). The per-regime
        YAML values already express the operator's intent.
        """
        # Set YAML limits: RSI max 60, ATR min 0.30
        self.controller._yaml_smart_entry_limits = {
            'rsi_buy_max': 60.0,
            'min_atr_pct_for_grid': 0.30,
            'max_up_accel_pct': 5.0,
            'rsi_extreme_low': 18.0,
            'max_down_accel_pct': -6.0,
        }

        # Adaptive tries to loosen all of them
        filters = {
            'rsi_buy_max': 75.0,    # wants 75 — NOT clamped (BULL regime can raise RSI max)
            'atr_min_pct': 0.05,    # wants 0.05 — NOT clamped (regime can lower ATR min)
            'max_up_accel_pct': 8.0,  # wants 8, YAML says max 5
            'rsi_buy_min': 10.0,    # wants 10, YAML extreme_low says 18
            'max_down_accel_pct': -3.0,  # wants -3 (looser), YAML says -6
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, filters)

        # rsi_buy_max: freely set by regime (BULL=76 > baseline=65 is valid)
        self.assertEqual(self.base_cfg.rsi_buy_max, 75.0)
        # ATR min: regime override allowed
        self.assertEqual(self.base_cfg.min_atr_pct_for_grid, 0.05)
        # accel max: still clamped to YAML ceiling
        self.assertEqual(self.base_cfg.max_up_accel_pct, 5.0)
        # rsi extreme_low: clamped to YAML floor
        self.assertEqual(self.base_cfg.rsi_extreme_low, 18.0)
        # down_accel: clamped (more negative = stricter = allowed; less negative = blocked)
        self.assertEqual(self.base_cfg.max_down_accel_pct, -6.0)

    def test_yaml_limits_allow_stricter(self):
        """RE-01: Adaptive CAN tighten beyond YAML limits"""
        self.controller._yaml_smart_entry_limits = {
            'rsi_buy_max': 60.0,
            'min_atr_pct_for_grid': 0.30,
        }

        # Adaptive wants stricter values
        filters = {
            'rsi_buy_max': 55.0,    # stricter than YAML 60 → allowed
            'atr_min_pct': 0.50,    # stricter than YAML 0.30 → allowed
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, filters)

        self.assertEqual(self.base_cfg.rsi_buy_max, 55.0)
        self.assertEqual(self.base_cfg.min_atr_pct_for_grid, 0.50)


if __name__ == '__main__':
    unittest.main()
