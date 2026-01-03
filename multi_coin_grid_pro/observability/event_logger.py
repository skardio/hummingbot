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
from typing import Any, Dict, Optional

try:
    from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage
except ImportError:
    # Fallback for tests/standalone usage
    ReasonCode = None
    Stage = None


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
    ):
        """
        Initialize EventLogger.

        Args:
            enabled: Enable event logging (default: False for safety)
            output_dir: Directory for event files
            buffer_size: Number of events to buffer before auto-flush
            config_hash: Config hash for run tracking
        """
        self.enabled = enabled
        self.output_dir = Path(output_dir)
        self.buffer_size = buffer_size
        self.config_hash = config_hash

        self.buffer = []
        self.file_handle = None
        self.logger = logging.getLogger(__name__)

        if self.enabled:
            try:
                self.output_dir.mkdir(parents=True, exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                filename = f"events_{timestamp}.jsonl"
                self.file_path = self.output_dir / filename
                self.file_handle = open(self.file_path, "a", buffering=1)  # Line buffered
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
                json_line = json.dumps(event)
                self.file_handle.write(json_line + "\n")
            self.file_handle.flush()
            self.buffer.clear()
        except Exception as e:
            # Non-fatal: log but don't raise
            self.logger.error(f"Failed to flush events (non-fatal): {e}")
            # Clear buffer anyway to prevent memory buildup
            self.buffer.clear()

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
        metadata: Optional[Dict] = None
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
        """
        self._emit("gate_denied", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "stage": stage,
            "reason_code": reason_code,
            "reason_msg": reason_msg,
            "metadata": metadata or {}
        })

    def emit_gate_passed(
        self,
        correlation_id: str,
        symbol: str,
        stage: 'Stage',
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Emit gate_passed event (approval at stage).

        Args:
            correlation_id: Intent correlation ID
            symbol: Trading pair
            stage: Pipeline stage that passed
            metadata: Optional additional context
        """
        self._emit("gate_passed", {
            "correlation_id": correlation_id,
            "symbol": symbol,
            "stage": stage,
            "metadata": metadata or {}
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
