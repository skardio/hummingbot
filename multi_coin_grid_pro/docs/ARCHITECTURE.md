# Architecture Documentation

## Overview

The Multi-Coin Grid Trading Bot is built on Hummingbot's Strategy V2 framework, using a controller-based architecture with executors for order management.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    Hummingbot Strategy V2                    │
│                  (Script Strategy Base)                      │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│              MultiCoinGridStrategyV2                         │
│  - Initializes connectors                                   │
│  - Loads configuration                                      │
│  - Creates controller                                       │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│            MultiCoinGridController                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Coin Discovery                                        │  │
│  │ - Finds tradeable coins                               │  │
│  │ - Filters by volume/spread                            │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Trend Calculator                                      │  │
│  │ - Tracks price history                                │  │
│  │ - Calculates trends (EMA, LinReg, Consensus)         │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Risk Management                                       │  │
│  │ - Stop-loss monitoring                                │  │
│  │ - Circuit breaker                                     │  │
│  │ - Position limits                                     │  │
│  └──────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Executor Orchestrator                                 │  │
│  │ - Creates GridExecutor                                │  │
│  │ - Stops executors                                     │  │
│  │ - Tracks executor status                              │  │
│  └──────────────────────────────────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    GridExecutor                              │
│  - Places grid orders                                        │
│  - Manages order lifecycle                                  │
│  - Handles fills                                            │
│  - Triple barrier (stop-loss/take-profit)                   │
└─────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. MultiCoinGridController

**Responsibilities:**
- Coin discovery and selection
- Trend calculation and monitoring
- Risk management (stop-loss, circuit breaker, position limits)
- Executor lifecycle management
- Switch decision logic

**Key Methods:**
- `update_processed_data()`: Main update loop
- `determine_executor_actions()`: Decide what actions to take
- `_should_create_new_grid()`: Switch decision logic
- `_create_grid_action()`: Create grid executor
- `_create_stop_action()`: Stop current executor

### 2. CoinDiscovery

**Responsibilities:**
- Discover tradeable coins from exchange
- Filter by volume and liquidity
- Exclude expensive coins (BTC/ETH) if configured

**Key Methods:**
- `discover_coins()`: Main discovery method

### 3. TrendCalculator

**Responsibilities:**
- Track price history per coin
- Calculate multiple trend indicators:
  - Raw percentage trend
  - Volatility-normalized trend
  - EMA-based trend (EMA30/EMA60)
  - Linear regression slope
  - Multi-indicator consensus

**Key Methods:**
- `update_coin_trend()`: Update trend for a coin
- `get_best_coin()`: Find best trending coin

### 4. GridExecutor

**Responsibilities:**
- Place grid orders between start_price and end_price
- Manage order lifecycle
- Handle fills and refills
- Execute stop-loss/take-profit via TripleBarrierConfig

## Data Flow

1. **Startup:**
   - Load configuration
   - Initialize connectors
   - Discover coins
   - Initialize trend calculator

2. **Update Loop (every 10 seconds):**
   - Update coin trends
   - Find best trending coin
   - Check if should switch
   - Create/stop executors as needed
   - Monitor stop-loss and volatility

3. **Grid Execution:**
   - GridExecutor places orders
   - Orders fill as price moves
   - Executor refills orders
   - Stop-loss triggers if breached

## Risk Management Flow

```
Price Update
    │
    ▼
Check Stop-Loss ──→ Breached? ──→ Stop Executor ──→ Close Position
    │                                    │
    └── Not Breached                    └── Log Event
    │
    ▼
Check Volatility ──→ High? ──→ Circuit Breaker ──→ Pause Trading
    │                              │
    └── Normal                     └── Alert
    │
    ▼
Check Position Limits ──→ Exceeded? ──→ Block New Executor
    │
    └── Within Limits
    │
    ▼
Continue Trading
```

## Configuration Flow

```
config.dev.yaml / config.test.yaml / config.prod.yaml
    │
    ▼
ConfigManager.load_config()
    │
    ▼
Apply Environment Overrides (BOT_* env vars)
    │
    ▼
Validate with Pydantic (MultiCoinGridConfig)
    │
    ▼
Load into Controller
```

## Testing Architecture

```
Unit Tests (test_*.py)
    │
    ├── Test individual methods
    ├── Mock dependencies
    └── Fast execution

Integration Tests (test_full_cycle.py)
    │
    ├── Test complete cycles
    ├── Mock API calls
    └── Test error scenarios

Backtesting (backtest_engine.py)
    │
    ├── Historical data simulation
    ├── P&L calculation
    └── Strategy comparison

Paper Trading (paper_trading_mode.py)
    │
    ├── Simulate orders
    ├── Track positions
    └── Calculate P&L
```

## Monitoring Architecture

```
Bot Logs
    │
    ▼
Data Collector (collector.py)
    │
    ├── Parse logs
    ├── Detect events
    └── Store in SQLite
    │
    ├───→ Dashboard (dashboard.py) ──→ Flask Web UI
    └───→ Telegram Bot (telegram_bot.py) ──→ Alerts & Commands
```

## Error Handling

1. **API Errors:**
   - Count consecutive errors
   - Exponential backoff
   - Pause after 3 errors
   - Manual reset required

2. **Network Errors:**
   - Retry with backoff
   - Graceful degradation
   - Log all errors

3. **Validation Errors:**
   - Validate before execution
   - Log validation failures
   - Use fallback values if safe

## Performance Considerations

- **Update Interval:** 10 seconds (configurable)
- **Trend Lookback:** 60 minutes (configurable)
- **Grid Refresh:** On price movement >3%
- **Order Management:** Via GridExecutor (optimized)

## Scalability

- **Current:** Single executor (1 coin at a time)
- **Future:** Multiple executors (parallel trading)
- **Capital:** Designed for €10,000+ (currently tested with €120-€500)
