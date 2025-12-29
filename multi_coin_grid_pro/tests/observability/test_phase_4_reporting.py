"""
Tests for EventAggregator and ConsoleReporter.

Phase 4: US-E3 "Why No Trade?" Summary Report
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage
from multi_coin_grid_pro.observability.console_reporter import ConsoleReporter
from multi_coin_grid_pro.observability.event_aggregator import AggregationPeriod, EventAggregator, PeriodSummary


class TestEventAggregator(unittest.TestCase):
    """Test EventAggregator functionality"""

    def setUp(self):
        """Create test setup with sample events"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.aggregator = EventAggregator(self.temp_dir)

        # Create sample events file
        self.now = datetime.now()
        self.events_file = self.temp_dir / "events_test.jsonl"

        # Create sample events spanning 3 hours
        self.sample_events = []

        # Hour 0: 5 RSI rejections, 3 ATR rejections
        for i in range(5):
            self.sample_events.append({
                'timestamp': (self.now - timedelta(hours=2, minutes=i)).isoformat(),
                'event_type': 'gate_denied',
                'stage': Stage.SMART_ENTRY.value,
                'reason_code': ReasonCode.RSI_EXTREME_BLOCK.value,
                'symbol': 'BTC-EUR',
                'correlation_id': f'test-{i}'
            })

        for i in range(3):
            self.sample_events.append({
                'timestamp': (self.now - timedelta(hours=2, minutes=10 + i)).isoformat(),
                'event_type': 'gate_denied',
                'stage': Stage.SMART_ENTRY.value,
                'reason_code': ReasonCode.ATR_TOO_LOW.value,
                'symbol': 'ETH-EUR',
                'correlation_id': f'test-atr-{i}'
            })

        # Hour 1: 2 SLOT_FULL rejections, 1 approval
        for i in range(2):
            self.sample_events.append({
                'timestamp': (self.now - timedelta(hours=1, minutes=i)).isoformat(),
                'event_type': 'gate_denied',
                'stage': Stage.EXECUTION.value,
                'reason_code': ReasonCode.SLOT_FULL.value,
                'symbol': 'ADA-EUR',
                'correlation_id': f'test-slot-{i}'
            })

        self.sample_events.append({
            'timestamp': (self.now - timedelta(hours=1, minutes=30)).isoformat(),
            'event_type': 'gate_passed',
            'stage': Stage.SMART_ENTRY.value,
            'symbol': 'DOT-EUR',
            'correlation_id': 'test-passed-1'
        })

        # Write events to file
        with open(self.events_file, 'w') as f:
            for event in self.sample_events:
                f.write(json.dumps(event) + '\n')

    def tearDown(self):
        """Cleanup temp files"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_read_events_all(self):
        """Test reading all events from file"""
        events = self.aggregator.read_events()
        self.assertEqual(len(events), 11)  # 5 RSI + 3 ATR + 2 SLOT_FULL + 1 passed

    def test_read_events_with_time_filter(self):
        """Test reading events with time range filter"""
        # Read only events from last hour
        start_time = self.now - timedelta(hours=1, minutes=30)
        events = self.aggregator.read_events(start_time=start_time)

        # Should get 2 SLOT_FULL + 1 passed = 3 events
        self.assertEqual(len(events), 3)

    def test_aggregate_period(self):
        """Test aggregating events for a specific period"""
        # Aggregate 2 hours ago (should get RSI + ATR rejections)
        period = AggregationPeriod(
            start_time=self.now - timedelta(hours=3),
            end_time=self.now - timedelta(hours=1, minutes=59)
        )

        summary = self.aggregator._aggregate_period(period)

        self.assertEqual(summary.total_intents, 8)  # 5 RSI + 3 ATR
        self.assertEqual(summary.denied, 8)
        self.assertEqual(summary.approved, 0)
        self.assertEqual(summary.denial_rate, 100.0)

        # Check top rejections
        self.assertEqual(len(summary.top_rejections), 2)  # RSI and ATR
        self.assertEqual(summary.top_rejections[0].reason_code, ReasonCode.RSI_EXTREME_BLOCK.value)
        self.assertEqual(summary.top_rejections[0].count, 5)
        self.assertEqual(summary.top_rejections[1].reason_code, ReasonCode.ATR_TOO_LOW.value)
        self.assertEqual(summary.top_rejections[1].count, 3)

    def test_aggregate_hourly(self):
        """Test hourly aggregation"""
        summaries = self.aggregator.aggregate_hourly(date=self.now, hours=3)

        self.assertEqual(len(summaries), 3)

        # Check that we got summaries for each hour
        self.assertIsInstance(summaries[0], PeriodSummary)

    def test_get_summary_stats(self):
        """Test summary statistics calculation"""
        stats = self.aggregator.get_summary_stats(hours=24)

        self.assertIn('total_intents', stats)
        self.assertIn('total_denied', stats)
        self.assertIn('total_approved', stats)
        self.assertIn('denial_rate', stats)
        self.assertIn('top_rejection_reasons', stats)

        # Should have total of 11 events
        self.assertEqual(stats['total_intents'], 11)
        self.assertEqual(stats['total_denied'], 10)
        self.assertEqual(stats['total_approved'], 1)

        # Check top rejection reasons
        top_reasons = stats['top_rejection_reasons']
        self.assertGreater(len(top_reasons), 0)
        self.assertEqual(top_reasons[0]['reason_code'], ReasonCode.RSI_EXTREME_BLOCK.value)
        self.assertEqual(top_reasons[0]['count'], 5)

    def test_rejections_by_stage(self):
        """Test stage breakdown"""
        period = AggregationPeriod(
            start_time=self.now - timedelta(hours=3),
            end_time=self.now
        )

        summary = self.aggregator._aggregate_period(period)

        # Should have rejections from SMART_ENTRY and EXECUTION stages
        self.assertIn(Stage.SMART_ENTRY.value, summary.rejections_by_stage)
        self.assertIn(Stage.EXECUTION.value, summary.rejections_by_stage)

        # SMART_ENTRY should have 8 rejections (5 RSI + 3 ATR)
        self.assertEqual(summary.rejections_by_stage[Stage.SMART_ENTRY.value], 8)

        # EXECUTION should have 2 rejections (2 SLOT_FULL)
        self.assertEqual(summary.rejections_by_stage[Stage.EXECUTION.value], 2)

    def test_rejections_by_symbol(self):
        """Test symbol breakdown"""
        period = AggregationPeriod(
            start_time=self.now - timedelta(hours=3),
            end_time=self.now
        )

        summary = self.aggregator._aggregate_period(period)

        # Should track rejections per symbol
        self.assertIn('BTC-EUR', summary.rejections_by_symbol)
        self.assertIn('ETH-EUR', summary.rejections_by_symbol)
        self.assertIn('ADA-EUR', summary.rejections_by_symbol)

        self.assertEqual(summary.rejections_by_symbol['BTC-EUR'], 5)  # RSI rejections
        self.assertEqual(summary.rejections_by_symbol['ETH-EUR'], 3)  # ATR rejections
        self.assertEqual(summary.rejections_by_symbol['ADA-EUR'], 2)  # SLOT_FULL rejections


class TestConsoleReporter(unittest.TestCase):
    """Test ConsoleReporter functionality"""

    def setUp(self):
        """Create test setup"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.reporter = ConsoleReporter(self.temp_dir, bot_name="test_bot")

        # Create sample events
        now = datetime.now()
        events_file = self.temp_dir / "events_test.jsonl"

        sample_events = [
            {
                'timestamp': (now - timedelta(minutes=30)).isoformat(),
                'event_type': 'gate_denied',
                'stage': Stage.SMART_ENTRY.value,
                'reason_code': ReasonCode.RSI_EXTREME_BLOCK.value,
                'symbol': 'BTC-EUR',
                'correlation_id': 'test-1'
            },
            {
                'timestamp': (now - timedelta(minutes=20)).isoformat(),
                'event_type': 'gate_passed',
                'stage': Stage.SMART_ENTRY.value,
                'symbol': 'ETH-EUR',
                'correlation_id': 'test-2'
            }
        ]

        with open(events_file, 'w') as f:
            for event in sample_events:
                f.write(json.dumps(event) + '\n')

    def tearDown(self):
        """Cleanup"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_reporter_initialization(self):
        """Test that reporter initializes correctly"""
        self.assertIsNotNone(self.reporter.aggregator)
        self.assertIsNotNone(self.reporter.logger)

    def test_report_summary_no_crash(self):
        """Test that summary report doesn't crash"""
        # Should not raise exception
        try:
            self.reporter.report_summary(hours=1)
        except Exception as e:
            self.fail(f"report_summary raised exception: {e}")

    def test_report_by_stage_no_crash(self):
        """Test that stage report doesn't crash"""
        try:
            self.reporter.report_by_stage(hours=1)
        except Exception as e:
            self.fail(f"report_by_stage raised exception: {e}")

    def test_report_by_symbol_no_crash(self):
        """Test that symbol report doesn't crash"""
        try:
            self.reporter.report_by_symbol(hours=1, top_n=5)
        except Exception as e:
            self.fail(f"report_by_symbol raised exception: {e}")

    def test_full_dashboard_no_crash(self):
        """Test that full dashboard doesn't crash"""
        try:
            self.reporter.report_full_dashboard(hours=1)
        except Exception as e:
            self.fail(f"report_full_dashboard raised exception: {e}")


if __name__ == "__main__":
    unittest.main()
