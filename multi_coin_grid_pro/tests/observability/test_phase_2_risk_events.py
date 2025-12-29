"""
Phase 2 Observability Tests: Risk Stage Event Emission

Tests that RiskGuard emits proper gate_denied/gate_passed events when:
- Exposure per coin limit exceeded
- Total exposure limit exceeded
- Kill switch active (daily loss limit)
- Risk checks pass
"""
import json
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock

from multi_coin_grid_pro.observability.event_logger import EventLogger
from multi_coin_grid_pro.risk.pnl_tracker import RealtimePnLTracker
from multi_coin_grid_pro.risk.risk_guard import RiskGuardV2


class TestPhase2RiskEvents(unittest.TestCase):
    """Test Phase 2: Risk stage event emission"""

    def setUp(self):
        """Setup test fixtures"""
        self.test_events_dir = Path(__file__).parent / "test_events_risk"
        self.test_events_dir.mkdir(exist_ok=True)

        # Create EventLogger (enabled)
        self.event_logger = EventLogger(
            enabled=True,
            output_dir=str(self.test_events_dir),
            buffer_size=1  # Write immediately for testing
        )

        # Mock PnL tracker
        self.pnl_tracker = Mock(spec=RealtimePnLTracker)
        self.pnl_tracker.starting_balance = Decimal("100")  # €100 starting capital
        self.pnl_tracker.positions = {}  # No open positions initially

        # Mock alerter
        self.alerter = Mock()

        # Create RiskGuard with EventLogger
        self.risk_guard = RiskGuardV2(
            cfg={
                'max_daily_loss_pct': 3.0,
                'max_weekly_loss_pct': 8.0,
                'max_monthly_loss_pct': 12.0,
                'max_exposure_per_coin_pct': 40,  # 40 = 40% (integer form)
                'max_total_exposure_pct': 80,    # 80 = 80% (integer form)
            },
            pnl_tracker=self.pnl_tracker,
            alerter=self.alerter,
            event_logger=self.event_logger
        )

    def tearDown(self):
        """Cleanup test files"""
        import shutil
        if self.test_events_dir.exists():
            shutil.rmtree(self.test_events_dir)

    def _read_all_events(self):
        """Read all events from JSONL files"""
        events = []
        for jsonl_file in self.test_events_dir.glob("events_*.jsonl"):
            with open(jsonl_file, 'r') as f:
                for line in f:
                    if line.strip():
                        events.append(json.loads(line))
        return events

    def test_exposure_per_coin_limit_emits_event(self):
        """Test that exceeding per-coin exposure limit emits gate_denied event"""
        # Arrange: Try to open position > 40% of capital (€50 > €40)
        correlation_id = "test-correlation-exposure-per-coin"

        # Act
        allowed, reason = self.risk_guard.can_open_position(
            symbol="BTC-EUR",
            size_eur=Decimal("50"),  # Exceeds €40 limit
            correlation_id=correlation_id
        )

        # Assert: Should deny
        self.assertFalse(allowed)
        self.assertIn("Position size", reason)
        self.assertIn("€50.00 > max €40.00", reason)

        # Validate event was emitted
        events = self._read_all_events()
        self.assertEqual(len(events), 1)

        event = events[0]
        self.assertEqual(event["event_type"], "gate_denied")
        self.assertEqual(event["stage"], "RISK")
        self.assertEqual(event["reason_code"], "EXPOSURE_LIMIT")
        self.assertEqual(event["symbol"], "BTC-EUR")
        self.assertEqual(event["correlation_id"], correlation_id)
        self.assertIn("exposure_type", event["metadata"])
        self.assertEqual(event["metadata"]["exposure_type"], "per_coin")
        self.assertEqual(event["metadata"]["size_eur"], 50.0)

    def test_total_exposure_limit_emits_event(self):
        """Test that exceeding total exposure limit emits gate_denied event"""
        # Arrange: Create fake position of €60, then try to add €30 (total=€90 > €80)
        mock_position = Mock()
        mock_position.notional_eur = Decimal("60")
        self.pnl_tracker.positions = {"ETH-EUR": mock_position}

        correlation_id = "test-correlation-exposure-total"

        # Act
        allowed, reason = self.risk_guard.can_open_position(
            symbol="BTC-EUR",
            size_eur=Decimal("30"),  # Would push total to €90
            correlation_id=correlation_id
        )

        # Assert: Should deny
        self.assertFalse(allowed)
        self.assertIn("Total exposure", reason)
        self.assertIn("€90.00 > max €80.00", reason)

        # Validate event
        events = self._read_all_events()
        self.assertEqual(len(events), 1)

        event = events[0]
        self.assertEqual(event["event_type"], "gate_denied")
        self.assertEqual(event["stage"], "RISK")
        self.assertEqual(event["reason_code"], "EXPOSURE_LIMIT")
        self.assertEqual(event["metadata"]["exposure_type"], "total")
        self.assertEqual(event["metadata"]["current_total_exposure"], 60.0)

    def test_kill_switch_active_emits_event(self):
        """Test that active kill switch emits gate_denied event"""
        # Arrange: Activate kill switch
        self.risk_guard.trading_enabled = False
        self.risk_guard.kill_reason = "Daily loss -3.5% ≤ -3.0%"

        correlation_id = "test-correlation-kill-switch"

        # Act
        allowed, reason = self.risk_guard.can_open_position(
            symbol="SOL-EUR",
            size_eur=Decimal("20"),
            correlation_id=correlation_id
        )

        # Assert: Should deny
        self.assertFalse(allowed)
        self.assertIn("Kill switch active", reason)

        # Validate event
        events = self._read_all_events()
        self.assertEqual(len(events), 1)

        event = events[0]
        self.assertEqual(event["event_type"], "gate_denied")
        self.assertEqual(event["stage"], "RISK")
        self.assertEqual(event["reason_code"], "DAILY_LOSS_LIMIT")
        self.assertIn("Kill switch active", event["reason_msg"])

    def test_risk_checks_pass_no_event(self):
        """Test that passing risk checks does NOT emit event (only denials emit)"""
        # Note: gate_passed event is emitted by controller, not RiskGuard
        # RiskGuard only emits gate_denied events

        correlation_id = "test-correlation-pass"

        # Act
        allowed, reason = self.risk_guard.can_open_position(
            symbol="NEAR-EUR",
            size_eur=Decimal("30"),  # Within limits
            correlation_id=correlation_id
        )

        # Assert: Should allow
        self.assertTrue(allowed)
        self.assertEqual(reason, "Position allowed")

        # Validate NO event emitted (gate_passed is controller's job)
        events = self._read_all_events()
        self.assertEqual(len(events), 0, "RiskGuard should not emit gate_passed, only gate_denied")

    def test_event_logger_disabled_no_events(self):
        """Test that disabled event logger doesn't emit events"""
        # Arrange: Create RiskGuard without event_logger
        risk_guard_no_logger = RiskGuardV2(
            cfg={'max_exposure_per_coin_pct': 40, 'max_total_exposure_pct': 80},
            pnl_tracker=self.pnl_tracker,
            alerter=self.alerter,
            event_logger=None  # No logger
        )

        # Act: Trigger denial
        allowed, reason = risk_guard_no_logger.can_open_position(
            symbol="BTC-EUR",
            size_eur=Decimal("50"),  # Exceeds limit
            correlation_id="test-no-logger"
        )

        # Assert: Should deny but no events
        self.assertFalse(allowed)
        # No events to check - EventLogger was never created


if __name__ == '__main__':
    unittest.main()
