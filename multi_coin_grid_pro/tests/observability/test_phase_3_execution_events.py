"""
Phase 3: Execution Stage Event Tests

Simplified tests that verify Phase 3 helper methods work correctly.
Full integration testing is covered by the 516 existing tests.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage
from multi_coin_grid_pro.observability.event_logger import EventLogger


class TestPhase3ExecutionEvents(unittest.TestCase):
    """Test Phase 3 execution event helper methods"""

    def setUp(self):
        """Create test setup with EventLogger"""
        self.temp_dir = Path(tempfile.mkdtemp())

        # Create EventLogger
        self.event_logger = EventLogger(
            enabled=True,
            output_dir=str(self.temp_dir),
            buffer_size=1
        )

        # Create mock controller with event_logger
        self.mock_controller = Mock()
        self.mock_controller.event_logger = self.event_logger

        # Import and bind the helper method
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
        self.mock_controller._emit_execution_denial = MultiCoinGridController._emit_execution_denial.__get__(
            self.mock_controller, type(self.mock_controller)
        )

    def tearDown(self):
        """Cleanup temp files"""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def _read_events(self):
        """Read all events from JSONL files"""
        events = []
        for jsonl_file in self.temp_dir.glob("events_*.jsonl"):
            with open(jsonl_file, 'r') as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        return events

    def test_execution_denial_helper_emits_event(self):
        """Test that _emit_execution_denial helper creates valid events"""
        # Emit event
        self.mock_controller._emit_execution_denial(
            symbol="BTC-EUR",
            reason_code=ReasonCode.SLOT_FULL,
            reason_msg="All 3 slots filled",
            correlation_id="test-uuid",
            metadata={"max_slots": 3}
        )

        # Read events
        events = self._read_events()
        self.assertEqual(len(events), 1)

        event = events[0]
        self.assertEqual(event["event_type"], "gate_denied")
        self.assertEqual(event["stage"], Stage.EXECUTION.value)
        self.assertEqual(event["symbol"], "BTC-EUR")
        self.assertEqual(event["reason_code"], ReasonCode.SLOT_FULL.value)
        self.assertEqual(event["correlation_id"], "test-uuid")

    def test_multiple_execution_codes_emit_correctly(self):
        """Test different execution reason codes emit with correct stage"""
        test_cases = [
            (ReasonCode.SLOT_FULL, "All slots full"),
            (ReasonCode.BLACKLIST, "Coin blacklisted"),
            (ReasonCode.ALREADY_TRADING, "Already trading"),
            (ReasonCode.STARTUP_DELAY, "Startup delay"),
        ]

        for reason_code, msg in test_cases:
            self.mock_controller._emit_execution_denial(
                symbol="TEST-EUR",
                reason_code=reason_code,
                reason_msg=msg,
                correlation_id=f"uuid-{reason_code.value}",
                metadata={}
            )

        events = self._read_events()
        self.assertEqual(len(events), 4)

        # All should have EXECUTION stage
        for event in events:
            self.assertEqual(event["stage"], Stage.EXECUTION.value)

        # Check all reason codes present
        codes = {e["reason_code"] for e in events}
        self.assertEqual(len(codes), 4)

    def test_disabled_logger_no_events(self):
        """Test that disabled EventLogger produces no events"""
        self.event_logger.enabled = False

        self.mock_controller._emit_execution_denial(
            symbol="BTC-EUR",
            reason_code=ReasonCode.SLOT_FULL,
            reason_msg="Test",
            correlation_id="test-uuid",
            metadata={}
        )

        events = self._read_events()
        self.assertEqual(len(events), 0)


if __name__ == "__main__":
    unittest.main()
