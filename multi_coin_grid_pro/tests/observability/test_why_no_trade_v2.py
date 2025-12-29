"""
Unit tests for Why-No-Trade Report v2

Tests:
- Funnel calculation with correlation_id tracking
- Percentile calculations (p50/p90)
- Threshold comparison logic
- Symbol stats and vampire detection
- Regime breakdown
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from multi_coin_grid_pro.observability.why_no_trade_v2 import FunnelMetrics, ThresholdStats, WhyNoTradeV2


class TestWhyNoTradeV2(unittest.TestCase):
    """Test suite for WhyNoTradeV2 analyzer"""

    def setUp(self):
        """Set up test fixtures"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_dir = Path(self.temp_dir)

        # Sample config
        self.config = {
            'min_atr_pct_for_grid': 0.5,
            'max_atr_pct_for_grid': 6.0,
            'vwap_max_deviation_pct': 5.0,
            'rsi_block_min': 80.0,
            'rsi_extreme_low': 30.0
        }

        self.analyzer = WhyNoTradeV2(self.log_dir, config=self.config)

    def test_funnel_calculation(self):
        """Test funnel calculation with correlation_id tracking"""
        events = [
            # Intent 1: denied at smartentry
            {'event_type': 'gate_denied', 'correlation_id': 'id1', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW', 'timestamp': '2025-12-27T20:00:00'},
            # Intent 2: passes smartentry, denied at MTF
            {'event_type': 'gate_passed', 'correlation_id': 'id2', 'stage': 'SMART_ENTRY',
             'timestamp': '2025-12-27T20:00:10'},
            {'event_type': 'gate_denied', 'correlation_id': 'id2', 'stage': 'MTF',
             'reason_code': 'MTF_CRASH_DETECTED', 'timestamp': '2025-12-27T20:00:15'},
            # Intent 3: passes all, order submitted
            {'event_type': 'gate_passed', 'correlation_id': 'id3', 'stage': 'SMART_ENTRY',
             'timestamp': '2025-12-27T20:00:20'},
            {'event_type': 'gate_passed', 'correlation_id': 'id3', 'stage': 'MTF',
             'timestamp': '2025-12-27T20:00:25'},
            {'event_type': 'gate_passed', 'correlation_id': 'id3', 'stage': 'RISK',
             'timestamp': '2025-12-27T20:00:30'},
            {'event_type': 'order_submitted', 'correlation_id': 'id3',
             'timestamp': '2025-12-27T20:00:35'},
        ]

        funnel = self.analyzer._calculate_funnel(events)

        self.assertEqual(funnel.intents_total, 3)
        self.assertEqual(funnel.smartentry_pass, 2)  # id2, id3
        self.assertEqual(funnel.mtf_pass, 1)  # id3
        self.assertEqual(funnel.risk_allow, 1)  # id3
        self.assertEqual(funnel.orders_submitted, 1)  # id3
        self.assertEqual(funnel.fills, 0)  # no fills in test

    def test_percentile_calculations(self):
        """Test p50/p90 calculations for threshold stats"""
        events = [
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW', 'metadata': {'atr_pct': 0.3},
             'timestamp': '2025-12-27T20:00:00'},
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW', 'metadata': {'atr_pct': 0.4},
             'timestamp': '2025-12-27T20:00:10'},
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW', 'metadata': {'atr_pct': 0.45},
             'timestamp': '2025-12-27T20:00:20'},
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW', 'metadata': {'atr_pct': 0.48},
             'timestamp': '2025-12-27T20:00:30'},
        ]

        top_reasons = [('ATR_TOO_LOW', 'SMART_ENTRY', 4, 100.0)]
        threshold_stats = self.analyzer._calculate_threshold_stats(events, top_reasons)

        self.assertEqual(len(threshold_stats), 1)
        stat = threshold_stats[0]
        self.assertEqual(stat.reason_code, 'ATR_TOO_LOW')
        self.assertEqual(stat.metric_name, 'atr_pct')
        self.assertEqual(stat.threshold, 0.5)  # from config
        self.assertEqual(stat.threshold_direction, '>')
        self.assertAlmostEqual(stat.p50, 0.425, places=2)  # median of 0.4, 0.45
        self.assertAlmostEqual(stat.min_val, 0.3, places=2)
        self.assertAlmostEqual(stat.max_val, 0.48, places=2)
        self.assertEqual(stat.sample_count, 4)

    def test_threshold_comparison_with_config(self):
        """Test that thresholds are correctly extracted from config"""
        events = [
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'RSI_OVERBOUGHT', 'metadata': {'rsi': 85.0},
             'timestamp': '2025-12-27T20:00:00'},
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'RSI_OVERBOUGHT', 'metadata': {'rsi': 90.0},
             'timestamp': '2025-12-27T20:00:10'},
        ]

        top_reasons = [('RSI_OVERBOUGHT', 'SMART_ENTRY', 2, 100.0)]
        threshold_stats = self.analyzer._calculate_threshold_stats(events, top_reasons)

        self.assertEqual(len(threshold_stats), 1)
        stat = threshold_stats[0]
        self.assertEqual(stat.reason_code, 'RSI_OVERBOUGHT')
        self.assertEqual(stat.threshold, 80.0)  # rsi_block_min from config
        self.assertEqual(stat.threshold_direction, '<')
        self.assertAlmostEqual(stat.p50, 87.5, places=1)  # median of 85, 90

    def test_symbol_vampire_detection(self):
        """Test symbol ranking and vampire detection (>95% rejection)"""
        events = [
            # BTC-EUR: 1 denied, 1 passed = 50%
            {'event_type': 'gate_denied', 'symbol': 'BTC-EUR', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW', 'timestamp': '2025-12-27T20:00:00'},
            {'event_type': 'gate_passed', 'symbol': 'BTC-EUR', 'stage': 'SMART_ENTRY',
             'timestamp': '2025-12-27T20:00:10'},
            # ETH-EUR: 10 denied, 0 passed = 100% (vampire)
            *[{'event_type': 'gate_denied', 'symbol': 'ETH-EUR', 'stage': 'SMART_ENTRY',
               'reason_code': 'RSI_OVERBOUGHT', 'timestamp': f'2025-12-27T20:0{i}:00'}
              for i in range(10)],
            # ADA-EUR: 19 denied, 1 passed = 95% (not vampire, exactly at threshold)
            *[{'event_type': 'gate_denied', 'symbol': 'ADA-EUR', 'stage': 'SMART_ENTRY',
               'reason_code': 'VWAP_DEVIATION_TOO_HIGH', 'timestamp': f'2025-12-27T20:1{i}:00'}
              for i in range(9)],
            {'event_type': 'gate_passed', 'symbol': 'ADA-EUR', 'stage': 'SMART_ENTRY',
             'timestamp': '2025-12-27T20:19:10'},
        ]

        symbol_stats = self.analyzer._calculate_symbol_stats(events, top_n=3)

        # Should be sorted by denial_rate descending
        self.assertEqual(len(symbol_stats), 3)

        # ETH-EUR: 100% denial (vampire)
        eth_stat = symbol_stats[0]
        self.assertEqual(eth_stat.symbol, 'ETH-EUR')
        self.assertEqual(eth_stat.total_denied, 10)
        self.assertEqual(eth_stat.total_evaluated, 10)
        self.assertAlmostEqual(eth_stat.denial_rate, 100.0, places=1)
        self.assertEqual(eth_stat.top_reason, 'RSI_OVERBOUGHT')

        # ADA-EUR: 90% denial (9 denied, 1 passed)
        ada_stat = symbol_stats[1]
        self.assertEqual(ada_stat.symbol, 'ADA-EUR')
        self.assertAlmostEqual(ada_stat.denial_rate, 90.0, places=1)

        # BTC-EUR: 50% denial
        btc_stat = symbol_stats[2]
        self.assertEqual(btc_stat.symbol, 'BTC-EUR')
        self.assertAlmostEqual(btc_stat.denial_rate, 50.0, places=1)

    def test_regime_breakdown(self):
        """Test regime breakdown calculation"""
        events = [
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW', 'metadata': {'regime': 'BULL'},
             'timestamp': '2025-12-27T20:00:00'},
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW', 'metadata': {'regime': 'BULL'},
             'timestamp': '2025-12-27T20:00:10'},
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'RSI_OVERBOUGHT', 'metadata': {'regime': 'BEAR'},
             'timestamp': '2025-12-27T20:00:20'},
        ]

        regime_breakdown = self.analyzer._calculate_regime_breakdown(events, top_n=3)

        self.assertEqual(len(regime_breakdown), 2)

        # BULL regime
        bull_regime = next(r for r in regime_breakdown if r.regime == 'BULL')
        self.assertEqual(bull_regime.total_intents, 2)
        self.assertEqual(bull_regime.denied, 2)
        self.assertEqual(bull_regime.top_reasons[0][0], 'ATR_TOO_LOW')
        self.assertEqual(bull_regime.top_reasons[0][1], 2)  # count

        # BEAR regime
        bear_regime = next(r for r in regime_breakdown if r.regime == 'BEAR')
        self.assertEqual(bear_regime.total_intents, 1)
        self.assertEqual(bear_regime.denied, 1)
        self.assertEqual(bear_regime.top_reasons[0][0], 'RSI_OVERBOUGHT')

    def test_empty_events(self):
        """Test handling of empty event list"""
        events = []

        funnel = self.analyzer._calculate_funnel(events)
        self.assertEqual(funnel.intents_total, 0)
        self.assertEqual(funnel.smartentry_pass, 0)

        top_reasons = []
        threshold_stats = self.analyzer._calculate_threshold_stats(events, top_reasons)
        self.assertEqual(len(threshold_stats), 0)

        symbol_stats = self.analyzer._calculate_symbol_stats(events, top_n=5)
        self.assertEqual(len(symbol_stats), 0)

    def test_missing_metadata_handling(self):
        """Test handling of events with missing metadata fields"""
        events = [
            # Event without metadata
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW',
             'timestamp': '2025-12-27T20:00:00'},
            # Event with metadata but missing atr_pct
            {'event_type': 'gate_denied', 'stage': 'SMART_ENTRY',
             'reason_code': 'ATR_TOO_LOW', 'metadata': {'other_field': 123},
             'timestamp': '2025-12-27T20:00:10'},
        ]

        top_reasons = [('ATR_TOO_LOW', 'SMART_ENTRY', 2, 100.0)]
        # Should not crash, should return empty stats for this reason_code
        threshold_stats = self.analyzer._calculate_threshold_stats(events, top_reasons)
        # Either empty or skips ATR_TOO_LOW due to no valid samples
        if threshold_stats:
            self.assertNotEqual(threshold_stats[0].reason_code, 'ATR_TOO_LOW')

    def test_conversion_rate_calculation(self):
        """Test funnel conversion rate calculation"""
        funnel = FunnelMetrics(
            intents_total=100,
            smartentry_pass=80,
            mtf_pass=60,
            risk_allow=50,
            orders_submitted=40,
            fills=30
        )

        # Test conversion rates
        self.assertEqual(funnel.conversion_rate(80, 100), 80.0)
        self.assertEqual(funnel.conversion_rate(60, 80), 75.0)
        self.assertEqual(funnel.conversion_rate(0, 100), 0.0)
        self.assertEqual(funnel.conversion_rate(50, 0), 0.0)  # division by zero protection


class TestThresholdStats(unittest.TestCase):
    """Test ThresholdStats dataclass"""

    def test_threshold_stats_formatting(self):
        """Test string representation of ThresholdStats"""
        stat = ThresholdStats(
            reason_code='ATR_TOO_LOW',
            metric_name='atr_pct',
            threshold=0.5,
            threshold_direction='>',
            p50=0.35,
            p90=0.48,
            min_val=0.2,
            max_val=0.49,
            sample_count=100
        )

        output = str(stat)
        self.assertIn('ATR_TOO_LOW', output)
        self.assertIn('atr_pct', output)
        self.assertIn('0.50', output)  # threshold
        self.assertIn('≥', output)  # direction symbol
        self.assertIn('p50=0.35', output)
        self.assertIn('p90=0.48', output)
        self.assertIn('n=100', output)


class TestIntegration(unittest.TestCase):
    """Integration tests with real JSONL events"""

    def setUp(self):
        """Set up test fixtures with sample JSONL file"""
        self.temp_dir = tempfile.mkdtemp()
        self.log_dir = Path(self.temp_dir)

        # Create sample JSONL file with realistic events
        now = datetime.now()
        events = [
            # Scenario: 3 intents, 2 denied at smartentry, 1 passes all
            {'event_type': 'gate_denied', 'correlation_id': 'corr1', 'symbol': 'BTC-EUR',
             'stage': 'SMART_ENTRY', 'reason_code': 'ATR_TOO_LOW',
             'metadata': {'atr_pct': 0.3, 'exchange': 'kraken'},
             'timestamp': (now - timedelta(minutes=30)).isoformat()},
            {'event_type': 'gate_denied', 'correlation_id': 'corr2', 'symbol': 'ETH-EUR',
             'stage': 'SMART_ENTRY', 'reason_code': 'RSI_OVERBOUGHT',
             'metadata': {'rsi': 85.0, 'exchange': 'kraken'},
             'timestamp': (now - timedelta(minutes=20)).isoformat()},
            {'event_type': 'gate_passed', 'correlation_id': 'corr3', 'symbol': 'ADA-EUR',
             'stage': 'SMART_ENTRY', 'timestamp': (now - timedelta(minutes=10)).isoformat()},
            {'event_type': 'gate_passed', 'correlation_id': 'corr3', 'symbol': 'ADA-EUR',
             'stage': 'MTF', 'timestamp': (now - timedelta(minutes=9)).isoformat()},
            {'event_type': 'gate_passed', 'correlation_id': 'corr3', 'symbol': 'ADA-EUR',
             'stage': 'RISK', 'timestamp': (now - timedelta(minutes=8)).isoformat()},
            {'event_type': 'order_submitted', 'correlation_id': 'corr3', 'symbol': 'ADA-EUR',
             'timestamp': (now - timedelta(minutes=7)).isoformat()},
        ]

        # Write JSONL file
        log_file = self.log_dir / "events.jsonl"
        with open(log_file, 'w') as f:
            for event in events:
                f.write(json.dumps(event) + '\n')

        self.config = {
            'min_atr_pct_for_grid': 0.5,
            'rsi_block_min': 80.0,
        }

        self.analyzer = WhyNoTradeV2(self.log_dir, config=self.config)

    def test_full_analysis_integration(self):
        """Test full analyze() method with sample JSONL"""
        # Create events with current timestamps
        now = datetime.now()
        events = [
            {'event_type': 'gate_denied', 'correlation_id': 'corr1', 'symbol': 'BTC-EUR',
             'stage': 'SMART_ENTRY', 'reason_code': 'ATR_TOO_LOW',
             'metadata': {'atr_pct': 0.3, 'exchange': 'kraken'},
             'timestamp': now.isoformat()},
            {'event_type': 'gate_denied', 'correlation_id': 'corr2', 'symbol': 'ETH-EUR',
             'stage': 'SMART_ENTRY', 'reason_code': 'RSI_OVERBOUGHT',
             'metadata': {'rsi': 85.0, 'exchange': 'kraken'},
             'timestamp': now.isoformat()},
        ]

        # Write to today's log file
        today = now.strftime('%Y%m%d')
        log_file = self.log_dir / f"events_{today}.jsonl"
        with open(log_file, 'w') as f:
            for event in events:
                f.write(json.dumps(event) + '\n')

        report = self.analyzer.analyze(window_minutes=60, top_n_reasons=5, top_n_symbols=3)

        # Verify report contains expected sections
        self.assertIn('WHY-NO-TRADE REPORT v2', report)
        self.assertIn('PIPELINE FUNNEL', report)
        self.assertIn('Total Intents:', report)
        self.assertIn('TOP REJECTION REASONS', report)
        self.assertIn('THRESHOLDS vs REALITY', report)


if __name__ == '__main__':
    unittest.main()
