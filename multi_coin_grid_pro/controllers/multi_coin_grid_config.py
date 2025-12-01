"""
Configuration for Multi-Coin Grid Trading Controller

This config defines all parameters for the multi-coin grid trading strategy.
"""

from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import Field, field_validator

from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.core.data_type.common import OrderType
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

    # Logging Configuration (optional, used by strategy script)
    log_level: Optional[str] = Field(
        default="INFO",
        client_data=ClientFieldData(
            prompt=lambda mi: "Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Paper Trading Mode (optional, used by strategy script)
    paper_trading: bool = Field(
        default=False,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable paper trading mode? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

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
    manual_trading_pairs: Optional[List[str]] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Manual trading pairs (comma separated, e.g. XRP-EUR,ADA-EUR) or leave empty for auto-discovery: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    max_coins_to_monitor: int = Field(
        default=20,
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum number of coins to monitor (only used if manual_trading_pairs is empty): ",
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

    # Coin Rotation Parameters
    coin_rotation_threshold: int = Field(
        default=90,
        client_data=ClientFieldData(
            prompt=lambda mi: "Coin rotation threshold (number of updates without trades before replacement, default 90 = ~15 min): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Trend Detection Parameters
    trend_lookback_minutes: int = Field(
        default=1440,  # Default to 24 hours (1440 minutes) for real trend detection
        client_data=ClientFieldData(
            prompt=lambda mi: "Trend lookback period in minutes (1440 = 24h): ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Phase 2.5: Multi-Timeframe Trend Parameters
    trend_lookback_short_minutes: int = Field(
        default=60,  # 1 hour lookback
        client_data=ClientFieldData(
            prompt=lambda mi: "Short-term trend lookback (minutes, default 60 = 1h): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    trend_lookback_mid_minutes: int = Field(
        default=240,  # 4 hours lookback
        client_data=ClientFieldData(
            prompt=lambda mi: "Mid-term trend lookback (minutes, default 240 = 4h): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    trend_lookback_long_minutes: int = Field(
        default=1440,  # 24 hours lookback
        client_data=ClientFieldData(
            prompt=lambda mi: "Long-term trend lookback (minutes, default 1440 = 24h): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    switch_threshold_percent: float = Field(
        default=1.5,  # Minimum 1.5% trend_score difference to switch
        client_data=ClientFieldData(
            prompt=lambda mi: "Switch threshold percent (default 1.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    exit_short_threshold: float = Field(
        default=-0.5,  # Exit if 60m trend < -0.5% (aangescherpt voor snellere exit)
        client_data=ClientFieldData(
            prompt=lambda mi: "Exit short-term threshold (default -0.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    exit_mid_threshold: float = Field(
        default=0.5,  # Exit if 240m trend < +0.5%
        client_data=ClientFieldData(
            prompt=lambda mi: "Exit mid-term threshold (default 0.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # PRO EXIT SYSTEM - Layer 3: Price-Based Emergency Exits
    emergency_exit_pct: float = Field(
        default=-2.5,  # Exit immediately if price drops 2.5% below entry (prevents crash losses)
        client_data=ClientFieldData(
            prompt=lambda mi: "Emergency exit percentage (default -2.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    hard_stop_pct: float = Field(
        default=-4.0,  # Fail-safe exit if price drops 4.0% below entry (last resort protection)
        client_data=ClientFieldData(
            prompt=lambda mi: "Hard stop percentage (default -4.0%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # PRO EXIT SYSTEM - Layer 5: Grid Profit Exit
    min_grid_profit_pct: float = Field(
        default=0.6,  # Exit if grid realized profit >= 0.6% (guarantees profit)
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum grid profit percentage to exit (default 0.6%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Startup delay - wait before first trade
    min_startup_wait_seconds: int = Field(
        default=3600,  # Wait 1 hour (3600 seconds) before first trade
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum startup wait time in seconds before first trade (default 3600 = 1 hour): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    use_multi_timeframe: bool = Field(
        default=True,  # Enable multi-timeframe analysis
        client_data=ClientFieldData(
            prompt=lambda mi: "Use multi-timeframe trend analysis? (Phase 2.5): ",
            prompt_on_new=False,
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
        default=900,  # 15 minutes default (Phase 3.3)
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum time between coin switches (seconds): ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Phase 3: Switch Logic Improvements
    min_hold_time_seconds: int = Field(
        default=900,  # 15 minutes minimum hold time (anti-whipsaw)
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum hold time before switching (seconds, Phase 3.3): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    smart_switch_k: float = Field(
        default=1.75,  # Volatility multiplier for smart switch threshold (Phase 3.1)
        client_data=ClientFieldData(
            prompt=lambda mi: "Smart switch K multiplier (1.5-2.0, Phase 3.1): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    switch_cost_multiplier: float = Field(
        default=2.0,  # Only switch if expected_profit > switch_cost * multiplier (Phase 3.2)
        client_data=ClientFieldData(
            prompt=lambda mi: "Switch cost multiplier (Phase 3.2): ",
            prompt_on_new=False,
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
            prompt=lambda mi: "Number of grid levels (base, adjusted by volatility): ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Phase 4: Grid Strategy Optimization
    use_atr_grid_ranges: bool = Field(
        default=True,  # Use ATR-based dynamic grid ranges (Phase 4.1)
        client_data=ClientFieldData(
            prompt=lambda mi: "Use ATR-based grid ranges? (Phase 4.1): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    atr_multiplier_down: float = Field(
        default=1.0,  # Grid lower = price - (ATR * multiplier_down) (Phase 4.1)
        client_data=ClientFieldData(
            prompt=lambda mi: "ATR multiplier for lower grid (Phase 4.1): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    atr_multiplier_up: float = Field(
        default=1.5,  # Grid upper = price + (ATR * multiplier_up) (Phase 4.1)
        client_data=ClientFieldData(
            prompt=lambda mi: "ATR multiplier for upper grid (Phase 4.1): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    use_asymmetric_grids: bool = Field(
        default=True,  # Adjust grid distribution based on trend (Phase 4.3)
        client_data=ClientFieldData(
            prompt=lambda mi: "Use asymmetric grid adjustment? (Phase 4.3): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    smart_refill_threshold_pct: Decimal = Field(
        default=Decimal("3.0"),  # Rebuild grid if price moved >3% (Phase 4.4)
        client_data=ClientFieldData(
            prompt=lambda mi: "Smart refill threshold % (Phase 4.4): ",
            prompt_on_new=False,
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

    max_position_size_per_symbol: Dict[str, Decimal] = Field(
        default_factory=dict,
        client_data=ClientFieldData(
            prompt=lambda mi: "(Optional) Max position size per symbol in quote (e.g., {'BTC-USDT': 50}): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )

    min_liquidation_distance_pct_per_symbol: Dict[str, Decimal] = Field(
        default_factory=dict,
        client_data=ClientFieldData(
            prompt=lambda mi: "(Optional) Min liquidation distance %% per symbol (e.g., {'BTC-USDT': 2}): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
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

    # Phase 1.4: Position Size Limits
    max_exposure_per_coin_pct: Decimal = Field(
        default=Decimal("0.15"),  # Max 15% of capital per coin
        client_data=ClientFieldData(
            prompt=lambda mi: "Max exposure per coin (% of total capital, e.g., 0.15 for 15%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    max_total_exposure_pct: Decimal = Field(
        default=Decimal("0.90"),  # Max 90% of capital total
        client_data=ClientFieldData(
            prompt=lambda mi: "Max total exposure (% of capital, e.g., 0.90 for 90%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Phase 1.2: Circuit Breaker
    circuit_breaker_volatility_pct: float = Field(
        default=0.05,  # 5% volatility threshold
        client_data=ClientFieldData(
            prompt=lambda mi: "Circuit breaker volatility threshold (%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    circuit_breaker_time_window: int = Field(
        default=60,  # 1 minute window
        client_data=ClientFieldData(
            prompt=lambda mi: "Circuit breaker time window (seconds): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Phase 1.3: API Error Handling
    api_error_max_retries: int = Field(
        default=3,  # Max consecutive errors before pause
        client_data=ClientFieldData(
            prompt=lambda mi: "Max consecutive API errors before pause: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    api_error_backoff_time: int = Field(
        default=60,  # Wait 60 seconds before retry
        client_data=ClientFieldData(
            prompt=lambda mi: "API error backoff time (seconds): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    @property
    def triple_barrier_config(self) -> TripleBarrierConfig:
        """
        Create TripleBarrierConfig for GridExecutor

        This configures stop-loss, take-profit, and order types for the grid.

        For futures/perpetual exchanges, use LIMIT instead of LIMIT_MAKER
        because many futures exchanges don't support LIMIT_MAKER order type.
        """
        # Check if this is a futures/perpetual exchange
        is_futures = (
            "perpetual" in self.connector_name.lower() or
            hasattr(self, "derivative_leverage") and getattr(self, "derivative_leverage", 1) > 1
        )

        # Use LIMIT for futures, LIMIT_MAKER for spot (lower fees)
        order_type = OrderType.LIMIT if is_futures else OrderType.LIMIT_MAKER

        return TripleBarrierConfig(
            stop_loss=self.stop_loss_pct,
            take_profit=self.take_profit_pct,
            time_limit=None,  # No time limit for now
            trailing_stop=None,  # No trailing stop for now (can add later)
            open_order_type=order_type,
            take_profit_order_type=order_type,
            stop_loss_order_type=OrderType.MARKET,  # Market order for fast exit
            time_limit_order_type=OrderType.MARKET
        )

    @field_validator('max_position_size_per_symbol')
    @classmethod
    def validate_max_position_size(cls, values: Dict[str, Decimal]) -> Dict[str, Decimal]:
        for symbol, amount in values.items():
            if amount is not None and amount <= 0:
                raise ValueError(f"Max position size for {symbol} must be positive")
        return values

    @field_validator('min_liquidation_distance_pct_per_symbol')
    @classmethod
    def validate_min_liquidation_distance(cls, values: Dict[str, Decimal]) -> Dict[str, Decimal]:
        for symbol, distance in values.items():
            if distance is not None and distance < 0:
                raise ValueError(f"Min liquidation distance for {symbol} cannot be negative")
        return values

    @field_validator('trend_lookback_minutes')
    @classmethod
    def validate_trend_lookback(cls, v: int) -> int:
        """Validate trend lookback is reasonable"""
        if v < 5:
            raise ValueError("Trend lookback must be at least 5 minutes")
        if v > 1440:
            raise ValueError("Trend lookback should not exceed 1440 minutes (24 hours)")
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
