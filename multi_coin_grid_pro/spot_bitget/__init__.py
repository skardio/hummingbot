"""
Bitget SPOT module for multi-coin grid trading.
"""

from multi_coin_grid_pro.spot_bitget.config_manager import SpotGridBitgetConfigManager
from multi_coin_grid_pro.spot_bitget.config_schema import SpotGridBitgetConfig
from multi_coin_grid_pro.spot_bitget.controller import SpotGridBitgetController

__all__ = [
    "SpotGridBitgetConfig",
    "SpotGridBitgetConfigManager",
    "SpotGridBitgetController",
]
