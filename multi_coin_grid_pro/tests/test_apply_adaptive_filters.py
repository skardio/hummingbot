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

    def test_ignore_non_smartentry_filters(self):
        """Test that grid_spacing_mult and max_active_grids are ignored"""
        filters = {
            'rsi_buy_max': 85.0,
            'grid_spacing_mult': 1.5,
            'max_active_grids': 3,
        }

        MultiCoinGridController._apply_adaptive_filters(self.controller, filters)

        self.assertEqual(self.base_cfg.rsi_buy_max, 85.0)
        self.assertFalse(hasattr(self.base_cfg, 'grid_spacing_mult'))
        self.assertFalse(hasattr(self.base_cfg, 'max_active_grids'))

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


if __name__ == '__main__':
    unittest.main()
