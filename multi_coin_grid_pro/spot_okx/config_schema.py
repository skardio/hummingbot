"""
Pydantic schema for the OKX SPOT grid controller.
Based on the base MultiCoinGridConfig with OKX-specific spot settings.
"""

from decimal import Decimal

from pydantic import Field

from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig


class SpotGridOKXConfig(MultiCoinGridConfig):
    """
    OKX SPOT Grid Configuration

    Extends MultiCoinGridConfig with OKX-specific fields.
    OKX EU uses USD pair names (BTC-USD, ETH-USD) with USDC balances.
    """

    # Core OKX identifiers
    connector_name: str = Field(
        default="okx",
        description="Connector name for OKX SPOT"
    )

    quote_asset: str = Field(
        default="USD",
        description="Quote currency used in OKX pair names"
    )

    # OKX-specific volume and fee settings
    min_24h_volume_usdt: Decimal = Field(
        default=Decimal("1000000"),
        description="Minimum 24h volume in USDT for pair selection"
    )

    okx_maker_fee_pct: Decimal = Field(
        default=Decimal("0.0008"),
        description="OKX SPOT maker fee VIP0 (0.08% = 0.0008)"
    )

    okx_taker_fee_pct: Decimal = Field(
        default=Decimal("0.001"),
        description="OKX SPOT taker fee VIP0 (0.10% = 0.001)"
    )

    # OKX rate limiting (generous limits — OKX allows 60 orders/sec)
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
