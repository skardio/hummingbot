"""
Utility modules for Multi-Coin Grid Controllers

This package contains helper utilities for:
- Liquidity proxy (orderbook depth calculations)
"""

from hummingbot.multi_coin_grid_controllers.utils.liquidity_proxy import (
    calculate_orderbook_depth,
    calculate_required_depth,
    get_orderbook_snapshot,
    is_sufficient_depth,
)

__all__ = [
    'calculate_orderbook_depth',
    'calculate_required_depth',
    'is_sufficient_depth',
    'get_orderbook_snapshot',
]
