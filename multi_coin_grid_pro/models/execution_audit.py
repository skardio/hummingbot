"""
Story B2: Execution Audit Records
==================================

Professional audit trail for every grid execution.
Enables post-analysis, KPI calculation, and strategy optimization.

Design:
- One record per grid completion (any reason)
- JSONL format (one JSON object per line)
- Versionable schema for future extensions
- Minimal overhead (async writes recommended for production)
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional


@dataclass
class ExecutionAudit:
    """
    Audit record for completed grid execution.

    Written on:
    - Take profit complete
    - Stop loss
    - Timeout (NO_FILL, NO_PROGRESS, TIME_LIMIT)
    - Manual close
    - Risk kill-switch
    """

    # Identity
    symbol: str                          # e.g. "BTC-EUR"
    executor_id: str                     # Unique executor ID

    # Lifecycle timestamps
    start_ts: float                      # Executor start timestamp
    end_ts: float                        # Executor end timestamp
    duration_sec: float                  # Total execution time

    # Close reason (from CloseType)
    close_reason: str                    # "TAKE_PROFIT" | "NO_FILL_TIMEOUT" | "STOP_LOSS" etc
    close_type_priority: int             # Priority level of close reason

    # Financial metrics
    realized_pnl_quote: str              # Realized PNL in quote currency (Decimal as string)
    fees_quote: str                      # Total fees paid (Decimal as string)
    net_pnl_quote: str                   # PNL after fees (Decimal as string)

    # Execution statistics
    num_fills: int                       # Total number of fills
    num_open_fills: int                  # Number of entry fills
    num_close_fills: int                 # Number of exit fills
    num_closed_levels: int               # Number of grid levels completed

    # Timing metrics (for KPI analysis)
    time_to_first_fill_sec: Optional[float]    # Seconds until first fill (None if no fills)
    time_to_last_fill_sec: Optional[float]     # Seconds until last fill
    time_in_graceful_unwind_sec: Optional[float]  # Time spent in graceful close phase
    time_in_aggressive_unwind_sec: Optional[float]  # Time spent in aggressive close phase

    # Timeout flags
    timeout_triggered: bool              # True if any timeout triggered
    timeout_type: Optional[str]          # "NO_FILL" | "NO_PROGRESS" | "TIME_LIMIT" if timeout

    # Unwind details (Story B1)
    unwind_phase_reached: Optional[str]  # "GRACEFUL" | "AGGRESSIVE" | None
    graceful_close_success: Optional[bool]  # True if closed in graceful phase

    # Risk metrics (best effort - can be None)
    max_adverse_excursion: Optional[str]  # MAE in quote (Decimal as string)
    max_favorable_excursion: Optional[str]  # MFE in quote (Decimal as string)
    max_position_size_quote: Optional[str]  # Peak exposure (Decimal as string)

    # Config snapshot (for reproducibility)
    config_snapshot: Dict                # Key grid parameters used

    # Metadata
    version: str = "1.0"                 # Audit schema version
    recorded_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_json(self) -> str:
        """Convert to JSON string (for JSONL output)"""
        return json.dumps(asdict(self), sort_keys=True)

    @classmethod
    def from_dict(cls, data: Dict) -> "ExecutionAudit":
        """Create from dict (for reading audit logs)"""
        return cls(**data)

    def to_dict(self) -> Dict:
        """Convert to dict"""
        return asdict(self)


class AuditWriter:
    """
    Writes ExecutionAudit records to JSONL files.

    File structure:
    audits/
      2025-12-30.jsonl  (one file per day)
      2025-12-31.jsonl

    Each line = one JSON object (ExecutionAudit)
    """

    def __init__(self, audit_dir: str = "audits"):
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)

    def write(self, audit: ExecutionAudit) -> None:
        """
        Write audit record to daily JSONL file.

        Thread-safe: appends to file atomically
        Uses start_ts from audit to determine date
        """
        # Use audit start_ts for date (not current time)
        audit_date = datetime.fromtimestamp(audit.start_ts)
        date_str = audit_date.strftime("%Y-%m-%d")
        file_path = self.audit_dir / f"{date_str}.jsonl"

        # Append to file (creates if not exists)
        with open(file_path, 'a') as f:
            f.write(audit.to_json() + '\n')

    def read_day(self, date_str: str) -> list[ExecutionAudit]:
        """
        Read all audit records for a specific day.

        Args:
            date_str: Date in format "YYYY-MM-DD"

        Returns:
            List of ExecutionAudit objects
        """
        file_path = self.audit_dir / f"{date_str}.jsonl"

        if not file_path.exists():
            return []

        audits = []
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    data = json.loads(line)
                    audits.append(ExecutionAudit.from_dict(data))

        return audits

    def read_latest(self, n: int = 10) -> list[ExecutionAudit]:
        """
        Read latest N audit records across all files.

        Args:
            n: Number of records to read

        Returns:
            List of ExecutionAudit objects (newest first)
        """
        # Get all JSONL files sorted by date (newest first)
        files = sorted(self.audit_dir.glob("*.jsonl"), reverse=True)

        audits = []
        for file_path in files:
            with open(file_path, 'r') as f:
                lines = f.readlines()
                # Read from end of file (newest records)
                for line in reversed(lines):
                    line = line.strip()
                    if line:
                        data = json.loads(line)
                        audits.append(ExecutionAudit.from_dict(data))
                        if len(audits) >= n:
                            return audits

        return audits


def create_audit_from_executor(executor, close_reason: str) -> ExecutionAudit:
    """
    Helper: Create ExecutionAudit from GridExecutor or ExecutorInfo.

    Called by controller when executor finishes.

    Args:
        executor: GridExecutor instance or ExecutorInfo object
        close_reason: CloseType string

    Returns:
        ExecutionAudit ready to write
    """
    try:
        from hummingbot.strategy_v2.models.executors import CLOSE_TYPE_PRIORITY
        from hummingbot.strategy_v2.models.executors_info import ExecutorInfo
    except ModuleNotFoundError:
        # Unit tests for this pure audit helper can run without the full
        # Hummingbot connector dependency stack installed.
        CLOSE_TYPE_PRIORITY = {}
        ExecutorInfo = None

    is_executor_info = ExecutorInfo is not None and isinstance(executor, ExecutorInfo)

    # Handle both GridExecutor and ExecutorInfo
    if is_executor_info:
        # Working with ExecutorInfo (from executors_info list)
        end_ts = executor.close_timestamp if executor.close_timestamp else executor.timestamp
        start_ts = executor.timestamp
    else:
        # Working with GridExecutor instance directly
        end_ts = executor.current_timestamp if hasattr(executor, 'current_timestamp') else executor._strategy.current_timestamp
        start_ts = executor._start_timestamp

    duration_sec = end_ts - start_ts if end_ts and start_ts else 0

    # Calculate timing metrics
    time_to_first_fill = None
    time_to_last_fill = None
    if hasattr(executor, '_last_fill_timestamp') and executor._last_fill_timestamp:
        time_to_first_fill = executor._last_fill_timestamp - start_ts
        time_to_last_fill = executor._last_fill_timestamp - start_ts

    # Unwind timing
    time_in_graceful = None
    time_in_aggressive = None
    if hasattr(executor, '_unwind_graceful_start_ts') and executor._unwind_graceful_start_ts:
        if hasattr(executor, '_unwind_aggressive_start_ts') and executor._unwind_aggressive_start_ts:
            time_in_graceful = executor._unwind_aggressive_start_ts - executor._unwind_graceful_start_ts
            time_in_aggressive = end_ts - executor._unwind_aggressive_start_ts
        else:
            time_in_graceful = end_ts - executor._unwind_graceful_start_ts

    # Timeout detection
    timeout_triggered = close_reason in ["NO_FILL_TIMEOUT", "NO_PROGRESS_TIMEOUT", "TIME_LIMIT"]
    timeout_type = close_reason if timeout_triggered else None

    # Unwind phase
    unwind_phase = None
    graceful_success = None
    if hasattr(executor, '_unwind_phase'):
        unwind_phase = executor._unwind_phase
        graceful_success = (unwind_phase == "GRACEFUL")

    # Financial metrics (safely convert Decimal to string)
    # GridExecutor.realized_pnl_quote/net_pnl_quote are already net of fees.
    # Do not subtract cum_fees_quote again here; that was double-counting buy
    # fees in audit output.
    if is_executor_info:
        custom_info = executor.custom_info or {}
        realized_pnl = str(custom_info.get("realized_pnl_quote", executor.net_pnl_quote))
        fees = str(custom_info.get("realized_fees_quote", executor.cum_fees_quote))
        net_pnl = str(executor.net_pnl_quote)
    else:
        realized_value = getattr(executor, 'realized_pnl_quote', None)
        if not isinstance(realized_value, (Decimal, int, float, str)):
            realized_value = None
        if realized_value is None and hasattr(executor, 'cum_realized_pnl_quote'):
            realized_value = executor.cum_realized_pnl_quote
        if realized_value is None:
            realized_value = getattr(executor, 'net_pnl_quote', Decimal("0"))
        realized_pnl = str(realized_value)
        fees_value = executor.cum_fees_quote if hasattr(executor, 'cum_fees_quote') else Decimal("0")
        if not isinstance(fees_value, (Decimal, int, float, str)):
            fees_value = Decimal("0")
        fees = str(fees_value)
        net_value = executor.net_pnl_quote if hasattr(executor, 'net_pnl_quote') else realized_value
        if not isinstance(net_value, (Decimal, int, float, str)):
            net_value = realized_value
        net_pnl = str(net_value)

    # Config snapshot (minimal - extend as needed)
    if is_executor_info:
        # ExecutorInfo: use config object
        config = executor.config
        config_snapshot = {
            "connector": config.connector_name,
            "trading_pair": config.trading_pair,
            "total_amount_quote": str(config.total_amount_quote) if hasattr(config, 'total_amount_quote') else "0",
            "start_price": str(config.start_price) if hasattr(config, 'start_price') else "0",
            "end_price": str(config.end_price) if hasattr(config, 'end_price') else "0",
            "no_fill_timeout_sec": config.custom_info.get("no_fill_timeout_sec", 1800) if hasattr(config, 'custom_info') else 1800,
            "no_progress_timeout_sec": config.custom_info.get("no_progress_timeout_sec", 3600) if hasattr(config, 'custom_info') else 3600,
            "close_grace_sec": config.custom_info.get("close_grace_sec", 120) if hasattr(config, 'custom_info') else 120,
        }
        executor_id = executor.id
        filled_orders = executor.custom_info.get('filled_orders', []) if hasattr(executor, 'custom_info') else []
    else:
        # GridExecutor instance
        config_snapshot = {
            "connector": executor.config.connector_name,
            "trading_pair": executor.config.trading_pair,
            "total_amount_quote": str(executor.config.total_amount_quote),
            "grid_range_down": str(executor.config.start_price * (Decimal('1') - executor.config.grid_range_pct_down)) if hasattr(executor.config, 'grid_range_pct_down') else "0",
            "grid_range_up": str(executor.config.start_price * (Decimal('1') + executor.config.grid_range_pct_up)) if hasattr(executor.config, 'grid_range_pct_up') else "0",
            "num_grids": executor.config.num_grids if hasattr(executor.config, 'num_grids') else 0,
            "no_fill_timeout_sec": executor.config.custom_info.get("no_fill_timeout_sec", 1800) if hasattr(executor.config, 'custom_info') else 1800,
            "no_progress_timeout_sec": executor.config.custom_info.get("no_progress_timeout_sec", 3600) if hasattr(executor.config, 'custom_info') else 3600,
            "close_grace_sec": executor.config.custom_info.get("close_grace_sec", 120) if hasattr(executor.config, 'custom_info') else 120,
        }
        executor_id = executor.executor_id if hasattr(executor, 'executor_id') else executor.config.id
        filled_orders = executor.filled_orders if hasattr(executor, 'filled_orders') else []

    return ExecutionAudit(
        symbol=executor.config.trading_pair,
        executor_id=executor_id,
        start_ts=start_ts,
        end_ts=end_ts if end_ts else start_ts,
        duration_sec=duration_sec,
        close_reason=close_reason,
        close_type_priority=CLOSE_TYPE_PRIORITY.get(close_reason, 0),
        realized_pnl_quote=realized_pnl,
        fees_quote=fees,
        net_pnl_quote=net_pnl,
        num_fills=len(filled_orders),
        num_open_fills=len(executor.custom_info.get('open_fills', [])) if is_executor_info and hasattr(executor, 'custom_info') else 0,
        num_close_fills=len(executor.custom_info.get('close_fills', [])) if is_executor_info and hasattr(executor, 'custom_info') else 0,
        num_closed_levels=len(executor.custom_info.get('closed_levels', [])) if is_executor_info and hasattr(executor, 'custom_info') else 0,
        time_to_first_fill_sec=time_to_first_fill,
        time_to_last_fill_sec=time_to_last_fill,
        time_in_graceful_unwind_sec=time_in_graceful,
        time_in_aggressive_unwind_sec=time_in_aggressive,
        timeout_triggered=timeout_triggered,
        timeout_type=timeout_type,
        unwind_phase_reached=unwind_phase,
        graceful_close_success=graceful_success,
        max_adverse_excursion=None,  # TODO: Calculate from executor state
        max_favorable_excursion=None,  # TODO: Calculate from executor state
        max_position_size_quote=None,  # TODO: Calculate from executor state
        config_snapshot=config_snapshot,
    )
