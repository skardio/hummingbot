"""
Pydantic schema for the Bitget futures grid controller.
"""

from enum import Enum

from pydantic import Field

from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig


class FuturesPositionMode(str, Enum):
    ONEWAY = "ONEWAY"
    HEDGE = "HEDGE"


class FuturesGridBitgetConfig(MultiCoinGridConfig):
    """
    Extends the generic multi-coin config with Bitget futures-specific settings.
    """

    derivative_leverage: int = Field(
        default=1,
        ge=1,
        le=125,
        description="Perpetual leverage to apply on Bitget (1-125).",
    )
    position_mode: FuturesPositionMode = Field(
        default=FuturesPositionMode.ONEWAY,
        description="Bitget futures position mode.",
    )
