"""
Parabolic Blacklist - Per-symbol cooldown tracking

Part of EPIC v3.4: Momentum Health Guards
Story 3: Parabolic Detector + Cooldown Blacklist

Maintains an in-memory dictionary of symbols with expiring cooldowns.
"""
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class ParabolicBlacklist:
    """
    Session-scoped blacklist for symbols in parabolic conditions.

    Automatically removes expired entries on check.
    """
    blacklist: Dict[str, float] = field(default_factory=dict)

    def add(self, symbol: str, cooldown_sec: int) -> None:
        """
        Add symbol to blacklist with cooldown.

        Args:
            symbol: Trading pair symbol (e.g., "PEPE-EUR")
            cooldown_sec: Cooldown duration in seconds
        """
        expiry = time.time() + cooldown_sec
        self.blacklist[symbol] = expiry

    def is_blocked(self, symbol: str) -> Tuple[bool, Optional[int]]:
        """
        Check if symbol is currently blocked.

        Returns:
            Tuple of (blocked: bool, remaining_seconds: Optional[int])
            - (False, None) if not blocked or expired
            - (True, remaining) if actively blocked
        """
        if symbol not in self.blacklist:
            return False, None

        expiry = self.blacklist[symbol]
        now = time.time()

        if now >= expiry:
            # Expired - remove and unblock
            del self.blacklist[symbol]
            return False, None

        # Still blocked
        remaining = int(expiry - now)
        return True, remaining

    def clear(self) -> None:
        """Clear all blacklist entries (for testing)."""
        self.blacklist.clear()

    def get_all_blocked(self) -> Dict[str, int]:
        """
        Get all currently blocked symbols with remaining seconds.

        Returns:
            Dict of {symbol: remaining_seconds}
        """
        now = time.time()
        blocked = {}

        # Clean up expired entries
        expired = [s for s, exp in self.blacklist.items() if now >= exp]
        for symbol in expired:
            del self.blacklist[symbol]

        # Return active entries
        for symbol, expiry in self.blacklist.items():
            remaining = int(expiry - now)
            blocked[symbol] = remaining

        return blocked
