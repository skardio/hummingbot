"""
Compatibility wrapper exposing the shared global risk manager models
inside the core Hummingbot package.

The actual implementation lives in ``multi_coin_grid_pro.core`` so we
re-export the public classes here to keep legacy imports (e.g.
``hummingbot.core.global_risk_manager``) working during the migration.
"""

from multi_coin_grid_pro.core.global_risk_manager import AllocationRecord, GlobalRiskManager, RiskLimits  # noqa: F401

__all__ = [
    "AllocationRecord",
    "GlobalRiskManager",
    "RiskLimits",
]
