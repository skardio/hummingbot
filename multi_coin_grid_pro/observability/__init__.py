"""Observability module for structured events and metrics."""

from .event_logger import EventLogger, compute_config_hash

__all__ = ["EventLogger", "compute_config_hash"]
