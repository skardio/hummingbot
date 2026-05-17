"""
Integration test for EventLogger with correlation_id tracking.

Simulates 5 coin evaluations with different decision outcomes:
1. SmartEntry rejection (RSI)
2. SmartEntry pass → MTF rejection
3. Risk rejection (cooldown)
4. Full approval → order submission
5. Execution rejection (blacklist)

Verifies JSONL output contains:
- All events with correlation_id
- Correct stage + reason_code for rejections
- Config hash in all events
"""

import json
import tempfile
import unittest
from pathlib import Path

from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage
from multi_coin_grid_pro.observability.event_logger import EventLogger


class TestEventLoggerIntegration(unittest.TestCase):
    """Integration test suite for EventLogger"""

    def setUp(self):
        """Create temp directory for test events"""
        self.temp_dir = tempfile.mkdtemp()

    def test_five_decisions_with_correlation_id(self):
        """
        Simulate 5 coin evaluations with different outcomes.
        Verify JSONL contains correlation_id, stage, reason_code for each.
        """
        logger = EventLogger(
            enabled=True,
            output_dir=self.temp_dir,
            buffer_size=5,  # Force flush after 5 events
            config_hash="test_abc123"
        )

        # ===== Decision 1: SmartEntry reject (RSI) =====
        logger.emit_gate_denied(
            correlation_id="corr_001",
            symbol="BTC-EUR",
            stage=Stage.SMART_ENTRY,
            reason_code=ReasonCode.RSI_OVERBOUGHT,
            reason_msg="RSI 75.3 > 60.0 (overbought)",
            metadata={"rsi": 75.3, "threshold": 60.0}
        )

        # ===== Decision 2: SmartEntry pass → MTF reject =====
        logger.emit_gate_passed(
            correlation_id="corr_002",
            symbol="ETH-EUR",
            stage=Stage.SMART_ENTRY,
            metadata={"rsi": 45.2, "vwap_dev": 1.2, "regime": "BULL"}
        )

        logger.emit_gate_denied(
            correlation_id="corr_002",  # Same correlation as pass
            symbol="ETH-EUR",
            stage=Stage.MTF,
            reason_code=ReasonCode.MTF_INSUFFICIENT,
            reason_msg="1h trend -2.5% < -2.0% (too weak)",
            metadata={"timeframe": "1h", "trend_pct": -2.5}
        )

        # ===== Decision 3: Risk reject (cooldown) =====
        logger.emit_gate_denied(
            correlation_id="corr_003",
            symbol="SOL-EUR",
            stage=Stage.RISK,
            reason_code=ReasonCode.COOLDOWN_EXIT,
            reason_msg="Exit cooldown active (120s remaining)",
            metadata={"remaining_seconds": 120}
        )

        # ===== Decision 4: Full approval + order =====
        logger.emit_gate_passed(
            correlation_id="corr_004",
            symbol="ADA-EUR",
            stage=Stage.SMART_ENTRY,
            metadata={}
        )

        logger.emit_gate_passed(
            correlation_id="corr_004",
            symbol="ADA-EUR",
            stage=Stage.MTF,
            metadata={"trend_1h": 1.2, "trend_4h": 2.3}
        )

        logger.emit_order_submitted(
            correlation_id="corr_004",
            symbol="ADA-EUR",
            order_id="order_xyz123",
            side="BUY",
            price=0.4523,
            amount=1000
        )

        # ===== Decision 5: Execution reject (blacklist) =====
        logger.emit_gate_denied(
            correlation_id="corr_005",
            symbol="DOGE-EUR",
            stage=Stage.EXECUTION,
            reason_code=ReasonCode.BLACKLIST,
            reason_msg="Coin in config blacklist",
            metadata={"blacklist_type": "config"}
        )

        # Force flush and close
        logger.flush()
        logger.close()

        # ===== Verify JSONL Output =====
        event_files = list(Path(self.temp_dir).glob("events_*.jsonl"))
        self.assertEqual(len(event_files), 1, "Should have exactly 1 event file")

        with open(event_files[0], "r") as f:
            events = [json.loads(line) for line in f]

        # Verify event count (config_loaded + 8 events)
        self.assertEqual(len(events), 9, f"Expected 9 events, got {len(events)}")

        # Verify config_loaded event
        config_event = events[0]
        self.assertEqual(config_event["event_type"], "config_loaded")
        self.assertEqual(config_event["config_hash"], "test_abc123")

        # Verify all events have config_hash
        for event in events:
            self.assertIn("config_hash", event)
            self.assertEqual(event["config_hash"], "test_abc123")

        # Verify gate_denied events
        gate_denied_events = [e for e in events if e["event_type"] == "gate_denied"]
        self.assertEqual(len(gate_denied_events), 4, "Expected 4 gate_denied events")

        # Verify each gate_denied has required fields
        for event in gate_denied_events:
            self.assertIn("correlation_id", event)
            self.assertIn("stage", event)
            self.assertIn("reason_code", event)
            self.assertIn("symbol", event)
            self.assertIn("reason_msg", event)
            self.assertIn("metadata", event)
            self.assertIn("regime", event)

        # Verify gate_passed events
        gate_passed_events = [e for e in events if e["event_type"] == "gate_passed"]
        self.assertEqual(len(gate_passed_events), 3, "Expected 3 gate_passed events")

        for event in gate_passed_events:
            self.assertIn("correlation_id", event)
            self.assertIn("stage", event)
            self.assertIn("symbol", event)
            self.assertIn("regime", event)

        # ===== Verify Specific Event Details =====

        # Decision 1: BTC-EUR RSI rejection
        btc_event = next(
            e for e in events
            if e.get("symbol") == "BTC-EUR" and e["event_type"] == "gate_denied"
        )
        self.assertEqual(btc_event["stage"], "SMART_ENTRY")
        self.assertEqual(btc_event["reason_code"], "RSI_OVERBOUGHT")
        self.assertEqual(btc_event["correlation_id"], "corr_001")
        self.assertIn("rsi", btc_event["metadata"])
        self.assertEqual(btc_event["metadata"]["rsi"], 75.3)

        # Decision 2: ETH-EUR SmartEntry pass then MTF reject
        eth_passed = next(
            e for e in events
            if e.get("symbol") == "ETH-EUR"
            and e["event_type"] == "gate_passed"
            and e["stage"] == "SMART_ENTRY"
        )
        self.assertEqual(eth_passed["correlation_id"], "corr_002")
        self.assertEqual(eth_passed["regime"], "BULL")

        eth_denied = next(
            e for e in events
            if e.get("symbol") == "ETH-EUR" and e["event_type"] == "gate_denied"
        )
        self.assertEqual(eth_denied["correlation_id"], "corr_002")  # Same correlation
        self.assertEqual(eth_denied["stage"], "MTF")
        self.assertEqual(eth_denied["reason_code"], "MTF_INSUFFICIENT")

        # Decision 3: SOL-EUR risk cooldown
        sol_event = next(
            e for e in events
            if e.get("symbol") == "SOL-EUR" and e["event_type"] == "gate_denied"
        )
        self.assertEqual(sol_event["stage"], "RISK")
        self.assertEqual(sol_event["reason_code"], "COOLDOWN_EXIT")
        self.assertEqual(sol_event["correlation_id"], "corr_003")

        # Decision 4: ADA-EUR full approval + order
        ada_order = next(
            e for e in events
            if e.get("symbol") == "ADA-EUR" and e["event_type"] == "order_submitted"
        )
        self.assertEqual(ada_order["correlation_id"], "corr_004")
        self.assertEqual(ada_order["order_id"], "order_xyz123")
        self.assertEqual(ada_order["side"], "BUY")
        self.assertEqual(ada_order["price"], 0.4523)

        # Decision 5: DOGE-EUR blacklist
        doge_event = next(
            e for e in events
            if e.get("symbol") == "DOGE-EUR" and e["event_type"] == "gate_denied"
        )
        self.assertEqual(doge_event["stage"], "EXECUTION")
        self.assertEqual(doge_event["reason_code"], "BLACKLIST")
        self.assertEqual(doge_event["correlation_id"], "corr_005")

    def test_logger_disabled_mode(self):
        """Verify EventLogger does nothing when disabled"""
        logger = EventLogger(
            enabled=False,
            output_dir=self.temp_dir,
            config_hash="test456"
        )

        # Emit events (should be no-ops)
        logger.emit_gate_denied(
            correlation_id="x",
            symbol="BTC-EUR",
            stage=Stage.SMART_ENTRY,
            reason_code=ReasonCode.RSI_OVERBOUGHT,
            reason_msg="test"
        )
        logger.flush()
        logger.close()

        # Verify no files created
        event_files = list(Path(self.temp_dir).glob("events_*.jsonl"))
        self.assertEqual(len(event_files), 0, "Should have no files when disabled")

    def test_buffer_auto_flush(self):
        """Verify buffer auto-flushes at buffer_size"""
        logger = EventLogger(
            enabled=True,
            output_dir=self.temp_dir,
            buffer_size=3,  # Flush every 3 events
            config_hash="test789"
        )

        # Emit 3 events (should trigger auto-flush)
        for i in range(3):
            logger.emit_gate_passed(
                correlation_id=f"c{i}",
                symbol="TEST-EUR",
                stage=Stage.SMART_ENTRY,
                metadata={}
            )

        # Read file (should have config_loaded + 3 events)
        logger.close()

        event_files = list(Path(self.temp_dir).glob("events_*.jsonl"))
        self.assertEqual(len(event_files), 1)

        with open(event_files[0], "r") as f:
            events = [json.loads(line) for line in f]

        # Config event + 3 gate_passed
        self.assertEqual(len(events), 4)


if __name__ == "__main__":
    unittest.main()
