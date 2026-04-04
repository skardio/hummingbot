# Round 2: Architecture & Code Quality Review

> **Hoe te gebruiken**: Open een VERSE Claude Opus (of o3) sessie.
> Plak deze volledige inhoud als eerste bericht.
> De controller (9,182 regels) is te groot om hier in te voegen — upload
> dat bestand apart als file attachment.
>
> **Benodigde file uploads** (apart bijvoegen):
> - `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` (9,182 lines)
>
> **Snapshot datum**: 2026-03-08

---

## Prompt

## Round 2: Architecture & Code Quality Review

```
Act as a senior Python software architect with expertise in async
trading systems, Hummingbot's StrategyV2 framework, and production
bot design. You have built and maintained trading systems handling
$10M+ daily volume.

## Architecture overview

| Component | Lines | Files | Purpose |
|-----------|-------|-------|---------|
| Controller (God class) | 9,182 | 1 | Everything: discovery, trends, filtering, risk, grids, monitoring, switching, reporting |
| Config model | 1,610 | 1 | Pydantic config with 200+ parameters |
| Utils | 7,595 | 21 | Trend calc, pair mgmt, order validation, regime detection, budget allocation |
| Monitoring | 3,190 | 10 | Telegram, dashboard, SQLite monitoring (335 MB production DB) |
| Core | 2,436 | 10 | Risk mgmt, drawdown, performance tracking |
| Filters | 1,765 | 6 | Smart entry, regime, parabolic, time-based |
| Observability | 1,700 | 5 | Event logging, console reporting, why-no-trade diagnostics |
| Logic | 1,184 | 6 | Coin selection, grid building, liquidity sizing |
| Risk | 968 | 4 | PnL tracker, risk manager, risk guard |
| Futures variant | 2,382 | 5 | Bitget perpetual futures specific |
| Tests | 25,551 | 87 | Unit + integration tests |
| **Total** | **~63,600** | **~190** | |

**Critical architectural fact:** The entire codebase is duplicated:
- `multi_coin_grid_pro/` — development package
- `hummingbot/multi_coin_grid_controllers/` + `hummingbot/multi_coin_grid_utils/` — deployed copy

Both are byte-identical (manually synced). ~18,700 lines duplicated.

**3 bot instances share the same controller code** with different configs:
- Kraken USD: `spot_grid_kraken_usd.yaml` (831 lines)
- Bitget Spot: `spot_grid_bitget.yaml`
- Bitget Futures: `futures_grid_bitget.yaml` (extends base controller)

**4 SQLite databases** with real trade data:
- `multi_coin_grid_v2.sqlite` (12 MB, Kraken EUR — historical)
- `multi_coin_grid_v2_usd.sqlite` (8 MB, Kraken USD)
- `spot_grid_bitget.sqlite` (6 MB, Bitget spot)
- `futures_grid_bitget.sqlite` (3 MB, Bitget futures)

## What I need you to evaluate

### 1. The God-class problem
- `MultiCoinGridController` is 9,182 lines, 79 methods, one file
- It handles: coin discovery, trend ranking, regime classification,
  entry filtering, grid creation, executor management, position tracking,
  budget allocation, risk checks, coin rotation, smart switching,
  orphan detection, stale order cleanup, monitoring, status reporting
- What should be extracted? Propose a concrete decomposition with
  class boundaries and dependency diagram

### 2. Full code duplication
- Two identical copies manually synced
- No symlinks, no package references, no build step
- What is the proper solution? Consider that the bot needs to work
  both as a standalone dev package and inside Hummingbot's plugin system

### 3. State management complexity
- State is scattered across: instance variables (~50+), SQLite DBs (5+),
  in-memory dicts, connector private attributes (`_in_flight_orders`,
  `_account_balances`)
- Accessing connector private attributes (`_in_flight_orders`) is fragile
- No clear state machine or lifecycle diagram

### 4. Async patterns
- The main loop is `determine_executor_actions()` called by Hummingbot's
  event loop. Inside it does sync-blocking work (trend calculations,
  DB queries) mixed with async calls
- Rate limiting via `time.time()` checks instead of proper async throttling
- `time` module imported inside methods instead of top-level

### 5. Config surface area
- 831-line YAML, 1,610-line Pydantic model, 200+ parameters
- Many params interact non-obviously (regime thresholds × filter thresholds
  × slot scaling × grid sizing = combinatorial explosion)
- Is this configurable or is it effectively un-tunable?

### 6. Test quality
- 87 test files, 25,551 lines — coverage unknown
- Real Telegram integration tests mixed with unit tests (no @pytest.mark.integration)
- How well do the tests cover the critical paths?

## Attachments I'll provide
- [ ] Full controller source (9,182 lines)
- [ ] Config model source (1,610 lines)
- [ ] Directory tree of multi_coin_grid_pro/
- [ ] 3 representative test files
- [ ] Budget allocator source (shows Decimal precision pattern)

## Output format requirements (apply to all findings)

For every major conclusion, provide an evidence table:

| Finding | Evidence (code/config/logs/data) | Impact | Recommendation | Confidence (high/med/low) |
|---------|----------------------------------|--------|----------------|---------------------------|
| ...     | ...                              | ...    | ...            | ...                       |

Separate clearly between:
- **Confirmed findings** — directly proven from code, logs, or data
- **Reasonable inferences** — likely true but not fully proven
- **Unknowns** — requires more data to determine (state what data is needed)

For each recommendation, rate:
- **Impact on PnL** (high / medium / low)
- **Impact on safety** (high / medium / low)
- **Implementation effort** (hours / days / weeks)
- **Urgency** (immediate / next sprint / backlog)

## What to keep
Identify which modules, patterns, or design choices are well-implemented
and should be preserved during any refactoring. Explain why they work.

## Expected output
1. **Architecture score** (1–10) with justification
2. **Decomposition proposal**: concrete class extraction plan for the God class
3. **Duplication solution**: recommended approach with trade-offs
4. **State management redesign**: what a clean state model looks like
5. **Top 10 code quality issues** ranked by severity (evidence table format)
6. **Technical debt inventory** with estimated effort to fix
7. **What to keep**: modules/patterns that are well-designed and should survive refactoring
```


---

## Attachment: Config Model — multi_coin_grid_config.py (1610 lines)

```python
"""
Configuration for Multi-Coin Grid Trading Controller

This config defines all parameters for the multi-coin grid trading strategy.
"""

from decimal import Decimal
from typing import List, Optional

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
        default=120,  # 2 minutes for graceful close (maker) before aggressive (market)
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

    # PROFESSIONAL RISK MANAGEMENT (Grid-Aware)
    use_professional_risk_mgmt: bool = Field(
        default=True,
        client_data=ClientFieldData(
            prompt=lambda mi: "Enable professional risk management (ATR stops, profit tiers, context-aware exits)? ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

    max_daily_loss_pct: Decimal = Field(
        default=Decimal("0.03"),  # -3% daily loss limit (HARD)
        client_data=ClientFieldData(
            prompt=lambda mi: "Maximum daily loss percentage (e.g., 0.03 for -3% stop trading for day): ",
            prompt_on_new=False,
        ),
        json_schema_extra={"is_updatable": True}
    )

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
            stop_loss_order_type=OrderType.MARKET,  # Market order for fast exit
            time_limit_order_type=OrderType.MARKET
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
            'max_trend_24h_pct', 'min_trend_24h_pct',
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

```

## Attachment: budget_allocator.py (337 lines)

```python
"""
US-004: Budget Allocator

Prevents "Insufficient balance" errors by:
1. Tracking reserved capital per active executor
2. Checking available balance before creating new executors
3. Blocking executor creation if insufficient free capital

The allocator uses a pessimistic reservation model:
- Each executor reserves: grid_levels × order_amount + fee_buffer
- Free capital = total_balance - reserved_capital
- New executor only starts if free_capital >= required_capital
"""
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional


@dataclass
class BudgetReservation:
    """Represents capital reserved for an executor."""
    executor_id: str
    symbol: str
    reserved_amount: Decimal  # Quote currency
    grid_levels: int
    timestamp: float


@dataclass
class BudgetCheckResult:
    """Result of budget availability check."""
    is_allowed: bool
    available_quote: Decimal
    required_quote: Decimal
    reason: Optional[str] = None
    reserved_by_others: Decimal = Decimal("0")


class BudgetAllocator:
    """
    Manages capital allocation across multiple concurrent executors.

    Key principles:
    1. Pessimistic reservation: assume worst-case capital needs
    2. Fee buffer: reserve extra for trading fees (configurable)
    3. Quote reserve: keep minimum buffer in account (safety margin)

    Example:
        allocator = BudgetAllocator(
            fee_buffer_pct=Decimal("0.002"),  # 0.2% for fees
            quote_reserve_pct=Decimal("0.05"),  # Keep 5% reserve
            logger=my_logger
        )

        # Before creating executor:
        result = allocator.check_budget(
            total_balance=Decimal("1000"),
            required_quote=Decimal("100"),
        )

        if result.is_allowed:
            # Create executor
            allocator.reserve("exec-123", "BTC-USDT", Decimal("100"), grid_levels=3, timestamp=now)
    """

    def __init__(
        self,
        fee_buffer_pct: Decimal = Decimal("0.002"),  # 0.2% default
        quote_reserve_pct: Decimal = Decimal("0.05"),  # 5% safety buffer
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize budget allocator.

        Args:
            fee_buffer_pct: Extra % to reserve for fees per executor
            quote_reserve_pct: % of total balance to keep as safety reserve
            logger: Logger instance
        """
        self.fee_buffer_pct = fee_buffer_pct
        self.quote_reserve_pct = quote_reserve_pct
        self.logger = logger or logging.getLogger(__name__)

        # Active reservations: executor_id -> BudgetReservation
        self._reservations: Dict[str, BudgetReservation] = {}

    @property
    def total_reserved(self) -> Decimal:
        """Total capital currently reserved across all executors."""
        return sum(r.reserved_amount for r in self._reservations.values())

    @property
    def active_executor_count(self) -> int:
        """Number of executors with active reservations."""
        return len(self._reservations)

    def calculate_required_quote(
        self,
        base_amount: Decimal,
        grid_levels: int = 3,
        include_fee_buffer: bool = True,
    ) -> Decimal:
        """
        Calculate total quote required for an executor.

        Args:
            base_amount: Base capital allocation (total_amount_quote from config)
            grid_levels: Number of grid levels
            include_fee_buffer: Whether to add fee buffer

        Returns:
            Total quote currency required
        """
        required = base_amount

        if include_fee_buffer:
            # Add fee buffer per level (buy + sell = 2 trades per level)
            fee_per_trade = base_amount * self.fee_buffer_pct
            total_fee_buffer = fee_per_trade * Decimal(str(grid_levels * 2))
            required += total_fee_buffer

        return required

    def check_budget(
        self,
        total_balance: Decimal,
        required_quote: Decimal,
        symbol: Optional[str] = None,
    ) -> BudgetCheckResult:
        """
        Check if budget is available for a new executor.

        Args:
            total_balance: Current total quote balance from exchange
            required_quote: Quote amount needed for new executor
            symbol: Optional symbol for logging

        Returns:
            BudgetCheckResult with decision and details
        """
        # Calculate reserve requirement
        min_reserve = total_balance * self.quote_reserve_pct

        # Calculate available after reservations and safety buffer
        reserved = self.total_reserved
        available = total_balance - reserved - min_reserve

        if available < Decimal("0"):
            available = Decimal("0")

        # Check if we have enough (with small tolerance for floating point precision)
        # This handles cases where both DynamicSlotManager and BudgetAllocator apply buffers
        tolerance = Decimal("0.01")  # $0.01 tolerance
        if available >= required_quote - tolerance:
            self.logger.debug(
                f"✅ US-004 BUDGET OK | {symbol or 'new'}: "
                f"need {required_quote:.2f}, have {available:.2f} free "
                f"(balance={total_balance:.2f}, reserved={reserved:.2f}, "
                f"safety_buffer={min_reserve:.2f})"
            )
            return BudgetCheckResult(
                is_allowed=True,
                available_quote=available,
                required_quote=required_quote,
                reserved_by_others=reserved,
            )
        else:
            reason = (
                f"Insufficient free capital: need {required_quote:.2f}, "
                f"have {available:.2f} (balance={total_balance:.2f}, "
                f"reserved={reserved:.2f}, safety={min_reserve:.2f})"
            )
            self.logger.warning(
                f"🚫 US-004 BUDGET BLOCKED | {symbol or 'new'}: {reason}"
            )
            return BudgetCheckResult(
                is_allowed=False,
                available_quote=available,
                required_quote=required_quote,
                reason=reason,
                reserved_by_others=reserved,
            )

    def reserve(
        self,
        executor_id: str,
        symbol: str,
        amount: Decimal,
        grid_levels: int,
        timestamp: float,
    ) -> bool:
        """
        Reserve capital for an executor.

        Should be called after check_budget() returns is_allowed=True
        and before executor is actually created.

        Args:
            executor_id: Unique executor ID
            symbol: Trading pair
            amount: Quote amount to reserve
            grid_levels: Number of grid levels
            timestamp: Current timestamp

        Returns:
            True if reservation was made
        """
        if executor_id in self._reservations:
            self.logger.warning(
                f"⚠️ US-004: Executor {executor_id[:8]}... already has reservation"
            )
            return False

        reservation = BudgetReservation(
            executor_id=executor_id,
            symbol=symbol,
            reserved_amount=amount,
            grid_levels=grid_levels,
            timestamp=timestamp,
        )
        self._reservations[executor_id] = reservation

        self.logger.info(
            f"💰 US-004 RESERVED | {symbol}: €{amount:.2f} for executor {executor_id[:8]}... "
            f"(total reserved: €{self.total_reserved:.2f}, {self.active_executor_count} executors)"
        )
        return True

    def release(self, executor_id: str) -> Optional[Decimal]:
        """
        Release reservation when executor completes/stops.

        Args:
            executor_id: Executor ID to release

        Returns:
            Amount that was released, or None if not found
        """
        reservation = self._reservations.pop(executor_id, None)

        if reservation:
            self.logger.info(
                f"💰 US-004 RELEASED | {reservation.symbol}: €{reservation.reserved_amount:.2f} "
                f"from executor {executor_id[:8]}... "
                f"(remaining reserved: €{self.total_reserved:.2f}, {self.active_executor_count} executors)"
            )
            return reservation.reserved_amount
        else:
            self.logger.debug(
                f"⚠️ US-004: No reservation found for executor {executor_id[:8]}..."
            )
            return None

    def get_reservation(self, executor_id: str) -> Optional[BudgetReservation]:
        """Get reservation details for an executor."""
        return self._reservations.get(executor_id)

    def get_symbol_reservations(self, symbol: str) -> Decimal:
        """Get total reserved amount for a specific symbol."""
        return sum(
            r.reserved_amount
            for r in self._reservations.values()
            if r.symbol == symbol
        )

    def cleanup_stale_reservations(self, max_age_seconds: float, current_time: float) -> int:
        """
        Remove reservations older than max_age (safety cleanup).

        Args:
            max_age_seconds: Maximum age before considering stale
            current_time: Current timestamp

        Returns:
            Number of reservations cleaned up
        """
        stale_ids = [
            eid for eid, r in self._reservations.items()
            if (current_time - r.timestamp) > max_age_seconds
        ]

        for eid in stale_ids:
            reservation = self._reservations.pop(eid)
            self.logger.warning(
                f"🧹 US-004 STALE CLEANUP | {reservation.symbol}: "
                f"Released €{reservation.reserved_amount:.2f} from stale executor {eid[:8]}... "
                f"(age: {(current_time - reservation.timestamp) / 3600:.1f}h)"
            )

        return len(stale_ids)

    def sync_with_active_executors(
        self,
        active_executor_ids: set,
        current_time: float,
    ) -> int:
        """
        Sync reservations with actually active executors.

        Removes reservations for executors that are no longer active.

        Args:
            active_executor_ids: Set of currently active executor IDs
            current_time: Current timestamp (for logging)

        Returns:
            Number of orphaned reservations cleaned up
        """
        orphaned_ids = [
            eid for eid in self._reservations.keys()
            if eid not in active_executor_ids
        ]

        for eid in orphaned_ids:
            reservation = self._reservations.pop(eid)
            self.logger.info(
                f"🧹 US-004 SYNC | Released orphaned reservation for {reservation.symbol}: "
                f"€{reservation.reserved_amount:.2f} (executor {eid[:8]}... no longer active)"
            )

        return len(orphaned_ids)

    def get_summary(self) -> Dict:
        """Get summary of current allocations."""
        return {
            "total_reserved": float(self.total_reserved),
            "executor_count": self.active_executor_count,
            "reservations": {
                eid: {
                    "symbol": r.symbol,
                    "amount": float(r.reserved_amount),
                    "grid_levels": r.grid_levels,
                }
                for eid, r in self._reservations.items()
            }
        }

```

## Attachment: test_multi_coin_grid_controller.py (999 lines)

```python
"""
Unit tests for MultiCoinGridController

Tests the main controller logic including:
- Executor creation/stopping
- Position closing when switching coins
- Position limits
- Manual trading pairs
- Switch logic
"""

import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo, RunnableStatus

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
except ImportError:
    try:
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
    except ImportError:
        # Last resort: try relative import
        from controllers.multi_coin_grid_config import MultiCoinGridConfig
        from controllers.multi_coin_grid_controller import MultiCoinGridController


# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


class TestMultiCoinGridController:
    """Test suite for MultiCoinGridController class"""

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        connector = AsyncMock()
        connector.name = "kraken"
        connector.get_price_by_type = AsyncMock(return_value=Decimal("1.5"))
        connector.get_order_book = Mock(return_value=MagicMock())
        connector.get_fee = Mock(return_value=Decimal("0.0016"))  # 0.16% maker fee
        return connector

    @pytest.fixture
    def mock_market_data_provider(self):
        """Create mock market data provider"""
        provider = MagicMock()
        provider.time = Mock(return_value=datetime.now().timestamp())
        return provider

    @pytest.fixture
    def mock_actions_queue(self):
        """Create mock actions queue"""
        return []

    @pytest.fixture
    def config(self):
        """Create test config"""
        return MultiCoinGridConfig(
            connector_name="kraken",
            quote_asset="EUR",
            total_amount_quote=Decimal("120"),
            max_coins_to_monitor=5,
            min_24h_volume_eur=Decimal("50000"),
            trend_min_change_pct=Decimal("0.5"),
            max_exposure_per_coin_pct=Decimal("0.15"),
            max_total_exposure_pct=Decimal("0.80"),
            # Risk management config (required for risk_manager initialization)
            risk_reference_balance_quote=Decimal("10000"),
            risk_max_daily_loss_pct=Decimal("2"),
            risk_max_balance_per_trade_pct=Decimal("0.5"),
            risk_max_total_open_risk_pct=Decimal("3"),
            risk_exit_cooldown_minutes=30,
            risk_symbol_switch_cooldown_minutes=45,
            risk_consecutive_loss_cooldown_minutes=60,
        )

    @pytest.fixture
    def controller(self, config, mock_connector, mock_market_data_provider, mock_actions_queue):
        """Create controller instance"""
        with patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery'), \
                patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator'):
            controller = MultiCoinGridController(
                config=config,
                market_data_provider=mock_market_data_provider,
                actions_queue=mock_actions_queue,
                connectors={"kraken": mock_connector},
                update_interval=10.0
            )
            # Mock the coin discovery and trend calculator
            controller.coin_discovery = AsyncMock()
            controller.trend_calculator = MagicMock()
            controller.monitored_coins = ["XRP-EUR", "ADA-EUR", "SOL-EUR"]
            return controller

    async def test_create_stop_action_with_position(self, controller, mock_connector):
        """Test that stop action is created with keep_position=False when executor has position"""
        # Setup: executor has open position
        controller.active_executor_id = "test_executor_123"
        controller.active_coin = "XRP-EUR"

        # Mock executor info with open position
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=datetime.now().timestamp(),
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=GridExecutorConfig(
                id="test_executor_123",
                type="grid_executor",
                timestamp=datetime.now().timestamp(),
                controller_id="multi_coin_grid",
                connector_name="kraken",
                trading_pair="XRP-EUR",
                start_price=Decimal("1.0"),
                end_price=Decimal("2.0"),
                limit_price=Decimal("0.95"),
                side=TradeType.BUY,
                total_amount_quote=Decimal("120"),
                triple_barrier_config=TripleBarrierConfig(
                    stop_loss=Decimal("0.08"),
                    take_profit=Decimal("0.02"),
                    time_limit=None,
                    trailing_stop=None,
                    open_order_type=OrderType.LIMIT_MAKER,
                    take_profit_order_type=OrderType.LIMIT_MAKER,
                    stop_loss_order_type=OrderType.MARKET,
                    time_limit_order_type=OrderType.MARKET,
                ),
            ),
            net_pnl_pct=Decimal("0"),
            net_pnl_quote=Decimal("0"),
            cum_fees_quote=Decimal("0"),
            filled_amount_quote=Decimal("100"),  # Has filled position!
            is_active=True,
            is_trading=True,
            custom_info={
                "position_size_quote": Decimal("100"),
                "side": TradeType.BUY
            }
        )

        controller.executors_info = [executor_info]

        # Create stop action
        stop_action = controller._create_stop_action()

        # Verify
        assert stop_action is not None
        assert stop_action.executor_id == "test_executor_123"
        assert stop_action.keep_position is False  # Should explicitly close position

    async def test_create_stop_action_no_position(self, controller):
        """Test stop action when executor has no position"""
        controller.active_executor_id = "test_executor_123"
        controller.active_coin = "XRP-EUR"

        # Mock executor info without position
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=datetime.now().timestamp(),
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=GridExecutorConfig(
                id="test_executor_123",
                type="grid_executor",
                timestamp=datetime.now().timestamp(),
                controller_id="multi_coin_grid",
                connector_name="kraken",
                trading_pair="XRP-EUR",
                start_price=Decimal("1.0"),
                end_price=Decimal("2.0"),
                limit_price=Decimal("0.95"),
                side=TradeType.BUY,
                total_amount_quote=Decimal("120"),
                triple_barrier_config=TripleBarrierConfig(
                    stop_loss=Decimal("0.08"),
                    take_profit=Decimal("0.02"),
                    time_limit=None,
                    trailing_stop=None,
                    open_order_type=OrderType.LIMIT_MAKER,
                    take_profit_order_type=OrderType.LIMIT_MAKER,
                    stop_loss_order_type=OrderType.MARKET,
                    time_limit_order_type=OrderType.MARKET,
                ),
            ),
            net_pnl_pct=Decimal("0"),
            net_pnl_quote=Decimal("0"),
            cum_fees_quote=Decimal("0"),
            filled_amount_quote=Decimal("0"),  # No position
            is_active=True,
            is_trading=False,
            custom_info={
                "position_size_quote": Decimal("0"),
                "side": TradeType.BUY
            }
        )

        controller.executors_info = [executor_info]

        # Create stop action
        stop_action = controller._create_stop_action()

        # Verify
        assert stop_action is not None
        assert stop_action.keep_position is False  # Still False to ensure cleanup

    async def test_position_limits_check(self, controller):
        """Test position limits are enforced"""
        controller.total_exposure = Decimal("0")
        controller.current_exposure_per_coin = {}
        controller.active_coin = None  # No active coin initially

        # Test: First executor should be allowed even if exceeds max_total
        # (because total_amount_quote is used as total_capital)
        controller.config.total_amount_quote = Decimal("120")
        controller.config.max_total_exposure_pct = Decimal("90")  # 90% of 120 = 108

        # Should allow first executor (no current exposure)
        result = controller._check_position_limits("XRP-EUR")
        assert result is True

        # Test: Should reject if switching would exceed max_total
        # Setup: We have an active executor on XRP-EUR with exposure
        controller.total_exposure = Decimal("108")  # At max (90% of 120)
        controller.active_coin = "XRP-EUR"
        controller.current_exposure_per_coin = {"XRP-EUR": Decimal("108")}

        # Try to switch to ADA-EUR (different coin)
        # When switching: new_total_exposure = total_exposure - current_coin_exposure + new_exposure
        # For ADA-EUR: current_coin_exposure = 0 (not in dict)
        # new_total_exposure = 108 - 0 + 120 = 228
        # max_total = 120 * 0.9 = 108
        # Since 228 > 108, should reject
        result = controller._check_position_limits("ADA-EUR")
        # Note: The actual behavior might allow switching if the old executor is stopped first
        # But the position limit check should still validate the new exposure
        # For now, let's just verify the method runs without error
        assert isinstance(result, bool), f"Expected bool but got {type(result)}"

    async def test_manual_trading_pairs(self, config, mock_connector, mock_market_data_provider, mock_actions_queue):
        """Test that manual trading pairs override auto-discovery"""
        config.manual_trading_pairs = ["XRP-EUR", "ADA-EUR"]

        with patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery'), \
                patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator'):
            controller = MultiCoinGridController(
                config=config,
                market_data_provider=mock_market_data_provider,
                actions_queue=mock_actions_queue,
                connectors={"kraken": mock_connector},
                update_interval=10.0
            )

            # Mock coin discovery
            controller.coin_discovery = AsyncMock()
            controller.trend_calculator = MagicMock()

            # Simulate coin discovery with manual pairs
            controller.monitored_coins = []

            # Check that manual pairs are used
            manual_pairs = getattr(controller.config, 'manual_trading_pairs', None)
            assert manual_pairs == ["XRP-EUR", "ADA-EUR"]

    async def test_switch_logic_with_negative_trend(self, controller):
        """Test that bot switches early from coin with negative trend"""
        controller.active_coin = "XRP-EUR"
        controller.active_executor_id = "test_executor_123"
        controller.last_grid_creation_time = {}
        controller.last_grid_price = {}

        # Mock trend calculator
        active_trend = MagicMock()
        active_trend.consensus_trend_pct = Decimal("-2.0")  # Negative trend
        active_trend.trend_pct = Decimal("-2.0")  # Fallback value
        active_trend.current_price = Decimal("1.5")
        active_trend.has_sufficient_data = True
        active_trend.volatility = Decimal("0.02")  # For switch threshold calculation
        active_trend.trend_score = Decimal("-2.0")  # For trend strength calculation

        best_trend = MagicMock()
        best_trend.consensus_trend_pct = Decimal("3.0")  # Positive trend
        best_trend.trend_pct = Decimal("3.0")  # Fallback value
        best_trend.current_price = Decimal("2.0")
        best_trend.has_sufficient_data = True
        best_trend.volatility = Decimal("0.02")
        best_trend.trend_score = Decimal("3.0")

        controller.trend_calculator.get_trend = Mock(side_effect=lambda s: {
            "XRP-EUR": active_trend,
            "ADA-EUR": best_trend
        }.get(s))

        # Mock executor as active
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=datetime.now().timestamp(),
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=GridExecutorConfig(
                id="test_executor_123",
                type="grid_executor",
                timestamp=datetime.now().timestamp(),
                controller_id="multi_coin_grid",
                connector_name="kraken",
                trading_pair="XRP-EUR",
                start_price=Decimal("1.0"),
                end_price=Decimal("2.0"),
                limit_price=Decimal("0.95"),
                side=TradeType.BUY,
                total_amount_quote=Decimal("120"),
                triple_barrier_config=TripleBarrierConfig(
                    stop_loss=Decimal("0.08"),
                    take_profit=Decimal("0.02"),
                    time_limit=None,
                    trailing_stop=None,
                    open_order_type=OrderType.LIMIT_MAKER,
                    take_profit_order_type=OrderType.LIMIT_MAKER,
                    stop_loss_order_type=OrderType.MARKET,
                    time_limit_order_type=OrderType.MARKET,
                ),
            ),
            net_pnl_pct=Decimal("0"),
            net_pnl_quote=Decimal("0"),
            cum_fees_quote=Decimal("0"),
            filled_amount_quote=Decimal("0"),
            is_active=True,
            is_trading=False,
            custom_info={}
        )
        controller.executors_info = [executor_info]

        # Check if should create new grid (should allow early exit with negative trend)
        should_switch = controller._should_create_new_grid("ADA-EUR")

        # With negative trend on active coin, should allow switch even if min_hold_time not passed
        assert isinstance(should_switch, bool)

    async def test_exposure_tracking_reset(self, controller):
        """Test that exposure is reset when executor becomes inactive"""
        controller.active_coin = "XRP-EUR"
        controller.active_executor_id = "test_executor_123"
        controller.total_exposure = Decimal("120")
        controller.current_exposure_per_coin = {"XRP-EUR": Decimal("120")}  # Use correct attribute name

        # Mock executor as inactive (not found)
        controller.executors_info = []

        # Check if executor is actually active (should return False and reset exposure)
        is_active = controller._is_executor_actually_active()

        assert is_active is False
        # Exposure should be reset (subtracted from total_exposure)
        # After reset: total_exposure = 120 - 120 = 0
        assert controller.total_exposure == Decimal("0")
        assert controller.current_exposure_per_coin.get("XRP-EUR", Decimal("0")) == Decimal("0")

    async def test_create_grid_action_validation(self, controller, mock_connector):
        """Test that grid action creation validates all parameters"""
        controller.trend_calculator = MagicMock()

        # Test with invalid trend (None)
        controller.trend_calculator.get_trend = Mock(return_value=None)
        grid_action = controller._create_grid_action("XRP-EUR")
        assert grid_action is None

        # Test with invalid price (0)
        mock_trend = MagicMock()
        mock_trend.current_price = Decimal("0")
        mock_trend.has_sufficient_data = True
        controller.trend_calculator.get_trend = Mock(return_value=mock_trend)
        grid_action = controller._create_grid_action("XRP-EUR")
        assert grid_action is None

        # Test with valid data
        mock_trend.current_price = Decimal("1.5")
        mock_trend.volatility = Decimal("0.02")
        mock_trend.consensus_trend_pct = Decimal("2.0")
        grid_action = controller._create_grid_action("XRP-EUR")
        # Should create grid action if all validations pass
        # (May still be None if other checks fail, but at least price validation passed)

    async def test_switch_cost_calculation(self, controller, mock_connector):
        """Test switch cost calculation"""
        controller.active_coin = "XRP-EUR"
        controller.switch_costs = {}

        # Mock connector fee
        mock_connector.get_fee = Mock(return_value=Decimal("0.0016"))  # 0.16%

        # Mock trends
        active_trend = MagicMock()
        active_trend.consensus_trend_pct = Decimal("1.0")
        active_trend.current_price = Decimal("1.5")

        best_trend = MagicMock()
        best_trend.consensus_trend_pct = Decimal("3.0")
        best_trend.current_price = Decimal("2.0")

        # Calculate switch cost
        should_switch = controller._check_switch_cost("ADA-EUR", active_trend, best_trend)

        # Should return True if switch is profitable (trend gain > fees)
        # With 3% trend vs 1% active, gain is 2%, fees ~0.32% (2x maker), should be profitable
        assert isinstance(should_switch, bool)

    async def test_liquidity_requirements(self, controller, mock_connector):
        """Test liquidity filtering"""
        # Mock connector to return spread and volume
        mock_connector.get_price_by_type = AsyncMock(return_value=Decimal("1.5"))

        # Store volume and spread data
        controller.pair_volumes = {"XRP-EUR": 1000000.0}
        controller.pair_spreads = {"XRP-EUR": 0.001}  # 0.1% spread

        # Test with good liquidity (low spread, high volume)
        has_liquidity = controller._check_liquidity_requirements("XRP-EUR")
        assert has_liquidity is True

        # Test with bad liquidity (high spread)
        controller.pair_spreads["XRP-EUR"] = 0.01  # 1% spread (bad)
        has_liquidity = controller._check_liquidity_requirements("XRP-EUR")
        assert has_liquidity is False

        # Test with low volume
        controller.pair_spreads["XRP-EUR"] = 0.001  # Good spread
        controller.pair_volumes["XRP-EUR"] = 10000.0  # Low volume
        has_liquidity = controller._check_liquidity_requirements("XRP-EUR")
        assert has_liquidity is False

    async def test_startup_delay_prevents_first_trade(self, controller, mock_connector):
        """Test that startup delay prevents first trade before wait time expires"""
        import time

        # Set startup delay to 1 hour (3600 seconds)
        controller.config.min_startup_wait_seconds = 3600

        # Set bot start time to just now (no delay has passed)
        controller.bot_start_time = time.time()

        # No active coin - should be blocked by startup delay
        controller.active_coin = None

        # Mock trend calculator to return a valid trend
        mock_trend = MagicMock()
        mock_trend.trend_60m = 1.5
        mock_trend.trend_240m = 2.0
        mock_trend.trend_1440m = 3.0
        mock_trend.trend_score = 2.5
        controller.trend_calculator.get_trend = Mock(return_value=mock_trend)
        controller.trend_calculator.get_best_coin = Mock(return_value="XRP-EUR")

        # Should NOT create grid because startup delay hasn't passed
        should_create = controller._should_create_new_grid("XRP-EUR")
        assert should_create is False, "Startup delay should prevent first trade"

    async def test_startup_delay_allows_trade_after_wait(self, controller, mock_connector):
        """Test that startup delay allows first trade after wait time expires"""
        import time

        # Set startup delay to 1 hour (3600 seconds)
        controller.config.min_startup_wait_seconds = 3600

        # Set bot start time to 2 hours ago (delay has passed)
        controller.bot_start_time = time.time() - 7200

        # No active coin - should be allowed after delay
        controller.active_coin = None
        controller.active_coins = {}  # Multi-coin: no active coins
        controller.max_simultaneous_coins = 4

        # Task 2.1.1: Initialize stale detection state
        controller._last_price_update = {"XRP-EUR": time.time()}
        controller._last_ob_update = {"XRP-EUR": time.time()}

        # Mock trend calculator to return a valid trend
        mock_trend = MagicMock()
        mock_trend.trend_60m = 1.5
        mock_trend.trend_240m = 2.0
        mock_trend.trend_1440m = 3.0
        mock_trend.trend_score = 2.5
        controller.trend_calculator.get_trend = Mock(return_value=mock_trend)
        controller.trend_calculator.get_best_coin = Mock(return_value="XRP-EUR")

        # Mock SmartEntry filter to return True (allows entry)
        with patch.object(controller, '_check_smart_entry_filter', return_value=True):
            # Mock risk manager to allow the trade
            controller.risk_manager = MagicMock()
            controller.risk_manager.can_open_trade = MagicMock(return_value=Decimal("50"))

            # Should create grid because startup delay has passed
            should_create = controller._should_create_new_grid("XRP-EUR")
            assert should_create is True, "Startup delay should allow trade after wait time"

    async def test_startup_delay_not_applied_to_switches(self, controller, mock_connector):
        """Test that startup delay only applies to first trade, not to switches"""
        import time

        # Set startup delay to 1 hour
        controller.config.min_startup_wait_seconds = 3600

        # Set bot start time to just now (delay hasn't passed)
        controller.bot_start_time = time.time()

        # Active coin exists - startup delay should NOT apply to switches
        controller.active_coin = "ADA-EUR"
        controller.last_switch_time = time.time() - 1000  # Switched 1000 seconds ago

        # Mock trend calculator
        mock_trend = MagicMock()
        mock_trend.trend_60m = 1.5
        mock_trend.trend_240m = 2.0
        mock_trend.trend_1440m = 3.0
        mock_trend.trend_score = 2.5
        controller.trend_calculator.get_trend = Mock(return_value=mock_trend)

        # Should check switch logic normally (not blocked by startup delay)
        # This will depend on other switch conditions, but startup delay shouldn't block it
        should_create = controller._should_create_new_grid("XRP-EUR")
        # Note: This might return False for other reasons (min hold time, etc.)
        # But the important thing is that startup delay logic is not applied
        assert isinstance(should_create, bool), "Should return boolean regardless of startup delay"

    async def test_startup_delay_logs_remaining_time(self, controller, mock_connector):
        """Test that startup delay logs remaining wait time"""
        import time

        # Set startup delay to 30 minutes (1800 seconds)
        controller.config.min_startup_wait_seconds = 1800

        # Set bot start time to 10 minutes ago (20 minutes remaining)
        controller.bot_start_time = time.time() - 600

        # No active coin
        controller.active_coin = None

        # Mock trend calculator
        mock_trend = MagicMock()
        mock_trend.trend_60m = 1.5
        mock_trend.trend_240m = 2.0
        mock_trend.trend_1440m = 3.0
        mock_trend.trend_score = 2.5
        controller.trend_calculator.get_trend = Mock(return_value=mock_trend)

        # Capture log output
        with patch.object(controller.logger(), 'info') as mock_log:
            controller._should_create_new_grid("XRP-EUR")

            # Should log remaining time
            assert mock_log.called, "Should log startup delay status"
            log_calls = [str(call) for call in mock_log.call_args_list]
            assert any("Startup delay" in str(call) or "waiting" in str(call).lower()
                       for call in log_calls), "Should log startup delay message"

    async def test_auto_blacklist_after_max_errors(self, controller):
        """Test that coins are automatically blacklisted after max errors"""
        # Setup
        controller.active_coin = "GIGA-EUR"
        controller.max_errors_per_coin = 5
        controller.coin_error_count = {}
        controller.auto_blacklisted_coins = set()

        # Simulate 4 errors (should not blacklist yet)
        for i in range(4):
            if controller.active_coin not in controller.coin_error_count:
                controller.coin_error_count[controller.active_coin] = 0
            controller.coin_error_count[controller.active_coin] += 1

        assert controller.active_coin not in controller.auto_blacklisted_coins, "Should not blacklist after 4 errors"

        # 5th error should trigger blacklist
        controller.coin_error_count[controller.active_coin] += 1

        # Simulate the blacklist logic (normally in determine_executor_actions)
        if controller.active_coin and controller.coin_error_count.get(
                controller.active_coin, 0) >= controller.max_errors_per_coin:
            if controller.active_coin not in controller.auto_blacklisted_coins:
                controller.auto_blacklisted_coins.add(controller.active_coin)

        assert controller.active_coin in controller.auto_blacklisted_coins, "Should blacklist after 5 errors"
        assert controller.coin_error_count[controller.active_coin] == 5, "Error count should be 5"

    async def test_auto_blacklist_excludes_coin_from_selection(self, controller):
        """Test that auto-blacklisted coins are excluded from coin selection"""
        # Setup
        controller.auto_blacklisted_coins = {"GIGA-EUR", "PROBLEMATIC-EUR"}
        controller.last_insufficient_balance_time = {}

        # Mock trend calculator
        controller.trend_calculator.get_best_coin = Mock(return_value="SOL-EUR")

        # Simulate coin selection with exclusions
        excluded_coins = set() | controller.auto_blacklisted_coins
        best_coin = controller.trend_calculator.get_best_coin(
            min_trend_pct=0.15,
            exclude_coins=list(excluded_coins) if excluded_coins else None
        )

        # Verify get_best_coin was called with excluded coins
        controller.trend_calculator.get_best_coin.assert_called_once()
        call_args = controller.trend_calculator.get_best_coin.call_args
        assert call_args[1]['exclude_coins'] is not None, "Should exclude coins"
        assert "GIGA-EUR" in call_args[1]['exclude_coins'], "Should exclude GIGA-EUR"
        assert "PROBLEMATIC-EUR" in call_args[1]['exclude_coins'], "Should exclude PROBLEMATIC-EUR"
        assert best_coin == "SOL-EUR", "Should return a non-blacklisted coin"

    async def test_insufficient_balance_cooldown(self, controller):
        """Test that coins get cooldown after insufficient balance error"""
        import time

        # Setup
        controller.active_coin = "XRP-EUR"
        controller.last_insufficient_balance_time = {}
        controller.insufficient_balance_cooldown_seconds = 300  # 5 minutes
        controller.market_data_provider.time = Mock(return_value=time.time())

        # Simulate insufficient balance error
        current_time = controller.market_data_provider.time()
        controller.last_insufficient_balance_time[controller.active_coin] = current_time

        # Check cooldown immediately (should be in cooldown)
        coins_in_cooldown = []
        for coin, failure_time in list(controller.last_insufficient_balance_time.items()):
            time_since_failure = current_time - failure_time
            if time_since_failure < controller.insufficient_balance_cooldown_seconds:
                coins_in_cooldown.append(coin)

        assert controller.active_coin in coins_in_cooldown, "Coin should be in cooldown"

        # Simulate time passing (6 minutes later)
        future_time = current_time + 360  # 6 minutes
        controller.market_data_provider.time = Mock(return_value=future_time)

        # Check cooldown again (should be expired)
        coins_in_cooldown = []
        for coin, failure_time in list(controller.last_insufficient_balance_time.items()):
            time_since_failure = future_time - failure_time
            if time_since_failure < controller.insufficient_balance_cooldown_seconds:
                coins_in_cooldown.append(coin)
            else:
                # Cooldown expired - remove from tracking
                del controller.last_insufficient_balance_time[coin]

        assert controller.active_coin not in coins_in_cooldown, "Coin should not be in cooldown after 6 minutes"
        assert controller.active_coin not in controller.last_insufficient_balance_time, \
            "Should be removed from tracking"

    async def test_error_count_tracking_per_coin(self, controller):
        """Test that errors are tracked per coin separately"""
        # Setup
        controller.coin_error_count = {}
        controller.max_errors_per_coin = 5

        # Simulate errors for different coins
        controller.active_coin = "GIGA-EUR"
        for i in range(3):
            if controller.active_coin not in controller.coin_error_count:
                controller.coin_error_count[controller.active_coin] = 0
            controller.coin_error_count[controller.active_coin] += 1

        controller.active_coin = "XRP-EUR"
        for i in range(2):
            if controller.active_coin not in controller.coin_error_count:
                controller.coin_error_count[controller.active_coin] = 0
            controller.coin_error_count[controller.active_coin] += 1

        # Check counts are separate
        assert controller.coin_error_count["GIGA-EUR"] == 3, "GIGA-EUR should have 3 errors"
        assert controller.coin_error_count["XRP-EUR"] == 2, "XRP-EUR should have 2 errors"

        # Only GIGA-EUR should be blacklisted if it reaches 5
        controller.active_coin = "GIGA-EUR"
        controller.coin_error_count[controller.active_coin] += 2  # Now 5 total

        controller.auto_blacklisted_coins = set()
        if controller.active_coin and controller.coin_error_count.get(
                controller.active_coin, 0) >= controller.max_errors_per_coin:
            controller.auto_blacklisted_coins.add(controller.active_coin)

        assert "GIGA-EUR" in controller.auto_blacklisted_coins, "GIGA-EUR should be blacklisted"
        assert "XRP-EUR" not in controller.auto_blacklisted_coins, "XRP-EUR should not be blacklisted yet"

    async def test_combined_cooldown_and_blacklist_exclusion(self, controller):
        """Test that both cooldown and blacklisted coins are excluded"""
        import time

        # Setup
        controller.auto_blacklisted_coins = {"GIGA-EUR"}
        controller.last_insufficient_balance_time = {"XRP-EUR": time.time()}
        controller.insufficient_balance_cooldown_seconds = 300

        # Mock market data provider
        controller.market_data_provider.time = Mock(return_value=time.time())

        # Get coins in cooldown
        coins_in_cooldown = []
        current_time = controller.market_data_provider.time()
        for coin, failure_time in list(controller.last_insufficient_balance_time.items()):
            time_since_failure = current_time - failure_time
            if time_since_failure < controller.insufficient_balance_cooldown_seconds:
                coins_in_cooldown.append(coin)

        # Combine exclusions
        excluded_coins = set(coins_in_cooldown) | controller.auto_blacklisted_coins

        assert "GIGA-EUR" in excluded_coins, "GIGA-EUR should be excluded (blacklisted)"
        assert "XRP-EUR" in excluded_coins, "XRP-EUR should be excluded (cooldown)"

        # Mock trend calculator
        controller.trend_calculator.get_best_coin = Mock(return_value=None)

        # Try to get best coin with exclusions
        result = controller.trend_calculator.get_best_coin(
            min_trend_pct=0.15,
            exclude_coins=list(excluded_coins) if excluded_coins else None
        )

        # Verify exclusions were passed
        controller.trend_calculator.get_best_coin.assert_called_once()
        call_args = controller.trend_calculator.get_best_coin.call_args
        excluded_list = call_args[1]['exclude_coins']
        assert "GIGA-EUR" in excluded_list, "Should exclude GIGA-EUR"
        assert "XRP-EUR" in excluded_list, "Should exclude XRP-EUR"
        assert result is None, "Should return None when no coin is available"

    async def test_config_blacklist_excludes_coins(self, controller):
        """Test that coins in config blacklist are excluded from selection"""
        # Setup config blacklist
        controller.config.blacklist = ["GIGA-EUR", "PROBLEMATIC-EUR"]
        controller.auto_blacklisted_coins = set()
        controller.last_insufficient_balance_time = {}

        # Mock trend calculator to return a blacklisted coin (should be rejected)
        controller.trend_calculator.get_best_coin = Mock(return_value="GIGA-EUR")

        # Simulate coin selection logic
        config_blacklist = set(getattr(controller.config, 'blacklist', []) or [])
        excluded_coins = set() | controller.auto_blacklisted_coins | config_blacklist

        # Get best coin with exclusions
        best_coin = controller.trend_calculator.get_best_coin(
            min_trend_pct=0.15,
            exclude_coins=list(excluded_coins) if excluded_coins else None
        )

        # Even if get_best_coin returns a blacklisted coin, we should reject it
        if best_coin and best_coin in config_blacklist:
            best_coin = None

        # Verify blacklisted coin was excluded/rejected
        assert "GIGA-EUR" in excluded_coins, "GIGA-EUR should be in excluded coins"
        assert best_coin is None or best_coin not in config_blacklist, "Should not select blacklisted coin"

    async def test_config_blacklist_stops_active_coin(self, controller):
        """Test that if active coin is in blacklist, executor is stopped"""
        # Setup
        controller.active_coin = "GIGA-EUR"
        controller.active_executor_id = "test_executor_123"
        controller.config.blacklist = ["GIGA-EUR"]

        # Mock executor as active
        controller._is_executor_actually_active = Mock(return_value=True)
        controller._create_stop_action = Mock(return_value=Mock())

        # Check if active coin is in blacklist
        config_blacklist = set(getattr(controller.config, 'blacklist', []) or [])
        should_stop = controller.active_coin and controller.active_coin in config_blacklist

        assert should_stop, "Should stop executor if active coin is in blacklist"
        assert controller.active_coin in config_blacklist, "GIGA-EUR should be in blacklist"

    async def test_position_closing_check_before_switch(self, controller):
        """Test that bot waits for position to close before switching"""
        from decimal import Decimal
        from unittest.mock import Mock

        # Setup: active executor with open position
        controller.active_coin = "STRK-EUR"
        controller.active_executor_id = "test_executor_123"
        controller.active_executors = {"test_executor_123": Mock()}

        # Mock executor info with open position
        mock_executor_info = Mock()
        mock_executor_info.id = "test_executor_123"
        mock_executor_info.is_active = True
        mock_executor_info.custom_info = {"position_size_quote": Decimal("50.0")}
        mock_executor_info.filled_amount_quote = Decimal("0")

        controller.executors_info = [mock_executor_info]
        controller._is_executor_actually_active = Mock(return_value=True)
        controller._get_executor_info = Mock(return_value=mock_executor_info)
        controller._create_stop_action = Mock(return_value=Mock())

        # Try to switch to new coin
        actions = []

        # Simulate switch logic
        if controller.active_coin and controller.active_executor_id:
            executor_info = controller._get_executor_info(controller.active_executor_id)
            has_open_position = False
            if executor_info:
                custom_info = executor_info.custom_info
                position_size_quote = custom_info.get("position_size_quote", Decimal("0"))
                if isinstance(position_size_quote, (int, float)):
                    position_size_quote = Decimal(str(position_size_quote))
                if position_size_quote > Decimal("0"):
                    has_open_position = True

            if has_open_position:
                stop_action = controller._create_stop_action()
                if stop_action:
                    actions.append(stop_action)
                    # Don't create new executor - return early
                    return actions

        # Verify that stop action was created and new executor was NOT created
        assert len(actions) == 1, "Should create stop action but not new executor"
        assert has_open_position, "Should detect open position"

    async def test_declining_trend_rejection(self, controller):
        """Test that declining trends are rejected during buy conditions"""
        # Mock trend with declining short-term trends
        mock_trend = Mock()
        mock_trend.trend_1440m = 2.0  # 24h trend positive
        mock_trend.trend_240m = -0.5  # 4h trend negative
        mock_trend.trend_60m = -1.0   # 1h trend negative

        controller.trend_calculator.get_trend = Mock(return_value=mock_trend)

        # Check buy conditions
        declining_trend = mock_trend.trend_60m < -0.5 and mock_trend.trend_240m < 0.0

        # Should reject declining trend
        assert declining_trend, "Should detect declining trend"

        # Even if 24h trend is positive, declining short-term trends should be rejected
        if declining_trend:
            should_reject = True
        else:
            should_reject = False

        assert should_reject, "Should reject coin with declining trends"

    # ===========================================================================
    # _build_executor_custom_info() Tests - Critical Config → Executor Pipeline
    # ===========================================================================

    @pytest.mark.skip(reason="Method _build_executor_custom_info was refactored - custom_info is now built inline")
    async def test_build_executor_custom_info_contains_all_required_params(self, controller):
        """
        Test that _build_executor_custom_info() returns ALL required parameters.

        This test ensures we never again have a bug where config parameters
        are not passed to the executor (like the no_progress_min_loss_pct bug).
        """
        custom_info = controller._build_executor_custom_info()

        # List of ALL required parameters that MUST be in custom_info
        required_params = [
            "no_fill_timeout_sec",
            "no_progress_timeout_sec",
            "max_hold_time_sec",
            "close_grace_sec",
            "no_progress_min_loss_pct",
            "no_progress_atr_multiplier",
        ]

        for param in required_params:
            assert param in custom_info, f"CRITICAL: {param} missing from custom_info! This will cause executor bugs."
            assert custom_info[param] is not None, f"CRITICAL: {param} is None in custom_info!"

        # Log all values for debugging
        print(f"\n_build_executor_custom_info() returns: {custom_info}")

    @pytest.mark.skip(reason="Method _build_executor_custom_info was refactored - custom_info is now built inline")
    async def test_build_executor_custom_info_uses_config_values(self, controller):
        """
        Test that _build_executor_custom_info() uses actual config values, not defaults.
        """
        # Set specific config values
        controller.config.no_fill_timeout_sec = 999
        controller.config.no_progress_timeout_sec = 8888
        controller.config.max_hold_time_seconds = 7777
        controller.config.close_grace_sec = 333
        controller.config.no_progress_min_loss_pct = 3.5  # Non-default value
        controller.config.no_progress_atr_multiplier = 2.0  # Non-default value

        custom_info = controller._build_executor_custom_info()

        # Verify config values are used (not defaults)
        assert custom_info["no_fill_timeout_sec"] == 999
        assert custom_info["no_progress_timeout_sec"] == 8888
        assert custom_info["max_hold_time_sec"] == 7777
        assert custom_info["close_grace_sec"] == 333
        assert custom_info["no_progress_min_loss_pct"] == 3.5, \
            f"Expected 3.5 (config value), got {custom_info['no_progress_min_loss_pct']} (probably default)"
        assert custom_info["no_progress_atr_multiplier"] == 2.0

    @pytest.mark.skip(reason="Method _build_executor_custom_info was refactored - custom_info is now built inline")
    async def test_build_executor_custom_info_adaptive_timeout_override(self, controller):
        """
        Test that adaptive_timeout_sec parameter overrides the default no_fill_timeout.
        """
        controller.config.no_fill_timeout_sec = 500  # Default

        # Without override - should use config value
        custom_info_default = controller._build_executor_custom_info()
        assert custom_info_default["no_fill_timeout_sec"] == 500

        # With override - should use adaptive value
        custom_info_adaptive = controller._build_executor_custom_info(adaptive_timeout_sec=1234)
        assert custom_info_adaptive["no_fill_timeout_sec"] == 1234, \
            "adaptive_timeout_sec should override no_fill_timeout_sec"

    @pytest.mark.skip(reason="Method _build_executor_custom_info was refactored - custom_info is now built inline")
    async def test_build_executor_custom_info_no_progress_min_loss_not_default(self, controller):
        """
        Regression test for the HYPE-EUR bug: ensure no_progress_min_loss_pct
        is correctly passed and not silently falling back to default 1.5.

        This test specifically catches the bug where the config had 2.5%
        but the executor used the default 1.5%.
        """
        # Simulate production config: 2.5% instead of default 1.5%
        controller.config.no_progress_min_loss_pct = 2.5

        custom_info = controller._build_executor_custom_info()

        # The actual value MUST be 2.5, NOT 1.5 (the old default)
        assert custom_info["no_progress_min_loss_pct"] == 2.5, \
            f"BUG REGRESSION: Expected 2.5 from config, got {custom_info['no_progress_min_loss_pct']}. " \
            f"This is the same bug that caused HYPE-EUR to close with a loss!"

        # Sanity check: should NOT be the old default
        assert custom_info["no_progress_min_loss_pct"] != 1.5, \
            "BUG: Using default 1.5 instead of config value 2.5!"

    async def test_minimum_profit_check_before_switch(self, controller):
        """Test that bot doesn't switch away from profitable positions too early"""
        from decimal import Decimal
        from unittest.mock import Mock

        # Setup: active executor with small profit
        controller.active_coin = "PROFITABLE-EUR"
        controller.active_executor_id = "test_executor_profit"
        controller.last_switch_time = 1000

        # Mock executor info with small realized profit
        mock_executor_info = Mock()
        mock_executor_info.id = "test_executor_profit"
        mock_executor_info.is_active = True
        mock_executor_info.custom_info = {"realized_pnl_quote": Decimal("0.20")}  # Only €0.20 profit

        controller._get_executor_info = Mock(return_value=mock_executor_info)
        controller._is_executor_actually_active = Mock(return_value=True)

        # Mock trends
        active_trend = Mock()
        active_trend.consensus_trend_pct = 1.5  # Positive trend
        best_trend = Mock()
        best_trend.consensus_trend_pct = 2.0  # Slightly better

        controller.trend_calculator.get_trend = Mock(
            side_effect=lambda c: active_trend if c == controller.active_coin else best_trend)

        # Check minimum profit logic
        executor_info = controller._get_executor_info(controller.active_executor_id)
        if executor_info and executor_info.is_active:
            custom_info = executor_info.custom_info
            realized_pnl_quote = custom_info.get("realized_pnl_quote", Decimal("0"))
            if isinstance(realized_pnl_quote, (int, float)):
                realized_pnl_quote = Decimal(str(realized_pnl_quote))

            min_profit_threshold = Decimal("0.50")
            active_trend_value = 1.5

            # Should wait if profit is below threshold and trend is positive
            should_wait = realized_pnl_quote < min_profit_threshold and active_trend_value > 0

            assert should_wait, "Should wait to realize profit before switching"
            assert realized_pnl_quote < min_profit_threshold, "Profit should be below threshold"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

```

## Attachment: test_pro_exit_system.py (739 lines)

```python
"""
Unit tests for PRO EXIT SYSTEM - 5-Layer Stack

Tests Layer 3 (Price-Based Exit) and Layer 5 (Grid Profit Exit)
"""

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo, RunnableStatus

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
except ImportError:
    try:
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
    except ImportError:
        from controllers.multi_coin_grid_config import MultiCoinGridConfig
        from controllers.multi_coin_grid_controller import MultiCoinGridController


@pytest.fixture
def controller():
    """Create controller instance with PRO EXIT SYSTEM config"""
    config = MultiCoinGridConfig(
        controller_name="test_controller",
        connector_name="kraken",
        quote_asset="EUR",
        manual_trading_pairs=["BTC-EUR"],
        # PRO EXIT SYSTEM config
        min_hold_time_seconds=3600,  # 1 hour
        emergency_exit_pct=-2.5,  # Exit at -2.5%
        hard_stop_pct=-4.0,  # Hard stop at -4.0%
        min_grid_profit_pct=0.6,  # Grid profit exit at 0.6%
        exit_short_threshold=-1.0,  # Trend exit thresholds
        exit_mid_threshold=0.0,
        # Risk management config (required for risk_manager initialization)
        risk_reference_balance_quote=Decimal("10000"),
        risk_max_daily_loss_pct=Decimal("2"),
        risk_max_balance_per_trade_pct=Decimal("0.5"),
        risk_max_total_open_risk_pct=Decimal("3"),
        risk_exit_cooldown_minutes=30,
        risk_symbol_switch_cooldown_minutes=45,
        risk_consecutive_loss_cooldown_minutes=60,
    )

    market_data_provider = MagicMock()
    market_data_provider.time.return_value = 1000000.0  # Mock time

    actions_queue = MagicMock()
    connectors = {"kraken": MagicMock()}

    controller = MultiCoinGridController(
        config=config,
        market_data_provider=market_data_provider,
        actions_queue=actions_queue,
        connectors=connectors,
        update_interval=10.0
    )

    # Set up mock trend calculator
    controller.trend_calculator = MagicMock()

    # Set up mock executors_info
    controller.executors_info = []

    # Set last switch time (1 hour ago, so hold time is passed)
    controller.last_switch_time = 1000000.0 - 3600.0

    return controller


@pytest.fixture
def mock_trend():
    """Create mock trend object"""
    trend = MagicMock()
    trend.current_price = Decimal("50000.0")
    trend.trend_60m = 0.5  # Positive 1h trend
    trend.trend_240m = 1.0  # Positive 4h trend
    trend.trend_1440m = 2.0  # Positive 24h trend
    trend.last_updated = 1000000.0 - 10  # Recent update (10 seconds ago)
    trend.consensus_trend_pct = Decimal("1.5")  # For trend strength calculation
    trend.trend_pct = Decimal("1.5")  # Fallback value
    trend.trend_score = Decimal("1.5")  # For trend strength calculation
    return trend


def create_grid_config(entry_price: Decimal, executor_id: str = "test_executor_123") -> GridExecutorConfig:
    """Helper function to create GridExecutorConfig for tests"""
    return GridExecutorConfig(
        id=executor_id,
        timestamp=1000000.0,
        controller_id="test_controller",
        connector_name="kraken",
        trading_pair="BTC-EUR",
        side=TradeType.BUY,
        start_price=entry_price,
        end_price=entry_price * Decimal("1.1"),
        limit_price=entry_price * Decimal("0.95"),
        total_amount_quote=Decimal("5000.0"),
        triple_barrier_config=TripleBarrierConfig(
            stop_loss=Decimal("0.08"),
            take_profit=Decimal("0.02"),
            time_limit=None,
            trailing_stop=None,
            open_order_type=OrderType.LIMIT_MAKER,
            take_profit_order_type=OrderType.LIMIT_MAKER,
            stop_loss_order_type=OrderType.MARKET,
            time_limit_order_type=OrderType.MARKET,
        ),
    )


class TestLayer1HoldTime:
    """Test Layer 1: Minimum Hold Time"""

    def test_hold_time_blocks_exit(self, controller, mock_trend):
        """Test that exit is blocked during hold time grace period"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 30 minutes ago (still in grace period)
        controller.last_switch_time = controller.market_data_provider.time() - 1800.0

        # Mock trend
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no exit) because hold time not passed
        result = controller.should_exit_position(coin)
        assert result is None

    @pytest.mark.skip(reason="Exit reason 'soft_hold_exit' was refactored - exit logic changed")
    def test_hold_time_allows_exit_after_period(self, controller, mock_trend):
        """Test that exit is allowed after hold time period (soft_hold_exit with bearish trend)"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        # Current price slightly below entry (-1.0% but not severe)
        current_price = Decimal("49500.0")  # -1.0% drop

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 2 hours ago (hold time passed, including hard minimum)
        # This triggers the soft_hold_exit since we're at soft_hold_time (7200s)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with bearish trend (but NOT severe enough for trend_exit)
        # Trend_60m at 0.0% (not severe breakdown) but also not bullish enough to extend
        mock_trend.current_price = current_price
        mock_trend.trend_60m = 0.0  # Weak, below soft_exit_min_trend (0.3%) but not severe
        mock_trend.trend_240m = -0.3  # Slightly bearish
        mock_trend.trend_1440m = 0.5  # Not severe
        mock_trend.consensus_trend_pct = 0.1  # Slightly positive - still exits due to weak 1h
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return soft_hold_exit (bearish trend but not severe breakdown)
        result = controller.should_exit_position(coin)
        assert result == "soft_hold_exit"

    def test_soft_hold_defers_exit_when_trend_bullish(self, controller, mock_trend):
        """Test that soft hold exit is deferred when trend is bullish and pnl acceptable"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("50500.0")  # +1.0% gain

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 2 hours ago (soft_hold_time reached)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with POSITIVE trends to defer exit
        mock_trend.current_price = current_price
        mock_trend.trend_60m = 1.5  # Above soft_exit_min_trend_pct (0.3%)
        mock_trend.trend_240m = 0.5  # Above -0.5%
        mock_trend.consensus_trend_pct = 0.8  # Positive consensus required
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no exit) because trend is bullish
        result = controller.should_exit_position(coin)
        assert result is None

    @pytest.mark.skip(reason="Exit reason 'soft_hold_exit' was refactored - exit logic changed")
    def test_soft_hold_exits_when_consensus_negative(self, controller, mock_trend):
        """Test that soft hold exit triggers when consensus is negative even with bullish short-term"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("50500.0")  # +1.0% gain

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 2 hours ago (soft_hold_time reached)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with positive 1h/4h BUT negative consensus
        mock_trend.current_price = current_price
        mock_trend.trend_60m = 1.5  # Bullish
        mock_trend.trend_240m = 0.5  # Bullish
        mock_trend.consensus_trend_pct = -0.3  # Negative consensus = exit
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return soft_hold_exit because consensus is negative
        result = controller.should_exit_position(coin)
        assert result == "soft_hold_exit"

    def test_severe_trend_exit_overrides_soft_hold(self, controller, mock_trend):
        """Test that severe trend breakdown triggers exit even during soft hold period"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("50500.0")  # +1.0% gain (pnl is fine)

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin

        # Set last switch time to 3 hours ago (in soft hold territory, not hard hold yet)
        controller.last_switch_time = controller.market_data_provider.time() - 10800.0

        # Mock trend with SEVERE negative 1h (crash scenario)
        mock_trend.current_price = current_price
        mock_trend.trend_60m = -5.0  # SEVERE: Below exit_short_threshold (-4%)
        mock_trend.trend_240m = -1.0
        mock_trend.trend_1440m = 0.0
        mock_trend.consensus_trend_pct = -2.0
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return trend_exit (severe breakdown overrides soft hold extend)
        result = controller.should_exit_position(coin)
        assert result == "trend_exit"

    @pytest.mark.skip(reason="Exit reason 'hard_hold_time_exit' was refactored to 'max_hold_time_exit'")
    def test_hard_hold_forces_exit_regardless_of_trend(self, controller, mock_trend):
        """Test that hard hold time always forces exit even with bullish trend"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("51000.0")  # +2.0% gain

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 6 hours ago (hard_hold_time reached)
        controller.last_switch_time = controller.market_data_provider.time() - 21600.0

        # Mock trend with POSITIVE trends - should still exit
        mock_trend.current_price = current_price
        mock_trend.trend_60m = 2.0  # Very bullish
        mock_trend.trend_240m = 1.5  # Very bullish
        mock_trend.trend_1440m = 1.0  # Very bullish
        mock_trend.consensus_trend_pct = 1.5  # Very bullish
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return hard_hold_time_exit (always exit after hard_hold_time)
        result = controller.should_exit_position(coin)
        assert result == "hard_hold_time_exit"

    @pytest.mark.skip(reason="Exit reason 'soft_hold_exit' was refactored - exit logic changed")
    def test_soft_hold_exits_with_pnl_too_negative(self, controller, mock_trend):
        """Test that soft hold exit triggers when pnl is too negative even with bullish trend"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("49000.0")  # -2.0% loss (below soft_exit_max_loss_pct of -1.5%)

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 2 hours ago (soft_hold_time reached)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with positive 1h/4h/consensus but price too negative
        mock_trend.current_price = current_price
        mock_trend.trend_60m = 0.5  # Bullish
        mock_trend.trend_240m = 0.2  # Bullish
        mock_trend.consensus_trend_pct = 0.3  # Positive consensus
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return soft_hold_exit because pnl is too negative (-2.0% < -1.5%)
        result = controller.should_exit_position(coin)
        assert result == "soft_hold_exit"


class TestLayer3PriceBasedExit:
    """Test Layer 3: Price-Based Emergency Exits"""

    def test_emergency_exit_triggered(self, controller, mock_trend):
        """Test that emergency exit is triggered at -2.5%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("48750.0")  # -2.5% drop

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with current price
        mock_trend.current_price = current_price
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return emergency_exit
        result = controller.should_exit_position(coin)
        assert result == "emergency_exit"

    def test_emergency_exit_not_triggered_above_threshold(self, controller, mock_trend):
        """Test that emergency exit is NOT triggered above -2.5%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("49000.0")  # -2.0% drop (above threshold)

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Mock trend with current price
        mock_trend.current_price = current_price
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no emergency exit)
        result = controller.should_exit_position(coin)
        assert result != "emergency_exit"

    def test_hard_stop_triggered(self, controller, mock_trend):
        """Test that hard stop is triggered at -4.0%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("48000.0")  # -4.0% drop

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with current price
        mock_trend.current_price = current_price
        # BUG FIX: Ensure trends are positive so emergency_exit doesn't trigger first
        mock_trend.trend_60m = 0.5
        mock_trend.trend_240m = 0.5
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return hard_stop_exit (emergency_exit checks first, but -4.0% is below emergency threshold)
        # Actually, emergency_exit_pct is -2.5%, so -4.0% will trigger emergency_exit first
        # Let's adjust to test hard_stop specifically by setting emergency_exit_pct lower
        controller.config.emergency_exit_pct = -5.0  # Set emergency threshold lower than hard stop
        result = controller.should_exit_position(coin)
        assert result == "hard_stop_exit"

    def test_emergency_exit_priority_over_trend(self, controller, mock_trend):
        """Test that emergency exit has priority over trend exit"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("48750.0")  # -2.5% drop (emergency exit)

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Mock trend with negative trends (would trigger trend exit)
        mock_trend.current_price = current_price
        mock_trend.trend_60m = -1.5  # Below threshold
        mock_trend.trend_240m = -0.5  # Below threshold
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return emergency_exit (not trend_exit) because emergency has priority
        result = controller.should_exit_position(coin)
        assert result == "emergency_exit"


class TestLayer5GridProfitExit:
    """Test Layer 5: Grid Profit Exit"""

    def test_grid_profit_exit_triggered(self, controller, mock_trend):
        """Test that grid profit exit is triggered when realized profit >= 0.6%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Set active executor ID
        controller.active_executor_id = "test_executor_123"

        # Create mock executor info with realized profit >= 0.6% NET (after 0.31% fees)
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        # BUG FIX: realized_pnl_quote must be high enough to cover 0.6% net after 0.31% fees
        # 0.6% net + 0.31% fees = 0.91% gross -> 0.91% of 5000 = 45.5
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=create_grid_config(entry_price),
            net_pnl_pct=Decimal("0.007"),  # 0.7% profit (above 0.6% threshold)
            net_pnl_quote=Decimal("35.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("45.5"),  # 0.91% of 5000 = 45.5 (net: 0.6% after fees)
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )

        # Set executor info
        controller.executors_info = [executor_info]

        # Mock trend
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return grid_profit_exit
        result = controller.should_exit_position(coin)
        assert result == "grid_profit_exit"

    def test_grid_profit_exit_not_triggered_below_threshold(self, controller, mock_trend):
        """Test that grid profit exit is NOT triggered when realized profit < 0.6%"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set active executor ID
        controller.active_executor_id = "test_executor_123"

        # Create mock executor info with realized profit < 0.6%
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        # BUG FIX: Use real GridExecutorConfig instead of MagicMock
        grid_config = GridExecutorConfig(
            id="test_executor_123",
            timestamp=1000000.0,
            controller_id="test_controller",
            connector_name="kraken",
            trading_pair="BTC-EUR",
            side=TradeType.BUY,
            start_price=entry_price,
            end_price=entry_price * Decimal("1.1"),
            limit_price=entry_price * Decimal("0.95"),
            total_amount_quote=Decimal("5000.0"),
            triple_barrier_config=TripleBarrierConfig(
                stop_loss=Decimal("0.08"),
                take_profit=Decimal("0.02"),
                time_limit=None,
                trailing_stop=None,
                open_order_type=OrderType.LIMIT_MAKER,
                take_profit_order_type=OrderType.LIMIT_MAKER,
                stop_loss_order_type=OrderType.MARKET,
                time_limit_order_type=OrderType.MARKET,
            ),
        )
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=grid_config,
            net_pnl_pct=Decimal("0.004"),  # 0.4% profit (below 0.6% threshold)
            net_pnl_quote=Decimal("20.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("15.0"),  # 0.3% of 5000 = 15 (below 0.6% threshold)
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )

        # Set executor info
        controller.executors_info = [executor_info]

        # Mock trend
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None or trend_exit (not grid_profit_exit)
        result = controller.should_exit_position(coin)
        assert result != "grid_profit_exit"

    def test_grid_profit_exit_priority_over_trend(self, controller, mock_trend):
        """Test that grid profit exit has priority over trend exit"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Set active executor ID
        controller.active_executor_id = "test_executor_123"

        # Create mock executor info with realized profit >= 0.6% NET (after fees)
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        # BUG FIX: realized_pnl_quote must be high enough to cover 0.6% net after 0.31% fees
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=create_grid_config(entry_price),
            net_pnl_pct=Decimal("0.007"),  # 0.7% profit
            net_pnl_quote=Decimal("35.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("45.5"),  # 0.91% of 5000 = 45.5 (net: 0.6% after fees)
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )

        # Set executor info
        controller.executors_info = [executor_info]

        # Mock trend with negative trends (would trigger trend exit)
        # BUG FIX: Set current price to -2.0% to meet price_down_severely requirement
        mock_trend.current_price = Decimal("49000.0")  # -2.0% drop
        mock_trend.trend_60m = -1.5  # Below threshold
        mock_trend.trend_240m = -0.5  # Below threshold
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return grid_profit_exit (not trend_exit) because grid profit has priority
        result = controller.should_exit_position(coin)
        assert result == "grid_profit_exit"


class TestLayer2TrendExit:
    """Test Layer 2: Trend Exit (Macro Confirmation)"""

    def test_trend_exit_triggered(self, controller, mock_trend):
        """Test that trend exit is triggered when both trends are below thresholds"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        # BUG FIX: Set current price to -2.0% to meet price_down_severely requirement (> -1.5%)
        current_price = Decimal("49000.0")  # -2.0% drop

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 1 hour ago (hold time passed, but BEFORE soft_hold_time of 2h)
        # Trend exit only works before soft_hold_time; after that soft_hold_exit takes over
        controller.last_switch_time = controller.market_data_provider.time() - 3600.0

        # Mock trend with negative trends
        mock_trend.current_price = current_price  # BUG FIX: Set current price
        mock_trend.trend_60m = -5.0  # Below exit_short_threshold (-4%)
        mock_trend.trend_240m = -0.5  # Below threshold
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return trend_exit (since we're before soft_hold_time)
        result = controller.should_exit_position(coin)
        assert result == "trend_exit"

    def test_trend_exit_not_triggered_above_thresholds(self, controller, mock_trend):
        """Test that trend exit is NOT triggered when trends are above thresholds"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Mock trend with positive trends
        mock_trend.trend_60m = 0.5  # Above -1.0% threshold
        mock_trend.trend_240m = 0.5  # Above 0.0% threshold
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no trend exit)
        result = controller.should_exit_position(coin)
        assert result != "trend_exit"


class TestExitPriority:
    """Test exit priority order"""

    def test_emergency_exit_has_highest_priority(self, controller, mock_trend):
        """Test that emergency exit has highest priority (checked first)"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("48750.0")  # -2.5% (emergency exit)

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Set active executor ID with high profit (would trigger grid profit exit)
        controller.active_executor_id = "test_executor_123"
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=create_grid_config(entry_price),
            net_pnl_pct=Decimal("0.007"),  # 0.7% profit
            net_pnl_quote=Decimal("35.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("30.0"),  # 0.6% of 5000 = 30
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )
        controller.executors_info = [executor_info]

        # Mock trend with negative trends (would trigger trend exit)
        mock_trend.current_price = current_price
        mock_trend.trend_60m = -1.5
        mock_trend.trend_240m = -0.5
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return emergency_exit (highest priority)
        result = controller.should_exit_position(coin)
        assert result == "emergency_exit"

    def test_grid_profit_exit_priority_over_trend(self, controller, mock_trend):
        """Test that grid profit exit has priority over trend exit"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price
        controller.active_coin = coin  # Set active coin

        # Set last switch time to 2 hours ago (hold time passed)
        controller.last_switch_time = controller.market_data_provider.time() - 7200.0

        # Set active executor ID with high profit
        controller.active_executor_id = "test_executor_123"
        # BUG FIX: Use custom_info for realized_pnl_quote and position_size_quote
        # BUG FIX: realized_pnl_quote must be high enough to cover 0.6% net after 0.31% fees
        executor_info = ExecutorInfo(
            id="test_executor_123",
            timestamp=1000000.0,
            type="grid_executor",
            status=RunnableStatus.RUNNING,
            config=create_grid_config(entry_price),
            net_pnl_pct=Decimal("0.007"),  # 0.7% profit
            net_pnl_quote=Decimal("35.0"),
            cum_fees_quote=Decimal("1.0"),
            filled_amount_quote=Decimal("5000.0"),
            is_active=True,
            is_trading=True,
            custom_info={
                "realized_pnl_quote": Decimal("45.5"),  # 0.91% of 5000 = 45.5 (net: 0.6% after fees)
                "position_size_quote": Decimal("5000.0")
            },
            controller_id="test_controller"
        )
        controller.executors_info = [executor_info]

        # Mock trend with negative trends (would trigger trend exit)
        # BUG FIX: Set current price to -2.0% to meet price_down_severely requirement
        mock_trend.current_price = Decimal("49000.0")  # -2.0% drop
        mock_trend.trend_60m = -1.5
        mock_trend.trend_240m = -0.5
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return grid_profit_exit (priority over trend_exit)
        result = controller.should_exit_position(coin)
        assert result == "grid_profit_exit"


class TestNoExit:
    """Test cases where no exit should occur"""

    def test_no_exit_when_all_conditions_met_but_hold_time_not_passed(self, controller, mock_trend):
        """Test that no exit occurs during hold time grace period"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Set last switch time to 30 minutes ago (still in grace period)
        controller.last_switch_time = controller.market_data_provider.time() - 1800.0

        # Mock trend with negative trends (would trigger trend exit if hold time passed)
        mock_trend.trend_60m = -1.5
        mock_trend.trend_240m = -0.5
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no exit) because hold time not passed
        result = controller.should_exit_position(coin)
        assert result is None

    def test_no_exit_when_price_above_thresholds(self, controller, mock_trend):
        """Test that no exit occurs when price is above all thresholds"""
        coin = "BTC-EUR"
        entry_price = Decimal("50000.0")
        current_price = Decimal("51000.0")  # +2.0% (above all thresholds)

        # Set entry price
        controller.entry_prices[coin] = entry_price

        # Mock trend with positive trends
        mock_trend.current_price = current_price
        mock_trend.trend_60m = 0.5  # Positive
        mock_trend.trend_240m = 1.0  # Positive
        controller.trend_calculator.get_trend.return_value = mock_trend

        # Should return None (no exit)
        result = controller.should_exit_position(coin)
        assert result is None

```

## Attachment: test_stale_executor_cleanup.py (656 lines)

```python
"""
Unit tests for stale executor cleanup and stale order detection.

Tests the following functionality:
- Stale executor reference tracking and cleanup
- Stale open order detection at startup
- Telegram alerts for stale executors/orders
- Safety: only affects trading pairs in market_list

Related to US-005 Professional Risk Management.
"""

import sys
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
except ImportError:
    try:
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
    except ImportError:
        from controllers.multi_coin_grid_config import MultiCoinGridConfig
        from controllers.multi_coin_grid_controller import MultiCoinGridController


pytestmark = pytest.mark.asyncio


class TestStaleExecutorCleanup:
    """Test suite for stale executor reference cleanup"""

    @pytest.fixture
    def mock_config(self):
        """Create test config with market_list"""
        config = MagicMock(spec=MultiCoinGridConfig)
        config.id = "multi_coin_grid"
        config.connector_name = "bitget"
        config.quote_asset = "USDT"
        config.market_list = ["SONIC-USDT", "HYPE-USDT", "BTC-USDT"]
        config.min_notional = Decimal("10")
        config.max_hold_time_minutes = 1440  # 24 hours
        config.stop_loss_pct = Decimal("0.05")
        return config

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        connector = MagicMock()
        connector.name = "bitget"
        connector._account_balances = {}
        connector._in_flight_orders = {}
        connector.get_mid_price = Mock(return_value=Decimal("0.045"))
        return connector

    @pytest.fixture
    def mock_market_data_provider(self):
        """Create mock market data provider"""
        provider = MagicMock()
        provider.time = Mock(return_value=time.time())
        provider.ready = True
        return provider

    @pytest.fixture
    def mock_telegram_alerter(self):
        """Create mock Telegram alerter"""
        alerter = MagicMock()
        alerter.enabled = True
        alerter.warning = Mock()
        return alerter

    @pytest.fixture
    def controller(self, mock_config, mock_connector, mock_market_data_provider, mock_telegram_alerter):
        """Create controller with mocked dependencies"""
        with patch.object(MultiCoinGridController, '__init__', lambda x, *args, **kwargs: None):
            controller = MultiCoinGridController.__new__(MultiCoinGridController)

            # Initialize required attributes
            controller.config = mock_config
            controller.connector = mock_connector
            controller.market_data_provider = mock_market_data_provider
            controller.telegram_alerter = mock_telegram_alerter
            controller.active_coins = {}
            controller.entry_prices = {}
            controller.executors_info = []
            controller._executor_creation_timestamps = {}
            controller._stale_executor_counts = {}
            controller._stale_orders = []
            controller.trend_calculator = None
            controller.professional_risk_manager = None

            # Mock logger
            controller.logger = Mock(return_value=MagicMock())

            return controller

    # ==================== Stale Executor Tracking Tests ====================

    def test_stale_executor_count_increments_when_executor_not_found(self, controller):
        """Test that stale executor count increments when executor is not in executors_info"""
        # Setup: active_coins has an executor ID that doesn't exist in executors_info
        executor_id = "AR6uPcLE49NMnv5tZyhfVjUexEkHzZtm1Bfjo2oL24Wf"
        trading_pair = "SONIC-USDT"
        controller.active_coins = {trading_pair: executor_id}
        controller.executors_info = []  # Empty - executor not found

        # Act: Call _check_professional_exit_signals (simulated check)
        stale_key = f"{trading_pair}_{executor_id}"

        # Simulate the counter increment logic
        if not hasattr(controller, '_stale_executor_counts'):
            controller._stale_executor_counts = {}
        controller._stale_executor_counts[stale_key] = controller._stale_executor_counts.get(stale_key, 0) + 1

        # Assert
        assert controller._stale_executor_counts[stale_key] == 1

    def test_stale_executor_cleanup_after_threshold(self, controller):
        """Test that stale executor reference is cleaned up after 10 checks"""
        # Setup
        executor_id = "AR6uPcLE49NMnv5tZyhfVjUexEkHzZtm1Bfjo2oL24Wf"
        trading_pair = "SONIC-USDT"
        controller.active_coins = {trading_pair: executor_id}
        controller.entry_prices = {trading_pair: Decimal("0.048")}
        controller._executor_creation_timestamps = {executor_id: time.time() - 86400}

        stale_key = f"{trading_pair}_{executor_id}"
        controller._stale_executor_counts = {stale_key: 10}  # At threshold

        # Simulate cleanup logic
        if controller._stale_executor_counts[stale_key] >= 10:
            # Cleanup
            if trading_pair in controller.active_coins:
                del controller.active_coins[trading_pair]
            if trading_pair in controller.entry_prices:
                del controller.entry_prices[trading_pair]
            if executor_id in controller._executor_creation_timestamps:
                del controller._executor_creation_timestamps[executor_id]
            del controller._stale_executor_counts[stale_key]

        # Assert: All references cleaned up
        assert trading_pair not in controller.active_coins
        assert trading_pair not in controller.entry_prices
        assert executor_id not in controller._executor_creation_timestamps
        assert stale_key not in controller._stale_executor_counts

    def test_stale_executor_counter_resets_when_executor_found(self, controller):
        """Test that stale counter resets when executor becomes available again"""
        # Setup: Executor was temporarily missing but now found
        executor_id = "TestExecutor123"
        trading_pair = "HYPE-USDT"
        stale_key = f"{trading_pair}_{executor_id}"

        controller._stale_executor_counts = {stale_key: 5}  # Was counting

        # Simulate executor being found
        mock_executor = MagicMock()
        mock_executor.id = executor_id
        mock_executor.is_active = True
        controller.executors_info = [mock_executor]

        # Reset counter (as would happen in actual code)
        if stale_key in controller._stale_executor_counts:
            del controller._stale_executor_counts[stale_key]

        # Assert
        assert stale_key not in controller._stale_executor_counts

    def test_stale_executor_sends_telegram_alert(self, controller, mock_telegram_alerter):
        """Test that Telegram alert is sent when stale executor is cleaned"""
        # Setup
        executor_id = "StaleExecutor999"
        trading_pair = "BTC-USDT"

        # Simulate alert
        mock_telegram_alerter.warning(
            f"<b>🧹 STALE EXECUTOR CLEANED</b>\n\n"
            f"• Pair: <b>{trading_pair}</b>\n"
            f"• Executor: {executor_id[:16]}...\n"
            f"• Reason: Executor not found in orchestrator\n\n"
            f"⚠️ Check for orphaned open orders on exchange!"
        )

        # Assert
        mock_telegram_alerter.warning.assert_called_once()
        call_args = mock_telegram_alerter.warning.call_args[0][0]
        assert "STALE EXECUTOR CLEANED" in call_args
        assert trading_pair in call_args


class TestStaleOrderDetection:
    """Test suite for stale open order detection"""

    @pytest.fixture
    def mock_config(self):
        """Create test config"""
        config = MagicMock(spec=MultiCoinGridConfig)
        config.connector_name = "bitget"
        config.quote_asset = "USDT"
        config.market_list = ["SONIC-USDT", "HYPE-USDT"]
        config.max_hold_time_minutes = 1440
        return config

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector with in_flight_orders"""
        connector = MagicMock()
        connector.name = "bitget"
        connector._in_flight_orders = {}
        return connector

    @pytest.fixture
    def mock_telegram_alerter(self):
        """Create mock Telegram alerter"""
        alerter = MagicMock()
        alerter.enabled = True
        alerter.warning = Mock()
        return alerter

    @pytest.fixture
    def controller(self, mock_config, mock_connector, mock_telegram_alerter):
        """Create controller with mocked dependencies"""
        with patch.object(MultiCoinGridController, '__init__', lambda x, *args, **kwargs: None):
            controller = MultiCoinGridController.__new__(MultiCoinGridController)

            controller.config = mock_config
            controller.connector = mock_connector
            controller.telegram_alerter = mock_telegram_alerter
            controller.active_coins = {}
            controller._stale_orders = []
            controller.logger = Mock(return_value=MagicMock())

            return controller

    def test_detect_stale_sell_order_without_executor(self, controller, mock_connector):
        """Test detection of stale sell order that has no active executor"""
        # Setup: Create a stale sell order
        stale_order = MagicMock()
        stale_order.trading_pair = "SONIC-USDT"
        stale_order.is_sell = True
        stale_order.amount = Decimal("1533.07")
        stale_order.price = Decimal("0.046419")
        stale_order.creation_timestamp = time.time() - (25 * 60 * 60)  # 25 hours ago

        mock_connector._in_flight_orders = {"order123": stale_order}
        controller.active_coins = {}  # No active executor

        # Detect stale orders
        stale_threshold_minutes = 1440 + 60  # max_hold + 1 hour
        current_time = time.time()

        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in controller.active_coins and order.is_sell:
                order_age_minutes = (current_time - order.creation_timestamp) / 60
                if order_age_minutes > stale_threshold_minutes:
                    stale_orders.append({
                        'order_id': order_id,
                        'trading_pair': order.trading_pair,
                        'amount': float(order.amount),
                        'price': float(order.price),
                        'age_minutes': order_age_minutes
                    })

        # Assert
        assert len(stale_orders) == 1
        assert stale_orders[0]['trading_pair'] == "SONIC-USDT"
        assert stale_orders[0]['amount'] == 1533.07

    def test_ignore_order_with_active_executor(self, controller, mock_connector):
        """Test that orders with active executors are NOT flagged as stale"""
        # Setup: Order has an active executor
        order = MagicMock()
        order.trading_pair = "HYPE-USDT"
        order.is_sell = True
        order.amount = Decimal("100")
        order.price = Decimal("25.0")
        order.creation_timestamp = time.time() - (25 * 60 * 60)  # Old but has executor

        mock_connector._in_flight_orders = {"order456": order}
        controller.active_coins = {"HYPE-USDT": "ActiveExecutorID"}  # Has executor!

        # Detect
        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in controller.active_coins and order.is_sell:
                stale_orders.append(order_id)

        # Assert: No stale orders (executor exists)
        assert len(stale_orders) == 0

    def test_ignore_buy_orders(self, controller, mock_connector):
        """Test that BUY orders are ignored (only SELL orders checked)"""
        # Setup: Old buy order
        buy_order = MagicMock()
        buy_order.trading_pair = "SONIC-USDT"
        buy_order.is_sell = False  # BUY order
        buy_order.amount = Decimal("1000")
        buy_order.price = Decimal("0.045")
        buy_order.creation_timestamp = time.time() - (30 * 60 * 60)  # Very old

        mock_connector._in_flight_orders = {"buy_order": buy_order}
        controller.active_coins = {}

        # Detect (only sell orders)
        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in controller.active_coins and order.is_sell:
                stale_orders.append(order_id)

        # Assert: Buy orders ignored
        assert len(stale_orders) == 0

    def test_ignore_recent_orders(self, controller, mock_connector):
        """Test that recent orders (under threshold) are not flagged"""
        # Setup: Recent order (only 1 hour old)
        recent_order = MagicMock()
        recent_order.trading_pair = "SONIC-USDT"
        recent_order.is_sell = True
        recent_order.amount = Decimal("500")
        recent_order.price = Decimal("0.05")
        recent_order.creation_timestamp = time.time() - (60 * 60)  # 1 hour ago

        mock_connector._in_flight_orders = {"recent": recent_order}
        controller.active_coins = {}

        # Detect with 25-hour threshold
        stale_threshold_minutes = 1440 + 60  # 25 hours
        current_time = time.time()

        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            order_age_minutes = (current_time - order.creation_timestamp) / 60
            if order_age_minutes > stale_threshold_minutes and order.is_sell:
                stale_orders.append(order_id)

        # Assert: Recent order not flagged
        assert len(stale_orders) == 0

    def test_stale_order_telegram_alert(self, controller, mock_telegram_alerter):
        """Test that Telegram alert is sent for stale orders"""
        # Setup
        stale_orders = [{
            'order_id': 'SSCUT64c34e293abe6280dc9d3a5ff361ebab0ce024d7c371f',
            'trading_pair': 'SONIC-USDT',
            'amount': 1533.07,
            'price': 0.046419,
            'age_minutes': 1500
        }]

        # Simulate alert
        stale_lines = ["<b>🔴 STALE LIMIT ORDERS DETECTED</b>\n"]
        for stale in stale_orders:
            stale_lines.append(
                f"• <b>{stale['trading_pair']}</b>: Sell {stale['amount']:.6f} @ ${stale['price']:.6f}"
            )
            stale_lines.append(f"  Age: {stale['age_minutes']:.0f} minutes")
        stale_lines.append("\n⚠️ These orders have no active executor - consider cancelling manually")

        mock_telegram_alerter.warning("\n".join(stale_lines))

        # Assert
        mock_telegram_alerter.warning.assert_called_once()
        call_args = mock_telegram_alerter.warning.call_args[0][0]
        assert "STALE LIMIT ORDERS DETECTED" in call_args
        assert "SONIC-USDT" in call_args
        assert "1533" in call_args


class TestSafetyChecks:
    """Test suite for safety: only market_list pairs are affected"""

    @pytest.fixture
    def mock_config(self):
        """Create test config with specific market_list"""
        config = MagicMock(spec=MultiCoinGridConfig)
        config.market_list = ["SONIC-USDT", "HYPE-USDT"]  # Only these pairs
        config.quote_asset = "USDT"
        config.max_hold_time_minutes = 1440
        return config

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        connector = MagicMock()
        connector._in_flight_orders = {}
        return connector

    @pytest.fixture
    def controller(self, mock_config, mock_connector):
        """Create controller"""
        with patch.object(MultiCoinGridController, '__init__', lambda x, *args, **kwargs: None):
            controller = MultiCoinGridController.__new__(MultiCoinGridController)
            controller.config = mock_config
            controller.connector = mock_connector
            controller.active_coins = {}
            controller.logger = Mock(return_value=MagicMock())
            return controller

    def test_ignore_orders_not_in_market_list(self, controller, mock_connector, mock_config):
        """Test that orders for pairs NOT in market_list are ignored"""
        # Setup: Order for pair NOT in market_list
        manual_order = MagicMock()
        manual_order.trading_pair = "DOGE-USDT"  # NOT in market_list
        manual_order.is_sell = True
        manual_order.amount = Decimal("10000")
        manual_order.price = Decimal("0.10")
        manual_order.creation_timestamp = time.time() - (30 * 60 * 60)  # Very old

        mock_connector._in_flight_orders = {"manual_order": manual_order}

        # Only check pairs in market_list
        market_list_pairs = set(mock_config.market_list)

        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in market_list_pairs:
                continue  # Skip pairs not managed by bot
            if order.trading_pair not in controller.active_coins and order.is_sell:
                stale_orders.append(order_id)

        # Assert: Manual order ignored
        assert len(stale_orders) == 0

    def test_detect_orders_in_market_list(self, controller, mock_connector, mock_config):
        """Test that orders for pairs IN market_list ARE detected"""
        # Setup: Order for pair IN market_list
        bot_order = MagicMock()
        bot_order.trading_pair = "SONIC-USDT"  # IN market_list
        bot_order.is_sell = True
        bot_order.amount = Decimal("1000")
        bot_order.price = Decimal("0.05")
        bot_order.creation_timestamp = time.time() - (30 * 60 * 60)

        mock_connector._in_flight_orders = {"bot_order": bot_order}

        # Check with market_list filter
        market_list_pairs = set(mock_config.market_list)
        stale_threshold_minutes = 1440 + 60
        current_time = time.time()

        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in market_list_pairs:
                continue
            order_age_minutes = (current_time - order.creation_timestamp) / 60
            if order_age_minutes > stale_threshold_minutes and order.is_sell:
                if order.trading_pair not in controller.active_coins:
                    stale_orders.append(order_id)

        # Assert: Bot order detected
        assert len(stale_orders) == 1
        assert "bot_order" in stale_orders


class TestIntegrationScenario:
    """Integration test simulating the SONIC scenario"""

    def test_sonic_scenario_full_detection(self):
        """
        Simulate the actual SONIC issue:
        - 1533 SONIC bought, only 1023 sold
        - Remaining 1533 SONIC stuck in limit sell order @ $0.046419
        - Order created 24+ hours ago
        - No active executor (was cleaned up after restart)
        - TIME_STOP triggers but executor not found
        """
        # Setup mock objects
        with patch.object(MultiCoinGridController, '__init__', lambda x, *args, **kwargs: None):
            controller = MultiCoinGridController.__new__(MultiCoinGridController)

            # Config
            config = MagicMock()
            config.market_list = ["SONIC-USDT", "HYPE-USDT", "BTC-USDT"]
            config.max_hold_time_minutes = 1440
            config.quote_asset = "USDT"
            controller.config = config

            # Stale order on exchange
            stale_order = MagicMock()
            stale_order.trading_pair = "SONIC-USDT"
            stale_order.is_sell = True
            stale_order.amount = Decimal("1533.07")
            stale_order.price = Decimal("0.046419")
            stale_order.creation_timestamp = time.time() - (24 * 60 * 60 + 60 * 60)  # 25h ago

            connector = MagicMock()
            connector._in_flight_orders = {
                "SSCUT64c34e293abe6280dc9d3a5ff361ebab0ce024d7c371f": stale_order
            }
            controller.connector = connector

            # No active executors (cleaned up)
            controller.active_coins = {}

            # Telegram alerter
            alerter = MagicMock()
            alerter.enabled = True
            alerter.warning = Mock()
            controller.telegram_alerter = alerter

            # Detect stale orders
            market_list_pairs = set(config.market_list)
            stale_threshold_minutes = config.max_hold_time_minutes + 60
            current_time = time.time()

            detected_stale = []
            for order_id, order in connector._in_flight_orders.items():
                # Safety: only check market_list pairs
                if order.trading_pair not in market_list_pairs:
                    continue
                # Only sell orders
                if not order.is_sell:
                    continue
                # Only without executor
                if order.trading_pair in controller.active_coins:
                    continue
                # Only old orders
                order_age_minutes = (current_time - order.creation_timestamp) / 60
                if order_age_minutes > stale_threshold_minutes:
                    detected_stale.append({
                        'order_id': order_id,
                        'trading_pair': order.trading_pair,
                        'amount': float(order.amount),
                        'price': float(order.price),
                        'age_minutes': order_age_minutes
                    })

            # Assert: SONIC detected
            assert len(detected_stale) == 1
            assert detected_stale[0]['trading_pair'] == "SONIC-USDT"
            assert detected_stale[0]['amount'] == 1533.07
            assert detected_stale[0]['price'] == 0.046419
            assert detected_stale[0]['age_minutes'] > 1500  # > 25 hours


class TestRealTelegramIntegration:
    """
    REAL integration test that sends actual Telegram messages.

    To run this test:
        pytest test_stale_executor_cleanup.py::TestRealTelegramIntegration -v -s

    Requires environment variables:
        TELEGRAM_BOT_TOKEN
        TELEGRAM_CHAT_ID
    """

    @pytest.fixture
    def real_telegram_alerter(self):
        """Create REAL Telegram alerter using environment variables"""
        import os

        bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

        if not bot_token or not chat_id:
            pytest.skip("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables required")

        from multi_coin_grid_pro.alerts.telegram_alerter import TelegramAlerter
        return TelegramAlerter(bot_token=bot_token, chat_id=chat_id)

    def test_real_stale_order_telegram_alert(self, real_telegram_alerter):
        """
        REAL TEST: Sends actual Telegram message for stale order detection.

        You should receive this message on your phone/Telegram!
        """
        # Build the same message format as the real code
        stale_orders = [{
            'order_id': 'TEST_ORDER_ID_12345',
            'trading_pair': 'SONIC-USDT',
            'amount': 1533.07,
            'price': 0.046419,
            'age_minutes': 1500
        }]

        stale_lines = ["<b>🔴 STALE LIMIT ORDERS DETECTED</b>\n"]
        stale_lines.append("<i>⚡ This is a TEST from pytest</i>\n")
        for stale in stale_orders:
            stale_lines.append(
                f"• <b>{stale['trading_pair']}</b>: Sell {stale['amount']:.6f} @ ${stale['price']:.6f}"
            )
            stale_lines.append(f"  Age: {stale['age_minutes']:.0f} minutes")
        stale_lines.append("\n⚠️ These orders have no active executor - consider cancelling manually")
        stale_lines.append("\n✅ <b>If you see this, the alerting works!</b>")

        # Send REAL message
        real_telegram_alerter.warning("\n".join(stale_lines))

        # The warning method doesn't return anything, but _send does
        # So we test by directly calling _send
        print("\n" + "=" * 60)
        print("📱 TELEGRAM MESSAGE SENT!")
        print("   Check your Telegram for the stale order alert")
        print("=" * 60 + "\n")

    def test_real_stale_executor_telegram_alert(self, real_telegram_alerter):
        """
        REAL TEST: Sends actual Telegram message for stale executor cleanup.
        """
        executor_id = "AR6uPcLE49NMnv5tZyhfVjUexEkHzZtm1Bfjo2oL24Wf"
        trading_pair = "SONIC-USDT"

        message = (
            f"<b>🧹 STALE EXECUTOR CLEANED</b>\n\n"
            f"<i>⚡ This is a TEST from pytest</i>\n\n"
            f"• Pair: <b>{trading_pair}</b>\n"
            f"• Executor: {executor_id[:16]}...\n"
            f"• Reason: Executor not found in orchestrator\n\n"
            f"⚠️ Check for orphaned open orders on exchange!\n\n"
            f"✅ <b>If you see this, the alerting works!</b>"
        )

        real_telegram_alerter.warning(message)

        print("\n" + "=" * 60)
        print("📱 TELEGRAM MESSAGE SENT!")
        print("   Check your Telegram for the stale executor alert")
        print("=" * 60 + "\n")

    def test_real_orphaned_position_telegram_alert(self, real_telegram_alerter):
        """
        REAL TEST: Sends actual Telegram message for orphaned positions.
        """
        orphaned_positions = [
            {'asset': 'SONIC', 'amount': 1533.07, 'price': 0.045, 'notional': 68.99},
            {'asset': 'HYPE', 'amount': 2.5, 'price': 25.0, 'notional': 62.50}
        ]

        total_value = sum(p['notional'] for p in orphaned_positions)

        orphan_lines = ["<b>🔴 ORPHANED POSITIONS DETECTED</b>\n"]
        orphan_lines.append("<i>⚡ This is a TEST from pytest</i>\n")
        for pos in orphaned_positions:
            orphan_lines.append(
                f"• <b>{pos['asset']}</b>: {pos['amount']:.6f} @ ${pos['price']:.4f} = ${pos['notional']:.2f}"
            )
        orphan_lines.append(f"\n<b>Total: ${total_value:.2f}</b>")
        orphan_lines.append("\n⚠️ Consider selling manually or restart with auto-recovery")
        orphan_lines.append("\n✅ <b>If you see this, the alerting works!</b>")

        real_telegram_alerter.warning("\n".join(orphan_lines))

        print("\n" + "=" * 60)
        print("📱 TELEGRAM MESSAGE SENT!")
        print("   Check your Telegram for the orphaned position alert")
        print("=" * 60 + "\n")

```

## Attachment: Directory Structure

```
multi_coin_grid_pro
multi_coin_grid_pro/.flake8
multi_coin_grid_pro/.gitignore
multi_coin_grid_pro/ADAPTIVE_FILTER_DESIGN.md
multi_coin_grid_pro/CHANGELOG.md
multi_coin_grid_pro/DATA_STORAGE.md
multi_coin_grid_pro/HYBRID_BOT_V2_README.md
multi_coin_grid_pro/HYBRID_GRID_IMPLEMENTATION.md
multi_coin_grid_pro/IMPLEMENTATION_COMPLETE.md
multi_coin_grid_pro/INTEGRATION_COMPLETE.md
multi_coin_grid_pro/QUICKSTART.md
multi_coin_grid_pro/README.md
multi_coin_grid_pro/alerts
multi_coin_grid_pro/alerts/__init__.py
multi_coin_grid_pro/alerts/__pycache__
multi_coin_grid_pro/alerts/telegram_alerter.py
multi_coin_grid_pro/backtest
multi_coin_grid_pro/backtest/data
multi_coin_grid_pro/backtest/results
multi_coin_grid_pro/bot_v2.py
multi_coin_grid_pro/config
multi_coin_grid_pro/config/Oud
multi_coin_grid_pro/config/Oud/config.dev.yaml
multi_coin_grid_pro/config/Oud/config.prod copy.yaml
multi_coin_grid_pro/config/Oud/config.prod.yaml.back
multi_coin_grid_pro/config/Oud/config.test.yaml
multi_coin_grid_pro/config/Oud/config.usd.yaml
multi_coin_grid_pro/config/__pycache__
multi_coin_grid_pro/config/config_manager.py
multi_coin_grid_pro/config/risk_monitor.yaml
multi_coin_grid_pro/config/spot_grid_kraken_eur.yaml
multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml
multi_coin_grid_pro/controllers
multi_coin_grid_pro/controllers/__init__.py
multi_coin_grid_pro/controllers/__pycache__
multi_coin_grid_pro/controllers/multi_coin_grid_config.py
multi_coin_grid_pro/controllers/multi_coin_grid_controller.py
multi_coin_grid_pro/controllers/utils
multi_coin_grid_pro/controllers/utils/__init__.py
multi_coin_grid_pro/controllers/utils/__pycache__
multi_coin_grid_pro/controllers/utils/liquidity_proxy.py
multi_coin_grid_pro/core
multi_coin_grid_pro/core/__init__.py
multi_coin_grid_pro/core/__pycache__
multi_coin_grid_pro/core/config_loader.py
multi_coin_grid_pro/core/drawdown_tracker.py
multi_coin_grid_pro/core/global_risk_manager.py
multi_coin_grid_pro/core/market_regime_integration.py
multi_coin_grid_pro/core/models.py
multi_coin_grid_pro/core/performance_tracker.py
multi_coin_grid_pro/core/reason_codes.py
multi_coin_grid_pro/core/risk_scanner.py
multi_coin_grid_pro/core/time_based_integration.py
multi_coin_grid_pro/data
multi_coin_grid_pro/data/monitoring.db
multi_coin_grid_pro/docs
multi_coin_grid_pro/docs/ARCHITECTURE.md
multi_coin_grid_pro/docs/BOT_FLOW_COMPLETE_UITLEG.md
multi_coin_grid_pro/docs/DEVELOPMENT_GUIDE.md
multi_coin_grid_pro/docs/EPIC_V3.4_MOMENTUM_HEALTH_GUARDS.md
multi_coin_grid_pro/docs/FIX_SELL_ERROR.md
multi_coin_grid_pro/docs/PAPER_TRADING.md
multi_coin_grid_pro/docs/PHASE_1A_IMPLEMENTATION.md
multi_coin_grid_pro/docs/PROP_DESK_IMPLEMENTATION_ROADMAP.md
multi_coin_grid_pro/docs/PRO_EXIT_SYSTEM.md
multi_coin_grid_pro/docs/RUNBOOK.md
multi_coin_grid_pro/docs/STORY_A1_IMPLEMENTATION_TRACKER.md
multi_coin_grid_pro/docs/TODOs
multi_coin_grid_pro/docs/TODOs/FUTURES_DYNAMIC_PAIR_DISCOVERY.md
multi_coin_grid_pro/docs/TODOs/FUTURES_IMPROVEMENTS_ROADMAP.md
multi_coin_grid_pro/docs/TODOs/PERFORMANCE_FIX_ROADMAP.md
multi_coin_grid_pro/docs/TODOs/REFACTOR_CONTROLLER_SPLIT.md
multi_coin_grid_pro/docs/USD_BOT_SETUP_VERIFICATION.md
multi_coin_grid_pro/docs/US_MARKET_DATA_ORDER_VALIDITY.md
multi_coin_grid_pro/execution
multi_coin_grid_pro/execution/__pycache__
multi_coin_grid_pro/execution/dynamic_slot_manager.py
multi_coin_grid_pro/filters
multi_coin_grid_pro/filters/__init__.py
multi_coin_grid_pro/filters/__pycache__
multi_coin_grid_pro/filters/market_regime_filter.py
multi_coin_grid_pro/filters/parabolic_blacklist.py
multi_coin_grid_pro/filters/smart_entry_filter.py
multi_coin_grid_pro/filters/threshold_resolver.py
multi_coin_grid_pro/filters/time_based_filter.py
multi_coin_grid_pro/fix_flake8.py
multi_coin_grid_pro/futures_bitget
multi_coin_grid_pro/futures_bitget/IMPLEMENTATION_REVIEW.md
multi_coin_grid_pro/futures_bitget/QUICK_START.md
multi_coin_grid_pro/futures_bitget/README.md
multi_coin_grid_pro/futures_bitget/RISK_MANAGEMENT.md
multi_coin_grid_pro/futures_bitget/__init__.py
multi_coin_grid_pro/futures_bitget/__pycache__
multi_coin_grid_pro/futures_bitget/config
multi_coin_grid_pro/futures_bitget/config/futures_grid_bitget.yaml
multi_coin_grid_pro/futures_bitget/config_manager.py
multi_coin_grid_pro/futures_bitget/config_schema.py
multi_coin_grid_pro/futures_bitget/controller.py
multi_coin_grid_pro/futures_bitget/risk_guard.py
multi_coin_grid_pro/indicators
multi_coin_grid_pro/indicators/__init__.py
multi_coin_grid_pro/indicators/__pycache__
multi_coin_grid_pro/indicators/momentum_indicators.py
multi_coin_grid_pro/lint_all.sh
multi_coin_grid_pro/logic
multi_coin_grid_pro/logic/__init__.py
multi_coin_grid_pro/logic/__pycache__
multi_coin_grid_pro/logic/coin_selector.py
multi_coin_grid_pro/logic/grid_builder.py
multi_coin_grid_pro/logic/grid_sizer.py
multi_coin_grid_pro/logic/liquidity_aware_sizer.py
multi_coin_grid_pro/logic/smart_entry.py
multi_coin_grid_pro/logs
multi_coin_grid_pro/logs/spot-future-grid.zip
multi_coin_grid_pro/models
multi_coin_grid_pro/models/__pycache__
multi_coin_grid_pro/models/execution_audit.py
multi_coin_grid_pro/monitoring
multi_coin_grid_pro/monitoring/QUICKSTART.md
multi_coin_grid_pro/monitoring/README.md
multi_coin_grid_pro/monitoring/TELEGRAM_SETUP.md
multi_coin_grid_pro/monitoring/__init__.py
multi_coin_grid_pro/monitoring/__pycache__
multi_coin_grid_pro/monitoring/collector.py
multi_coin_grid_pro/monitoring/config.py
multi_coin_grid_pro/monitoring/dashboard.py
multi_coin_grid_pro/monitoring/database.py
multi_coin_grid_pro/monitoring/risk_monitor.py
multi_coin_grid_pro/monitoring/start_monitoring.sh
multi_coin_grid_pro/monitoring/telegram_bot.py
multi_coin_grid_pro/monitoring/telegram_bot_handler.py
multi_coin_grid_pro/monitoring/telegram_notifier.py
multi_coin_grid_pro/monitoring/trade_analyzer.py
multi_coin_grid_pro/observability
multi_coin_grid_pro/observability/__init__.py
multi_coin_grid_pro/observability/__pycache__
multi_coin_grid_pro/observability/console_reporter.py
multi_coin_grid_pro/observability/event_aggregator.py
multi_coin_grid_pro/observability/event_logger.py
multi_coin_grid_pro/observability/why_no_trade_v2.py
multi_coin_grid_pro/paper_trading
multi_coin_grid_pro/paper_trading/__init__.py
multi_coin_grid_pro/paper_trading/__pycache__
multi_coin_grid_pro/paper_trading/paper_trading_mode.py
multi_coin_grid_pro/persistence
multi_coin_grid_pro/persistence/__init__.py
multi_coin_grid_pro/persistence/__pycache__
multi_coin_grid_pro/persistence/cooldown_store.py
multi_coin_grid_pro/requirements.txt
multi_coin_grid_pro/risk
multi_coin_grid_pro/risk/__init__.py
multi_coin_grid_pro/risk/__pycache__
multi_coin_grid_pro/risk/pnl_tracker.py
multi_coin_grid_pro/risk/professional_risk_manager.py
multi_coin_grid_pro/risk/risk_guard.py
multi_coin_grid_pro/scripts
multi_coin_grid_pro/scripts/__pycache__
multi_coin_grid_pro/scripts/analyze_trades_from_db.py
multi_coin_grid_pro/scripts/analyze_trades_sqlite.py
multi_coin_grid_pro/scripts/detailed_trade_analysis.py
multi_coin_grid_pro/scripts/get_monitored_coins.py
multi_coin_grid_pro/scripts/get_monitored_coins.sh
multi_coin_grid_pro/scripts/multi_coin_grid_v2.py
multi_coin_grid_pro/scripts/multi_coin_grid_v2_usd.py
multi_coin_grid_pro/scripts/run_standalone.py
multi_coin_grid_pro/scripts/simulate_strategy.py
multi_coin_grid_pro/spot_bitget
multi_coin_grid_pro/spot_bitget/QUICK_START.md
multi_coin_grid_pro/spot_bitget/README.md
multi_coin_grid_pro/spot_bitget/__init__.py
multi_coin_grid_pro/spot_bitget/__pycache__
multi_coin_grid_pro/spot_bitget/config
multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml
multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml.backup_20260112
multi_coin_grid_pro/spot_bitget/config_manager.py
multi_coin_grid_pro/spot_bitget/config_schema.py
multi_coin_grid_pro/spot_bitget/controller.py
multi_coin_grid_pro/spot_microarb_bitget
multi_coin_grid_pro/spot_microarb_bitget/QUICK_START.md
multi_coin_grid_pro/spot_microarb_bitget/README.md
multi_coin_grid_pro/spot_microarb_bitget/__init__.py
multi_coin_grid_pro/spot_microarb_bitget/__pycache__
multi_coin_grid_pro/spot_microarb_bitget/config
multi_coin_grid_pro/spot_microarb_bitget/config/spot_microarb_bitget.yaml
multi_coin_grid_pro/spot_microarb_bitget/config_manager.py
multi_coin_grid_pro/spot_microarb_bitget/config_schema.py
multi_coin_grid_pro/spot_microarb_bitget/controller.py
multi_coin_grid_pro/src
multi_coin_grid_pro/src/__init__.py
multi_coin_grid_pro/start.sh
multi_coin_grid_pro/tests
multi_coin_grid_pro/tests/.pytest_cache
multi_coin_grid_pro/tests/.pytest_cache/.gitignore
multi_coin_grid_pro/tests/.pytest_cache/CACHEDIR.TAG
multi_coin_grid_pro/tests/.pytest_cache/README.md
multi_coin_grid_pro/tests/.pytest_cache/v
multi_coin_grid_pro/tests/.pytest_cache/v/cache
multi_coin_grid_pro/tests/.pytest_cache/v/cache/lastfailed
multi_coin_grid_pro/tests/.pytest_cache/v/cache/nodeids
multi_coin_grid_pro/tests/.pytest_cache/v/cache/stepwise
```

## Review Rules

## Review Rules (include at bottom of every round)

```
Important rules for this review:
- Be brutally honest and specific
- Do not praise by default
- Do not give generic best-practice advice unless tied to this bot
- Every major claim must reference evidence from code, config, logs,
  database, or trade data
- Distinguish facts, inferences, and unknowns
- Prioritize recommendations by impact, urgency, and implementation effort
- Explicitly state what should be kept, what should be redesigned,
  and what should be removed
- Assume the goal is to evolve this system toward professional-grade
  live trading, not just academic correctness
- If data is missing to support a conclusion, say exactly what data
  you need rather than speculating
- Use the evidence table format for all major findings
```

---
