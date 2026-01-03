"""
Story C1: Log Throttling Unit Tests
====================================

Tests for LogThrottle, StructuredLogger, and LogBudget.
"""

import time
import unittest
from unittest.mock import MagicMock

from multi_coin_grid_pro.utils.log_throttle import LogBudget, LogThrottle, StructuredLogger


class TestLogThrottle(unittest.TestCase):
    """Test LogThrottle time-based and count-based throttling"""

    def setUp(self):
        """Create fresh throttle for each test"""
        self.throttle = LogThrottle()

    def test_time_based_throttle_first_log_allowed(self):
        """Test: First log is always allowed"""
        self.assertTrue(self.throttle.should_log("test_key", interval_sec=30))

    def test_time_based_throttle_blocks_rapid_logs(self):
        """Test: Rapid logs within interval are throttled"""
        key = "test_key"

        # First log allowed
        self.assertTrue(self.throttle.should_log(key, interval_sec=30))

        # Immediate second log blocked
        self.assertFalse(self.throttle.should_log(key, interval_sec=30))
        self.assertFalse(self.throttle.should_log(key, interval_sec=30))

    def test_time_based_throttle_allows_after_interval(self):
        """Test: Log allowed after interval passes"""
        key = "test_key"
        interval = 0.1  # 100ms for fast test

        # First log
        self.assertTrue(self.throttle.should_log(key, interval_sec=interval))

        # Blocked immediately
        self.assertFalse(self.throttle.should_log(key, interval_sec=interval))

        # Wait for interval
        time.sleep(interval + 0.01)

        # Now allowed
        self.assertTrue(self.throttle.should_log(key, interval_sec=interval))

    def test_different_keys_independent(self):
        """Test: Different keys have independent throttles"""
        self.assertTrue(self.throttle.should_log("key1", interval_sec=30))
        self.assertTrue(self.throttle.should_log("key2", interval_sec=30))

        # Both keys now throttled
        self.assertFalse(self.throttle.should_log("key1", interval_sec=30))
        self.assertFalse(self.throttle.should_log("key2", interval_sec=30))

    def test_count_based_throttle_every_nth(self):
        """Test: Count-based throttling logs every Nth occurrence"""
        key = "count_test"
        max_count = 5

        # First 4 occurrences blocked (count < max)
        self.assertFalse(self.throttle.should_log_count(key, max_count=max_count))
        self.assertFalse(self.throttle.should_log_count(key, max_count=max_count))
        self.assertFalse(self.throttle.should_log_count(key, max_count=max_count))
        self.assertFalse(self.throttle.should_log_count(key, max_count=max_count))

        # 5th occurrence allowed
        self.assertTrue(self.throttle.should_log_count(key, max_count=max_count))

        # Counter resets - next 4 blocked again
        self.assertFalse(self.throttle.should_log_count(key, max_count=max_count))
        self.assertFalse(self.throttle.should_log_count(key, max_count=max_count))

    def test_reset_specific_key(self):
        """Test: Reset specific key clears throttle"""
        key = "test_key"

        # Throttle key
        self.assertTrue(self.throttle.should_log(key, interval_sec=30))
        self.assertFalse(self.throttle.should_log(key, interval_sec=30))

        # Reset key
        self.throttle.reset(key)

        # Now allowed again
        self.assertTrue(self.throttle.should_log(key, interval_sec=30))

    def test_reset_all_keys(self):
        """Test: Reset without key clears all throttles"""
        self.assertTrue(self.throttle.should_log("key1", interval_sec=30))
        self.assertTrue(self.throttle.should_log("key2", interval_sec=30))

        # Both throttled
        self.assertFalse(self.throttle.should_log("key1", interval_sec=30))
        self.assertFalse(self.throttle.should_log("key2", interval_sec=30))

        # Reset all
        self.throttle.reset()

        # Both allowed again
        self.assertTrue(self.throttle.should_log("key1", interval_sec=30))
        self.assertTrue(self.throttle.should_log("key2", interval_sec=30))

    def test_accumulate_and_get_summary(self):
        """Test: Summary stats accumulation"""
        key = "summary_test"

        # Accumulate stats
        self.throttle.accumulate_stat(key, "fills", 1)
        self.throttle.accumulate_stat(key, "fills", 1)
        self.throttle.accumulate_stat(key, "fills", 1)
        self.throttle.accumulate_stat(key, "pnl", 2.5)
        self.throttle.accumulate_stat(key, "pnl", 1.5)

        # Get summary
        stats = self.throttle.get_summary(key, reset=False)

        self.assertEqual(stats["fills"], 3)
        self.assertEqual(stats["pnl"], 4.0)

        # Stats still there (no reset)
        stats2 = self.throttle.get_summary(key, reset=False)
        self.assertEqual(stats2["fills"], 3)

        # Get with reset
        stats3 = self.throttle.get_summary(key, reset=True)
        self.assertEqual(stats3["fills"], 3)

        # Now empty
        stats4 = self.throttle.get_summary(key, reset=False)
        self.assertEqual(stats4, {})


class TestStructuredLogger(unittest.TestCase):
    """Test StructuredLogger formatting"""

    def setUp(self):
        """Create mock logger"""
        self.mock_logger = MagicMock()
        self.slog = StructuredLogger(self.mock_logger)

    def test_info_log_formatting(self):
        """Test: INFO log formatted correctly"""
        self.slog.info("GRID_SUMMARY", symbol="BTC-EUR", pnl=2.5, fills=3)

        # Verify called with formatted string
        self.mock_logger.info.assert_called_once()
        call_args = self.mock_logger.info.call_args[0][0]

        self.assertIn("GRID_SUMMARY", call_args)
        self.assertIn("symbol=BTC-EUR", call_args)
        self.assertIn("pnl=2.5", call_args)
        self.assertIn("fills=3", call_args)

    def test_warning_log_formatting(self):
        """Test: WARNING log formatted correctly"""
        self.slog.warning("TIMEOUT_TRIGGER", reason="NO_FILL", age=1800)

        self.mock_logger.warning.assert_called_once()
        call_args = self.mock_logger.warning.call_args[0][0]

        self.assertIn("TIMEOUT_TRIGGER", call_args)
        self.assertIn("reason=NO_FILL", call_args)
        self.assertIn("age=1800", call_args)

    def test_error_log_formatting(self):
        """Test: ERROR log formatted correctly"""
        self.slog.error("UNWIND_FAILED", reason="ORDER_REJECTED", attempts=3)

        self.mock_logger.error.assert_called_once()
        call_args = self.mock_logger.error.call_args[0][0]

        self.assertIn("UNWIND_FAILED", call_args)
        self.assertIn("reason=ORDER_REJECTED", call_args)
        self.assertIn("attempts=3", call_args)

    def test_key_value_ordering(self):
        """Test: Keys sorted for consistent output"""
        self.slog.info("TEST", z=3, a=1, m=2)

        call_args = self.mock_logger.info.call_args[0][0]

        # Keys should appear in alphabetical order
        a_pos = call_args.index("a=1")
        m_pos = call_args.index("m=2")
        z_pos = call_args.index("z=3")

        self.assertLess(a_pos, m_pos)
        self.assertLess(m_pos, z_pos)

    def test_float_precision_formatting(self):
        """Test: Floats formatted with reasonable precision"""
        self.slog.info("TEST", price=50000.123456789)

        call_args = self.mock_logger.info.call_args[0][0]

        # Should not have excessive decimals
        self.assertIn("price=50000.123456", call_args)


class TestLogBudget(unittest.TestCase):
    """Test LogBudget monitoring"""

    def test_within_budget_allows_logs(self):
        """Test: Logs allowed when within budget"""
        budget = LogBudget(max_lines_per_hour=100)

        # First 100 logs allowed
        for _ in range(100):
            self.assertTrue(budget.check_and_increment())

    def test_exceeding_budget_blocks_logs(self):
        """Test: Logs blocked when budget exceeded"""
        budget = LogBudget(max_lines_per_hour=10)

        # First 10 allowed
        for _ in range(10):
            self.assertTrue(budget.check_and_increment())

        # 11th blocked
        self.assertFalse(budget.check_and_increment())
        self.assertFalse(budget.check_and_increment())

    def test_budget_resets_after_hour(self):
        """Test: Budget resets after 1 hour window"""
        budget = LogBudget(max_lines_per_hour=5)

        # Use up budget
        for _ in range(5):
            budget.check_and_increment()

        # Blocked
        self.assertFalse(budget.check_and_increment())

        # Simulate hour passing (hack internal state for test speed)
        budget.window_start = time.time() - 3601

        # Now allowed again
        self.assertTrue(budget.check_and_increment())

    def test_get_usage_stats(self):
        """Test: Usage stats correct"""
        budget = LogBudget(max_lines_per_hour=100)

        # Log 25 times
        for _ in range(25):
            budget.check_and_increment()

        stats = budget.get_usage()

        self.assertEqual(stats["lines_logged"], 25)
        self.assertEqual(stats["max_lines"], 100)
        self.assertEqual(stats["utilization_pct"], 25.0)
        self.assertGreater(stats["current_rate_per_hour"], 0)


class TestIntegrationScenario(unittest.TestCase):
    """Integration tests: real-world usage patterns"""

    def test_grid_summary_logging_with_throttle(self):
        """Test: Grid summary logged once per 30s"""
        throttle = LogThrottle()
        logger = MagicMock()

        # Simulate control loop - log at 0s
        key = "grid_summary_BTC-EUR"
        if throttle.should_log(key, interval_sec=30):
            logger.info("GRID_SUMMARY | fills=0")

        # Simulate waiting 30s and log again
        throttle._last_log_times[key] = throttle._last_log_times[key] - 30
        if throttle.should_log(key, interval_sec=30):
            logger.info("GRID_SUMMARY | fills=30")

        # Should log 2 times (initial + after 30s)
        self.assertEqual(logger.info.call_count, 2)

    def test_event_logging_with_budget(self):
        """Test: Event logs respect budget"""
        budget = LogBudget(max_lines_per_hour=50)
        logger = MagicMock()

        # Simulate 100 events
        for i in range(100):
            if budget.check_and_increment():
                logger.info(f"EVENT_{i}")

        # Only first 50 logged
        self.assertEqual(logger.info.call_count, 50)


if __name__ == "__main__":
    unittest.main()
