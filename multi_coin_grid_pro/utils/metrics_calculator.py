"""
Story C2: Metrics Export + KPI Calculation
==========================================

Reads ExecutionAudit records and computes performance KPIs for analysis and optimization.

Key Metrics:
- time_to_first_fill: How fast does executor get first fill?
- timeout_rate: % of executions that timeout
- pnl_per_hour: Profitability normalized by time
- win_rate: % of profitable executions
- avg_fills_per_execution: Grid efficiency
- graceful_vs_aggressive_rate: % reaching aggressive unwind

Usage:
    calculator = MetricsCalculator()
    metrics = calculator.calculate_period_metrics(days=7)
    calculator.export_to_json(metrics, "metrics_7d.json")
"""

import csv
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

from multi_coin_grid_pro.models.execution_audit import AuditWriter, ExecutionAudit


@dataclass
class PeriodMetrics:
    """Aggregated metrics for a time period"""

    # Time range
    start_date: str  # YYYY-MM-DD
    end_date: str    # YYYY-MM-DD
    total_executions: int

    # Fill timing metrics
    avg_time_to_first_fill_sec: Optional[float]  # None if no fills
    median_time_to_first_fill_sec: Optional[float]
    p95_time_to_first_fill_sec: Optional[float]  # 95th percentile

    # Timeout metrics
    timeout_count: int
    timeout_rate: float  # 0.0 to 1.0
    avg_duration_before_timeout_sec: Optional[float]

    # PNL metrics
    total_pnl_net: str  # Decimal as string
    avg_pnl_per_execution: str
    pnl_per_hour: str  # Total PNL / total hours

    # Win rate
    profitable_count: int
    win_rate: float  # 0.0 to 1.0

    # Grid efficiency
    avg_open_fills_per_execution: float
    avg_close_fills_per_execution: float
    total_open_fills: int
    total_close_fills: int

    # Unwind metrics
    graceful_unwind_count: int
    aggressive_unwind_count: int
    graceful_vs_aggressive_rate: float  # graceful / (graceful + aggressive)

    # Duration metrics
    avg_execution_duration_sec: float
    median_execution_duration_sec: float
    total_execution_hours: float

    # Per-symbol breakdown (optional)
    by_symbol: Optional[Dict[str, Dict[str, Any]]] = None


class MetricsCalculator:
    """Calculate KPIs from ExecutionAudit records"""

    def __init__(self, audit_dir: Path = None):
        """
        Args:
            audit_dir: Directory containing audit JSONL files (default: audits/)
        """
        self.writer = AuditWriter(audit_dir=audit_dir)

    def calculate_period_metrics(
        self,
        days: int = 7,
        end_date: Optional[datetime] = None,
        by_symbol: bool = False
    ) -> PeriodMetrics:
        """
        Calculate metrics for the last N days.

        Args:
            days: Number of days to analyze
            end_date: End date (default: today)
            by_symbol: Include per-symbol breakdown

        Returns:
            PeriodMetrics with aggregated KPIs
        """
        if end_date is None:
            end_date = datetime.now()

        start_date = end_date - timedelta(days=days)

        # Read audits for period
        audits = self._read_period_audits(start_date, end_date)

        if not audits:
            return self._empty_metrics(start_date, end_date)

        # Calculate metrics
        metrics = PeriodMetrics(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            total_executions=len(audits),

            # Fill timing
            avg_time_to_first_fill_sec=self._calc_avg_time_to_first_fill(audits),
            median_time_to_first_fill_sec=self._calc_median_time_to_first_fill(audits),
            p95_time_to_first_fill_sec=self._calc_p95_time_to_first_fill(audits),

            # Timeout
            timeout_count=sum(1 for a in audits if a.timeout_triggered),
            timeout_rate=sum(1 for a in audits if a.timeout_triggered) / len(audits),
            avg_duration_before_timeout_sec=self._calc_avg_timeout_duration(audits),

            # PNL
            total_pnl_net=str(sum(Decimal(a.net_pnl_quote) for a in audits)),
            avg_pnl_per_execution=str(sum(Decimal(a.net_pnl_quote) for a in audits) / len(audits)),
            pnl_per_hour=self._calc_pnl_per_hour(audits),

            # Win rate
            profitable_count=sum(1 for a in audits if Decimal(a.net_pnl_quote) > 0),
            win_rate=sum(1 for a in audits if Decimal(a.net_pnl_quote) > 0) / len(audits),

            # Grid efficiency
            avg_open_fills_per_execution=sum(a.num_open_fills for a in audits) / len(audits),
            avg_close_fills_per_execution=sum(a.num_close_fills for a in audits) / len(audits),
            total_open_fills=sum(a.num_open_fills for a in audits),
            total_close_fills=sum(a.num_close_fills for a in audits),

            # Unwind
            graceful_unwind_count=sum(1 for a in audits if a.unwind_phase_reached == "GRACEFUL"),
            aggressive_unwind_count=sum(1 for a in audits if a.unwind_phase_reached == "AGGRESSIVE"),
            graceful_vs_aggressive_rate=self._calc_unwind_rate(audits),

            # Duration
            avg_execution_duration_sec=sum(a.duration_sec for a in audits) / len(audits),
            median_execution_duration_sec=self._calc_median_duration(audits),
            total_execution_hours=sum(a.duration_sec for a in audits) / 3600,

            by_symbol=self._calc_by_symbol_metrics(audits) if by_symbol else None
        )

        return metrics

    def _read_period_audits(self, start_date: datetime, end_date: datetime) -> List[ExecutionAudit]:
        """Read all audits within date range"""
        audits = []
        current = start_date

        while current <= end_date:
            date_str = current.strftime("%Y-%m-%d")
            day_audits = self.writer.read_day(date_str)
            audits.extend(day_audits)
            current += timedelta(days=1)

        return audits

    def _empty_metrics(self, start_date: datetime, end_date: datetime) -> PeriodMetrics:
        """Return empty metrics when no audits found"""
        return PeriodMetrics(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=end_date.strftime("%Y-%m-%d"),
            total_executions=0,
            avg_time_to_first_fill_sec=None,
            median_time_to_first_fill_sec=None,
            p95_time_to_first_fill_sec=None,
            timeout_count=0,
            timeout_rate=0.0,
            avg_duration_before_timeout_sec=None,
            total_pnl_net="0",
            avg_pnl_per_execution="0",
            pnl_per_hour="0",
            profitable_count=0,
            win_rate=0.0,
            avg_open_fills_per_execution=0.0,
            avg_close_fills_per_execution=0.0,
            total_open_fills=0,
            total_close_fills=0,
            graceful_unwind_count=0,
            aggressive_unwind_count=0,
            graceful_vs_aggressive_rate=0.0,
            avg_execution_duration_sec=0.0,
            median_execution_duration_sec=0.0,
            total_execution_hours=0.0,
            by_symbol=None
        )

    def _calc_avg_time_to_first_fill(self, audits: List[ExecutionAudit]) -> Optional[float]:
        """Average time from start to first fill"""
        times = [a.time_to_first_fill_sec for a in audits if a.time_to_first_fill_sec is not None]
        return sum(times) / len(times) if times else None

    def _calc_median_time_to_first_fill(self, audits: List[ExecutionAudit]) -> Optional[float]:
        """Median time to first fill"""
        times = sorted([a.time_to_first_fill_sec for a in audits if a.time_to_first_fill_sec is not None])
        if not times:
            return None
        mid = len(times) // 2
        return times[mid] if len(times) % 2 == 1 else (times[mid - 1] + times[mid]) / 2

    def _calc_p95_time_to_first_fill(self, audits: List[ExecutionAudit]) -> Optional[float]:
        """95th percentile time to first fill"""
        times = sorted([a.time_to_first_fill_sec for a in audits if a.time_to_first_fill_sec is not None])
        if not times:
            return None
        idx = int(len(times) * 0.95)
        return times[min(idx, len(times) - 1)]

    def _calc_avg_timeout_duration(self, audits: List[ExecutionAudit]) -> Optional[float]:
        """Average duration before timeout for executions that timed out"""
        timeout_audits = [a for a in audits if a.timeout_triggered]
        if not timeout_audits:
            return None
        return sum(a.duration_sec for a in timeout_audits) / len(timeout_audits)

    def _calc_pnl_per_hour(self, audits: List[ExecutionAudit]) -> str:
        """Total PNL divided by total execution hours"""
        total_pnl = sum(Decimal(a.net_pnl_quote) for a in audits)
        total_hours = sum(a.duration_sec for a in audits) / 3600

        if total_hours == 0:
            return "0"

        return str(total_pnl / Decimal(str(total_hours)))

    def _calc_unwind_rate(self, audits: List[ExecutionAudit]) -> float:
        """Graceful unwind rate (graceful / total_unwinds)"""
        graceful = sum(1 for a in audits if a.unwind_phase_reached == "GRACEFUL")
        aggressive = sum(1 for a in audits if a.unwind_phase_reached == "AGGRESSIVE")
        total_unwinds = graceful + aggressive

        return graceful / total_unwinds if total_unwinds > 0 else 0.0

    def _calc_median_duration(self, audits: List[ExecutionAudit]) -> float:
        """Median execution duration"""
        durations = sorted([a.duration_sec for a in audits])
        mid = len(durations) // 2
        return durations[mid] if len(durations) % 2 == 1 else (durations[mid - 1] + durations[mid]) / 2

    def _calc_by_symbol_metrics(self, audits: List[ExecutionAudit]) -> Dict[str, Dict[str, Any]]:
        """Calculate metrics grouped by symbol"""
        by_symbol = {}

        # Group by symbol
        symbol_audits = {}
        for audit in audits:
            if audit.symbol not in symbol_audits:
                symbol_audits[audit.symbol] = []
            symbol_audits[audit.symbol].append(audit)

        # Calculate per-symbol metrics
        for symbol, sym_audits in symbol_audits.items():
            by_symbol[symbol] = {
                "total_executions": len(sym_audits),
                "total_pnl_net": str(sum(Decimal(a.net_pnl_quote) for a in sym_audits)),
                "win_rate": sum(1 for a in sym_audits if Decimal(a.net_pnl_quote) > 0) / len(sym_audits),
                "timeout_rate": sum(1 for a in sym_audits if a.timeout_triggered) / len(sym_audits),
                "avg_open_fills": sum(a.num_open_fills for a in sym_audits) / len(sym_audits),
            }

        return by_symbol

    def export_to_json(self, metrics: PeriodMetrics, output_path: Path) -> None:
        """Export metrics to JSON file"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with output_path.open('w') as f:
            json.dump(asdict(metrics), f, indent=2)

    def export_to_csv(self, metrics: PeriodMetrics, output_path: Path) -> None:
        """Export metrics to CSV file (flattened)"""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Flatten to dict (exclude by_symbol for CSV)
        data = asdict(metrics)
        data.pop('by_symbol', None)

        with output_path.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=data.keys())
            writer.writeheader()
            writer.writerow(data)
