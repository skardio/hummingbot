"""
Pydantic schema for the Bitget SPOT grid controller.
Based on the base MultiCoinGridConfig with Bitget-specific spot settings.
"""

from decimal import Decimal

from pydantic import Field

from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig


class SpotGridBitgetConfig(MultiCoinGridConfig):
    """
    Bitget SPOT Grid Configuration

    Extends MultiCoinGridConfig with Bitget-specific fields.
    Uses Decimal format for percentages (0.35 = 35%).
    """

    # Core Bitget identifiers
    connector_name: str = Field(
        default="bitget",
        description="Connector name for Bitget SPOT"
    )

    quote_asset: str = Field(
        default="USDT",
        description="Quote currency (USDT)"
    )

    # Bitget-specific volume and fee settings
    min_24h_volume_usdt: Decimal = Field(
        default=Decimal("1000000"),
        description="Minimum 24h volume in USDT for pair selection"
    )

    bitget_maker_fee_pct: Decimal = Field(
        default=Decimal("0.001"),
        description="Bitget SPOT maker fee (0.1% = 0.001)"
    )

    bitget_taker_fee_pct: Decimal = Field(
        default=Decimal("0.001"),
        description="Bitget SPOT taker fee (0.1% = 0.001)"
    )

    # Bitget rate limiting
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

    @property
    def triple_barrier_config(self):
        """Override to use LIMIT instead of LIMIT_MAKER for Bitget

        Bitget does NOT support OrderType.LIMIT_MAKER even for SPOT.
        Must use OrderType.LIMIT for all order types.
        """
        from hummingbot.core.data_type.common import OrderType
        from hummingbot.strategy_v2.executors.position_executor.data_types import TrailingStop, TripleBarrierConfig

        trailing_stop = None
        if self.trailing_stop_activation_pct and self.trailing_stop_delta_pct:
            trailing_stop = TrailingStop(
                activation_price=self.trailing_stop_activation_pct,
                trailing_delta=self.trailing_stop_delta_pct,
            )

        return TripleBarrierConfig(
            stop_loss=self.stop_loss_pct,
            take_profit=self.take_profit_pct,
            time_limit=None,
            trailing_stop=trailing_stop,
            open_order_type=OrderType.LIMIT,  # Bitget: Use LIMIT, not LIMIT_MAKER
            take_profit_order_type=OrderType.LIMIT,  # Bitget: Use LIMIT, not LIMIT_MAKER
            stop_loss_order_type=OrderType.MARKET,
            time_limit_order_type=OrderType.MARKET
        )
