"""
Thin controller stub for Spot Micro-Arb Bitget.
Currently the trading logic lives in scripts/spot_micro_arb_bitget.py.
This stub is provided for parity with other modules and future reuse.
"""
from multi_coin_grid_pro.spot_microarb_bitget.config_schema import MicroArbBitgetConfig


class MicroArbBitgetController:
    def __init__(self, config: MicroArbBitgetConfig):
        self.config = config

    def __repr__(self) -> str:  # pragma: no cover
        return f"MicroArbBitgetController(symbols={self.config.symbols})"
