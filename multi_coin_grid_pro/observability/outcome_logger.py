"""
AI-F2: Outcome Logger

Links each decision_id (from AI-F1) to executor outcome:
fill_happened, pnl, fees, hold_time, close_type, etc.

Design principles (same as AI-F1):
- Logging failure NEVER blocks trading (all writes wrapped in try/except)
- < 5ms latency per record (synchronous buffered JSONL writes)
- Works in live/paper/replay modes
- Daily file rotation with configurable retention
- Schema versioned for future ML pipeline compatibility

File structure:
    data/outcome_logs/
        outcomes_2026-04-03.jsonl

Linking strategy:
    When an entry decision is accepted AND an executor is created,
    the decision_id is stored in _pending_decisions[executor_id].
    When the executor terminates, the outcome is recorded with
    that decision_id, closing the feedback loop.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

OUTCOME_SCHEMA_VERSION = "1.0.0"


@dataclass
class OutcomeRecord:
    """
    Execution outcome linked to a decision snapshot.

    Every field is JSON-serializable after _serialize().
    """

    # Link to decision
    decision_id: str                        # UUID from DecisionSnapshot
    outcome_id: str = ""                    # Auto-generated for this record

    # Identity
    timestamp: float = 0.0                  # When outcome was recorded
    schema_version: str = OUTCOME_SCHEMA_VERSION

    # Executor identity
    executor_id: str = ""
    symbol: str = ""
    exchange: str = ""

    # Outcome
    filled: bool = False                    # At least one fill happened
    close_type: str = ""                    # TP, SL, NO_FILL_TIMEOUT, etc.
    close_reason: str = ""                  # Human-readable

    # Financial
    net_pnl_quote: float = 0.0             # P&L in quote currency
    net_pnl_pct: float = 0.0              # P&L as percentage
    cum_fees_quote: float = 0.0            # Total fees paid
    filled_amount_quote: float = 0.0       # Total volume

    # Timing
    entry_timestamp: float = 0.0           # When executor was created
    close_timestamp: float = 0.0           # When executor terminated
    hold_time_sec: float = 0.0             # Duration

    # Grid specifics
    grid_levels_filled: int = 0            # How many levels got fills
    realized_buy_size_quote: float = 0.0
    realized_sell_size_quote: float = 0.0

    # Missing outcome flag
    missing_outcome: bool = False           # True if decision accepted but no executor matched

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OutcomeLogger:
    """
    Buffered JSONL writer for execution outcomes.

    Links decision_ids from AI-F1 to executor results.

    Usage:
        logger = OutcomeLogger(enabled=True, output_dir="data/outcome_logs")
        # When decision accepted + executor created:
        logger.register_pending(decision_id, executor_id, symbol, exchange)
        # When executor terminates:
        logger.record_outcome(executor_id, executor_info, now)
    """

    def __init__(
        self,
        enabled: bool = False,
        output_dir: str = "data/outcome_logs",
        buffer_size: int = 20,
        retention_days: int = 90,
    ):
        self.enabled = enabled
        self.output_dir = Path(output_dir)
        self.buffer_size = buffer_size
        self.retention_days = retention_days

        # Pending decisions: executor_id → {decision_id, symbol, exchange, entry_ts}
        self._pending: Dict[str, Dict[str, Any]] = {}

        self._buffer: List[Dict[str, Any]] = []
        self._current_date: Optional[str] = None
        self._file_handle = None
        self._logger = logging.getLogger(__name__)
        self._total_logged: int = 0
        self._total_errors: int = 0
        self._total_missing: int = 0

        if self.enabled:
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                self._logger.info(
                    f"📝 OutcomeLogger initialized: {self.output_dir} "
                    f"(buffer={buffer_size}, retention={retention_days}d)"
                )
            except Exception as e:
                self._logger.error(f"OutcomeLogger init failed — disabling: {e}")
                self.enabled = False

    # ── public API ──────────────────────────────────────────────────

    def register_pending(
        self,
        decision_id: str,
        executor_id: str,
        symbol: str,
        exchange: str,
    ) -> None:
        """
        Register a pending decision→executor link.
        Called when an accepted entry decision creates an executor.
        Never raises.
        """
        if not self.enabled:
            return
        try:
            self._pending[executor_id] = {
                "decision_id": decision_id,
                "symbol": symbol,
                "exchange": exchange,
                "entry_ts": time.time(),
            }
        except Exception as e:
            self._total_errors += 1
            self._logger.error(f"OutcomeLogger.register_pending failed (non-fatal): {e}")

    def record_outcome(
        self,
        executor_id: str,
        executor_info,
        now: float,
    ) -> None:
        """
        Record outcome for a terminated executor.
        Looks up decision_id from pending registrations.
        Never raises.

        Args:
            executor_id: The executor's unique ID
            executor_info: ExecutorInfo object with outcome data
            now: Current timestamp
        """
        if not self.enabled:
            return
        try:
            import uuid
            pending = self._pending.pop(executor_id, None)
            decision_id = pending["decision_id"] if pending else ""

            # Extract data safely from executor_info
            custom_info = getattr(executor_info, "custom_info", {}) or {}
            config = getattr(executor_info, "config", None)
            trading_pair = getattr(config, "trading_pair", "") if config else ""
            symbol = pending["symbol"] if pending else trading_pair
            exchange = pending["exchange"] if pending else ""

            entry_ts = pending["entry_ts"] if pending else getattr(executor_info, "timestamp", now)
            close_ts = getattr(executor_info, "close_timestamp", now) or now

            # Determine close_type string
            close_type_raw = getattr(executor_info, "close_type", None)
            close_type_str = str(close_type_raw) if close_type_raw else "unknown"

            # Derive close_reason
            close_reason = self._derive_close_reason(close_type_str)

            # Check if any fills happened
            filled_amount = float(getattr(executor_info, "filled_amount_quote", 0) or 0)
            filled = filled_amount > 1.0  # > $1 means real fill

            # Grid specifics from custom_info
            buy_size = float(custom_info.get("realized_buy_size_quote", 0) or 0)
            sell_size = float(custom_info.get("realized_sell_size_quote", 0) or 0)
            levels_by_state = custom_info.get("levels_by_state", {})
            filled_levels = levels_by_state.get("FILLED", 0) if isinstance(levels_by_state, dict) else 0

            record = OutcomeRecord(
                decision_id=decision_id,
                outcome_id=str(uuid.uuid4()),
                timestamp=now,
                executor_id=executor_id,
                symbol=symbol,
                exchange=exchange,
                filled=filled,
                close_type=close_type_str,
                close_reason=close_reason,
                net_pnl_quote=float(getattr(executor_info, "net_pnl_quote", 0) or 0),
                net_pnl_pct=float(getattr(executor_info, "net_pnl_pct", 0) or 0),
                cum_fees_quote=float(getattr(executor_info, "cum_fees_quote", 0) or 0),
                filled_amount_quote=filled_amount,
                entry_timestamp=entry_ts,
                close_timestamp=close_ts,
                hold_time_sec=close_ts - entry_ts,
                grid_levels_filled=filled_levels,
                realized_buy_size_quote=buy_size,
                realized_sell_size_quote=sell_size,
                missing_outcome=not pending,
            )

            if not pending:
                self._total_missing += 1

            self._write(record)

        except Exception as e:
            self._total_errors += 1
            self._logger.error(f"OutcomeLogger.record_outcome failed (non-fatal): {e}")

    def flush(self) -> None:
        """Write buffer to daily JSONL file and clear."""
        if not self.enabled or not self._buffer:
            return
        try:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            fh = self._get_file_handle(today)
            if not fh:
                self._buffer.clear()
                return
            for record in self._buffer:
                fh.write(json.dumps(record, separators=(",", ":")) + "\n")
            fh.flush()
            self._total_logged += len(self._buffer)
            self._buffer.clear()
        except Exception as e:
            self._total_errors += 1
            self._logger.error(f"OutcomeLogger.flush failed (non-fatal): {e}")
            self._buffer.clear()

    def close(self) -> None:
        """Flush remaining buffer and close file handle."""
        try:
            self.flush()
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None
        except Exception as e:
            self._logger.error(f"OutcomeLogger.close failed (non-fatal): {e}")

    def rotate(self) -> None:
        """Delete JSONL files older than retention_days."""
        if not self.enabled:
            return
        try:
            cutoff = time.time() - self.retention_days * 86400
            for f in self.output_dir.glob("outcomes_*.jsonl"):
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    self._logger.info(f"🗑️  Rotated old outcome log: {f.name}")
        except Exception as e:
            self._logger.error(f"OutcomeLogger.rotate failed (non-fatal): {e}")

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "total_logged": self._total_logged,
            "total_errors": self._total_errors,
            "total_missing": self._total_missing,
            "pending_count": len(self._pending),
            "buffer_size": len(self._buffer),
        }

    # ── private helpers ─────────────────────────────────────────────

    def _write(self, record: OutcomeRecord) -> None:
        """Buffer a record for writing."""
        serialized = self._serialize(record.to_dict())
        self._buffer.append(serialized)
        if len(self._buffer) >= self.buffer_size:
            self.flush()

    def _get_file_handle(self, date_str: str):
        """Return (possibly cached) file handle for the given date."""
        if self._current_date == date_str and self._file_handle:
            return self._file_handle
        if self._file_handle:
            try:
                self._file_handle.close()
            except Exception:
                pass
        path = self.output_dir / f"outcomes_{date_str}.jsonl"
        try:
            self._file_handle = open(path, "a", buffering=1)
            self._current_date = date_str
            return self._file_handle
        except Exception as e:
            self._logger.error(f"Cannot open {path}: {e}")
            self._file_handle = None
            return None

    @staticmethod
    def _derive_close_reason(close_type_str: str) -> str:
        """Map close_type string to human-readable reason."""
        ct = close_type_str.upper()
        if "STOP_LOSS" in ct:
            return "stop_loss"
        if "TAKE_PROFIT" in ct or "PROFIT" in ct:
            return "take_profit"
        if "NO_FILL_TIMEOUT" in ct:
            return "no_fill_timeout"
        if "NO_PROGRESS" in ct:
            return "no_progress_timeout"
        if "TIME_LIMIT" in ct or "HARD_CAP" in ct:
            return "time_limit"
        if "SWITCH" in ct:
            return "switch"
        if "FAILED" in ct:
            return "failed"
        if "INSUFFICIENT" in ct:
            return "insufficient_balance"
        if "POSITION_HOLD" in ct:
            return "position_hold"
        return "unknown"

    @staticmethod
    def _serialize(obj: Any) -> Any:
        """Recursively convert Decimal/Enum to JSON-safe types."""
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: OutcomeLogger._serialize(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [OutcomeLogger._serialize(v) for v in obj]
        elif hasattr(obj, "value") and not isinstance(obj, (bool, str)):
            return obj.value
        else:
            return obj
