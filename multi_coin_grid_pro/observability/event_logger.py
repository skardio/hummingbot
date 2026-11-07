"""
Structured event logger for observability (JSONL format).

Writes events to JSONL file (one event per line) for offline analysis.
Feature-flagged via config: observability.structured_events_enabled

Design principles:
- Synchronous buffered writes (simple, reliable)
- One event per line (JSONL format)
- Feature-flagged (safe default: off)
- Correlation ID tracking for intent lineage
"""

import hashlib
import json
import logging
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage
except ImportError:
    # Fallback for tests/standalone usage
    ReasonCode = None
    Stage = None

# Per-run disk bound: at most 5 x 20 MB. A single run previously reached 106 MB unbounded.
DEFAULT_MAX_FILE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_FILES_PER_RUN = 5


class EventLogger:
    """
    Lightweight JSONL event logger with buffered writes.

    Usage:
        logger = EventLogger(enabled=True, output_dir="logs/events")
        logger.emit_gate_denied(
            correlation_id="abc123",
            symbol="BTC-EUR",
            stage=Stage.SMART_ENTRY,
            reason_code=ReasonCode.RSI_OVERBOUGHT,
            metadata={"rsi": 75.3}
        )
        logger.flush()  # Force write buffer to disk
    """

    def __init__(
        self,
        enabled: bool = False,
        output_dir: str = "logs/events",
        buffer_size: int = 100,
        config_hash: Optional[str] = None,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_files_per_run: int = DEFAULT_MAX_FILES_PER_RUN,
    ):
        """
        Initialize EventLogger.

        Args:
            enabled: Enable event logging (default: False for safety)
            output_dir: Directory for event files
            buffer_size: Number of events to buffer before auto-flush
            config_hash: Config hash for run tracking
            max_file_bytes: Rotate to a new part file once the current one would exceed this size
            max_files_per_run: Keep at most this many files of this run (oldest part of this run is
                deleted); files of other runs are never touched
        """
        self.enabled = enabled
        self.output_dir = Path(output_dir)
        self.buffer_size = buffer_size
        self.config_hash = config_hash
        self.max_file_bytes = max(1, int(max_file_bytes))
        self.max_files_per_run = max(1, int(max_files_per_run))

        self.buffer = []
        self.file_handle = None
        self.logger = logging.getLogger(__name__)
        self._run_files: List[Path] = []
        self._part = 0
        self._bytes_written = 0

        if self.enabled:
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                self._run_stem = f"events_{timestamp}"
                self.file_path = self.output_dir / f"{self._run_stem}.jsonl"
                self.file_handle = open(self.file_path, "a", buffering=1)  # Line buffered
                self._run_files.append(self.file_path)
                self._bytes_written = self.file_path.stat().st_size
                self.logger.info(f"📝 EventLogger initialized: {self.file_path}")

                # Emit config_loaded event
                if config_hash:
                    self.emit_config_loaded(config_hash)
            except Exception as e:
                # If we can't initialize, disable gracefully
                self.logger.error(f"EventLogger initialization failed - disabling: {e}")
                self.enabled = False
                self.file_handle = None

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Internal: emit event to buffer.

        Args:
            event_type: Event type identifier
            data: Event data dict
        """
        if not self.enabled:
            return

        try:
            event = {
                "ts": time.time(),
                "event_type": event_type,
                "config_hash": self.config_hash,
                **data
            }

            # Convert Decimal/Enum to JSON-safe types
            event = self._serialize(event)

            self.buffer.append(event)

            if len(self.buffer) >= self.buffer_size:
                self.flush()
        except Exception as e:
            # CRITICAL: Never let event logging break trading
            self.logger.error(f"EventLogger._emit failed (non-fatal): {e}")
            # Continue silently - observability is nice-to-have, not critical

    def _serialize(self, obj: Any) -> Any:
        """
        Recursively convert Decimal/Enum types to JSON-safe types.

        Args:
            obj: Object to serialize

        Returns:
            JSON-safe representation
        """
        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, dict):
            return {k: self._serialize(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._serialize(v) for v in obj]
        elif Stage and isinstance(obj, Stage):
            return obj.value
        elif ReasonCode and isinstance(obj, ReasonCode):
            return obj.value
        else:
            return obj

    def flush(self) -> None:
        """Write buffer to disk and clear."""
        if not self.enabled or not self.buffer:
            return

        # Check if file_handle is valid before writing
        if not self.file_handle:
            self.logger.debug("EventLogger file handle not available, clearing buffer")
            self.buffer.clear()
            return

        try:
            for event in self.buffer:
                json_line = json.dumps(event) + "\n"
                size = len(json_line.encode("utf-8"))
                if self._bytes_written > 0 and self._bytes_written + size > self.max_file_bytes:
                    self._rotate()
                self.file_handle.write(json_line)
                self._bytes_written += size
            self.file_handle.flush()
            self.buffer.clear()
        except Exception as e:
            # Non-fatal: log but don't raise
            self.logger.error(f"Failed to flush events (non-fatal): {e}")
            # Clear buffer anyway to prevent memory buildup
            self.buffer.clear()

    def _rotate(self) -> None:
        """Continue in the next part file of this run; drop this run's oldest part beyond the cap."""
        self.file_handle.flush()
        self.file_handle.close()
        self.file_handle = None  # if the next open fails, flush() degrades to dropping events quietly
        self._part += 1
        # "_pNNN" sorts after the base file, so readers using sorted(glob("events_*.jsonl")) keep order
        self.file_path = self.output_dir / f"{self._run_stem}_p{self._part:03d}.jsonl"
        self.file_handle = open(self.file_path, "a", buffering=1)
        self._run_files.append(self.file_path)
        self._bytes_written = 0
        dropped = []
        while len(self._run_files) > self.max_files_per_run:
            oldest = self._run_files.pop(0)
            try:
                oldest.unlink()
                dropped.append(oldest.name)
            except OSError as e:
                self.logger.warning(f"EventLogger could not remove {oldest.name} (non-fatal): {e}")
        self.logger.info(
            "EventLogger rotated to %s (max %s bytes/file, %s files/run); dropped=%s",
            self.file_path.name, self.max_file_bytes, self.max_files_per_run, dropped,
        )

    def close(self) -> None:
        """Close the event logger and flush any remaining events."""
        try:
            self.flush()
            if self.file_handle:
                self.file_handle.close()
                self.file_handle = None
        except Exception as e:
            # Best effort close - log but don't raise
            self.logger.error(f"EventLogger.close failed (non-fatal): {e}")

    # ===== Event Emission Methods =====

    def emit_config_loaded(self, config_hash: str, config_keys: Optional[Dict] = None) -> None:
        """
        Emit config_loaded event at startup.

        Args:
            config_hash: Hash of config for run tracking
            config_keys: Optional dict of key config values
        """
        self.config_hash = config_hash  # Persist so all subsequent events carry the hash
        self._emit("config_loaded", {
            "config_hash": config_hash,
            "config_keys": config_keys or {}
        })

    def emit_intent_created(
        self,
        correlation_id: str,
        symbol: str,
        side: str,
        size: float,
        urgency: str = "NORMAL"
    ) -> None:
        """
        Emit intent_created event.

        Args:
            correlation_id: Intent correlation ID
            symbol: Trading pair
            side: BUY or SELL
            size: Intent size (quote currency)
            urgency: Urgency level
        """
        self._emit("intent_created", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "side": side,
            "size": size,
            "urgency": urgency
        })

    def emit_gate_denied(
        self,
        correlation_id: str,
        symbol: str,
        stage: 'Stage',
        reason_code: 'ReasonCode',
        reason_msg: str,
        metadata: Optional[Dict] = None,
        connector: Optional[str] = None
    ) -> None:
        """
        Emit gate_denied event (rejection).

        Args:
            correlation_id: Intent correlation ID
            symbol: Trading pair
            stage: Pipeline stage where rejection occurred
            reason_code: Structured reason code
            reason_msg: Human-readable reason
            metadata: Optional additional context
            connector: Exchange connector name (kraken, bitget, etc.)
        """
        self._emit("gate_denied", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "stage": stage,
            "reason_code": reason_code,
            "reason_msg": reason_msg,
            "metadata": metadata or {},
            "connector": connector
        })

    def emit_gate_passed(
        self,
        correlation_id: str,
        symbol: str,
        stage: 'Stage',
        metadata: Optional[Dict] = None,
        connector: Optional[str] = None
    ) -> None:
        """
        Emit gate_passed event (approval at stage).

        Args:
            correlation_id: Intent correlation ID
            symbol: Trading pair
            stage: Pipeline stage that passed
            metadata: Optional additional context
            connector: Exchange connector name (kraken, bitget, etc.)
        """
        self._emit("gate_passed", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "stage": stage,
            "metadata": metadata or {},
            "connector": connector
        })

    def emit_order_submitted(
        self,
        correlation_id: str,
        symbol: str,
        order_id: str,
        side: str,
        price: float,
        amount: float
    ) -> None:
        """
        Emit order_submitted event.

        Args:
            correlation_id: Intent correlation ID
            symbol: Trading pair
            order_id: Exchange order ID
            side: BUY or SELL
            price: Order price
            amount: Order amount
        """
        self._emit("order_submitted", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "order_id": order_id,
            "side": side,
            "price": price,
            "amount": amount
        })

    def emit_schedule_pause(self, reason: str, connector: Optional[str] = None) -> None:
        """
        Emit schedule_pause event: new entries paused by the time-based filter.

        Not a trade intent - never counted as denied/approved. Emitted once per pause window.
        """
        self._emit("schedule_pause", {
            "reason": reason,
            "connector": connector
        })

    def emit_entry_guard_evaluation(
        self,
        connector: str,
        symbol: str,
        decision: str,
        regime: str = "NEUTRAL",
        reject_reason: Optional[str] = None,
        metrics: Optional[Dict[str, Optional[float]]] = None,
        thresholds: Optional[Dict[str, float]] = None,
        cooldown_remaining_sec: Optional[int] = None,
        mode: str = "live",
        correlation_id: Optional[str] = None
    ) -> None:
        """
        Emit entry_guard_evaluation event (EPIC v3.4 Story 6).

        Logs momentum health guard decisions for analysis and tuning.

        Args:
            connector: Exchange connector name ("kraken", "bitget")
            symbol: Trading pair (e.g., "PEPE-EUR", "BTC-USDT")
            decision: "ACCEPTED" or "REJECTED"
            regime: Market regime ("BULL", "CHOP", "BEAR", "NEUTRAL")
            reject_reason: Rejection reason code (e.g., "VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH")
            metrics: Momentum metrics dict with keys:
                - vwap_deviation_pct
                - vwap_slope_5m_pct (optional, for Story 9)
                - vwap_slope_15m_pct
                - accel_5m_pct
                - accel_15m_pct
            thresholds: Thresholds used for evaluation:
                - deviation_high_pct
                - slope_min_pct_5m (optional, for Story 9)
                - slope_min_pct_15m
                - accel_5m_min_pct
                - accel_15m_min_pct
            cooldown_remaining_sec: Remaining cooldown time (if applicable)
            mode: "shadow" or "live"
            correlation_id: Optional correlation ID for intent tracking
        """
        self._emit("entry_guard_evaluation", {
            "connector": connector,
            "symbol": symbol,
            "regime": regime,
            "decision": decision,
            "reject_reason": reject_reason,
            "metrics": metrics or {},
            "thresholds": thresholds or {},
            "cooldown_remaining_sec": cooldown_remaining_sec,
            "mode": mode,
            "correlation_id": correlation_id
        })


def compute_config_hash(config_dict: Dict, logger: Optional[logging.Logger] = None) -> str:
    """
    Compute stable hash of config for run tracking.

    Only includes relevant keys (excludes secrets/timestamps).

    Args:
        config_dict: Config dictionary (typically config.__dict__)
        logger: Optional logger to log hash to

    Returns:
        12-character hex hash string
    """
    relevant_keys = [
        "max_simultaneous_coins", "total_amount_quote",
        "trend_min_change_pct", "min_grid_spread_pct",
        "smart_entry_filter", "use_multi_timeframe_buy",
        "risk_limits", "observability"
    ]

    relevant_config = {k: config_dict.get(k) for k in relevant_keys if k in config_dict}
    config_str = json.dumps(relevant_config, sort_keys=True, default=str)
    config_hash = hashlib.sha256(config_str.encode()).hexdigest()[:12]

    # Log to normal logger for visibility
    if logger:
        logger.info(f"📋 Config hash: {config_hash}")
        logger.debug(f"   Hashed keys: {list(relevant_config.keys())}")

    return config_hash
