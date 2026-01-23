"""
US-007: Trace ID Generator for Order Lifecycle Tracking.

This module provides a simple trace_id generator and tracker to follow
each entry decision through the entire lifecycle:
  SmartEntry gate → Executor creation → Order attempts → Exchange response → Close

The trace_id is a short, human-readable ID that can be used to:
1. Correlate all log entries for a single trading decision
2. Debug issues by filtering logs/events by trace_id
3. Build audit trails for compliance

Usage:
    from multi_coin_grid_pro.utils.trace_generator import TraceGenerator

    trace_gen = TraceGenerator()
    trace_id = trace_gen.generate()  # Returns e.g., "T-241216-142532-ABC123"

    # Use trace_id throughout the decision lifecycle
    logger.info(f"[{trace_id}] SmartEntry approved for BTC-USDT")
    ...
    logger.info(f"[{trace_id}] Executor created: exec-456")
    ...
    logger.info(f"[{trace_id}] Order filled: qty=0.001 BTC @ 45000")
"""

import random
import string
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class TraceContext:
    """
    Context object that carries trace information through the pipeline.

    Attributes:
        trace_id: Unique identifier for this decision trace
        symbol: Trading pair (e.g., "BTC-USDT")
        stage: Current pipeline stage
        created_at: Timestamp when trace was created
        metadata: Additional context data
    """
    trace_id: str
    symbol: str
    stage: str = "INIT"
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert trace context to dictionary for logging/JSON."""
        return {
            "trace_id": self.trace_id,
            "symbol": self.symbol,
            "stage": self.stage,
            "created_at": self.created_at,
            "created_at_iso": datetime.fromtimestamp(self.created_at).isoformat(),
            **self.metadata
        }

    def with_stage(self, stage: str) -> "TraceContext":
        """Return new context with updated stage."""
        return TraceContext(
            trace_id=self.trace_id,
            symbol=self.symbol,
            stage=stage,
            created_at=self.created_at,
            metadata=self.metadata.copy()
        )

    def with_metadata(self, **kwargs) -> "TraceContext":
        """Return new context with additional metadata."""
        new_metadata = self.metadata.copy()
        new_metadata.update(kwargs)
        return TraceContext(
            trace_id=self.trace_id,
            symbol=self.symbol,
            stage=self.stage,
            created_at=self.created_at,
            metadata=new_metadata
        )


class TraceGenerator:
    """
    Generator for unique, human-readable trace IDs.

    Format: T-YYMMDD-HHMMSS-XXXXXX
    Where:
    - T: Prefix indicating "Trace"
    - YYMMDD: Date in compact format
    - HHMMSS: Time in compact format
    - XXXXXX: 6-char random alphanumeric suffix for uniqueness

    Example: T-241216-142532-ABC123
    """

    def __init__(self, prefix: str = "T"):
        """
        Initialize trace generator.

        Args:
            prefix: Prefix for trace IDs (default: "T" for Trace)
        """
        self.prefix = prefix
        self._counter = 0
        self._last_second = 0

    def generate(self, symbol: Optional[str] = None) -> str:
        """
        Generate a new unique trace ID.

        Args:
            symbol: Optional trading pair to include in trace

        Returns:
            Unique trace ID string
        """
        now = datetime.now()

        # Date part: YYMMDD
        date_part = now.strftime("%y%m%d")

        # Time part: HHMMSS
        time_part = now.strftime("%H%M%S")

        # Random suffix: 6 chars alphanumeric (uppercase)
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

        trace_id = f"{self.prefix}-{date_part}-{time_part}-{suffix}"

        return trace_id

    def generate_context(self, symbol: str, stage: str = "INIT", **metadata) -> TraceContext:
        """
        Generate a new TraceContext with trace ID.

        Args:
            symbol: Trading pair (e.g., "BTC-USDT")
            stage: Initial pipeline stage
            **metadata: Additional context data

        Returns:
            TraceContext with new trace ID
        """
        trace_id = self.generate(symbol)
        return TraceContext(
            trace_id=trace_id,
            symbol=symbol,
            stage=stage,
            metadata=metadata
        )


# Pipeline stages for trace tracking
class TraceStage:
    """Constants for trace pipeline stages."""

    # Entry decision stages
    SMART_ENTRY_CHECK = "SMART_ENTRY_CHECK"
    SMART_ENTRY_APPROVED = "SMART_ENTRY_APPROVED"
    SMART_ENTRY_DENIED = "SMART_ENTRY_DENIED"

    # Budget/validation stages
    BUDGET_CHECK = "BUDGET_CHECK"
    BUDGET_APPROVED = "BUDGET_APPROVED"
    BUDGET_DENIED = "BUDGET_DENIED"

    # Executor stages
    EXECUTOR_CREATE = "EXECUTOR_CREATE"
    EXECUTOR_STARTED = "EXECUTOR_STARTED"
    EXECUTOR_RUNNING = "EXECUTOR_RUNNING"
    EXECUTOR_CLOSING = "EXECUTOR_CLOSING"
    EXECUTOR_CLOSED = "EXECUTOR_CLOSED"

    # Order stages
    ORDER_PREPARE = "ORDER_PREPARE"
    ORDER_VALIDATE = "ORDER_VALIDATE"
    ORDER_SKIPPED = "ORDER_SKIPPED"
    ORDER_SUBMIT = "ORDER_SUBMIT"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"

    # Close stages
    POSITION_CLOSE = "POSITION_CLOSE"
    POSITION_CLOSED = "POSITION_CLOSED"


class TraceLogger:
    """
    Helper class for structured trace logging.

    Usage:
        trace_logger = TraceLogger(base_logger, trace_context)
        trace_logger.info("Order created", order_id="xyz", price=45000)
        # Output: [T-241216-142532-ABC123] BTC-USDT | ORDER_CREATED | Order created | order_id=xyz price=45000
    """

    def __init__(self, logger, context: TraceContext):
        """
        Initialize trace logger.

        Args:
            logger: Base logger to write to
            context: TraceContext for this trace
        """
        self._logger = logger
        self._context = context

    def _format_message(self, message: str, **kwargs) -> str:
        """Format message with trace context."""
        parts = [
            f"[{self._context.trace_id}]",
            self._context.symbol,
            "|",
            self._context.stage,
            "|",
            message
        ]

        if kwargs:
            kv_parts = [f"{k}={v}" for k, v in kwargs.items()]
            parts.append("|")
            parts.append(" ".join(kv_parts))

        return " ".join(parts)

    def debug(self, message: str, **kwargs):
        """Log debug message with trace context."""
        self._logger.debug(self._format_message(message, **kwargs))

    def info(self, message: str, **kwargs):
        """Log info message with trace context."""
        self._logger.info(self._format_message(message, **kwargs))

    def warning(self, message: str, **kwargs):
        """Log warning message with trace context."""
        self._logger.warning(self._format_message(message, **kwargs))

    def error(self, message: str, **kwargs):
        """Log error message with trace context."""
        self._logger.error(self._format_message(message, **kwargs))

    def with_stage(self, stage: str) -> "TraceLogger":
        """Return new logger with updated stage."""
        new_context = self._context.with_stage(stage)
        return TraceLogger(self._logger, new_context)


# Global trace generator instance (singleton pattern)
_global_trace_generator: Optional[TraceGenerator] = None


def get_trace_generator() -> TraceGenerator:
    """Get or create global trace generator."""
    global _global_trace_generator
    if _global_trace_generator is None:
        _global_trace_generator = TraceGenerator()
    return _global_trace_generator


def generate_trace_id(symbol: Optional[str] = None) -> str:
    """
    Convenience function to generate a trace ID.

    Args:
        symbol: Optional trading pair

    Returns:
        New trace ID string
    """
    return get_trace_generator().generate(symbol)
