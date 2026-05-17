"""
Pydantic schema for the Bybit SPOT grid controller.
Based on the base MultiCoinGridConfig with Bybit-specific spot settings.
"""

from decimal import Decimal

from pydantic import Field

from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig


class SpotGridBybitConfig(MultiCoinGridConfig):
    """
    Bybit SPOT Grid Configuration

    Extends MultiCoinGridConfig with Bybit-specific fields.
    Bybit.eu fees (standard tier): 0.10% maker / 0.10% taker.
    Bybit supports LIMIT_MAKER orders (unlike Bitget).
    """

    # Core Bybit identifiers
    connector_name: str = Field(
        default="bybit",
        description="Connector name for Bybit SPOT"
    )

    quote_asset: str = Field(
        default="USDT",
        description="Quote currency (USDT)"
    )

    # Bybit-specific volume and fee settings
    min_24h_volume_usdt: Decimal = Field(
        default=Decimal("1000000"),
        description="Minimum 24h volume in USDT for pair selection"
    )

    bybit_maker_fee_pct: Decimal = Field(
        default=Decimal("0.001"),
        description="Bybit SPOT maker fee standard tier (0.10% = 0.001)"
    )

    bybit_taker_fee_pct: Decimal = Field(
        default=Decimal("0.001"),
        description="Bybit SPOT taker fee standard tier (0.10% = 0.001)"
    )

    # Bybit rate limiting
    rate_limit_buffer: Decimal = Field(
        default=Decimal("0.8"),
        description="Use 80% of rate limits for safety"
    )

    order_refresh_time: int = Field(
        default=30,
        ge=10,
        le=300,
        description="Seconds between order refreshes"
    )
