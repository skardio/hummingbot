"""
Configuration for Multi-Coin Grid Trading Controller

This config defines all parameters for the multi-coin grid trading strategy.
"""

from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import Field, field_validator

from hummingbot.client.config.config_data_types import ClientFieldData
from hummingbot.core.data_type.common import OrderType
from hummingbot.core.global_risk_manager import RiskLimits
from hummingbot.strategy_v2.controllers.controller_base import ControllerConfigBase
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig


class MultiCoinGridConfig(ControllerConfigBase):
    """
    Configuration for Multi-Coin Grid Trading Strategy

    This strategy monitors multiple coins and automatically switches to trade
    the coin with the best trend using grid trading.
    """
    # Allow using aliases like min_24h_volume_quote instead of min_24h_volume_eur
    model_config = {"populate_by_name": True, "extra": "forbid"}

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

    # Instance Identifier (for multi-instance isolation)
    # Used to separate DBs, logs, and state between EUR/USD bots
    instance_id: Optional[str] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Instance ID for state isolation (e.g., eur, usd): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": False}  # Can't change at runtime
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

    # OKX EU Unified USD Orderbook: pairs trade as BTC-USD but balance is held in USDC.
    # Set balance_currency: USDC when quote_asset is USD to read the correct wallet balance.
    balance_currency: Optional[str] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Override balance currency (leave empty to use quote_asset): ",
            prompt_on_new=False,
        )
    )

    # Whitelisted Trading Pairs (loaded at startup for order book subscriptions)
    # IMPORTANT: Kraken WebSocket limit is ~25-30 subscriptions
    whitelisted_pairs: Optional[List[str]] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Whitelisted trading pairs for order books (leave empty for defaults): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": False}  # Can't change at runtime (requires restart)
    )

    # Dynamic Pair Discovery (scan all pairs via REST API at startup)
    use_dynamic_pair_discovery: bool = Field(
        default=False,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable dynamic pair discovery at startup? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": False}  # Can't change at runtime (requires restart)
    )

    # Coin Selection Parameters
    manual_trading_pairs: Optional[List[str]] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: (
                "Manual trading pairs (comma separated, e.g. XRP-EUR,ADA-EUR) "
                "or leave empty for auto-discovery: "
            ),
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

    # Volume threshold - works for any quote currency (EUR, USD, USDT, etc.)
    min_24h_volume_eur: Decimal = Field(
        default=Decimal("50000"),
        alias="min_24h_volume_quote",  # Alias for currency-agnostic naming
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum 24h volume in quote currency: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    universe_adaptive_liquidity_enabled: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable adaptive universe liquidity fallback when too few pairs pass volume filter? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="If enabled, min 24h volume can be relaxed within safe bounds to avoid empty/too-small candidate sets"
    )

    universe_adaptive_min_volume_floor_ratio: float = Field(
        default=0.25,
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum allowed ratio for adaptive volume fallback (0.01-1.00): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        ge=0.01,
        le=1.0,
        description="Adaptive fallback never lowers min volume below this ratio of configured min_24h_volume"
    )

    # Multi-Coin Simultaneous Trading
    max_simultaneous_coins: int = Field(
        default=1,
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum simultaneous coins to trade (1-12, capital divided equally): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        ge=1,
        le=12,
        description="Number of coins to trade simultaneously. Capital is divided equally among coins."
    )

    # US-007: Dynamic Pair Manager (two-tier pair discovery)
    use_dynamic_pair_manager: bool = Field(
        default=False,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable dynamic pair discovery (REST API scans all pairs, selects best): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Enable two-tier pair discovery: scans ALL pairs via REST, selects best for WebSocket"
    )

    pair_scan_interval_seconds: int = Field(
        default=300,
        client_data=ClientFieldData(
            prompt=lambda mi: "Interval for scanning all pairs (seconds): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        ge=60,
        le=3600,
        description="How often to scan all pairs for rotation (default: 300 = 5 min)"
    )

    max_spread_pct: float = Field(
        default=0.5,
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum bid-ask spread percentage for pair selection: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        ge=0.01,
        le=5.0,
        description="Pairs with spread above this are excluded (default: 0.5%)"
    )

    switch_grace_period_seconds: int = Field(
        default=600,
        client_data=ClientFieldData(
            prompt=lambda mi: "Grace period before switching coins (seconds, 0=disabled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        ge=0,
        description="Minimum time (seconds) before switching to a different coin. Professional practice: give trades time to develop (default: 600 = 10 min)"
    )

    # Task 2.2: Grace Period Bypass Logic
    grace_bypass_on_executor_error: bool = Field(
        default=True,
        description="Bypass grace period if executor is FAILED/ERROR state (immediate rotation)"
    )

    grace_bypass_on_sl_hit: bool = Field(
        default=True,
        description="Bypass grace period if stop-loss is hit (immediate exit)"
    )

    grace_bypass_on_regime_flip: bool = Field(
        default=True,
        description="Bypass grace period on extreme regime change (BULL→BEAR or vice versa)"
    )

    grace_bypass_on_slot_pressure: bool = Field(
        default=True,
        description="Bypass grace period if all slots are full and better opportunity exists"
    )

    grace_bypass_on_stale_data: bool = Field(
        default=True,
        description="Bypass grace period if market data for the pair is stale/unavailable"
    )

    # ==========================================================================
    # US-008: Staleness Guard - "Trade Only When Data Fresh"
    # ==========================================================================
    staleness_guard_enabled: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable staleness guard (reject trades on stale data)? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Block entries when market data is stale/outdated"
    )

    max_price_age_ms: int = Field(
        default=2000,
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum price data age in milliseconds (default 2000): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        ge=100,
        le=60000,
        description="Maximum allowed age for price data before considered stale"
    )

    max_orderbook_age_ms: int = Field(
        default=5000,
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum orderbook data age in milliseconds (default 5000): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        ge=100,
        le=60000,
        description="Maximum allowed age for orderbook data before considered stale"
    )

    # ==========================================================================
    # US-002: Auto-Quarantine - Temporary disable unhealthy pairs
    # ==========================================================================
    auto_quarantine: Optional[dict] = Field(
        default_factory=lambda: {
            "enabled": True,
            "threshold": 10,      # Max failures before quarantine
            "window_sec": 120,    # Rolling window (2 minutes)
            "duration_sec": 900,  # Quarantine duration (15 minutes)
        },
        client_data=ClientFieldData(
            prompt=lambda mi: "Auto-quarantine config (dict with enabled, threshold, window_sec, duration_sec): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Auto-quarantine pairs with persistent data issues"
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
            prompt=lambda mi: "Coin rotation threshold (number of updates without trades before replacement, default 90 = ~15 min): ",  # noqa: E501
            prompt_on_new=False,
        ),
        json_schema_extra={
            "is_updatable": True})

    # ST-03: Pool membership cooldown — prevent rapid in/out flipping
    pool_membership_cooldown_seconds: int = Field(
        default=1800,  # 30 min
        client_data=ClientFieldData(
            prompt=lambda mi: "Pool membership cooldown (seconds a coin must stay in pool, default 1800 = 30 min): ",
            prompt_on_new=False,
        ),
        json_schema_extra={
            "is_updatable": True,
            "description": "Coins stay in monitored pool for at least this long before being rotated out"
        },
        ge=0,
    )

    # Periodic Coin Discovery (auto-refresh pool during runtime)
    coin_discovery_refresh_interval_seconds: int = Field(
        default=3600,  # 1 hour
        client_data=ClientFieldData(
            prompt=lambda mi: "Coin discovery refresh interval in seconds (3600 = 1 hour, 0 = disabled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={
            "is_updatable": True,
            "description": "How often to rescan ALL available pairs and refresh the coin pool (0 = only at startup)"
        }
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
        default=-1.5,  # Exit if 60m trend < -1.5% (tighter crash protection)
        client_data=ClientFieldData(
            prompt=lambda mi: "Exit short-term threshold (default -0.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    exit_mid_threshold: float = Field(
        default=-0.5,  # Exit if 240m trend < -0.5%
        client_data=ClientFieldData(
            prompt=lambda mi: "Exit mid-term threshold (default 0.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    downtrend_gate_enabled: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable downtrend gate for new entries? (default True): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    downtrend_gate_1h_min: float = Field(
        default=-1.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Downtrend gate 1h minimum (default -1.0%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    downtrend_gate_4h_min: float = Field(
        default=-0.75,
        client_data=ClientFieldData(
            prompt=lambda mi: "Downtrend gate 4h minimum (default -0.75%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    downtrend_gate_24h_min: float = Field(
        default=-0.5,
        client_data=ClientFieldData(
            prompt=lambda mi: "Downtrend gate 24h minimum (default -0.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # PRO EXIT SYSTEM - Layer 3: Price-Based Emergency Exits
    emergency_exit_pct: float = Field(
        default=-2.0,  # Exit immediately if price drops 2.0% below entry (prevents crash losses)
        client_data=ClientFieldData(
            prompt=lambda mi: "Emergency exit percentage (default -2.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    hard_stop_pct: float = Field(
        default=-3.0,  # Fail-safe exit if price drops 3.0% below entry (last resort protection)
        client_data=ClientFieldData(
            prompt=lambda mi: "Hard stop percentage (default -4.0%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    no_loss_exit_enabled: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable no-loss exit on trend weakness? (default True): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    no_loss_exit_min_net_pct: float = Field(
        default=0.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum net % (after fees) for no-loss exit (default 0.0%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # PRO EXIT SYSTEM - Layer 5: Grid Profit Exit
    min_grid_profit_pct: float = Field(
        default=1.0,  # Exit if grid realized profit >= 1.0% (covers fees + spread)
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum grid profit percentage to exit (default 0.6%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Startup delay - wait before first trade
    min_startup_wait_seconds: int = Field(
        default=1800,  # Wait 30 minutes before first trade
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

    # Monitoring & Rotation Settings
    max_coin_monitoring_seconds: int = Field(
        default=300,  # 5 minutes
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum time to monitor a coin without execution (seconds): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    session_blacklist_duration_seconds: int = Field(
        default=7200,  # 2 hours
        client_data=ClientFieldData(
            prompt=lambda mi: "Duration to blacklist non-executing coins (seconds): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Switch Management
    min_switch_interval_seconds: int = Field(
        default=1800,  # 30 minutes default switch cooldown
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

    max_hold_time_seconds: int = Field(
        default=0,  # 0 = unlimited, else force rotation after X seconds (prevents 21h+ stuck positions)
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum hold time before force rotation (seconds, 0=unlimited): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # ==============================================================================
    # TREND-AWARE EXIT SYSTEM (Soft/Hard Hold Time)
    # ==============================================================================
    # Prevents "dom verkopen" after fixed time when trend is still bullish
    # After soft_hold: only exit if trend bearish OR pnl too negative
    # After hard_hold: always exit (bag-holder prevention)

    soft_hold_time_seconds: int = Field(
        default=7200,  # 2 hours - trend-aware exit kicks in
        client_data=ClientFieldData(
            prompt=lambda mi: "Soft hold time before trend-aware exit (seconds, default 7200=2h): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    hard_hold_time_seconds: int = Field(
        default=21600,  # 6 hours - always exit (bag-holder prevention)
        client_data=ClientFieldData(
            prompt=lambda mi: "Hard hold time before forced exit (seconds, default 21600=6h): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    soft_exit_min_trend_pct: float = Field(
        default=0.3,  # Trend must be > 0.3% to extend hold
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum trend % to extend hold time (default 0.3%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    soft_exit_max_loss_pct: float = Field(
        default=-1.5,  # Exit even with good trend if loss > 1.5%
        client_data=ClientFieldData(
            prompt=lambda mi: "Max loss % before forced exit (default -1.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    soft_exit_extend_seconds: int = Field(
        default=1800,  # Extend by 30 min if trend is bullish
        client_data=ClientFieldData(
            prompt=lambda mi: "Extend hold by X seconds if trend bullish (default 1800=30min): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # ==============================================================================
    # STORY A1: MULTI-TIMEOUT LIFECYCLE (Professional Rotation)
    # ==============================================================================

    no_fill_timeout_sec: int = Field(
        default=1200,  # 20 minutes - no fills at all → cancel + close
        client_data=ClientFieldData(
            prompt=lambda mi: "No-fill timeout (seconds, 0=disabled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    no_progress_timeout_sec: int = Field(
        default=3600,  # 1 hour - no new progress → start unwind
        client_data=ClientFieldData(
            prompt=lambda mi: "No-progress timeout (seconds, 0=disabled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Story 2.1/2.2: Rapid grid-fill detection — halve no-progress timeout when all buys fill fast
    rapid_fill_window_sec: int = Field(
        default=300,  # If all buy levels fill within 300s → falling knife suspected
        client_data=ClientFieldData(
            prompt=lambda mi: "Rapid fill window (seconds, 0=disabled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # PRO TIMEOUT: PnL-aware and ATR-aware timeout protection
    no_progress_min_loss_pct: float = Field(
        default=1.5,  # Only trigger timeout if unrealized loss > 1.5%
        client_data=ClientFieldData(
            prompt=lambda mi: "No-progress min loss % (only trigger if losing more than this): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    no_progress_atr_multiplier: float = Field(
        default=0.0,  # 0 = disabled, 1.5 = test, 2.0 = conservative
        client_data=ClientFieldData(
            prompt=lambda mi: "No-progress ATR multiplier (0=disabled, 1.5=test, 2.0=conservative): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    close_grace_sec: int = Field(
        default=600,  # ST-05b: 10 min for graceful close (LIMIT MAKER) before aggressive (MARKET)
        client_data=ClientFieldData(
            prompt=lambda mi: "Close grace period (seconds): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # ==============================================================================
    # STORY A2: SESSION BLACKLIST & ANTI-FLIPFLOP
    # ==============================================================================

    blacklist_after_timeout_sec: int = Field(
        default=1800,  # 30 minutes - timeout closes trigger temporary blacklist
        client_data=ClientFieldData(
            prompt=lambda mi: "Blacklist duration after timeout (seconds, 0=disabled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # ==============================================================================
    # STORY B1: TWO-PHASE UNWIND PROTOCOL (Graceful → Aggressive Fallback)
    # ==============================================================================

    aggressive_close_method: str = Field(
        default="MARKET",  # MARKET | TAKER_LIMIT_IOC (exchange-dependent)
        client_data=ClientFieldData(
            prompt=lambda mi: "Aggressive close method (MARKET, TAKER_LIMIT_IOC): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    aggressive_close_slippage_guard_pct: Decimal = Field(
        default=Decimal("0.30"),  # 0.3% max slippage for aggressive close
        client_data=ClientFieldData(
            prompt=lambda mi: "Aggressive close slippage guard (%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    fee_aware_timeout_bypass_sec: int = Field(
        default=0,  # 0 = auto (2 × no_progress_timeout_sec) for NO_PROGRESS timeout exits
        client_data=ClientFieldData(
            prompt=lambda mi: "Fee-aware timeout bypass after seconds (0=auto): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    max_close_retries: int = Field(
        default=2,  # Max retries for close orders (graceful + aggressive phases)
        client_data=ClientFieldData(
            prompt=lambda mi: "Max close order retries: ",
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

    min_grid_level_spacing_pct: float = Field(
        default=1.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum spacing between grid levels (%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Hybrid Grid: SmartEntryFilter Configuration
    use_smart_entry_filter: bool = Field(
        default=False,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable SmartEntryFilter (blocks bad entries)? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    smart_entry_filter: dict = Field(
        default_factory=dict,
        client_data=ClientFieldData(
            prompt=lambda mi: "SmartEntryFilter config (dict, leave empty for defaults): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Hybrid momentum sleeve: Phase 2 is detect-only scoring/logging.
    momentum_sleeve: dict = Field(
        default_factory=lambda: {
            "mode": "detect_only",
            "min_score_to_enter": 55,
            "momentum_1h_min_pct": 0.5,
            "momentum_4h_min_pct": 1.0,
            "momentum_max_rsi": 80,
            "momentum_min_volume_expansion": 1.2,
            "momentum_regime_gate": ["BULL", "CHOP"],
            "momentum_max_spread_pct": 0.5,
            "momentum_max_wick_risk": 0.7,
            "rejected_log_throttle_seconds": 300,
            "scorer_weights": {
                "trend_1h": 0.25,
                "trend_4h": 0.30,
                "volume_expansion": 0.20,
                "relative_strength": 0.15,
                "spread": 0.05,
                "rsi_wick_risk": 0.05,
            },
        },
        client_data=ClientFieldData(
            prompt=lambda mi: "Momentum sleeve config (detect-only dict): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Task 3.1: Dynamic Slot Manager (account-size and regime-aware slot scaling)
    dynamic_slots: dict = Field(
        default_factory=dict,
        client_data=ClientFieldData(
            prompt=lambda mi: "Dynamic slot manager config (dict, leave empty for defaults): ",
            prompt_on_new=False,
        ),
        json_schema_extra={
            "is_updatable": True,
            "description": "Account-size and regime-aware slot scaling. Keys: enabled (bool), min_slots (int), max_slots (int), regime_multipliers (dict)"
        }
    )

    # Hybrid Grid v2.0: Core Universe (manual trading pairs for v2.0)
    core_universe: Optional[List[str]] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Core universe for SmartEntry v2.0 (comma separated pairs): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Hybrid Grid v2.0: Coin Profiles (per-coin SmartEntry overrides)
    coin_profiles: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Coin profiles for SmartEntry v2.0 (dict of overrides): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Hybrid Grid v2.0: Telegram Alerts
    telegram: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Telegram config (dict with bot_token and chat_id): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Hybrid Grid: DynamicGridSizer Configuration
    use_dynamic_grid_sizer: bool = Field(
        default=False,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable DynamicGridSizer (ATR-based grid count)? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    dynamic_grid_sizer: dict = Field(
        default_factory=dict,
        client_data=ClientFieldData(
            prompt=lambda mi: "DynamicGridSizer config (dict, leave empty for defaults): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Regime-aware coin selection (regime_coin_selector.py)
    regime_coin_selection: dict = Field(
        default_factory=dict,
        json_schema_extra={"is_updatable": True}
    )

    # Fee-aware pre-entry filter (fee_aware_filter.py)
    fee_aware_filter: dict = Field(
        default_factory=dict,
        json_schema_extra={"is_updatable": True}
    )

    # ST-11: Idle mode — reduce scan frequency when no edge is found
    idle_mode: dict = Field(
        default_factory=lambda: {
            'enabled': True,
            'no_edge_cycles_to_idle': 10,
            'idle_scan_interval_seconds': 120,
            'normal_scan_interval_seconds': 10,
            'log_interval_cycles': 5,
        },
        json_schema_extra={"is_updatable": True}
    )

    # ST-12: Economic edge gate — block entries without positive EV
    economic_edge_gate: dict = Field(
        default_factory=lambda: {
            'enabled': True,
            'min_edge_pct': 0.10,
            'include_spread_cost': True,
            'include_slippage_buffer_pct': 0.05,
        },
        json_schema_extra={"is_updatable": True}
    )

    # Enhanced close cooldowns (escalating, per-outcome)
    close_cooldowns: dict = Field(
        default_factory=dict,
        json_schema_extra={"is_updatable": True}
    )

    # Regime-based executor timeouts
    regime_timeouts: dict = Field(
        default_factory=dict,
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

    min_order_amount_quote: Decimal = Field(
        default=Decimal("5"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum order amount in quote asset: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Risk Management
    # stop_loss_pct: None = disabled (rely on trend exit, emergency exit, time-based exit)
    stop_loss_pct: Optional[Decimal] = Field(
        default=None,  # None = disabled, grid relies on other exit mechanisms
        client_data=ClientFieldData(
            prompt=lambda mi: "Stop loss percentage (null to disable, 0.08 for -8%): ",
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

    # Trailing stop: lock in profit once TP activation is reached
    trailing_stop_activation_pct: Optional[Decimal] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Trailing stop activation (e.g., 0.01 for +1%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )
    trailing_stop_delta_pct: Optional[Decimal] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Trailing stop delta (e.g., 0.005 for 0.5% drawback): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Dynamic TP: scale take-profit per-coin using ATR
    dynamic_tp_enabled: bool = Field(
        default=False,
        json_schema_extra={"is_updatable": True}
    )
    dynamic_tp_atr_multiplier: Decimal = Field(
        default=Decimal("0.5"),
        json_schema_extra={"is_updatable": True}
    )
    dynamic_tp_min_pct: Decimal = Field(
        default=Decimal("0.008"),
        json_schema_extra={"is_updatable": True}
    )
    dynamic_tp_max_pct: Decimal = Field(
        default=Decimal("0.025"),
        json_schema_extra={"is_updatable": True}
    )

    # PROFESSIONAL RISK MANAGEMENT (Grid-Aware)
    use_professional_risk_mgmt: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable professional risk management (ATR stops, profit tiers, context-aware exits)? ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # T0-Q2: Removed duplicate max_daily_loss_pct (was Decimal("0.03") here, shadowed by float(5.0) at PHASE 1 section)
    # The active definition is in the "PHASE 1: Drawdown & Loss Limits" section below

    atr_stop_multiplier: Decimal = Field(
        default=Decimal("2.0"),  # Stop at 2×ATR (grid-aware)
        client_data=ClientFieldData(
            prompt=lambda mi: "ATR stop multiplier (e.g., 2.0 = stop at 2×ATR, wider for volatile coins): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    min_stop_pct: Decimal = Field(
        default=Decimal("0.02"),  # Min -2% stop
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum stop loss percentage (e.g., 0.02 = -2%, never too tight): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    max_stop_pct: Decimal = Field(
        default=Decimal("0.08"),  # Max -8% stop
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum stop loss percentage (e.g., 0.08 = -8%, cap for volatile coins): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Item 7: Dynamic Take-Profit — adjust TP based on trend strength
    use_dynamic_take_profit: bool = Field(
        default=False,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable dynamic take-profit (widen TP in uptrend, tighten in downtrend)? ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    min_take_profit_pct: Optional[Decimal] = Field(
        default=None,  # Defaults to 70% of base take_profit_pct
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum take-profit % in dynamic mode (e.g., 0.005 = 0.5%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    max_take_profit_pct: Optional[Decimal] = Field(
        default=None,  # Defaults to 200% of base take_profit_pct
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum take-profit % in dynamic mode (e.g., 0.04 = 4%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    time_based_stop_minutes: int = Field(
        default=360,  # 6 hours (grid needs time to work)
        client_data=ClientFieldData(
            prompt=lambda mi: "Time-based stop for stalled positions (minutes, e.g., 360 = 6 hours): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    time_stop_requires_stall: bool = Field(
        default=True,  # Only exit if price stalled OR no fills
        client_data=ClientFieldData(
            prompt=lambda mi: "Require price stall OR no fills for time exit? ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    price_stall_threshold_atr: Decimal = Field(
        default=Decimal("0.3"),  # < 0.3× ATR = stalled
        client_data=ClientFieldData(
            prompt=lambda mi: "Price stall threshold in ATR multiples (e.g., 0.3 = movement < 0.3×ATR is stalled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    min_minutes_since_last_fill: int = Field(
        default=45,  # Dead liquidity check
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum minutes since last fill to consider position dead (e.g., 45): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    min_rolling_pnl_pct: Decimal = Field(
        default=Decimal("-0.02"),  # Pause if rolling PnL < -2%
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum rolling PnL to keep trading (e.g., -0.02 = pause if last 20 trades avg < -2%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    min_win_rate_threshold: Decimal = Field(
        default=Decimal("0.35"),  # 35% WR acceptable for grids
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum win rate threshold (e.g., 0.35 = 35%, grids can be profitable at low WR): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    pause_cooldown_minutes: int = Field(
        default=120,  # 2-hour pause
        client_data=ClientFieldData(
            prompt=lambda mi: "Pause cooldown in minutes after trigger (e.g., 120 = 2 hours): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    resume_min_pnl_pct: Decimal = Field(
        default=Decimal("0.0"),  # Resume only if last 10 trades >= 0%
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum last 10 trades PnL to resume after pause (e.g., 0.0 = breakeven): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    max_pause_extensions: int = Field(
        default=2,
        client_data=ClientFieldData(
            prompt=lambda mi: "Max times pause can extend before forced resume (prevents deadlock): ",
            prompt_on_new=False,
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

    # PHASE 1: Slippage Protection (Fix #1)
    max_entry_spread_pct: float = Field(
        default=0.5,
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum entry spread % (e.g., 0.5 for 0.5%, rejects wide spreads): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # PHASE 1: Drawdown & Loss Limits (Fix #2 & #3)
    max_daily_loss_pct: float = Field(
        default=5.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Max daily loss % (trading pauses if exceeded): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )
    max_weekly_loss_pct: float = Field(
        default=10.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Max weekly loss %: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )
    max_monthly_loss_pct: float = Field(
        default=15.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Max monthly loss %: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )
    # Daily loss limit in quote currency - works for EUR, USD, USDT, etc.
    max_daily_loss_eur: Optional[float] = Field(
        default=None,
        alias="max_daily_loss_quote",  # Alias for currency-agnostic naming
        client_data=ClientFieldData(
            prompt=lambda mi: "Max daily loss in quote currency (optional, press enter to skip): ",
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
        default=Decimal("0.80"),  # Max 80% of capital total
        client_data=ClientFieldData(
            prompt=lambda mi: "Max total exposure (% of capital, e.g., 0.80 for 80%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # Global risk governance
    risk_reference_balance_quote: Decimal = Field(
        default=Decimal("1000"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Reference account balance in quote asset for risk sizing: ",
            prompt_on_new=True,
        ),
        json_schema_extra={"is_updatable": True},
    )
    risk_bucket_limits: Optional[Dict[str, float]] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Per-bucket max allocation % as dict (L1/L2/MEME/ILLIQUID/BLOCKED), or leave empty for defaults: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    risk_max_daily_loss_pct: Decimal = Field(
        default=Decimal("2"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum daily loss before halting trading (% of balance, default 2): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    risk_max_balance_per_trade_pct: Decimal = Field(
        default=Decimal("0.5"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum balance risk per trade (% of balance, default 0.5): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    risk_max_total_open_risk_pct: Decimal = Field(
        default=Decimal("3"),
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum total simultaneous risk (% of balance, default 3): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    risk_exit_cooldown_minutes: int = Field(
        default=0,  # TESTING: was 30, now 0 for fast retrying of same symbol
        client_data=ClientFieldData(
            prompt=lambda mi: "Exit cooldown in minutes before the same symbol can be retraded: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    r_unit_quote: float = Field(
        default=5.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "1R unit in quote currency (used for daily coin kill switch): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    daily_kill_switch_enabled: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable daily coin kill switch (-2R disables, -1R halves size): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    risk_symbol_switch_cooldown_minutes: int = Field(
        default=0,  # TESTING: was 45 minutes
        client_data=ClientFieldData(
            prompt=lambda mi: "Global symbol switch cooldown in minutes (default 45): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    risk_consecutive_loss_cooldown_minutes: int = Field(
        default=60,
        client_data=ClientFieldData(
            prompt=lambda mi: "Cooldown (minutes) after consecutive losses, default 60: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )

    # Item 16: Capital Efficiency Reserve
    capital_reserve_pct: float = Field(
        default=0.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Capital reserve % (0-50%, held back as opportunity reserve, activate at >€10k): ",
            prompt_on_new=False,
        ),
        description="Percentage of balance reserved as opportunistic reserve (0-50%)",
        json_schema_extra={"is_updatable": True},
        ge=0.0,
        le=50.0,
    )

    # Orphan recovery
    auto_sell_orphaned_positions: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Auto-sell orphaned positions at startup? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )

    # Trend strength controls
    trend_min_entry_strength: float = Field(
        default=0.10,  # LOWERED from 0.7 - allow entries in weaker trends (crypto rarely has +70% strength)
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum normalized trend strength to allow entries (0-1): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    trend_min_exit_strength: float = Field(
        default=-0.10,  # LOWERED from -0.7 - more responsive exits
        client_data=ClientFieldData(
            prompt=lambda mi: "Trend strength threshold to force exits (negative values): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )
    trend_confirmation_timeframes: int = Field(
        default=1,  # LOWERED: was 2, now 1 for testing (accept single timeframe confirmation)
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum number of agreeing timeframes required for trend confirmation: ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
    )

    # Warmup Override (Professional Pullback Buying)
    warmup_override_enabled: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable warmup 4H override (allow 1H dips in strong uptrends)? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Allow negative 1H trend if 4H trend is very strong (pullback buying strategy)"
    )

    warmup_4h_strong_min: float = Field(
        default=1.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Warmup override: minimum 4H trend % to allow 1H dips (default 1.0%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Minimum 4H trend required to override negative 1H trend"
    )

    warmup_1h_min_if_4h_strong: float = Field(
        default=-0.6,
        client_data=ClientFieldData(
            prompt=lambda mi: "Warmup override: minimum 1H trend % allowed when 4H strong (default -0.6%): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Minimum 1H trend allowed when 4H override is active (negative = pullback zone)"
    )

    warmup_max_minutes: int = Field(
        default=120,
        client_data=ClientFieldData(
            prompt=lambda mi: "Warmup period max duration in minutes (default 120): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Maximum warm-up period in minutes after bot start (default 120 = 2 hours)"
    )

    warmup_max_trend_24h_pct: float = Field(
        default=10.0,
        json_schema_extra={"is_updatable": True},
        description="Reject coins already up > this % in 24h during warmup (avoids chasing extended moves)"
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

    # ==============================================================================
    # FEATURE 1.1: MARKET REGIME FILTER (v3.3)
    # ==============================================================================

    market_regime: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Market regime filter config (dict): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # ==============================================================================
    # FEATURE 1.2: TIME-BASED TRADING RULES (v3.3)
    # ==============================================================================

    time_based_rules: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Time-based trading rules config (dict): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # ==============================================================================
    # FEATURE 1.3: PERFORMANCE TRACKING (v3.3)
    # ==============================================================================

    performance_tracking: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Performance tracking config (dict): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # ==============================================================================
    # FEATURE 1.2b: LIQUIDITY-AWARE SMART SIZING (v3.4)
    # ==============================================================================

    liquidity_aware_sizing: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Liquidity-aware sizing config (dict): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    # ==============================================================================
    # ORDERBOOK DEPTH-BASED LIQUIDITY PROXY (Phase 1-4: Multi-mode + Regime-Aware)
    # ==============================================================================

    orderbook_liquidity: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Orderbook liquidity config (dict): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description=(
            "Orderbook depth-based liquidity proxy config. "
            "Keys: enabled, mode ('shadow'|'ranking'|'early'), regime_aware, "
            "depth_pct_range, depth_levels, min_depth_multiplier, "
            "use_for_ranking, use_for_entry, log_depth_metrics. "
            "Mode: 'shadow'=test only (log), 'ranking'=filter in coin selection (Phase 1), "
            "'early'=filter before trend calculation (Phase 2 optimization). "
            "Regime-aware (Phase 4): BULL=8x, CHOP=5x, BEAR=10x multipliers."
        )
    )

    orderbook_prefetch: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Orderbook prefetch config (dict): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description=(
            "Orderbook prefetch config for top-N candidates. "
            "Keys: enabled (bool), mode ('shadow'|'live'), top_n (int), "
            "max_subscriptions_per_minute (int). "
            "Mode: 'shadow'=observe only (log cache status), 'live'=actually subscribe. "
            "Helps pre-warm orderbook data for top candidates before SmartEntry validation."
        )
    )

    # ==============================================================================
    # DEBUG TRACE SYSTEM (Decision Transparency)
    # ==============================================================================

    debug_trace_enabled: bool = Field(
        default=False,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable decision trace logging (debugging)? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Enable detailed logging of accept/reject decisions for trading pairs"
    )

    debug_trace_format: str = Field(
        default="compact",
        client_data=ClientFieldData(
            prompt=lambda mi: "Decision trace format (compact/detailed/json): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Output format for decision traces: compact (prod), detailed (debug), json (analysis)"
    )

    debug_trace_log_accepted: bool = Field(
        default=False,
        client_data=ClientFieldData(
            prompt=lambda mi: "Log accepted pairs (can be verbose)? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Log decision traces for accepted trading pairs"
    )

    debug_trace_log_rejected: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Log rejected pairs? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Log decision traces for rejected trading pairs"
    )

    # ===== ADAPTIVE REGIME DETECTION (Phase 1: Logging Only) =====
    adaptive_regime_detection: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable adaptive regime detection? (leave empty for disabled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": False},
        description="Adaptive regime detection config (BULL/CHOP/BEAR)"
    )

    adaptive_filters: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Adaptive filter config (leave empty for disabled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": False},
        description="Filter parameters per regime (BULL/CHOP/BEAR)"
    )

    # ===== GRID SUITABILITY SCORER (Per-Coin Mean-Reversion Fitness) =====
    grid_suitability: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Grid suitability scorer config (leave empty for disabled): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": False},
        description="Per-coin grid suitability scoring (mean-reversion fitness)"
    )

    # ===== MULTI-TIMEFRAME BUY PROTECTION =====
    use_multi_timeframe_buy: bool = Field(
        default=False,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable multi-timeframe buy protection? (Yes/No): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Require positive momentum on multiple timeframes before entry"
    )

    mtf_1h_min_pct: float = Field(
        default=-0.1,
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum 1h trend % (default -0.1): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Minimum 1h trend required for entry (allows small pullbacks)"
    )

    mtf_4h_min_pct: float = Field(
        default=0.3,
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum 4h trend % (default 0.3): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Minimum 4h trend required for entry (momentum required)"
    )

    mtf_24h_min_pct: float = Field(
        default=0.5,
        client_data=ClientFieldData(
            prompt=lambda mi: "Minimum 24h trend % (default 0.5): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Minimum 24h trend required for entry (uptrend required)"
    )

    mtf_declining_1h_max: float = Field(
        default=-0.5,
        client_data=ClientFieldData(
            prompt=lambda mi: "Max 1h decline for crash detection (default -0.5): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="If 1h < this AND 4h < 0%, reject entry (crash detection)"
    )

    mtf_declining_4h_max: float = Field(
        default=0.0,
        client_data=ClientFieldData(
            prompt=lambda mi: "Max 4h decline for crash detection (default 0.0): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="If 1h declining AND 4h < this, reject entry (prevents trading during crashes)"
    )

    # Phase 1C: Observability Configuration
    observability: Optional[dict] = Field(
        default=None,
        client_data=ClientFieldData(
            prompt=lambda mi: "Observability config (optional): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True},
        description="Observability settings (structured_events_enabled, events_output_dir, buffer_size)"
    )

    @property
    def triple_barrier_config(self) -> TripleBarrierConfig:
        """
        Create TripleBarrierConfig for GridExecutor

        This configures stop-loss, take-profit, and order types for the grid.

        For futures/perpetual exchanges, use LIMIT instead of LIMIT_MAKER
        because many futures exchanges don't support LIMIT_MAKER order type.

        FIX: Always use LIMIT_MAKER for spot trading to get maker fees (0.16% on Kraken).
        Only use LIMIT for perpetual/futures exchanges.
        """
        # Check if this is a futures/perpetual exchange
        is_futures = (
            "perpetual" in self.connector_name.lower()
            or "_perpetual" in self.connector_name.lower()
            or self.connector_name.endswith("_perp")
        )

        # Use LIMIT_MAKER for spot (lower fees), LIMIT for futures (better compatibility)
        order_type = OrderType.LIMIT if is_futures else OrderType.LIMIT_MAKER

        return TripleBarrierConfig(
            stop_loss=self.stop_loss_pct,  # None = no stop-loss (disabled)
            take_profit=self.take_profit_pct,
            time_limit=None,  # No time limit for now
            trailing_stop=None,  # No trailing stop for now (can add later)
            open_order_type=order_type,
            take_profit_order_type=order_type,
            stop_loss_order_type=OrderType.LIMIT,  # ST-05b: was MARKET → LIMIT for lower fees and less slippage
            time_limit_order_type=OrderType.LIMIT   # ST-05b: was MARKET → LIMIT for lower fees and less slippage
        )

    @field_validator('trend_lookback_minutes')
    @classmethod
    def validate_trend_lookback(cls, v: int) -> int:
        """Validate trend lookback is reasonable"""
        if v < 5:
            raise ValueError("Trend lookback must be at least 5 minutes")
        if v > 1440:
            raise ValueError("Trend lookback should not exceed 1440 minutes (24 hours)")
        return v

    @property
    def risk_limits(self) -> RiskLimits:
        """
        Convert configuration values into a RiskLimits instance usable
        by the global risk manager.
        """
        return RiskLimits(
            max_daily_loss_pct=self.risk_max_daily_loss_pct,
            max_balance_risk_per_trade_pct=self.risk_max_balance_per_trade_pct,
            max_total_open_risk_pct=self.risk_max_total_open_risk_pct,
            min_hold_seconds=self.min_hold_time_seconds,
            max_hold_seconds=self.max_hold_time_seconds,  # NEW: Force rotation after max hold time
            exit_cooldown_seconds=self.risk_exit_cooldown_minutes * 60,
            symbol_switch_cooldown_seconds=self.risk_symbol_switch_cooldown_minutes * 60,
            consecutive_loss_cooldown_seconds=self.risk_consecutive_loss_cooldown_minutes * 60,
        )

    @property
    def risk_reference_balance(self) -> Decimal:
        return self.risk_reference_balance_quote

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
    def validate_stop_loss(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        """Validate stop loss percentage - None = disabled"""
        if v is None:
            return None  # Disabled - rely on other exit mechanisms
        if v <= 0:
            raise ValueError("Stop loss must be positive (or null to disable)")
        if v > Decimal("0.5"):
            raise ValueError("Stop loss should not exceed 50%")
        return v

    @field_validator('smart_entry_filter')
    @classmethod
    def validate_smart_entry_filter(cls, v: dict) -> dict:
        """Validate SmartEntryFilter config dict"""
        if not v:  # Empty dict is OK (uses defaults)
            return v

        # Validate known keys
        valid_keys = {
            'rsi_buy_max', 'rsi_extreme_low', 'rsi_block_min',
            'vwap_max_deviation_pct', 'min_wick_ratio',
            'max_atr_pct_for_grid', 'min_atr_pct_for_grid',
            'max_5m_spike_pct', 'max_down_accel_pct', 'max_up_accel_pct',
            'max_trend_24h_pct', 'min_trend_24h_pct', 'max_trend_4h_pct',
            # Phase 2: Slippage Protection
            'slippage_check_enabled', 'max_entry_spread_pct',
            # Phase 2: Order Book Depth
            'depth_check_enabled', 'min_depth_multiplier',
            # EPIC v3.4: Momentum Health Guards (Stories 1-11)
            'vwap_slope_guard_enabled', 'vwap_slope_guard_shadow_mode',
            'vwap_slope_dual_confirmation',  # Story 9
            'vwap_slope_deviation_high_pct', 'vwap_slope_min_pct_5m', 'vwap_slope_min_pct_15m', 'vwap_slope_log_details',
            'parabolic_detector_enabled', 'parabolic_detector_shadow_mode',
            'parabolic_cooldown_persist',  # Story 10
            'parabolic_accel_5m_min_pct', 'parabolic_accel_15m_min_pct', 'parabolic_vwap_dev_min_pct',
            'parabolic_cooldown_minutes', 'parabolic_blacklist_scope', 'parabolic_log_details',
            'momentum_thresholds',
            # Story 11: Market Exhaustion Warning
            'market_exhaustion_enabled', 'market_exhaustion_threshold_pct',
            'market_exhaustion_sample_size', 'market_exhaustion_cooldown_min', 'market_exhaustion_telegram'
        }
        invalid_keys = set(v.keys()) - valid_keys
        if invalid_keys:
            raise ValueError(f"Invalid SmartEntryFilter keys: {invalid_keys}")

        return v

    @field_validator('dynamic_slots')
    @classmethod
    def validate_dynamic_slots(cls, v: dict) -> dict:
        """Validate dynamic_slots config dict"""
        if not v:  # Empty dict is OK (uses defaults)
            return v

        # Validate known keys
        valid_keys = {'enabled', 'min_slots', 'max_slots', 'regime_multipliers'}
        invalid_keys = set(v.keys()) - valid_keys
        if invalid_keys:
            raise ValueError(f"Invalid dynamic_slots keys: {invalid_keys}")

        # Validate slot counts
        if 'min_slots' in v and v['min_slots'] < 1:
            raise ValueError("min_slots must be at least 1")
        if 'max_slots' in v and v['max_slots'] > 20:
            raise ValueError("max_slots should not exceed 20 (resource constraints)")
        if 'min_slots' in v and 'max_slots' in v and v['min_slots'] > v['max_slots']:
            raise ValueError("min_slots must be less than or equal to max_slots")

        # Validate regime multipliers if present
        if 'regime_multipliers' in v and isinstance(v['regime_multipliers'], dict):
            for regime, multiplier in v['regime_multipliers'].items():
                if not isinstance(multiplier, (int, float)) or multiplier < 0:
                    raise ValueError(f"Regime multiplier for {regime} must be a non-negative number")
                if multiplier > 3.0:
                    raise ValueError(f"Regime multiplier for {regime} should not exceed 3.0 (risk management)")

        return v

    @field_validator('dynamic_grid_sizer')
    @classmethod
    def validate_dynamic_grid_sizer(cls, v: dict) -> dict:
        """Validate DynamicGridSizer config dict"""
        if not v:  # Empty dict is OK (uses defaults)
            return v

        # Validate known keys
        valid_keys = {'min_grids', 'max_grids', 'low_vol_atr_pct', 'mid_vol_atr_pct', 'high_vol_atr_pct'}
        invalid_keys = set(v.keys()) - valid_keys
        if invalid_keys:
            raise ValueError(f"Invalid DynamicGridSizer keys: {invalid_keys}")

        # Validate grid counts
        if 'min_grids' in v and v['min_grids'] < 2:
            raise ValueError("min_grids must be at least 2")
        if 'max_grids' in v and v['max_grids'] > 20:
            raise ValueError("max_grids should not exceed 20")
        if 'min_grids' in v and 'max_grids' in v and v['min_grids'] >= v['max_grids']:
            raise ValueError("min_grids must be less than max_grids")

        return v
