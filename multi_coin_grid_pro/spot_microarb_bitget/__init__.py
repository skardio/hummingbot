"""
Micro-arb Bitget (SPOT) package.
Provides config loading and controller exports for the spot micro-arbitrage bot.
"""
from multi_coin_grid_pro.spot_microarb_bitget.config_manager import MicroArbBitgetConfigManager
from multi_coin_grid_pro.spot_microarb_bitget.config_schema import MicroArbBitgetConfig
from multi_coin_grid_pro.spot_microarb_bitget.controller import MicroArbBitgetController

__all__ = [
    "MicroArbBitgetConfig",
    "MicroArbBitgetConfigManager",
    "MicroArbBitgetController",
]
