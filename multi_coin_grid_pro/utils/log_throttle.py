"""
Story C1: Log Sampling & Throttling
====================================

Prevents log spam by sampling repetitive messages.

Key Features:
- Throttle by key (e.g. "timeout_check_BTC-EUR")
- Time-based throttling (max 1 log per N seconds)
- Counter-based throttling (log every Nth occurrence)
- Summary logs (aggregate stats instead of spam)

Usage:
    throttle = LogThrottle()

    # Only log once per 30 seconds
    if throttle.should_log("grid_summary_BTC-EUR", interval_sec=30):
        logger.info(f"GRID_SUMMARY | pnl={pnl} fills={n}")

    # Only log every 10th occurrence
    if throttle.should_log_count("order_placed", max_count=10):
        logger.debug(f"ORDER_PLACED | ...")
"""

import time
from collections import defaultdict
from typing import Dict, Optional


class LogThrottle:
    """
    Throttles log messages to prevent spam.

    Thread-safe: uses simple timestamps (no locks needed for single-threaded use)
    """

    def __init__(self):
        # Time-based throttling: key -> last_log_timestamp
        self._last_log_times: Dict[str, float] = {}

        # Counter-based throttling: key -> count
        self._log_counts: Dict[str, int] = defaultdict(int)

        # Summary aggregation: key -> stats
        self._summary_stats: Dict[str, Dict] = defaultdict(dict)

    def should_log(self, key: str, interval_sec: float = 30.0) -> bool:
        """
        Check if message should be logged based on time throttling.

        Args:
            key: Unique key for this log type (e.g. "timeout_check_BTC-EUR")
            interval_sec: Minimum seconds between logs

        Returns:
            True if should log now, False if throttled
        """
        now = time.time()
        last_log = self._last_log_times.get(key, 0)

        if now - last_log >= interval_sec:
            self._last_log_times[key] = now
            return True

        return False

    def should_log_count(self, key: str, max_count: int = 10) -> bool:
        """
        Check if message should be logged based on occurrence count.

        Logs every Nth occurrence.

        Args:
            key: Unique key for this log type
            max_count: Log every Nth occurrence

        Returns:
            True if should log now, False otherwise
        """
        self._log_counts[key] += 1

        if self._log_counts[key] >= max_count:
            self._log_counts[key] = 0
            return True

        return False

    def reset(self, key: Optional[str] = None):
        """
        Reset throttling state.

        Args:
            key: Specific key to reset, or None to reset all
        """
        if key is None:
            self._last_log_times.clear()
            self._log_counts.clear()
            self._summary_stats.clear()
        else:
            self._last_log_times.pop(key, None)
            self._log_counts.pop(key, None)
            self._summary_stats.pop(key, None)

    def accumulate_stat(self, key: str, stat_name: str, value: float):
        """
        Accumulate a statistic for summary logging.

        Example:
            throttle.accumulate_stat("grid_BTC", "fills", 1)
            throttle.accumulate_stat("grid_BTC", "pnl", 2.5)

            # Later, in summary log:
            stats = throttle.get_summary("grid_BTC")
            logger.info(f"SUMMARY | fills={stats['fills']} pnl={stats['pnl']}")

        Args:
            key: Summary key
            stat_name: Name of statistic
            value: Value to add
        """
        if key not in self._summary_stats:
            self._summary_stats[key] = {}

        if stat_name not in self._summary_stats[key]:
            self._summary_stats[key][stat_name] = 0

        self._summary_stats[key][stat_name] += value

    def get_summary(self, key: str, reset: bool = True) -> Dict:
        """
        Get accumulated summary statistics.

        Args:
            key: Summary key
            reset: Whether to reset stats after getting them

        Returns:
            Dict of accumulated stats
        """
        stats = self._summary_stats.get(key, {}).copy()

        if reset:
            self._summary_stats[key] = {}

        return stats


# Global singleton for convenience
_global_throttle = LogThrottle()


def should_log(key: str, interval_sec: float = 30.0) -> bool:
    """Global convenience function"""
    return _global_throttle.should_log(key, interval_sec)


def should_log_count(key: str, max_count: int = 10) -> bool:
    """Global convenience function"""
    return _global_throttle.should_log_count(key, max_count)


def reset_throttle(key: Optional[str] = None):
    """Global convenience function"""
    _global_throttle.reset(key)


class StructuredLogger:
    """
    Helper for structured logging (key=value format).

    Usage:
        slog = StructuredLogger(logger)
        slog.info("GRID_SUMMARY", symbol="BTC-EUR", pnl=2.5, fills=3)

        Output:
        2025-12-30 10:00:00 INFO GRID_SUMMARY | symbol=BTC-EUR pnl=2.5 fills=3
    """

    def __init__(self, logger):
        self.logger = logger

    def _format(self, event: str, **kwargs) -> str:
        """Format structured log message"""
        parts = [event]

        # Sort keys for consistent output
        for key in sorted(kwargs.keys()):
            value = kwargs[key]
            # Format Decimal/float to reasonable precision
            if isinstance(value, float):
                # Truncate to 6 decimals to avoid floating point precision issues
                # Use string slicing to avoid additional rounding
                formatted = f"{value:.15f}"  # Get enough decimals
                # Find decimal point and truncate to 6 decimals
                if '.' in formatted:
                    int_part, dec_part = formatted.split('.')
                    dec_part = dec_part[:6].rstrip('0')  # Keep up to 6, strip trailing zeros
                    if dec_part:
                        value = f"{int_part}.{dec_part}"
                    else:
                        value = int_part
                else:
                    value = formatted
            parts.append(f"{key}={value}")

        return " | ".join(parts)

    def info(self, event: str, **kwargs):
        """Log structured INFO message"""
        self.logger.info(self._format(event, **kwargs))

    def warning(self, event: str, **kwargs):
        """Log structured WARNING message"""
        self.logger.warning(self._format(event, **kwargs))

    def error(self, event: str, **kwargs):
        """Log structured ERROR message"""
        self.logger.error(self._format(event, **kwargs))

    def debug(self, event: str, **kwargs):
        """Log structured DEBUG message"""
        self.logger.debug(self._format(event, **kwargs))


class LogBudget:
    """
    Monitors log volume and warns when budget exceeded.

    Usage:
        budget = LogBudget(max_lines_per_hour=1000)

        # In control loop:
        if budget.check_and_increment():
            logger.info("...")
        else:
            # Budget exceeded - skip log or use emergency channel
            pass
    """

    def __init__(self, max_lines_per_hour: int = 1000):
        self.max_lines_per_hour = max_lines_per_hour
        self.window_start = time.time()
        self.line_count = 0
        self.budget_exceeded_warned = False

    def check_and_increment(self) -> bool:
        """
        Check if within budget and increment counter.

        Returns:
            True if within budget, False if exceeded
        """
        now = time.time()

        # Reset window if hour passed
        if now - self.window_start >= 3600:
            self.window_start = now
            self.line_count = 0
            self.budget_exceeded_warned = False

        # Check budget
        if self.line_count >= self.max_lines_per_hour:
            if not self.budget_exceeded_warned:
                # Log warning once per window
                self.budget_exceeded_warned = True
            return False

        self.line_count += 1
        return True

    def get_usage(self) -> Dict:
        """
        Get current budget usage.

        Returns:
            Dict with usage stats
        """
        elapsed = time.time() - self.window_start
        rate = self.line_count / (elapsed / 3600) if elapsed > 0 else 0

        return {
            "lines_logged": self.line_count,
            "max_lines": self.max_lines_per_hour,
            "utilization_pct": (self.line_count / self.max_lines_per_hour) * 100,
            "current_rate_per_hour": rate,
        }
