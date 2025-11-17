"""
Configuration for Multi-Coin Grid Trading Controller

This config defines all parameters for the multi-coin grid trading strategy.
"""

from decimal import Decimal
from typing import List, Optional

from pydantic import Field, field_validator

from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.controllers.controller_base import ControllerConfigBase
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig


class MultiCoinGridConfig(ControllerConfigBase):
    """
    Configuration for Multi-Coin Grid Trading Strategy

    This strategy monitors multiple coins and automatically switches to trade
    the coin with the best trend using grid trading.
    """
    # Blacklist for coins to exclude (from YAML)
    blacklist: Optional[List[str]] = Field(
        default_factory=list,
        client_data=ClientFieldData(
            prompt=lambda mi: "Blacklist (comma separated, e.g. BTC-EUR,ETH-EUR): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    controller_name: str = "multi_coin_grid"
    controller_type: str = "generic"

    # Exchange Configuration
    connector_name: str = Field(
        default="kraken",
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the exchange name (e.g., kraken, binance): ",
            prompt_on_new=True,
        )
    )

    quote_asset: str = Field(
        default="EUR",
        client_data=ClientFieldData(
            prompt=lambda mi: "Enter the quote asset (e.g., EUR, USDT): ",
            prompt_on_new=True,
        )
    )

    # Coin Selection Parameters
    max_coins_to_monitor: int = Field(
        default=20,
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum number of coins to monitor: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    min_24h_volume_eur: Decimal = Field(
        default=Decimal("50000"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum 24h volume in EUR: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    exclude_expensive_coins: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Exclude BTC/ETH (too expensive for small capital)? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Trend Detection Parameters
    trend_lookback_minutes: int = Field(
        default=30,
        client_data=ClientFieldData(
            prompt=lambda mi: "Trend lookback period in minutes: ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    trend_min_change_pct: Decimal = Field(
        default=Decimal("0.5"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum trend change percentage to trade: ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    price_update_interval: int = Field(
        default=30,
        client_data=ClientFieldData(
            prompt=lambda mi: "Price update interval in seconds: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Switch Management
    min_switch_interval_seconds: int = Field(
        default=3600,
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum time between coin switches (seconds): ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Grid Configuration
    grid_range_pct_down: Decimal = Field(
        default=Decimal("3.0"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Grid range below current price (%): ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    grid_range_pct_up: Decimal = Field(
        default=Decimal("8.0"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Grid range above current price (%): ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    num_grids: int = Field(
        default=3,
        client_data=ClientFieldData(
            prompt=lambda mi: "Number of grid levels: ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Capital Management
    total_amount_quote: Decimal = Field(
        default=Decimal("80"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Total amount in quote asset per grid: ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    min_order_amount_quote: Decimal = Field(
        default=Decimal("5"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum order amount in quote asset: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Risk Management
    stop_loss_pct: Decimal = Field(
        default=Decimal("0.08"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Stop loss percentage (e.g., 0.08 for -8%): ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    take_profit_pct: Decimal = Field(
        default=Decimal("0.02"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Take profit percentage per grid level (e.g., 0.02 for +2%): ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    max_open_orders: int = Field(
        default=5,
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum open orders: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    order_frequency: int = Field(
        default=3,
        client_data=ClientFieldData(
            prompt=lambda mi: "Order frequency in seconds (cooldown between orders): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    @property
    def triple_barrier_config(self) -> TripleBarrierConfig:
        """
        Create TripleBarrierConfig for GridExecutor

        This configures stop-loss, take-profit, and order types for the grid.
        """
        return TripleBarrierConfig(
            stop_loss=self.stop_loss_pct,
            take_profit=self.take_profit_pct,
            time_limit=None,  # No time limit for now
            trailing_stop=None,  # No trailing stop for now (can add later)
            open_order_type=OrderType.LIMIT_MAKER,  # Maker orders for lower fees
            take_profit_order_type=OrderType.LIMIT_MAKER,
            stop_loss_order_type=OrderType.MARKET,  # Market order for fast exit
            time_limit_order_type=OrderType.MARKET
        )

    @field_validator('trend_lookback_minutes')
    @classmethod
    def validate_trend_lookback(cls, v: int) -> int:
        """Validate trend lookback is reasonable"""
        if v < 5:
            raise ValueError("Trend lookback must be at least 5 minutes")
        if v > 120:
            raise ValueError("Trend lookback should not exceed 120 minutes")
        return v

    @field_validator('num_grids')
    @classmethod
    def validate_num_grids(cls, v: int) -> int:
        """Validate number of grids is reasonable"""
        if v < 2:
            raise ValueError("Number of grids must be at least 2")
        if v > 10:
            raise ValueError("Number of grids should not exceed 10")
        return v

    @field_validator('stop_loss_pct')
    @classmethod
    def validate_stop_loss(cls, v: Decimal) -> Decimal:
        """Validate stop loss percentage"""
        if v <= 0:
            raise ValueError("Stop loss must be positive")
        if v > Decimal("0.5"):
            raise ValueError("Stop loss should not exceed 50%")
        return v
