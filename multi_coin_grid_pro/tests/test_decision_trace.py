"""
Unit tests for Decision Trace System

Tests the decision trace functionality using the existing PairDecisionTrace implementation.
"""

import unittest

from multi_coin_grid_pro.utils.decision_trace import FilterCheck, PairDecisionTrace


class TestFilterCheck(unittest.TestCase):
    """Test suite for FilterCheck"""

    def test_filter_check_with_threshold(self):
        """Test FilterCheck with single threshold"""
        check = FilterCheck(
            filter_name="rsi_check",
            value=45.0,
            threshold=70.0,
            passed=True,
            operator="<="
        )

        self.assertEqual(check.filter_name, "rsi_check")
        self.assertEqual(check.value, 45.0)
        self.assertTrue(check.passed)

    def test_filter_check_to_dict(self):
        """Test conversion to dictionary"""
        check = FilterCheck(
            filter_name="trend_check",
            value=2.5,
            threshold=0.5,
            passed=True
        )

        result = check.to_dict()
        self.assertIn("filter", result)
        self.assertTrue(result["passed"])


class TestPairDecisionTrace(unittest.TestCase):
    """Test suite for PairDecisionTrace"""

    def setUp(self):
        """Set up test fixtures"""
        self.trace = PairDecisionTrace(
            trading_pair="BTC-USDT",
            exchange="bitget",
            enabled=True
        )

    def test_initialization(self):
        """Test PairDecisionTrace initialization"""
        self.assertEqual(self.trace.trading_pair, "BTC-USDT")
        self.assertEqual(self.trace.exchange, "bitget")
        self.assertTrue(self.trace.enabled)
        self.assertEqual(len(self.trace.checks), 0)

    def test_add_check(self):
        """Test adding filter checks"""
        self.trace.add_check(
            filter_name="rsi_check",
            value=45.0,
            threshold=70.0,
            passed=True
        )

        self.assertEqual(len(self.trace.checks), 1)
        self.assertTrue(self.trace.checks[0].passed)

    def test_finalize_accepted(self):
        """Test finalizing with accepted decision"""
        self.trace.add_check("rsi", value=45.0, threshold=70.0, passed=True)
        self.trace.finalize(accepted=True)

        self.assertTrue(self.trace.accepted)

    def test_finalize_rejected(self):
        """Test finalizing with rejected decision"""
        self.trace.add_check("rsi", value=85.0, threshold=70.0, passed=False)
        self.trace.finalize(accepted=False, rejected_by="rsi")

        self.assertFalse(self.trace.accepted)
        self.assertEqual(self.trace.rejected_by, "rsi")


if __name__ == "__main__":
    unittest.main()
