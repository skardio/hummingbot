"""
Auto-Quarantine - US-002

Per-pair health monitor that automatically quarantines pairs with
persistent market data issues.

Usage:
    monitor = PairHealthMonitor(
        quarantine_threshold=10,  # Max failures in window
        quarantine_window_sec=120,  # 2 minute window
        quarantine_duration_sec=900,  # 15 minute quarantine
        logger=logger
    )

    # Record data failures
    monitor.record_failure("BTC-USDT", "NO_PRICE_DATA")
    monitor.record_failure("BTC-USDT", "NO_ORDERBOOK_DATA")

    # Check if pair is quarantined
    if monitor.is_quarantined("BTC-USDT"):
        # Skip this pair
        pass

    # Get quarantined pairs for exclusion
    excluded = monitor.get_quarantined_pairs()
"""
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, Dict, Optional, Set


class FailureType(Enum):
    """Types of market data failures."""
    NO_PRICE_DATA = "NO_PRICE_DATA"
    NO_ORDERBOOK_DATA = "NO_ORDERBOOK_DATA"
    STALE_PRICE = "STALE_PRICE"
    STALE_ORDERBOOK = "STALE_ORDERBOOK"
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    DEPTH_INSUFFICIENT = "DEPTH_INSUFFICIENT"


@dataclass
class FailureRecord:
    """Record of a single failure."""
    timestamp: float
    failure_type: FailureType


@dataclass
class QuarantineInfo:
    """Information about a quarantined pair."""
    pair: str
    quarantined_at: float
    release_at: float
    reason: str
    failure_count: int


@dataclass
class PairHealth:
    """Health state for a single trading pair."""
    pair: str
    failures: Deque[FailureRecord] = field(default_factory=lambda: deque(maxlen=100))
    is_quarantined: bool = False
    quarantine_until: float = 0.0
    quarantine_count: int = 0  # How many times this pair was quarantined
    last_success: float = field(default_factory=time.time)

    def add_failure(self, failure_type: FailureType) -> None:
        """Add a failure record."""
        self.failures.append(FailureRecord(
            timestamp=time.time(),
            failure_type=failure_type
        ))

    def count_failures_in_window(self, window_sec: float) -> int:
        """Count failures in the last N seconds."""
        cutoff = time.time() - window_sec
        return sum(1 for f in self.failures if f.timestamp > cutoff)

    def count_failures_by_type(self, window_sec: float) -> Dict[FailureType, int]:
        """Count failures by type in the last N seconds."""
        cutoff = time.time() - window_sec
        counts: Dict[FailureType, int] = {}
        for f in self.failures:
            if f.timestamp > cutoff:
                counts[f.failure_type] = counts.get(f.failure_type, 0) + 1
        return counts

    def record_success(self) -> None:
        """Record a successful data fetch."""
        self.last_success = time.time()


class PairHealthMonitor:
    """
    Monitors health of trading pairs and auto-quarantines unhealthy ones.

    Features:
    - Rolling window failure counting
    - Automatic quarantine on threshold breach
    - Automatic release after cooldown
    - Event emission for observability
    """

    def __init__(
        self,
        quarantine_threshold: int = 10,
        quarantine_window_sec: float = 120.0,
        quarantine_duration_sec: float = 900.0,
        enabled: bool = True,
        logger: Optional[logging.Logger] = None,
        event_logger: Optional[object] = None
    ):
        """
        Initialize pair health monitor.

        Args:
            quarantine_threshold: Max failures in window before quarantine
            quarantine_window_sec: Rolling window for counting failures (seconds)
            quarantine_duration_sec: How long to quarantine pairs (seconds)
            enabled: Whether quarantine is enabled
            logger: Optional logger instance
            event_logger: Optional EventLogger for structured events
        """
        self.quarantine_threshold = quarantine_threshold
        self.quarantine_window_sec = quarantine_window_sec
        self.quarantine_duration_sec = quarantine_duration_sec
        self.enabled = enabled
        self.logger = logger or logging.getLogger(__name__)
        self.event_logger = event_logger

        # Per-pair health tracking
        self._pair_health: Dict[str, PairHealth] = {}

        # Statistics
        self._total_quarantines: int = 0
        self._total_releases: int = 0

        self.logger.info(
            f"🏥 US-002: PairHealthMonitor initialized: "
            f"threshold={quarantine_threshold} failures in {quarantine_window_sec}s "
            f"→ quarantine {quarantine_duration_sec}s, enabled={enabled}"
        )

    def _get_or_create_health(self, pair: str) -> PairHealth:
        """Get or create health state for a pair."""
        if pair not in self._pair_health:
            self._pair_health[pair] = PairHealth(pair=pair)
        return self._pair_health[pair]

    def record_failure(self, pair: str, failure_type: str) -> bool:
        """
        Record a failure for a trading pair.

        Args:
            pair: Trading pair (e.g., "BTC-USDT")
            failure_type: Type of failure (see FailureType enum)

        Returns:
            True if pair was quarantined as a result
        """
        if not self.enabled:
            return False

        # Convert string to enum
        try:
            ftype = FailureType(failure_type)
        except ValueError:
            self.logger.debug(f"Unknown failure type: {failure_type}")
            return False

        health = self._get_or_create_health(pair)

        # Skip if already quarantined
        if self.is_quarantined(pair):
            return False

        # Record the failure
        health.add_failure(ftype)

        # Check if we should quarantine
        failure_count = health.count_failures_in_window(self.quarantine_window_sec)
        if failure_count >= self.quarantine_threshold:
            self._quarantine_pair(pair, failure_count)
            return True

        return False

    def record_success(self, pair: str) -> None:
        """
        Record a successful data fetch for a pair.

        Args:
            pair: Trading pair
        """
        if not self.enabled:
            return

        health = self._get_or_create_health(pair)
        health.record_success()

    def is_quarantined(self, pair: str) -> bool:
        """
        Check if a pair is currently quarantined.

        Args:
            pair: Trading pair to check

        Returns:
            True if pair is quarantined
        """
        if not self.enabled:
            return False

        health = self._pair_health.get(pair)
        if not health:
            return False

        if health.is_quarantined:
            # Check if quarantine has expired
            if time.time() >= health.quarantine_until:
                self._release_pair(pair)
                return False
            return True

        return False

    def get_quarantined_pairs(self) -> Set[str]:
        """
        Get all currently quarantined pairs.

        Returns:
            Set of quarantined pair names
        """
        if not self.enabled:
            return set()

        quarantined = set()
        for pair, health in self._pair_health.items():
            if health.is_quarantined:
                if time.time() >= health.quarantine_until:
                    self._release_pair(pair)
                else:
                    quarantined.add(pair)

        return quarantined

    def get_quarantine_info(self, pair: str) -> Optional[QuarantineInfo]:
        """
        Get quarantine details for a pair.

        Args:
            pair: Trading pair

        Returns:
            QuarantineInfo if quarantined, None otherwise
        """
        if not self.is_quarantined(pair):
            return None

        health = self._pair_health[pair]
        return QuarantineInfo(
            pair=pair,
            quarantined_at=health.quarantine_until - self.quarantine_duration_sec,
            release_at=health.quarantine_until,
            reason=f"{health.count_failures_in_window(self.quarantine_window_sec)} failures in {self.quarantine_window_sec}s",
            failure_count=health.count_failures_in_window(self.quarantine_window_sec)
        )

    def _quarantine_pair(self, pair: str, failure_count: int) -> None:
        """
        Put a pair in quarantine.

        Args:
            pair: Trading pair to quarantine
            failure_count: Number of failures that triggered quarantine
        """
        health = self._get_or_create_health(pair)

        now = time.time()
        health.is_quarantined = True
        health.quarantine_until = now + self.quarantine_duration_sec
        health.quarantine_count += 1
        self._total_quarantines += 1

        # Get failure breakdown
        failure_breakdown = health.count_failures_by_type(self.quarantine_window_sec)
        breakdown_str = ", ".join(f"{k.value}={v}" for k, v in failure_breakdown.items())

        self.logger.warning(
            f"🚧 US-002 QUARANTINED: {pair} for {self.quarantine_duration_sec / 60:.1f}min "
            f"({failure_count} failures in {self.quarantine_window_sec}s: {breakdown_str})"
        )

        # Emit event if event logger available
        if self.event_logger and hasattr(self.event_logger, 'emit'):
            try:
                self.event_logger.emit(
                    event_type="pair_quarantined",
                    data={
                        "pair": pair,
                        "failure_count": failure_count,
                        "quarantine_duration_sec": self.quarantine_duration_sec,
                        "failure_breakdown": {k.value: v for k, v in failure_breakdown.items()},
                        "quarantine_count_total": health.quarantine_count,
                    }
                )
            except Exception as e:
                self.logger.debug(f"Failed to emit quarantine event: {e}")

    def _release_pair(self, pair: str) -> None:
        """
        Release a pair from quarantine.

        Args:
            pair: Trading pair to release
        """
        health = self._pair_health.get(pair)
        if not health or not health.is_quarantined:
            return

        health.is_quarantined = False
        health.quarantine_until = 0.0
        health.failures.clear()  # Reset failure history
        self._total_releases += 1

        self.logger.info(
            f"✅ US-002 RELEASED: {pair} from quarantine "
            f"(was quarantined {health.quarantine_count} times)"
        )

        # Emit event if event logger available
        if self.event_logger and hasattr(self.event_logger, 'emit'):
            try:
                self.event_logger.emit(
                    event_type="pair_quarantine_released",
                    data={
                        "pair": pair,
                        "quarantine_count_total": health.quarantine_count,
                    }
                )
            except Exception as e:
                self.logger.debug(f"Failed to emit release event: {e}")

    def get_statistics(self) -> Dict[str, any]:
        """
        Get health monitor statistics.

        Returns:
            Dict with stats
        """
        quarantined = self.get_quarantined_pairs()

        # Find pairs with most failures
        pair_failures = []
        for pair, health in self._pair_health.items():
            count = health.count_failures_in_window(self.quarantine_window_sec)
            if count > 0:
                pair_failures.append((pair, count))
        pair_failures.sort(key=lambda x: -x[1])

        return {
            "enabled": self.enabled,
            "quarantine_threshold": self.quarantine_threshold,
            "quarantine_window_sec": self.quarantine_window_sec,
            "quarantine_duration_sec": self.quarantine_duration_sec,
            "total_pairs_tracked": len(self._pair_health),
            "currently_quarantined": len(quarantined),
            "quarantined_pairs": list(quarantined),
            "total_quarantines": self._total_quarantines,
            "total_releases": self._total_releases,
            "top_failing_pairs": pair_failures[:5],
        }

    def reset(self) -> None:
        """Reset all health tracking."""
        self._pair_health.clear()
        self._total_quarantines = 0
        self._total_releases = 0
        self.logger.info("🏥 US-002: PairHealthMonitor reset")

    def force_release(self, pair: str) -> bool:
        """
        Force release a pair from quarantine.

        Args:
            pair: Trading pair to release

        Returns:
            True if pair was released, False if not quarantined
        """
        health = self._pair_health.get(pair)
        if not health or not health.is_quarantined:
            return False

        self._release_pair(pair)
        return True
