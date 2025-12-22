"""
Unit tests for Decision Trace Integration

Tests the integration of decision trace with the controller.
"""

import unittest

from multi_coin_grid_pro.utils.decision_trace import PairDecisionTrace


class TestDecisionTraceIntegration(unittest.TestCase):
    """Test suite for Decision Trace Integration"""

    def setUp(self):
        """Set up test fixtures"""
        self.trace = PairDecisionTrace(
            trading_pair="BTC-USDT",
            exchange="bitget",
            enabled=True
        )

    def test_integration_buy_flow(self):
        """Test integration with buy decision flow"""
        # Simulate controller making a buy decision
        self.trace.add_check("rsi_check", value=45.0, threshold=70.0, passed=True)
        self.trace.add_check("atr_check", value=0.25, threshold=0.15, passed=True)
        self.trace.add_check("trend_check", value=2.5, threshold=0.5, passed=True)
        self.trace.finalize(accepted=True, final_reason="All filters passed")

        # Verify trace recorded correctly
        self.assertTrue(self.trace.accepted)
        self.assertEqual(len(self.trace.checks), 3)

    def test_integration_sell_flow(self):
        """Test integration with sell decision flow"""
        # Simulate sell decision
        self.trace.add_check("profit_target", value=2.5, threshold=2.0, passed=True)
        self.trace.finalize(accepted=True, final_reason="Take profit")

        self.assertTrue(self.trace.accepted)

    def test_integration_rejected_flow(self):
        """Test integration with rejected decision"""
        self.trace.add_check("rsi_check", value=85.0, threshold=70.0, passed=False)
        self.trace.finalize(accepted=False, rejected_by="rsi_check")

        self.assertFalse(self.trace.accepted)
        self.assertEqual(self.trace.rejected_by, "rsi_check")

    def test_integration_with_disabled_trace(self):
        """Test that disabled trace doesn't impact performance"""
        disabled_trace = PairDecisionTrace(
            trading_pair="ETH-USDT",
            exchange="kraken",
            enabled=False
        )

        # Should not record anything
        disabled_trace.add_check("test", value=1.0, threshold=0.5, passed=True)
        disabled_trace.finalize(accepted=True)

        self.assertEqual(len(disabled_trace.checks), 0)

    def test_integration_multiple_pairs(self):
        """Test tracing multiple pairs simultaneously"""
        traces = []

        for pair in ["BTC-USDT", "ETH-USDT", "SOL-USDT"]:
            trace = PairDecisionTrace(
                trading_pair=pair,
                exchange="bitget",
                enabled=True
            )
            trace.add_check("trend", value=1.5, threshold=0.5, passed=True)
            trace.finalize(accepted=True)
            traces.append(trace)

        # All should be independent
        self.assertEqual(len(traces), 3)
        for trace in traces:
            self.assertTrue(trace.accepted)

    def test_integration_to_dict_output(self):
        """Test that to_dict works for logging/storage"""
        self.trace.add_check("rsi", value=45.0, threshold=70.0, passed=True)
        self.trace.finalize(accepted=True)

        output = self.trace.to_dict()

        self.assertIsInstance(output, dict)
        self.assertIn("trading_pair", output)
        self.assertIn("decision", output)

    def test_integration_compact_log_output(self):
        """Test compact log for console output"""
        self.trace.add_check("rsi", value=45.0, threshold=70.0, passed=True)
        self.trace.finalize(accepted=True)

        compact = self.trace.to_compact_log()

        self.assertIsInstance(compact, str)
        self.assertIn("BTC-USDT", compact)


if __name__ == "__main__":
    unittest.main()
