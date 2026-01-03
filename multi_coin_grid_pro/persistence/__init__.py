"""
Persistence layer for multi-coin grid strategy.

Provides SQLite-based persistence for cooldowns, blacklists, and other state
that needs to survive bot restarts.

Part of EPIC v3.4 - Story 10: Cooldown Persistence
"""

from .cooldown_store import CooldownStore

__all__ = ["CooldownStore"]
