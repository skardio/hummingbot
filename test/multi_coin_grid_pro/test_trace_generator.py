"""
Test suite for US-007: Trace ID Generator.

Tests:
1. TraceGenerator produces unique IDs
2. TraceContext carries data through pipeline
3. TraceStage constants
4. TraceLogger formats messages correctly
"""

import importlib.util
import os
import time
import unittest
from unittest.mock import MagicMock

# Load the module directly to avoid dependency chain
spec = importlib.util.spec_from_file_location(
    "trace_generator",
    os.path.join(os.path.dirname(__file__), '..', '..', 'multi_coin_grid_pro', 'utils', 'trace_generator.py')
)
trace_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace_module)

TraceGenerator = trace_module.TraceGenerator
TraceContext = trace_module.TraceContext
TraceStage = trace_module.TraceStage
TraceLogger = trace_module.TraceLogger
generate_trace_id = trace_module.generate_trace_id
get_trace_generator = trace_module.get_trace_generator


class TestTraceGenerator(unittest.TestCase):
    """Test TraceGenerator class."""

    def setUp(self):
        """Set up test fixtures."""
        self.generator = TraceGenerator()

    def test_generate_returns_string(self):
        """Test that generate() returns a string."""
        trace_id = self.generator.generate()
        self.assertIsInstance(trace_id, str)

    def test_generate_format(self):
        """Test that trace ID has expected format: T-YYMMDD-HHMMSS-XXXXXX."""
        trace_id = self.generator.generate()

        # Should match pattern T-YYMMDD-HHMMSS-XXXXXX
        pattern = r'^T-\d{6}-\d{6}-[A-Z0-9]{6}$'
        self.assertRegex(trace_id, pattern, f"Trace ID '{trace_id}' doesn't match expected format")

    def test_generate_unique_ids(self):
        """Test that multiple generates produce unique IDs."""
        ids = [self.generator.generate() for _ in range(100)]
        unique_ids = set(ids)
        self.assertEqual(len(ids), len(unique_ids), "All trace IDs should be unique")

    def test_custom_prefix(self):
        """Test that custom prefix is used."""
        custom_gen = TraceGenerator(prefix="ORDER")
        trace_id = custom_gen.generate()
        self.assertTrue(trace_id.startswith("ORDER-"), "Trace ID should start with ORDER-")

    def test_generate_context(self):
        """Test generate_context returns TraceContext."""
        context = self.generator.generate_context("BTC-USDT", stage="INIT")

        self.assertIsInstance(context, TraceContext)
        self.assertEqual(context.symbol, "BTC-USDT")
        self.assertEqual(context.stage, "INIT")
        self.assertIsNotNone(context.trace_id)

    def test_generate_context_with_metadata(self):
        """Test generate_context with metadata."""
        context = self.generator.generate_context(
            "ETH-USDT",
            stage="SMART_ENTRY",
            rsi=45.5,
            trend="bullish"
        )

        self.assertEqual(context.symbol, "ETH-USDT")
        self.assertEqual(context.metadata["rsi"], 45.5)
        self.assertEqual(context.metadata["trend"], "bullish")


class TestTraceContext(unittest.TestCase):
    """Test TraceContext class."""

    def test_to_dict(self):
        """Test to_dict() returns all fields."""
        context = TraceContext(
            trace_id="T-241216-142532-ABC123",
            symbol="BTC-USDT",
            stage="ORDER_SUBMIT"
        )

        d = context.to_dict()

        self.assertEqual(d["trace_id"], "T-241216-142532-ABC123")
        self.assertEqual(d["symbol"], "BTC-USDT")
        self.assertEqual(d["stage"], "ORDER_SUBMIT")
        self.assertIn("created_at", d)
        self.assertIn("created_at_iso", d)

    def test_with_stage(self):
        """Test with_stage() returns new context."""
        context = TraceContext(
            trace_id="T-123",
            symbol="BTC-USDT",
            stage="INIT"
        )

        new_context = context.with_stage("ORDER_FILLED")

        # Original unchanged
        self.assertEqual(context.stage, "INIT")
        # New context has updated stage
        self.assertEqual(new_context.stage, "ORDER_FILLED")
        # Same trace_id preserved
        self.assertEqual(new_context.trace_id, "T-123")

    def test_with_metadata(self):
        """Test with_metadata() adds metadata."""
        context = TraceContext(
            trace_id="T-123",
            symbol="BTC-USDT",
            stage="INIT",
            metadata={"rsi": 50}
        )

        new_context = context.with_metadata(price=45000, qty=0.1)

        # Original unchanged
        self.assertEqual(context.metadata, {"rsi": 50})
        # New context has merged metadata
        self.assertEqual(new_context.metadata["rsi"], 50)
        self.assertEqual(new_context.metadata["price"], 45000)
        self.assertEqual(new_context.metadata["qty"], 0.1)

    def test_created_at_default(self):
        """Test created_at is set to current time by default."""
        before = time.time()
        context = TraceContext(trace_id="T-123", symbol="BTC-USDT")
        after = time.time()

        self.assertGreaterEqual(context.created_at, before)
        self.assertLessEqual(context.created_at, after)


class TestTraceStage(unittest.TestCase):
    """Test TraceStage constants."""

    def test_entry_stages_exist(self):
        """Test entry decision stages exist."""
        self.assertEqual(TraceStage.SMART_ENTRY_CHECK, "SMART_ENTRY_CHECK")
        self.assertEqual(TraceStage.SMART_ENTRY_APPROVED, "SMART_ENTRY_APPROVED")
        self.assertEqual(TraceStage.SMART_ENTRY_DENIED, "SMART_ENTRY_DENIED")

    def test_budget_stages_exist(self):
        """Test budget stages exist."""
        self.assertEqual(TraceStage.BUDGET_CHECK, "BUDGET_CHECK")
        self.assertEqual(TraceStage.BUDGET_APPROVED, "BUDGET_APPROVED")
        self.assertEqual(TraceStage.BUDGET_DENIED, "BUDGET_DENIED")

    def test_executor_stages_exist(self):
        """Test executor stages exist."""
        self.assertEqual(TraceStage.EXECUTOR_CREATE, "EXECUTOR_CREATE")
        self.assertEqual(TraceStage.EXECUTOR_STARTED, "EXECUTOR_STARTED")
        self.assertEqual(TraceStage.EXECUTOR_RUNNING, "EXECUTOR_RUNNING")
        self.assertEqual(TraceStage.EXECUTOR_CLOSING, "EXECUTOR_CLOSING")
        self.assertEqual(TraceStage.EXECUTOR_CLOSED, "EXECUTOR_CLOSED")

    def test_order_stages_exist(self):
        """Test order stages exist."""
        self.assertEqual(TraceStage.ORDER_PREPARE, "ORDER_PREPARE")
        self.assertEqual(TraceStage.ORDER_VALIDATE, "ORDER_VALIDATE")
        self.assertEqual(TraceStage.ORDER_SKIPPED, "ORDER_SKIPPED")
        self.assertEqual(TraceStage.ORDER_SUBMIT, "ORDER_SUBMIT")
        self.assertEqual(TraceStage.ORDER_CREATED, "ORDER_CREATED")
        self.assertEqual(TraceStage.ORDER_REJECTED, "ORDER_REJECTED")
        self.assertEqual(TraceStage.ORDER_FILLED, "ORDER_FILLED")
        self.assertEqual(TraceStage.ORDER_CANCELLED, "ORDER_CANCELLED")


class TestTraceLogger(unittest.TestCase):
    """Test TraceLogger class."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_logger = MagicMock()
        self.context = TraceContext(
            trace_id="T-241216-142532-ABC123",
            symbol="BTC-USDT",
            stage="ORDER_SUBMIT"
        )
        self.trace_logger = TraceLogger(self.mock_logger, self.context)

    def test_info_logs_with_context(self):
        """Test info() includes trace context."""
        self.trace_logger.info("Order submitted")

        self.mock_logger.info.assert_called_once()
        logged_message = self.mock_logger.info.call_args[0][0]

        self.assertIn("T-241216-142532-ABC123", logged_message)
        self.assertIn("BTC-USDT", logged_message)
        self.assertIn("ORDER_SUBMIT", logged_message)
        self.assertIn("Order submitted", logged_message)

    def test_info_with_kwargs(self):
        """Test info() includes kwargs in message."""
        self.trace_logger.info("Order created", order_id="xyz", price=45000)

        logged_message = self.mock_logger.info.call_args[0][0]
        self.assertIn("order_id=xyz", logged_message)
        self.assertIn("price=45000", logged_message)

    def test_warning_logs(self):
        """Test warning() calls logger.warning."""
        self.trace_logger.warning("Low balance")
        self.mock_logger.warning.assert_called_once()

    def test_error_logs(self):
        """Test error() calls logger.error."""
        self.trace_logger.error("Order failed")
        self.mock_logger.error.assert_called_once()

    def test_debug_logs(self):
        """Test debug() calls logger.debug."""
        self.trace_logger.debug("Checking price")
        self.mock_logger.debug.assert_called_once()

    def test_with_stage_returns_new_logger(self):
        """Test with_stage() returns new logger with updated stage."""
        new_logger = self.trace_logger.with_stage("ORDER_FILLED")
        new_logger.info("Fill complete")

        logged_message = self.mock_logger.info.call_args[0][0]
        self.assertIn("ORDER_FILLED", logged_message)

        # Original stage unchanged
        self.assertEqual(self.trace_logger._context.stage, "ORDER_SUBMIT")


class TestConvenienceFunctions(unittest.TestCase):
    """Test module-level convenience functions."""

    def test_generate_trace_id(self):
        """Test generate_trace_id() convenience function."""
        trace_id = generate_trace_id()
        self.assertIsInstance(trace_id, str)
        self.assertTrue(trace_id.startswith("T-"))

    def test_get_trace_generator_singleton(self):
        """Test get_trace_generator returns same instance."""
        gen1 = get_trace_generator()
        gen2 = get_trace_generator()
        self.assertIs(gen1, gen2)


class TestTraceIdUniqueness(unittest.TestCase):
    """Test trace ID uniqueness under load."""

    def test_rapid_generation_unique(self):
        """Test rapid generation still produces unique IDs."""
        generator = TraceGenerator()

        # Generate 1000 IDs as fast as possible
        ids = []
        for _ in range(1000):
            ids.append(generator.generate())

        unique_ids = set(ids)
        self.assertEqual(len(ids), len(unique_ids), "Rapid generation should still be unique")

    def test_trace_id_parseable(self):
        """Test trace ID can be parsed back to components."""
        generator = TraceGenerator()
        trace_id = generator.generate()

        parts = trace_id.split("-")
        self.assertEqual(len(parts), 4, "Trace ID should have 4 parts")
        self.assertEqual(parts[0], "T", "First part should be prefix")
        self.assertEqual(len(parts[1]), 6, "Date part should be 6 chars")
        self.assertEqual(len(parts[2]), 6, "Time part should be 6 chars")
        self.assertEqual(len(parts[3]), 6, "Suffix should be 6 chars")


if __name__ == '__main__':
    unittest.main()
