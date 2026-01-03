"""
Story B2: Audit Records Unit Tests
===================================

Tests for ExecutionAudit and AuditWriter.
"""

import shutil
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from multi_coin_grid_pro.models.execution_audit import AuditWriter, ExecutionAudit, create_audit_from_executor


class TestExecutionAudit(unittest.TestCase):
    """Test ExecutionAudit dataclass"""

    def test_audit_creation_with_minimal_fields(self):
        """Test: Audit can be created with required fields"""
        audit = ExecutionAudit(
            symbol="BTC-EUR",
            executor_id="test-123",
            start_ts=1000.0,
            end_ts=2000.0,
            duration_sec=1000.0,
            close_reason="TAKE_PROFIT",
            close_type_priority=10,
            realized_pnl_quote="5.50",
            fees_quote="0.10",
            net_pnl_quote="5.40",
            num_fills=5,
            num_open_fills=3,
            num_close_fills=2,
            num_closed_levels=2,
            time_to_first_fill_sec=100.0,
            time_to_last_fill_sec=900.0,
            time_in_graceful_unwind_sec=None,
            time_in_aggressive_unwind_sec=None,
            timeout_triggered=False,
            timeout_type=None,
            unwind_phase_reached=None,
            graceful_close_success=None,
            max_adverse_excursion=None,
            max_favorable_excursion=None,
            max_position_size_quote=None,
            config_snapshot={},
        )

        self.assertEqual(audit.symbol, "BTC-EUR")
        self.assertEqual(audit.close_reason, "TAKE_PROFIT")
        self.assertEqual(audit.num_fills, 5)
        self.assertFalse(audit.timeout_triggered)

    def test_audit_to_json_and_back(self):
        """Test: Audit can be serialized to JSON and deserialized"""
        audit = ExecutionAudit(
            symbol="ETH-EUR",
            executor_id="test-456",
            start_ts=1000.0,
            end_ts=1500.0,
            duration_sec=500.0,
            close_reason="NO_FILL_TIMEOUT",
            close_type_priority=50,
            realized_pnl_quote="0.00",
            fees_quote="0.00",
            net_pnl_quote="0.00",
            num_fills=0,
            num_open_fills=0,
            num_close_fills=0,
            num_closed_levels=0,
            time_to_first_fill_sec=None,
            time_to_last_fill_sec=None,
            time_in_graceful_unwind_sec=None,
            time_in_aggressive_unwind_sec=None,
            timeout_triggered=True,
            timeout_type="NO_FILL_TIMEOUT",
            unwind_phase_reached=None,
            graceful_close_success=None,
            max_adverse_excursion=None,
            max_favorable_excursion=None,
            max_position_size_quote=None,
            config_snapshot={"no_fill_timeout_sec": 1800},
        )

        # Serialize
        json_str = audit.to_json()
        self.assertIn("ETH-EUR", json_str)
        self.assertIn("NO_FILL_TIMEOUT", json_str)

        # Deserialize
        import json
        data = json.loads(json_str)
        audit2 = ExecutionAudit.from_dict(data)

        self.assertEqual(audit2.symbol, "ETH-EUR")
        self.assertEqual(audit2.close_reason, "NO_FILL_TIMEOUT")
        self.assertTrue(audit2.timeout_triggered)
        self.assertEqual(audit2.timeout_type, "NO_FILL_TIMEOUT")

    def test_timeout_audit_fields(self):
        """Test: Timeout audit has correct fields"""
        audit = ExecutionAudit(
            symbol="SOL-EUR",
            executor_id="test-789",
            start_ts=1000.0,
            end_ts=4600.0,
            duration_sec=3600.0,
            close_reason="NO_PROGRESS_TIMEOUT",
            close_type_priority=60,
            realized_pnl_quote="-1.20",
            fees_quote="0.30",
            net_pnl_quote="-1.50",
            num_fills=2,
            num_open_fills=2,
            num_close_fills=0,
            num_closed_levels=0,
            time_to_first_fill_sec=600.0,
            time_to_last_fill_sec=1200.0,
            time_in_graceful_unwind_sec=120.0,
            time_in_aggressive_unwind_sec=10.0,
            timeout_triggered=True,
            timeout_type="NO_PROGRESS_TIMEOUT",
            unwind_phase_reached="AGGRESSIVE",
            graceful_close_success=False,
            max_adverse_excursion=None,
            max_favorable_excursion=None,
            max_position_size_quote="60.00",
            config_snapshot={},
        )

        self.assertTrue(audit.timeout_triggered)
        self.assertEqual(audit.timeout_type, "NO_PROGRESS_TIMEOUT")
        self.assertEqual(audit.unwind_phase_reached, "AGGRESSIVE")
        self.assertFalse(audit.graceful_close_success)
        self.assertEqual(audit.time_in_graceful_unwind_sec, 120.0)
        self.assertEqual(audit.time_in_aggressive_unwind_sec, 10.0)


class TestAuditWriter(unittest.TestCase):
    """Test AuditWriter (file operations)"""

    def setUp(self):
        """Create temp directory for test outputs"""
        self.temp_dir = tempfile.mkdtemp()
        self.writer = AuditWriter(audit_dir=self.temp_dir)

    def tearDown(self):
        """Clean up temp directory"""
        shutil.rmtree(self.temp_dir)

    def test_write_and_read_single_audit(self):
        """Test: Write audit record and read it back"""
        from datetime import datetime

        # Use current timestamp so writer uses today's date
        now = datetime.utcnow().timestamp()

        audit = ExecutionAudit(
            symbol="BTC-EUR",
            executor_id="test-001",
            start_ts=now,
            end_ts=now + 1000.0,
            duration_sec=1000.0,
            close_reason="TAKE_PROFIT",
            close_type_priority=10,
            realized_pnl_quote="10.00",
            fees_quote="0.20",
            net_pnl_quote="9.80",
            num_fills=4,
            num_open_fills=2,
            num_close_fills=2,
            num_closed_levels=2,
            time_to_first_fill_sec=50.0,
            time_to_last_fill_sec=950.0,
            time_in_graceful_unwind_sec=None,
            time_in_aggressive_unwind_sec=None,
            timeout_triggered=False,
            timeout_type=None,
            unwind_phase_reached=None,
            graceful_close_success=None,
            max_adverse_excursion=None,
            max_favorable_excursion=None,
            max_position_size_quote=None,
            config_snapshot={},
        )

        # Write
        self.writer.write(audit)

        # Read back
        from datetime import datetime
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        audits = self.writer.read_day(date_str)

        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].symbol, "BTC-EUR")
        self.assertEqual(audits[0].close_reason, "TAKE_PROFIT")

    def test_write_multiple_audits_same_day(self):
        """Test: Multiple audits written to same file"""
        from datetime import datetime

        # Use current timestamp so all audits use today's date
        now = datetime.utcnow().timestamp()

        audits_to_write = []
        for i in range(5):
            audit = ExecutionAudit(
                symbol=f"COIN{i}-EUR",
                executor_id=f"test-{i:03d}",
                start_ts=now + i * 100,
                end_ts=now + 1000.0 + i * 100,
                duration_sec=1000.0,
                close_reason="TAKE_PROFIT" if i % 2 == 0 else "NO_FILL_TIMEOUT",
                close_type_priority=10,
                realized_pnl_quote=f"{i}.00",
                fees_quote="0.10",
                net_pnl_quote=f"{i - 0.1:.2f}",
                num_fills=i,
                num_open_fills=i,
                num_close_fills=0,
                num_closed_levels=0,
                time_to_first_fill_sec=None,
                time_to_last_fill_sec=None,
                time_in_graceful_unwind_sec=None,
                time_in_aggressive_unwind_sec=None,
                timeout_triggered=(i % 2 == 1),
                timeout_type="NO_FILL_TIMEOUT" if i % 2 == 1 else None,
                unwind_phase_reached=None,
                graceful_close_success=None,
                max_adverse_excursion=None,
                max_favorable_excursion=None,
                max_position_size_quote=None,
                config_snapshot={},
            )
            audits_to_write.append(audit)
            self.writer.write(audit)

        # Read all
        from datetime import datetime
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        audits_read = self.writer.read_day(date_str)

        self.assertEqual(len(audits_read), 5)

        # Verify order preserved
        for i, audit in enumerate(audits_read):
            self.assertEqual(audit.symbol, f"COIN{i}-EUR")

    def test_read_latest_n_audits(self):
        """Test: Read latest N audits across files"""
        # Write 3 audits
        for i in range(3):
            audit = ExecutionAudit(
                symbol=f"TEST{i}-EUR",
                executor_id=f"test-{i}",
                start_ts=1000.0 + i,
                end_ts=2000.0 + i,
                duration_sec=1000.0,
                close_reason="TAKE_PROFIT",
                close_type_priority=10,
                realized_pnl_quote="1.00",
                fees_quote="0.10",
                net_pnl_quote="0.90",
                num_fills=1,
                num_open_fills=1,
                num_close_fills=0,
                num_closed_levels=0,
                time_to_first_fill_sec=None,
                time_to_last_fill_sec=None,
                time_in_graceful_unwind_sec=None,
                time_in_aggressive_unwind_sec=None,
                timeout_triggered=False,
                timeout_type=None,
                unwind_phase_reached=None,
                graceful_close_success=None,
                max_adverse_excursion=None,
                max_favorable_excursion=None,
                max_position_size_quote=None,
                config_snapshot={},
            )
            self.writer.write(audit)

        # Read latest 2
        latest = self.writer.read_latest(n=2)
        self.assertEqual(len(latest), 2)

        # Should be in reverse order (newest first)
        self.assertEqual(latest[0].symbol, "TEST2-EUR")
        self.assertEqual(latest[1].symbol, "TEST1-EUR")

    def test_read_nonexistent_day(self):
        """Test: Reading nonexistent day returns empty list"""
        audits = self.writer.read_day("2020-01-01")
        self.assertEqual(audits, [])


class TestCreateAuditFromExecutor(unittest.TestCase):
    """Test create_audit_from_executor() helper"""

    def test_create_audit_from_mock_executor(self):
        """Test: Can create audit from mock executor"""
        # Create minimal mock executor
        executor = MagicMock()
        executor.current_timestamp = 2000.0
        executor._start_timestamp = 1000.0
        executor._last_fill_timestamp = 1500.0
        executor.cum_realized_pnl_quote = Decimal("5.50")
        executor.cum_fees_quote = Decimal("0.10")
        executor.filled_orders = [1, 2, 3]
        executor.open_fills = [1, 2]
        executor.close_fills = [3]
        executor.closed_levels = [1]
        executor._unwind_phase = "GRACEFUL"
        executor._unwind_graceful_start_ts = 1900.0

        executor.config = MagicMock()
        executor.config.connector_name = "kraken"
        executor.config.trading_pair = "BTC-EUR"
        executor.config.total_amount_quote = Decimal("60")
        executor.config.start_price = Decimal("50000")
        executor.config.grid_range_pct_down = Decimal("0.02")
        executor.config.grid_range_pct_up = Decimal("0.02")
        executor.config.num_grids = 5
        executor.config.custom_info = {
            "no_fill_timeout_sec": 1800,
            "no_progress_timeout_sec": 3600,
            "close_grace_sec": 120,
        }

        # Create audit
        audit = create_audit_from_executor(executor, "TAKE_PROFIT")

        # Verify
        self.assertEqual(audit.symbol, "BTC-EUR")
        self.assertEqual(audit.close_reason, "TAKE_PROFIT")
        self.assertEqual(audit.duration_sec, 1000.0)
        self.assertEqual(audit.num_fills, 3)
        self.assertEqual(audit.time_to_first_fill_sec, 500.0)
        self.assertFalse(audit.timeout_triggered)
        self.assertEqual(audit.unwind_phase_reached, "GRACEFUL")
        self.assertTrue(audit.graceful_close_success)


if __name__ == "__main__":
    unittest.main()
