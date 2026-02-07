"""
Pydantic schema for the Bitget futures grid controller.
"""

from enum import Enum

from pydantic import Field

from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig


class FuturesPositionMode(str, Enum):
    ONEWAY = "ONEWAY"
    HEDGE = "HEDGE"


class FuturesTradeDirection(str, Enum):
    """Trading direction for futures grid."""
    LONG = "long"      # Buy low, sell high (profit when price goes UP)
    SHORT = "short"    # Sell high, buy low (profit when price goes DOWN)
    AUTO = "auto"      # Automatically choose based on trend


class FuturesGridBitgetConfig(MultiCoinGridConfig):
    """
    Extends the generic multi-coin config with Bitget futures-specific settings.
    """

    # === TRADE DIRECTION (NEW!) ===
    trade_direction: FuturesTradeDirection = Field(
        default=FuturesTradeDirection.AUTO,
        description="Trading direction: 'long' (profit when UP), 'short' (profit when DOWN), 'auto' (based on trend).",
    )
    auto_direction_threshold_pct: float = Field(
        default=1.0,
        ge=0.1,
        le=5.0,
        description="Trend threshold for AUTO mode: >+X% = LONG, <-X% = SHORT.",
    )

    # === SHORT ENTRY THRESHOLDS ===
    short_24h_min_pct: float = Field(
        default=-1.0,
        le=0,
        description="24h trend must be below this value for SHORT entry (e.g., -1.0 = need 24h < -1%).",
    )
    short_4h_min_pct: float = Field(
        default=-1.0,
        le=0,
        description="4h trend must be below this value for SHORT entry (e.g., -1.0 = need 4h < -1%).",
    )
    short_1h_max_pct: float = Field(
        default=1.0,
        description="1h trend can be up to this value for SHORT (allows small bounces, e.g., +1%).",
    )
    short_pump_1h_max: float = Field(
        default=2.0,
        ge=0.5,
        description="Reject SHORT if 1h trend exceeds this (pump protection, e.g., reject if 1h > +2%).",
    )
    short_pump_4h_max: float = Field(
        default=1.0,
        ge=0.5,
        description="AND 4h trend exceeds this (both required for pump rejection).",
    )

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
    liquidation_buffer_pct: float = Field(
        default=0.2,
        ge=0.05,
        le=0.5,
        description="Fractional buffer to stay away from exchange liquidation (e.g. 0.2 keeps 20% headroom).",
    )
    futures_emergency_exit_pct: float = Field(
        default=-1.5,
        lt=0,
        description="Emergency exit threshold (in %) applied to leveraged positions.",
    )
    futures_hard_stop_pct: float = Field(
        default=-2.5,
        lt=0,
        description="Hard stop threshold (in %) applied to leveraged positions.",
    )
    futures_min_entry_strength_24h: float = Field(
        default=1.5,
        description="Minimum 24h trend (in %) required to enter a futures position.",
    )
    futures_min_entry_strength_4h: float = Field(
        default=1.0,
        description="Minimum 4h trend (in %) required to enter a futures position.",
    )
    futures_min_entry_strength_1h: float = Field(
        default=0.0,
        description="Minimum 1h trend (in %) required to enter a futures position.",
    )

    # === LIQUIDATION BEVEILIGING ===
    liquidation_safety_distance_pct: float = Field(
        default=0.5,
        ge=0.1,
        le=0.9,
        description="Welk deel van de afstand tot liquidatie we veilig willen houden (0.5 = 50% margin).",
    )

    # === RISK GUARD PARAMETERS ===
    risk_guard_enabled: bool = Field(
        default=True,
        description="Schakel automatische risk guard in die grid stopt bij gevaar.",
    )
    risk_guard_max_loss_pct: float = Field(
        default=-8.0,
        lt=0,
        description="Hard stop: maximaal toegestaan verlies (%) voordat grid emergency stop doet.",
    )
    risk_guard_max_grid_time_seconds: int = Field(
        default=3600,
        ge=300,
        le=86400,
        description="Max tijd (seconden) dat een grid mag draaien voordat we stoppen (1h = 3600s).",
    )
    risk_guard_max_grid_depth_pct: float = Field(
        default=0.65,
        ge=0.3,
        le=0.95,
        description="Max % van grid levels die gevuld mogen zijn (0.65 = 65% van buy orders gevuld).",
    )
    risk_guard_sell_starvation_seconds: int = Field(
        default=900,
        ge=0,  # 0 = disabled (grid executor tracks sells internally)
        le=3600,
        description="Max tijd (seconden) zonder sell voordat we exit doen. 0 = disabled.",
    )
    risk_guard_trend_break_pct: float = Field(
        default=-1.5,
        lt=0,
        description="1h trend (%) onder deze waarde = trend breuk → exit grid.",
    )
    risk_guard_atr_explosion_multiplier: float = Field(
        default=2.2,
        ge=1.5,
        le=5.0,
        description="ATR moet binnen X keer de baseline blijven, anders = te volatiel → exit.",
    )

    # === WARMUP MODE THRESHOLDS ===
    warmup_min_4h_trend_pct: float = Field(
        default=1.0,
        description="Minimum 4h trend (%) tijdens warmup fase (24h data nog niet compleet).",
    )
    warmup_min_1h_trend_pct: float = Field(
        default=0.5,
        description="Minimum 1h trend (%) tijdens warmup fase.",
    )

    # === EXCHANGE-SIDE STOP LOSS (SAFETY NET) ===
    # These orders are placed on Bitget itself, so if the bot crashes,
    # the exchange will still close the position automatically.
    exchange_stop_loss_enabled: bool = Field(
        default=True,
        description="Place a stop-loss order on Bitget when grid starts (safety net if bot crashes).",
    )
    exchange_stop_loss_pct: float = Field(
        default=5.0,
        ge=1.0,
        le=20.0,
        description="Stop-loss trigger distance from entry (%). E.g., 5.0 = SL triggers at -5% for LONG.",
    )
    exchange_take_profit_enabled: bool = Field(
        default=False,
        description="Place a take-profit order on Bitget (optional, grid already handles TP).",
    )
    exchange_take_profit_pct: float = Field(
        default=10.0,
        ge=1.0,
        le=50.0,
        description="Take-profit trigger distance from entry (%). E.g., 10.0 = TP triggers at +10% for LONG.",
    )

    # === DYNAMIC FEATURE TOGGLES (for small accounts) ===
    use_dynamic_grid_sizer: bool = Field(
        default=True,
        description="Use ATR-based dynamic grid sizing. Disable for small accounts to keep fixed num_grids.",
    )
    use_volatility_position_sizing: bool = Field(
        default=True,
        description="Adjust position size based on volatility. Disable for small accounts to prevent order size < min.",
    )
