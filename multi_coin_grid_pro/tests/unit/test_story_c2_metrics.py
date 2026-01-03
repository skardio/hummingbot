"""
Unit tests for Story C2: Metrics Export + KPI Calculation

Tests MetricsCalculator and PeriodMetrics functionality.
"""

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from multi_coin_grid_pro.models.execution_audit import AuditWriter, ExecutionAudit
from multi_coin_grid_pro.utils.metrics_calculator import MetricsCalculator


def create_test_audit(
    symbol: str = "TEST-USD",
    start_ts: float = None,
    duration_sec: float = 900,
    close_reason: str = "TAKE_PROFIT",
    net_pnl_quote: str = "10.0",
    realized_pnl_quote: str = "11.0",
    fees_quote: str = "1.0",
    num_open_fills: int = 2,
    num_close_fills: int = 2,
    time_to_first_fill_sec: float = 30.0,
    timeout_triggered: bool = False,
    timeout_type: str = None,
    unwind_phase_reached: str = None,
    graceful_close_success: bool = None
) -> ExecutionAudit:
    """Helper to create test audit with correct field names"""
    if start_ts is None:
        start_ts = datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S").timestamp()

    end_ts = start_ts + duration_sec

    return ExecutionAudit(
        symbol=symbol,
        executor_id=f"exec_{symbol}_{int(start_ts)}",
        start_ts=start_ts,
        end_ts=end_ts,
        duration_sec=duration_sec,
        close_reason=close_reason,
        close_type_priority=1,
        realized_pnl_quote=realized_pnl_quote,
        fees_quote=fees_quote,
        net_pnl_quote=net_pnl_quote,
        num_fills=num_open_fills + num_close_fills,
        num_open_fills=num_open_fills,
        num_close_fills=num_close_fills,
        num_closed_levels=num_close_fills,
        time_to_first_fill_sec=time_to_first_fill_sec,
        time_to_last_fill_sec=duration_sec if num_close_fills > 0 else None,
        time_in_graceful_unwind_sec=None,
        time_in_aggressive_unwind_sec=None,
        timeout_triggered=timeout_triggered,
        timeout_type=timeout_type,
        unwind_phase_reached=unwind_phase_reached,
        graceful_close_success=graceful_close_success,
        max_adverse_excursion=None,
        max_favorable_excursion=None,
        max_position_size_quote=None,
        config_snapshot={"grid_range_down": 0.05, "grid_range_up": 0.05},
        version="1.0"
    )


class TestMetricsCalculator(unittest.TestCase):
    """Test MetricsCalculator KPI calculations"""

    def setUp(self):
        """Create temp dir for test audits"""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.calculator = MetricsCalculator(audit_dir=self.temp_dir)
        self.writer = AuditWriter(audit_dir=self.temp_dir)

    def tearDown(self):
        """Clean up temp dir"""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_empty_period_metrics(self):
        """Empty metrics when no audits found"""
        metrics = self.calculator.calculate_period_metrics(days=7)

        self.assertEqual(metrics.total_executions, 0)
        self.assertEqual(metrics.total_pnl_net, "0")
        self.assertEqual(metrics.win_rate, 0.0)
        self.assertEqual(metrics.timeout_rate, 0.0)
        self.assertIsNone(metrics.avg_time_to_first_fill_sec)

    def test_single_execution_metrics(self):
        """Metrics from single audit"""
        # Create test audit using helper
        start_time = datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S")
        audit = create_test_audit(
            symbol="PEPE-USD",
            start_ts=start_time.timestamp(),
            duration_sec=900,  # 15 minutes
            close_reason="TAKE_PROFIT",
            realized_pnl_quote="100.50",
            fees_quote="5.25",
            net_pnl_quote="95.25",
            num_open_fills=5,
            num_close_fills=5,
            time_to_first_fill_sec=45.0,
            timeout_triggered=False,
            unwind_phase_reached=None
        )

        self.writer.write(audit)

        # Calculate metrics
        end_date = datetime.strptime("2025-12-30", "%Y-%m-%d")
        metrics = self.calculator.calculate_period_metrics(days=1, end_date=end_date)

        self.assertEqual(metrics.total_executions, 1)
        self.assertEqual(metrics.total_pnl_net, "95.25")
        self.assertEqual(metrics.win_rate, 1.0)  # 100% profitable
        self.assertEqual(metrics.timeout_rate, 0.0)
        self.assertEqual(metrics.avg_time_to_first_fill_sec, 45.0)
        self.assertEqual(metrics.total_open_fills, 5)
        self.assertEqual(metrics.total_close_fills, 5)

    def test_multiple_executions_aggregate(self):
        """Aggregate metrics from multiple audits"""
        # Create 3 test audits (2 profitable, 1 loss)
        start_times = [
            datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S"),
            datetime.strptime("2025-12-30 11:00:00", "%Y-%m-%d %H:%M:%S"),
            datetime.strptime("2025-12-30 13:00:00", "%Y-%m-%d %H:%M:%S")
        ]

        audits = [
            create_test_audit(
                symbol="PEPE-USD",
                start_ts=start_times[0].timestamp(),
                duration_sec=1800,
                close_reason="TAKE_PROFIT",
                realized_pnl_quote="50.0",
                fees_quote="2.0",
                net_pnl_quote="48.0",
                num_open_fills=3,
                num_close_fills=3,
                time_to_first_fill_sec=30.0,
                timeout_triggered=False,
                unwind_phase_reached=None
            ),
            create_test_audit(
                symbol="BTC-USD",
                start_ts=start_times[1].timestamp(),
                duration_sec=3600,
                close_reason="STOP_LOSS",
                realized_pnl_quote="-20.0",
                fees_quote="3.0",
                net_pnl_quote="-23.0",
                num_open_fills=2,
                num_close_fills=2,
                time_to_first_fill_sec=120.0,
                timeout_triggered=False,
                unwind_phase_reached="GRACEFUL"
            ),
            create_test_audit(
                symbol="ETH-USD",
                start_ts=start_times[2].timestamp(),
                duration_sec=600,
                close_reason="TAKE_PROFIT",
                realized_pnl_quote="75.0",
                fees_quote="5.0",
                net_pnl_quote="70.0",
                num_open_fills=4,
                num_close_fills=4,
                time_to_first_fill_sec=60.0,
                timeout_triggered=False,
                unwind_phase_reached=None
            )
        ]

        for audit in audits:
            self.writer.write(audit)

        # Calculate metrics
        end_date = datetime.strptime("2025-12-30", "%Y-%m-%d")
        metrics = self.calculator.calculate_period_metrics(days=1, end_date=end_date)

        self.assertEqual(metrics.total_executions, 3)
        self.assertEqual(Decimal(metrics.total_pnl_net), Decimal("95.0"))  # 48 - 23 + 70
        self.assertEqual(metrics.win_rate, 2 / 3)  # 2 profitable out of 3
        self.assertEqual(metrics.profitable_count, 2)
        self.assertEqual(metrics.timeout_rate, 0.0)
        self.assertEqual(metrics.total_open_fills, 9)  # 3 + 2 + 4
        self.assertEqual(metrics.total_close_fills, 9)
        self.assertEqual(metrics.avg_open_fills_per_execution, 3.0)
        self.assertEqual(metrics.graceful_unwind_count, 1)
        self.assertEqual(metrics.aggressive_unwind_count, 0)

    def test_timeout_rate_calculation(self):
        """Timeout rate when some executions timeout"""
        # Create 4 audits: 1 timeout, 3 normal
        base_time = datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S")

        for i in range(4):
            start_ts = (base_time + timedelta(minutes=i * 20)).timestamp()
            audit = create_test_audit(
                symbol="TEST-USD",
                start_ts=start_ts,
                duration_sec=900,
                close_reason="TIMEOUT" if i == 0 else "TAKE_PROFIT",
                realized_pnl_quote="10.0" if i > 0 else "0",
                fees_quote="1.0",
                net_pnl_quote="9.0" if i > 0 else "-1.0",
                num_open_fills=2 if i > 0 else 0,
                num_close_fills=2 if i > 0 else 0,
                time_to_first_fill_sec=None if i == 0 else 30.0,
                timeout_triggered=True if i == 0 else False,
                timeout_type="NO_FILL" if i == 0 else None,
                unwind_phase_reached=None
            )
            self.writer.write(audit)

        end_date = datetime.strptime("2025-12-30", "%Y-%m-%d")
        metrics = self.calculator.calculate_period_metrics(days=1, end_date=end_date)

        self.assertEqual(metrics.total_executions, 4)
        self.assertEqual(metrics.timeout_count, 1)
        self.assertEqual(metrics.timeout_rate, 0.25)  # 1 out of 4
        self.assertEqual(metrics.avg_duration_before_timeout_sec, 900.0)

    def test_time_to_first_fill_percentiles(self):
        """Median and P95 time to first fill"""
        # Create 10 audits with different fill times
        fill_times = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        base_time = datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S")

        for i, fill_time in enumerate(fill_times):
            start_ts = (base_time + timedelta(minutes=i * 15)).timestamp()
            audit = create_test_audit(
                symbol="TEST-USD",
                start_ts=start_ts,
                duration_sec=600,
                close_reason="TAKE_PROFIT",
                realized_pnl_quote="10.0",
                fees_quote="1.0",
                net_pnl_quote="9.0",
                num_open_fills=2,
                num_close_fills=2,
                time_to_first_fill_sec=float(fill_time),
                timeout_triggered=False,
                unwind_phase_reached=None
            )
            self.writer.write(audit)

        end_date = datetime.strptime("2025-12-30", "%Y-%m-%d")
        metrics = self.calculator.calculate_period_metrics(days=1, end_date=end_date)

        self.assertEqual(metrics.avg_time_to_first_fill_sec, 55.0)  # mean
        self.assertEqual(metrics.median_time_to_first_fill_sec, 55.0)  # median (10 values)
        self.assertEqual(metrics.p95_time_to_first_fill_sec, 100.0)  # 95th percentile

    def test_pnl_per_hour_calculation(self):
        """PNL per hour calculation"""
        # Create audit: $100 profit in 2 hours
        start_time = datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S")
        audit = create_test_audit(
            symbol="TEST-USD",
            start_ts=start_time.timestamp(),
            duration_sec=7200,  # 2 hours
            close_reason="TAKE_PROFIT",
            realized_pnl_quote="105.0",
            fees_quote="5.0",
            net_pnl_quote="100.0",
            num_open_fills=3,
            num_close_fills=3,
            time_to_first_fill_sec=45.0,
            timeout_triggered=False,
            unwind_phase_reached=None
        )
        self.writer.write(audit)

        end_date = datetime.strptime("2025-12-30", "%Y-%m-%d")
        metrics = self.calculator.calculate_period_metrics(days=1, end_date=end_date)

        # $100 / 2 hours = $50/hour
        self.assertEqual(Decimal(metrics.pnl_per_hour), Decimal("50"))
        self.assertEqual(metrics.total_execution_hours, 2.0)

    def test_unwind_rate_calculation(self):
        """Graceful vs aggressive unwind rate"""
        # Create 5 audits: 3 graceful, 2 aggressive
        base_time = datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S")

        for i in range(5):
            graceful = i < 3
            start_ts = (base_time + timedelta(minutes=i * 15)).timestamp()
            audit = create_test_audit(
                symbol="TEST-USD",
                start_ts=start_ts,
                duration_sec=600,
                close_reason="STOP_LOSS",
                realized_pnl_quote="-5.0",
                fees_quote="1.0",
                net_pnl_quote="-6.0",
                num_open_fills=2,
                num_close_fills=2,
                time_to_first_fill_sec=30.0,
                timeout_triggered=False,
                unwind_phase_reached="GRACEFUL" if graceful else "AGGRESSIVE",
                graceful_close_success=graceful
            )
            self.writer.write(audit)

        end_date = datetime.strptime("2025-12-30", "%Y-%m-%d")
        metrics = self.calculator.calculate_period_metrics(days=1, end_date=end_date)

        self.assertEqual(metrics.graceful_unwind_count, 3)
        self.assertEqual(metrics.aggressive_unwind_count, 2)
        self.assertEqual(metrics.graceful_vs_aggressive_rate, 0.6)  # 3/5

    def test_by_symbol_metrics(self):
        """Per-symbol breakdown"""
        # Create audits for 2 different symbols
        symbols = ["PEPE-USD", "PEPE-USD", "BTC-USD"]
        pnls = ["10.0", "20.0", "-5.0"]
        base_time = datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S")

        for i, (symbol, pnl) in enumerate(zip(symbols, pnls)):
            start_ts = (base_time + timedelta(minutes=i * 15)).timestamp()
            audit = create_test_audit(
                symbol=symbol,
                start_ts=start_ts,
                duration_sec=600,
                close_reason="TAKE_PROFIT",
                realized_pnl_quote=str(Decimal(pnl) + Decimal("1")),
                fees_quote="1.0",
                net_pnl_quote=pnl,
                num_open_fills=3,
                num_close_fills=3,
                time_to_first_fill_sec=30.0,
                timeout_triggered=False,
                unwind_phase_reached=None
            )
            self.writer.write(audit)

        end_date = datetime.strptime("2025-12-30", "%Y-%m-%d")
        metrics = self.calculator.calculate_period_metrics(
            days=1, end_date=end_date, by_symbol=True
        )

        self.assertIsNotNone(metrics.by_symbol)
        self.assertIn("PEPE-USD", metrics.by_symbol)
        self.assertIn("BTC-USD", metrics.by_symbol)

        pepe_metrics = metrics.by_symbol["PEPE-USD"]
        self.assertEqual(pepe_metrics["total_executions"], 2)
        self.assertEqual(Decimal(pepe_metrics["total_pnl_net"]), Decimal("30"))
        self.assertEqual(pepe_metrics["win_rate"], 1.0)  # both profitable

        btc_metrics = metrics.by_symbol["BTC-USD"]
        self.assertEqual(btc_metrics["total_executions"], 1)
        self.assertEqual(Decimal(btc_metrics["total_pnl_net"]), Decimal("-5"))
        self.assertEqual(btc_metrics["win_rate"], 0.0)  # loss


class TestMetricsExport(unittest.TestCase):
    """Test metrics export to JSON/CSV"""

    def setUp(self):
        """Create temp dirs"""
        self.audit_dir = Path(tempfile.mkdtemp())
        self.output_dir = Path(tempfile.mkdtemp())
        self.calculator = MetricsCalculator(audit_dir=self.audit_dir)
        self.writer = AuditWriter(audit_dir=self.audit_dir)

    def tearDown(self):
        """Clean up"""
        shutil.rmtree(self.audit_dir, ignore_errors=True)
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_export_to_json(self):
        """Export metrics to JSON file"""
        # Create test audit
        start_time = datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S")
        audit = create_test_audit(
            symbol="TEST-USD",
            start_ts=start_time.timestamp(),
            duration_sec=900,
            close_reason="TAKE_PROFIT",
            realized_pnl_quote="100.0",
            fees_quote="5.0",
            net_pnl_quote="95.0",
            num_open_fills=3,
            num_close_fills=3,
            time_to_first_fill_sec=45.0,
            timeout_triggered=False,
            unwind_phase_reached=None
        )
        self.writer.write(audit)

        # Calculate and export
        end_date = datetime.strptime("2025-12-30", "%Y-%m-%d")
        metrics = self.calculator.calculate_period_metrics(days=1, end_date=end_date)

        output_path = self.output_dir / "metrics.json"
        self.calculator.export_to_json(metrics, output_path)

        # Verify file exists and valid JSON
        self.assertTrue(output_path.exists())

        with output_path.open('r') as f:
            data = json.load(f)

        self.assertEqual(data["total_executions"], 1)
        self.assertEqual(data["total_pnl_net"], "95.0")
        self.assertEqual(data["win_rate"], 1.0)

    def test_export_to_csv(self):
        """Export metrics to CSV file"""
        # Create test audit
        start_time = datetime.strptime("2025-12-30 10:00:00", "%Y-%m-%d %H:%M:%S")
        audit = create_test_audit(
            symbol="TEST-USD",
            start_ts=start_time.timestamp(),
            duration_sec=900,
            close_reason="TAKE_PROFIT",
            realized_pnl_quote="50.0",
            fees_quote="2.0",
            net_pnl_quote="48.0",
            num_open_fills=2,
            num_close_fills=2,
            time_to_first_fill_sec=30.0,
            timeout_triggered=False,
            unwind_phase_reached=None
        )
        self.writer.write(audit)

        # Calculate and export
        end_date = datetime.strptime("2025-12-30", "%Y-%m-%d")
        metrics = self.calculator.calculate_period_metrics(days=1, end_date=end_date)

        output_path = self.output_dir / "metrics.csv"
        self.calculator.export_to_csv(metrics, output_path)

        # Verify file exists
        self.assertTrue(output_path.exists())

        # Read and verify CSV content
        with output_path.open('r') as f:
            lines = f.readlines()

        self.assertGreater(len(lines), 1)  # header + data row
        self.assertIn("total_executions", lines[0])  # header contains field
        self.assertIn("1", lines[1])  # data row has execution count


if __name__ == '__main__':
    unittest.main()
