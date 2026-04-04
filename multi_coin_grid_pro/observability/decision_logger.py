"""
AI-F1: Decision Snapshot Logger

Logs structured feature snapshots for every entry AND rotation decision.
Captures market state, strategy state, bot state, and risk context at decision time.
Each snapshot gets a unique decision_id for linking to outcomes (AI-F2).

Design principles:
- Logging failure NEVER blocks trading (all writes wrapped in try/except)
- < 5ms latency per decision (synchronous buffered JSONL writes)
- Works in live/paper/replay modes
- Daily file rotation with configurable retention
- Schema versioned for future ML pipeline compatibility

File structure:
    data/decision_logs/
        decisions_2026-03-17.jsonl
        decisions_2026-03-16.jsonl
"""

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "1.0.0"


@dataclass
class DecisionSnapshot:
    """
    Complete feature snapshot at decision time.

    Every field is JSON-serializable after _serialize().
    """

    # Identity
    decision_id: str                    # UUID, unique per decision
    timestamp: float                    # Unix timestamp (UTC)
    schema_version: str = SCHEMA_VERSION

    # Decision metadata
    decision_type: str = ""             # "entry" | "rotation"
    symbol: str = ""                    # Target trading pair
    exchange: str = ""                  # Exchange name

    # Outcome
    outcome: str = ""                   # "accepted" | "rejected"
    rejected_by: Optional[str] = None   # Filter/check that rejected
    reason_code: Optional[str] = None   # Machine-readable reason
    reason_msg: Optional[str] = None    # Human-readable reason

    # Market features
    market: Dict[str, Any] = field(default_factory=dict)

    # Strategy state
    strategy: Dict[str, Any] = field(default_factory=dict)

    # Bot state
    bot_state: Dict[str, Any] = field(default_factory=dict)

    # Risk context
    risk: Dict[str, Any] = field(default_factory=dict)

    # Rotation-specific (only for decision_type="rotation")
    rotation: Optional[Dict[str, Any]] = None

    # Filter check details (pass/fail per filter)
    filter_checks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DecisionLogger:
    """
    Buffered JSONL writer for decision snapshots.

    Usage:
        logger = DecisionLogger(enabled=True, output_dir="data/decision_logs")
        snapshot = logger.create_snapshot("entry", "BTC-EUR", "kraken")
        snapshot.market = {...}
        logger.log(snapshot)
    """

    def __init__(
        self,
        enabled: bool = False,
        output_dir: str = "data/decision_logs",
        buffer_size: int = 50,
        retention_days: int = 90,
    ):
        self.enabled = enabled
        self.output_dir = Path(output_dir)
        self.buffer_size = buffer_size
        self.retention_days = retention_days

        self._buffer: List[Dict[str, Any]] = []
        self._current_date: Optional[str] = None
        self._file_handle = None
        self._logger = logging.getLogger(__name__)
        self._total_logged: int = 0
        self._total_errors: int = 0

        if self.enabled:
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                self._logger.info(
                    f"📝 DecisionLogger initialized: {self.output_dir} "
                    f"(buffer={buffer_size}, retention={retention_days}d)"
                )
            except Exception as e:
                self._logger.error(f"DecisionLogger init failed — disabling: {e}")
                self.enabled = False

    # ── public API ──────────────────────────────────────────────────

    def create_snapshot(
        self,
        decision_type: str,
        symbol: str,
        exchange: str,
    ) -> DecisionSnapshot:
        """Create a new snapshot with a unique decision_id."""
        return DecisionSnapshot(
            decision_id=str(uuid.uuid4()),
            timestamp=time.time(),
            decision_type=decision_type,
            symbol=symbol,
            exchange=exchange,
        )

    def log(self, snapshot: DecisionSnapshot) -> None:
        """
        Buffer a snapshot for writing. Never raises.
        """
        if not self.enabled:
            return
        try:
            record = self._serialize(snapshot.to_dict())
            self._buffer.append(record)
            if len(self._buffer) >= self.buffer_size:
                self.flush()
        except Exception as e:
            self._total_errors += 1
            self._logger.error(f"DecisionLogger.log failed (non-fatal): {e}")

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
            self._logger.error(f"DecisionLogger.flush failed (non-fatal): {e}")
            self._buffer.clear()

    def close(self) -> None:
        """Flush remaining buffer and close file handle."""
        try:
            self.flush()
            if self._file_handle:
                self._file_handle.close()
                self._file_handle = None
        except Exception as e:
            self._logger.error(f"DecisionLogger.close failed (non-fatal): {e}")

    def rotate(self) -> None:
        """Delete JSONL files older than retention_days."""
        if not self.enabled:
            return
        try:
            cutoff = time.time() - self.retention_days * 86400
            for f in self.output_dir.glob("decisions_*.jsonl"):
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    self._logger.info(f"🗑️  Rotated old decision log: {f.name}")
        except Exception as e:
            self._logger.error(f"DecisionLogger.rotate failed (non-fatal): {e}")

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "total_logged": self._total_logged,
            "total_errors": self._total_errors,
            "buffer_size": len(self._buffer),
        }

    # ── private helpers ─────────────────────────────────────────────

    def _get_file_handle(self, date_str: str):
        """Return (possibly cached) file handle for the given date."""
        if self._current_date == date_str and self._file_handle:
            return self._file_handle
        # Date changed — close old handle, open new one
        if self._file_handle:
            try:
                self._file_handle.close()
            except Exception:
                pass
        path = self.output_dir / f"decisions_{date_str}.jsonl"
        try:
            self._file_handle = open(path, "a", buffering=1)
            self._current_date = date_str
            return self._file_handle
        except Exception as e:
            self._logger.error(f"Cannot open {path}: {e}")
            self._file_handle = None
            return None

    @staticmethod
    def _serialize(obj: Any) -> Any:
        """Recursively convert Decimal/Enum to JSON-safe types."""
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: DecisionLogger._serialize(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [DecisionLogger._serialize(v) for v in obj]
        elif hasattr(obj, "value"):  # Enum
            return obj.value
        else:
            return obj
