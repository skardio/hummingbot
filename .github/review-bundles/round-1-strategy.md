# Round 1: Strategy & Profitability Review

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

## Round 1: Strategy & Profitability Review

```
Act as a senior quantitative crypto trading engineer with deep expertise
in grid trading strategies, mean-reversion systems, and systematic
trend-following. You specialize in evaluating whether a trading strategy
has genuine edge after all costs.

## What this bot system is

A multi-coin adaptive grid trading bot built on Hummingbot's StrategyV2
framework (GridExecutor). It does NOT do arbitrage. It is a grid trader
with trend-based coin rotation, running as 3 separate bot instances:

### Bot 1: Kraken USD (spot)
- Dynamic coin discovery (25 monitored USD pairs)
- €300 capital, 6 max slots (usually capped to 4 by min order size)
- Grid: 5–7 levels, ATR-based asymmetric ranges
- Risk Manager currently BLOCKING: 30% WR, −0.44% rolling PnL → paused
- WebSocket errors (112 in current log session)

### Bot 2: Bitget USDT (spot)
- Dynamic coin discovery + manual pair fallback
- ~$100 capital, currently BLOCKED: $3.62 free < $30 minimum
- SONIC stuck LIMIT SELL @ $0.046419 (1533 units) locking ~$71
- Cannot trade until stuck order is manually cancelled

### Bot 3: Bitget Futures (perpetual)
- 37 manual USDT pairs, 3× leverage, HEDGE mode
- ~$50 capital, currently BLOCKED: $9.09–$9.25 < $15 minimum
- Direction: AUTO (long/short based on trend)
- Exchange-side TPSL orders (survives bot crashes)

### Shared mechanics (all 3 bots):
1. **Trend-based coin selection** — ranks coins by multi-indicator consensus
   trend score (EMA + linear regression + volatility-normalized + raw %),
   weighted across 1h/4h/24h timeframes
2. **Grid deployment** — places grid levels with ATR-based asymmetric
   ranges (down: 1.5×ATR / up: 2.0×ATR), or fixed fallback (−4% to +12%)
3. **Regime detection** — classifies market as BULL/CHOP/BEAR using
   consensus×0.80 + ATR_expansion×0.20, with hysteresis buffers
4. **Coin rotation** — switches coins when better trends appear, with
   smart-switch cost analysis, cooldowns, and session blacklists
5. **Multi-layer exit** — profit tiers (1%→breakeven, 2%→+0.7%, 3%→+1.5%),
   soft hold (2h trend-aware), hard hold (6h forced), emergency exit (−12%)
6. **Entry filters** — RSI, VWAP, ATR, spike detection, parabolic filter,
   BTC macro filter, multi-timeframe confirmation

## Actual performance data

> **Attach the latest data snapshot** with this round.
> File: `.github/data-snapshot-YYYY-MM-DD.md`
> Re-run the queries in that file before each review to get fresh data.
> Latest available: `.github/data-snapshot-2026-03-08.md`
>
> The snapshot contains: per-pair performance, close type distributions,
> error frequencies, WHY-NO-TRADE summaries, rotation timeout logs,
> and all SQL queries + bash commands to regenerate it.

## What I need you to evaluate

### 1. Does this strategy have real edge?
- Grid trading profits from mean-reversion within the grid range
- But the bot SELECTS coins by TREND — is there a contradiction?
  Trending coins move directionally; grids profit from oscillation.
  When does this combination work? When does it fail?
- **DATA SHOWS: 97–99% of executors never get a single fill.**
  The bot creates grids but they expire unfilled. Is the grid range
  too narrow? Are the entry filters killing the strategy?
- After Kraken fees (~0.16–0.26%), spread, and slippage, what is
  the realistic per-grid expected value? Current evidence: −€73 over
  2,216 executors with €2,236 volume = effectively near-zero edge.

### 2. Why is the fill rate so low?
- Current WHY-NO-TRADE data (today, March 8):
  - NO_ORDERBOOK_DATA: 35–44% of rejections (persistent)
  - RSI_OVERBOUGHT: 7–30% of rejections
  - SPREAD_TOO_WIDE: 0.1–9%
  - STALE_PRICE: 0.5–6%
- Kraken USD: close type 7 (no-fill timeout) = 210/212 executors
- Is the grid range too tight? Are the filters too restrictive?
- The bot approves 15–56% of intents hourly but still can't fill grids

### 3. Coin rotation: edge or overhead?
- Rotation is actively happening but dysfunctional:
  - Bitget Spot: SONIC-USDT stuck in 3-min rotation loop (21+ timeouts)
  - Kraken USD: SUI-USD hitting monitoring timeout repeatedly
- Rotation has costs: unrealized losses on exit, spread on new entry
- The bot uses 180-update timeout + 600s min switch interval
- Is this too aggressive? Evidence shows constant churn without fills

### 4. Capital adequacy problem
- Kraken USD: €300 → "Dynamic slots capped by min order size: 6→4"
- Bitget Spot: $3.62 free < $30 minimum (SONIC stuck order blocks $71)
- Bitget Futures: $9.09 < $15 minimum
- 2 of 3 bots are currently UNABLE TO TRADE due to capital constraints
- Is €300–€500 viable for this strategy at all?

### 5. Futures performance: is 3× leverage hiding a flawed strategy?
- 96% of filled futures trades closed via stop-loss (close type 8)
- ETH-USDT: 3 filled trades, all losses, −$62.78 total
- BTC-USDT: 3 filled trades, all losses, −$28.84 total
- SOL-USDT: only consistently profitable pair (+$9.31 from 2 fills)
- Total futures PnL: −$155 on $50 capital = −310% return
- Is the grid-on-futures approach fundamentally unsuitable?

### 6. Regime detector: effective or just adding complexity?
- BULL threshold: score ≥ 5.0, BEAR: < −3.0, CHOP: between
- During BEAR: slots reduce to 0.25× (1 slot for small capital)
- Risk Manager blocks SUI-USD repeatedly: "WR 30.0%, PnL −0.44%"
- Question: does the regime detector + risk manager effectively
  prevent the bot from ever trading? Is there a feedback loop where
  losses → pause → miss recovery → more losses?

## Attachments I'll provide
- [ ] Main controller source (9,182 lines)
- [ ] Production config YAMLs (Kraken USD + Bitget Spot + Bitget Futures)
- [ ] **Data snapshot** (`.github/data-snapshot-YYYY-MM-DD.md` — freshly generated)
- [ ] Error frequency summaries (included in data snapshot)

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
Identify which parts of the strategy design are worth preserving, and why.
Not everything needs to change — call out what works well and should NOT
be refactored away.

## Capital scaling verdict
Based on your reviewed evidence, state the maximum capital range you
would currently trust this bot with:
- [ ] Paper trading only
- [ ] Small live capital (< €500)
- [ ] Medium live capital (€500–€5,000)
- [ ] Larger serious capital (€5,000–€50,000)
- [ ] Professional capital (> €50,000)

Explain why, and what must change to move to the next tier.

## Expected output
1. **Edge assessment**: real edge, marginal edge, or no edge — with math
2. **Strategy contradictions**: where trend selection conflicts with grid mechanics
3. **Optimal operating conditions**: when this strategy works and when it doesn't
4. **Top 5 profitability leaks** with estimated impact (evidence table format)
5. **Concrete parameter suggestions** (grid levels, range, rotation frequency, regime thresholds)
6. **What to keep**: design decisions that are sound and should be preserved
7. **Capital scaling verdict**: current tier + what's needed for next tier
```


---

## Attachment: Config YAML — Kraken USD (979 lines)

```yaml
# ==============================================================================
# HYBRID GRID CONFIG v3.3 - USD VARIANT
# Kraken USD Multi-Coin Grid Bot (separate from EUR instance)
# Created: 2026-01-17
# ==============================================================================
# ⚠️ INSTANCE ISOLATION: This config runs INDEPENDENTLY from EUR bot
#    - Separate cooldowns DB: data/cooldowns_usd.db
#    - Separate logs: logs/logs_multi_coin_grid_usd_*.log
#    - Separate orders/state: no shared executors
# ==============================================================================

# INSTANCE IDENTIFIER - Used for DB path separation
instance_id: "usd"                  # 🔑 CRITICAL: Separates state from EUR bot


log_level: INFO
connector_name: kraken
quote_asset: USD                    # 🔄 CHANGED: EUR → USD
paper_trading: false                # 💰 LIVE TRADING MODE

# ==============================================================================
# DYNAMIC PAIR DISCOVERY (USD pairs)
# ==============================================================================

use_dynamic_pair_discovery: true
max_coins_to_monitor: 30                  # Was 25 → 30 (match met top_n voor orderbook prefetch)
min_24h_volume_quote: 500000          # Minimum 24h volume in quote currency (USD)

# US-007: Dynamic Pair Manager (two-tier discovery: REST scans all, WebSocket for best)
use_dynamic_pair_manager: true       # Enable two-tier pair discovery
pair_scan_interval_seconds: 300      # Interval between REST scans (5 min)
max_spread_pct: 0.5                  # Maximum bid-ask spread filter
exclude_expensive_coins: false

blacklist:
  # Stablecoins (no volatility)
  - USDT-USD
  - USDC-USD
  - DAI-USD
  - TUSD-USD
  - USDP-USD
  - GUSD-USD
  - PYUSD-USD
  # Wrapped/pegged assets
  - WBTC-USD
  - WETH-USD
  # Known problematic coins
  - MON-USD
  - CCD-USD
  - FARTCOIN-USD
  - GIGA-USD
  - XPL-USD
  - NIGHT-USD
  - AB-USD
  - XT-USD
  - EURC-USD
  - TRX-USD
  - PAXG-USD
  - SPX-USD
  - CH-USD
  - SAPIEN-USD
  - USELESS-USD
  - PUMP-USD
  - WLFI-USD
  # NL-restricted coins (if applicable)
  - Q-USD
  - STBL-USD
  # Non-existent Kraken USD pairs (cause WebSocket errors)
  - AUT-USD
  - AUD-USD
  - ACU-USD
  - XNY-USD
  - CC-USD
  - ZRO-USD
  - XCN-USD
  - VIRTUAL-USD   # Stuck executor - causes infinite retry loop
  - AAVE-USD      # No orderbook data
  - NEAR-USD      # No orderbook data
  - AXS-USD

# ==============================================================================
# ADAPTIVE REGIME DETECTION & FILTERS
# ==============================================================================

adaptive_regime_detection:
  enabled: true
  logging_only: false

  bull_score_min: 5.0
  chop_score_min: -3.0
  bear_score_max: -3.0
  min_confidence: 0.65

  bull_min_duration_sec: 1800
  chop_min_duration_sec: 900
  bear_min_duration_sec: 1800
  hysteresis_buffer: 1.0

  log_regime_changes: true
  log_filter_updates: true

adaptive_filters:
  baseline:
    rsi_buy_min: 25.0
    rsi_buy_max: 68.0       # 🛡️ Baseline: 68 (voorkom late pumps)
    rsi_extreme_min: 18.0
    vwap_max_deviation_pct: 18.0    # 🔧 FIX: 30→18 (align with smart_entry_filter)
    max_up_accel_pct: 4.0
    max_down_accel_pct: -8.0
    atr_min_pct: 0.08       # 🔧 FIX: 0.05→0.08 (align with smart_entry_filter)
    atr_max_pct: 7.0
    spike_5m_max_pct: 4.0
    wick_ratio_min: 0.0
    grid_spacing_mult: 1.0
    max_active_grids: 4
    entry_confidence_min: 0.65

  BULL:
    rsi_buy_max: 72.0       # 🛡️ Bull: 72 (iets ruimer voor momentum)
    vwap_max_deviation_pct: 20.0
    max_up_accel_pct: 3.0
    max_down_accel_pct: -4.0
    atr_min_pct: 0.05       # 🔧 FIX: 0.08→0.05
    spike_5m_max_pct: 3.5
    grid_spacing_mult: 1.2
    max_active_grids: 6
    entry_confidence_min: 0.60

  CHOP:
    rsi_buy_max: 68.0       # 🛡️ Chop: 68 (gelijk aan baseline)
    vwap_max_deviation_pct: 10.0
    max_up_accel_pct: 1.8
    max_down_accel_pct: -2.5
    atr_min_pct: 0.06       # 🔧 FIX: 0.10→0.06 (was too restrictive in quiet markets)
    spike_5m_max_pct: 2.5
    grid_spacing_mult: 0.8
    max_active_grids: 3
    entry_confidence_min: 0.75

  BEAR:
    rsi_buy_max: 62.0       # 🛡️ Bear: 62 (strengst)
    vwap_max_deviation_pct: 8.0
    max_up_accel_pct: 1.5
    max_down_accel_pct: -2.0
    atr_min_pct: 0.08       # 🔧 FIX: 0.15→0.08 (still allow some trades)
    spike_5m_max_pct: 2.0
    grid_spacing_mult: 1.5
    max_active_grids: 1             # 🔧 FIX: 0→1 (allow 1 grid for mean-reversion)
    entry_confidence_min: 0.90
    bear_allow_meanrev: false

# ==============================================================================
# COIN PROFILES & SMART ENTRY (USD pairs)
# ==============================================================================

manual_trading_pairs: []  # Dynamic discovery mode

# ==============================================================================
# MULTI-TIMEFRAME BUY PROTECTION
# ==============================================================================

use_multi_timeframe_buy: true
mtf_1h_min_pct: -2.0              # 🔧 FIX: 0→-2 (allow -2% pullback)
mtf_4h_min_pct: -1.5              # 🔧 FIX: 0→-1.5 (allow -1.5% pullback)
mtf_24h_min_pct: -2.5
mtf_declining_1h_max: -4.0
mtf_declining_4h_max: -2.0

# ==============================================================================
# WARMUP TREND OVERRIDE
# ==============================================================================

warmup_override_enabled: true
warmup_4h_strong_min: 0.5
warmup_1h_min_if_4h_strong: -1.5

# ==============================================================================
# FEATURE 1.1: MARKET REGIME FILTER - BTC Trend Following
# ==============================================================================

market_regime:
  enabled: true
  btc_symbol: "BTC-USD"             # 🔄 CHANGED: BTC-EUR → BTC-USD

  btc_trend_1h_min_pct: -2.0
  btc_trend_4h_min_pct: 0.0
  btc_trend_24h_min_pct: -5.0

  dump_threshold_pct: -5.0
  dump_pause_minutes: 60

  altcoin_breadth_min_pct: 30.0
  altcoin_breadth_sample_pairs:     # 🔄 CHANGED: USD pairs
    - ETH-USD
    - SOL-USD
    - BNB-USD
    - AVAX-USD
    - LINK-USD

  recovery_threshold_pct: 2.0

# ==============================================================================
# FEATURE 1.2: TIME-BASED TRADING RULES
# ==============================================================================

time_based_rules:
  enabled: false

  low_liquidity_hours: [0, 1, 2]
  low_liquidity_action: "monitor_only"

  high_liquidity_hours: [13, 14, 15, 16, 17, 18]
  high_liquidity_bonus_pct: 10.0

  max_total_size_multiplier: 1.2

  weekend_trading_enabled: true
  weekend_risk_multiplier: 0.5

  low_liquidity_overrides_weekend: true

  holidays: ["2025-12-25", "2026-01-01"]
  holiday_action: "reduce_size"
  holiday_risk_multiplier: 0.5

# ==============================================================================
# FEATURE 1.2b: LIQUIDITY-AWARE SMART SIZING
# ==============================================================================

liquidity_aware_sizing:
  enabled: true

  sizing_priority: ["low_liquidity", "holiday", "weekend", "time_bonus", "regime_bonus", "volatility_bonus"]
  base_size_calculation: "capital_pct_daily"

  cumulative_check_enabled: true
  cumulative_log_level: "WARNING"

  time_bonus_scalar:
    high_liquidity: 1.10
    normal_hours: 1.00
    low_liquidity: 0.70

  regime_bonus_scalar:
    strong_bull: 1.15
    neutral: 1.00
    weak_bear: 0.60

  volatility_bonus_scalar:
    high_vol: 0.85
    normal_vol: 1.00
    low_vol: 1.10

  max_cumulative_multiplier: 1.20

  log_sizing_calc: true
  log_format: "JSON"

# ==============================================================================
# FEATURE 1.3: PERFORMANCE TRACKING
# ==============================================================================

performance_tracking:
  enabled: true

  min_win_rate_pct: 45.0
  min_profit_factor: 1.2
  min_sharpe_ratio: 0.5
  max_drawdown_pct: 5.0

  lookback_trades: 20
  lookback_days: 7

  report_interval_hours: 4
  save_to_database: true

  track_per_symbol: true
  min_trades_per_symbol: 3

# ==============================================================================
# ORDERBOOK DEPTH-BASED LIQUIDITY PROXY
# ==============================================================================

orderbook_liquidity:
  enabled: true
  mode: live
  regime_aware: true
  depth_pct_range: 0.5
  depth_levels: 10
  min_depth_multiplier: 5.0
  use_for_ranking: true
  use_for_entry: true
  log_depth_metrics: true

# ==============================================================================
# ORDERBOOK PREFETCH
# ==============================================================================

orderbook_prefetch:
  enabled: true
  mode: live
  top_n: 30                          # Was 15 → 30 (moet >= max_coins_to_monitor zijn!)
  max_subscriptions_per_minute: 20

# ==============================================================================
# SMART ENTRY FILTER v2
# ==============================================================================

use_smart_entry_filter: true

smart_entry_filter:
  rsi_buy_max: 68.0              # 🛡️ Fallback: 68 (voorkom late pumps)
  rsi_extreme_low: 18.0
  rsi_block_min: 85.0

  vwap_max_deviation_pct: 18.0
  min_wick_ratio: 0.0

  max_atr_pct_for_grid: 7.0
  min_atr_pct_for_grid: 0.08

  max_5m_spike_pct: 4.0
  max_down_accel_pct: -8.0
  max_up_accel_pct: 4.0

  max_trend_24h_pct: 25.0          # 🔧 FIX: 35→25 (profiles override for memes)
  min_trend_24h_pct: -10.0

  max_entry_spread_pct: 0.3
  slippage_check_enabled: true

  min_depth_multiplier: 5.0
  depth_check_enabled: true

  # EPIC v3.4: MOMENTUM HEALTH GUARDS
  vwap_slope_guard_enabled: true
  vwap_slope_guard_shadow_mode: false
  vwap_slope_dual_confirmation: true

  parabolic_detector_enabled: true
  parabolic_detector_shadow_mode: false
  parabolic_cooldown_minutes: 60
  parabolic_cooldown_persist: true

  market_exhaustion_enabled: true
  market_exhaustion_threshold_pct: 0.70
  market_exhaustion_sample_size: 10
  market_exhaustion_cooldown_min: 30
  market_exhaustion_telegram: true

  momentum_thresholds:
    baseline:
      slope_min_pct_5m: 0.05
      slope_min_pct_15m: 0.02
      slope_max_pct_15m: 0.30
      dev_max_pct: 5.0
      accel_5m_min_pct: 1.0
      accel_5m_max_pct: 5.0
      accel_15m_max_pct: 8.0

    regimes:
      BULL:
        slope_min_pct_5m: 0.00
        slope_min_pct_15m: 0.02
        slope_max_pct_15m: 0.40
        dev_max_pct: 8.0
        accel_5m_max_pct: 7.0
        accel_15m_max_pct: 12.0

      CHOP:
        slope_min_pct_5m: 0.05
        slope_min_pct_15m: 0.03
        slope_max_pct_15m: 0.25
        dev_max_pct: 4.0
        accel_5m_max_pct: 4.0
        accel_15m_max_pct: 6.0

      BEAR:
        slope_min_pct_5m: 0.10
        slope_min_pct_15m: 0.05
        slope_max_pct_15m: 0.20
        dev_max_pct: 3.0
        accel_5m_max_pct: 3.0
        accel_15m_max_pct: 5.0

# ==============================================================================
# COIN PROFILES (USD pairs - will be populated as needed)
# ==============================================================================

coin_profiles:

  FET-USD:
    rsi_extreme_low: 20.0
    rsi_block_min: 76.0
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7           # Strakker: niet beide extreem
    vwap_max_deviation_pct: 14.0      # Midcap AI
    max_trend_24h_pct: 25.0

  SUI-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 15.0
    rsi_extreme_low: 18.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 25.0

  TAO-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7           # AI coin - midcap
    vwap_max_deviation_pct: 14.0      # Midcap AI
    rsi_extreme_low: 20.0
    rsi_block_min: 73.0
    max_trend_24h_pct: 22.0           # AI coins kunnen hard pumpen

  PEPE-USD:
    rsi_extreme_low: 18.0
    rsi_block_min: 80.0
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 20.0
    max_trend_24h_pct: 40.0

  AVAX-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7           # Iets strakker: niet beide extreem
    vwap_max_deviation_pct: 11.0     # Strakker: L1
    rsi_extreme_low: 22.0
    rsi_block_min: 74.0
    max_trend_24h_pct: 20.0

  LINK-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 9.0      # Strakker: stable oracle
    rsi_extreme_low: 23.0
    rsi_block_min: 72.0
    max_trend_24h_pct: 18.0

  DOT-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5
    vwap_max_deviation_pct: 9.0      # Strakker: stable L1
    rsi_extreme_low: 22.0
    rsi_block_min: 72.0
    max_trend_24h_pct: 18.0

  # NEAR-USD removed - in blacklist (no orderbook data)

  ATOM-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 10.0     # Strakker: stable cosmos
    rsi_extreme_low: 22.0
    rsi_block_min: 71.0
    max_trend_24h_pct: 18.0

  FTM-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7           # Iets strakker: niet beide extreem
    vwap_max_deviation_pct: 13.0
    rsi_extreme_low: 20.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 22.0

  SOL-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5
    vwap_max_deviation_pct: 10.0     # Strakker: large cap
    rsi_extreme_low: 22.0
    rsi_block_min: 71.0
    max_trend_24h_pct: 16.0
    max_5m_spike_pct: 1.8

  ADA-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 4
    vwap_max_deviation_pct: 9.0      # Strakker: stable large cap
    rsi_extreme_low: 23.0
    rsi_block_min: 72.0
    max_trend_24h_pct: 16.0

  XRP-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 9.0      # Strakker: large cap
    rsi_extreme_low: 22.0
    rsi_block_min: 71.0
    max_trend_24h_pct: 18.0

  POL-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5
    vwap_max_deviation_pct: 10.0     # Strakker: L2
    rsi_extreme_low: 22.0
    rsi_block_min: 70.0
    max_trend_24h_pct: 20.0

  LTC-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 4
    vwap_max_deviation_pct: 8.0      # Strakker: OG stable
    rsi_extreme_low: 24.0
    rsi_block_min: 70.0
    max_trend_24h_pct: 14.0

  BCH-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5
    vwap_max_deviation_pct: 8.0      # Strakker: OG stable
    rsi_extreme_low: 24.0
    rsi_block_min: 70.0
    max_trend_24h_pct: 14.0

  # PUMP-USD removed - in blacklist

  DYDX-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8           # Iets strakker
    vwap_max_deviation_pct: 13.0     # Midcap DeFi
    rsi_extreme_low: 22.0
    rsi_block_min: 76.0
    max_trend_24h_pct: 22.0

  XDC-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 10.0     # Strakker
    rsi_extreme_low: 24.0
    rsi_block_min: 70.0
    max_trend_24h_pct: 18.0

  SNX-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5.0
    vwap_max_deviation_pct: 10.0
    rsi_extreme_low: 25.0
    rsi_block_min: 74.0
    max_trend_24h_pct: 18.0
    max_5m_spike_pct: 1.5

  BTC-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 3
    vwap_max_deviation_pct: 6.0
    rsi_extreme_low: 25.0
    rsi_block_min: 68.0
    max_trend_24h_pct: 10.0
    max_5m_spike_pct: 1.2

  ETH-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 4
    vwap_max_deviation_pct: 7.5
    rsi_extreme_low: 24.0
    rsi_block_min: 70.0
    max_trend_24h_pct: 12.0
    max_5m_spike_pct: 1.3

  DOGE-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 18.0
    rsi_block_min: 80.0
    max_trend_24h_pct: 35.0
    max_5m_spike_pct: 1.8

  SHIB-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 22.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 40.0
    max_5m_spike_pct: 2.0

  # AAVE-USD removed - in blacklist (no orderbook data)

  UNI-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 22.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 18.0
    max_5m_spike_pct: 1.5

  INJ-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 22.0
    max_5m_spike_pct: 1.6

  RNDR-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 13.0
    rsi_extreme_low: 21.0
    rsi_block_min: 76.0
    max_trend_24h_pct: 22.0
    max_5m_spike_pct: 1.6

  ARB-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 78.0
    max_trend_24h_pct: 25.0
    max_5m_spike_pct: 1.7

  OP-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 78.0
    max_trend_24h_pct: 25.0
    max_5m_spike_pct: 1.7

  SEI-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 16.0
    rsi_extreme_low: 19.0
    rsi_block_min: 79.0
    max_trend_24h_pct: 30.0
    max_5m_spike_pct: 1.8

  WIF-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 11
    vwap_max_deviation_pct: 22.0
    rsi_extreme_low: 17.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 45.0
    max_5m_spike_pct: 2.2

  SAND-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 74.0
    max_trend_24h_pct: 20.0

  QNT-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5
    vwap_max_deviation_pct: 9.0
    rsi_extreme_low: 23.0
    rsi_block_min: 72.0
    max_trend_24h_pct: 16.0

  HBAR-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 10.0
    rsi_extreme_low: 22.0
    rsi_block_min: 72.0
    max_trend_24h_pct: 18.0

  MANA-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 74.0
    max_trend_24h_pct: 20.0

  PENGU-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 40.0

  0G-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 18.0
    rsi_block_min: 80.0
    max_trend_24h_pct: 35.0

  KTA-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 16.0
    rsi_extreme_low: 19.0
    rsi_block_min: 79.0
    max_trend_24h_pct: 30.0

  SENT-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  ALGO-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5
    vwap_max_deviation_pct: 9.0
    rsi_extreme_low: 23.0
    rsi_block_min: 72.0
    max_trend_24h_pct: 16.0

  FLR-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 10.0
    rsi_extreme_low: 22.0
    rsi_block_min: 73.0
    max_trend_24h_pct: 18.0

  DASH-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5
    vwap_max_deviation_pct: 9.0
    rsi_extreme_low: 23.0
    rsi_block_min: 71.0
    max_trend_24h_pct: 14.0

  BNB-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 4
    vwap_max_deviation_pct: 8.0
    rsi_extreme_low: 24.0
    rsi_block_min: 70.0
    max_trend_24h_pct: 14.0

  WLD-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  ICP-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 74.0
    max_trend_24h_pct: 20.0

  HYPE-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 18.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  BONK-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 22.0
    rsi_extreme_low: 17.0
    rsi_block_min: 83.0
    max_trend_24h_pct: 45.0

  AZTEC-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 15.0
    rsi_extreme_low: 19.0
    rsi_block_min: 78.0
    max_trend_24h_pct: 28.0

  FUN-USD:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

# ==============================================================================
# GRID CONFIGURATION
# ==============================================================================

grid_range_pct_down: 4.0
grid_range_pct_up: 12.0

num_grids: 5                      # 🔧 FIX: 7→5 (capital math: $300/4=$75, 5 grids=$15/level)

use_dynamic_grid_sizer: true

dynamic_grid_sizer:
  min_grids: 4                    # 🔧 FIX: 7→4 (allow smaller accounts)
  max_grids: 12                   # 🔧 FIX: 15→12 (order limit safety)
  low_vol_atr_pct: 0.7
  mid_vol_atr_pct: 2.0
  high_vol_atr_pct: 4.0

use_atr_grid_ranges: true
atr_multiplier_down: 1.5
atr_multiplier_up: 2.0

use_asymmetric_grids: true
smart_refill_threshold_pct: 3.0

# ==============================================================================
# TREND ENGINE
# ==============================================================================

use_multi_timeframe: true
trend_lookback_short_minutes: 60
trend_lookback_mid_minutes: 240
trend_lookback_long_minutes: 1440

switch_threshold_percent: 3.0
exit_short_threshold: -4.0
exit_mid_threshold: -3.0

trend_min_change_pct: 0.007
trend_min_entry_strength: 0.007

# ==============================================================================
# COIN ROTATION & MONITORING
# ==============================================================================

coin_rotation_threshold: 180
price_update_interval: 30

max_price_age_ms: 35000
max_orderbook_age_ms: 60000

max_coin_monitoring_seconds: 180
session_blacklist_duration_seconds: 7200

coin_discovery_refresh_interval_seconds: 3600

# ==============================================================================
# CAPITAL & RISK MANAGEMENT (USD - scaled appropriately)
# ==============================================================================
# 💡 TIP: Adjust these based on your USD balance
#    Example: $300 account → 3 slots × $100/coin
# ==============================================================================

max_simultaneous_coins: 4             # 🔧 FIX: 6→4 (order math: 4×7×2=56 < 60)

total_amount_quote: 300             # 🔄 CHANGED: $300 USD budget
min_order_amount_quote: 15          # $15 minimum order

risk_reference_balance_quote: 400   # 🔄 CHANGED: $400 reference
risk_max_daily_loss_pct: 30         # 30% daily loss limit (matches max_daily_loss_pct)
risk_max_balance_per_trade_pct: 60
risk_max_total_open_risk_pct: 75

max_exposure_per_coin_pct: 80
max_total_exposure_pct: 80

switch_grace_period_seconds: 180

# ==============================================================================
# PROFESSIONAL RISK MANAGEMENT
# ==============================================================================

use_professional_risk_mgmt: true

# STOP-LOSS UITGESCHAKELD - Grid krijgt ruimte voor DCA/mean-reversion
# Bescherming via: trend exit, emergency exit, time-based exit
stop_loss_pct: null
atr_stop_multiplier: 2.0
min_stop_pct: 0.02
max_stop_pct: 0.05

take_profit_pct: 0.05

time_based_stop_minutes: 360
time_stop_requires_stall: true
price_stall_threshold_atr: 0.3
min_minutes_since_last_fill: 45

min_rolling_pnl_pct: -0.02
min_win_rate_threshold: 0.35
pause_cooldown_minutes: 120
resume_min_pnl_pct: 0.0

min_grid_profit_pct: 0.8          # 🔧 FIX: 2.0→0.8 (Kraken 0.26%×2 + spread + buffer)

emergency_exit_pct: -12.0    # Alleen bij flash crash / exchange fuck-up / news-nuke
hard_stop_pct: -15.0          # Absolute laatste vangnet - niet bij normale volatiliteit

# ==============================================================================
# DRAWDOWN / KILL SWITCH
# ==============================================================================

max_daily_loss_pct: 30.0            # TIJDELIJK: Verhoogd naar 30% vanwege PnL tracking bug (20250214)
max_daily_loss_quote: 120.0         # Max daily loss in quote currency ($120 USD)
max_weekly_loss_pct: 7.0
max_monthly_loss_pct: 10.0

# ==============================================================================
# TELEGRAM ALERTS
# ==============================================================================

telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"

# ==============================================================================
# ORDER MANAGEMENT
# ==============================================================================

max_open_orders: 60               # 🔧 FIX: 30→60 (Kraken limit ~60)
order_frequency: 3

min_switch_interval_seconds: 600
min_hold_time_seconds: 3600       # 🔧 FIX: 7200→3600 (1h - clear progression)
max_hold_time_seconds: 21600      # 🔧 FIX: 14400→21600 (align with hard_hold)

# ==============================================================================
# TREND-AWARE EXIT SYSTEM (Soft/Hard Hold Time)
# ==============================================================================
# Prevents "dom verkopen" after fixed time when trend is still bullish
# After soft_hold: only exit if trend bearish OR pnl too negative
# After hard_hold: always exit (bag-holder prevention)
# ==============================================================================

soft_hold_time_seconds: 7200       # ⏰ 2 uur - trend-aware exit kicks in
hard_hold_time_seconds: 21600      # ⏰ 6 uur - always exit (bag-holder prevention)
soft_exit_min_trend_pct: 0.3       # 📈 Trend must be > 0.3% to extend hold
soft_exit_max_loss_pct: -1.5       # 📉 Exit even with good trend if loss > 1.5%
soft_exit_extend_seconds: 1800     # ⏳ Extend by 30 min if trend bullish

no_fill_timeout_sec: 1200
no_progress_timeout_sec: 5400    # 1.5 uur - meer ruimte voor herstel
no_progress_min_loss_pct: 2.5    # Niet bij mini verlies, alleen bij echte stagnatie
no_progress_atr_multiplier: 1.5
close_grace_sec: 120

min_startup_wait_seconds: 60

smart_switch_k: 2.0
switch_cost_multiplier: 2.5

# ==============================================================================
# DEBUG TRACE SYSTEM
# ==============================================================================

debug_trace_enabled: true
debug_trace_format: compact
debug_trace_log_accepted: false
debug_trace_log_rejected: true

# ==============================================================================
# OBSERVABILITY
# ==============================================================================

observability:
  structured_events_enabled: true
  events_output_dir: "logs/events_usd"  # 🔄 CHANGED: Separate events dir
  buffer_size: 100
  why_no_trade_report_enabled: true
  report_interval_seconds: 3600

# ==============================================================================
# DYNAMIC SLOT MANAGER
# ==============================================================================

dynamic_slots:
  enabled: true
  min_slots: 1
  max_slots: 12
  regime_multipliers:
    BULL: 1.5
    CHOP: 0.75
    BEAR: 0.25
```

## Attachment: Config YAML — Bitget Spot (1,456 lines)

```yaml
# ==============================================================================
# BITGET SPOT GRID CONFIG - Based on Kraken v3.3
# All advanced features enabled (Market Regime, Time Rules, Smart Sizing, etc.)
# Last updated: 2025-12-16
# ==============================================================================

controller_name: spot_grid_bitget
log_level: INFO

# ==============================================================================
# DEBUG & TRACING
# ==============================================================================

debug_trace_enabled: true          # 🔍 Enable decision trace logging
debug_trace_format: compact        # compact | detailed | json
debug_trace_log_accepted: false    # Only log rejections (reduces noise)
debug_trace_log_rejected: true     # Always log rejections

# ==============================================================================
# OBSERVABILITY (Phase 1A - Structured Events)
# ==============================================================================

observability:
  structured_events_enabled: true   # ✅ ENABLED: Track all decisions for analysis
  events_output_dir: "logs/events"
  buffer_size: 100
  why_no_trade_report_enabled: true   # ✅ ENABLED: Debug waarom geen trades
  report_interval_seconds: 3600

# ==============================================================================
# ORDERBOOK PREFETCH (Smart Subscription Strategy)
# ==============================================================================
# Pre-warms orderbook data for top candidates BEFORE SmartEntry validation.
# Only subscribes to:
#   - Active grids (1-2 pairs currently trading)
#   - Top N candidates (default: 5 best trend scores)
# Total max subscriptions: ~7 pairs (not all 15!)
# ==============================================================================

orderbook_prefetch:
  enabled: true                       # 🚀 TASK 1.0: Enable smart prefetch
  mode: 'live'                        # 'live' = actually subscribe | 'shadow' = log only
  top_n: 30                           # Was 5 → 30 (moet >= max_coins_to_monitor zijn!)
  max_subscriptions_per_minute: 20   # Was 10 → 20 (meer headroom)

# ==============================================================================
# DYNAMIC SLOT MANAGER (Task 3.1: Account-Size + Regime-Aware Slots)
# ==============================================================================
# Automatically scales max simultaneous trading slots based on:
#   1. Account balance (€350 → 4 slots, €1000 → 6, €2000 → 8)
#   2. Market regime (BULL 1.5x, CHOP 0.75x, BEAR 0.25x)
#
# Example: €1000 account
#   - baseline: 6 slots
#   - BULL: 9 slots (6 * 1.5)
#   - CHOP: 4 slots (6 * 0.75)
#   - BEAR: 1 slot (6 * 0.25)
# ==============================================================================

# dynamic_slots:
#   enabled: true                       # 🚀 Enable dynamic slot scaling
#   min_slots: 1                        # Minimum slots (always trade at least 1)
#   max_slots: 12                       # Maximum slots (resource constraint)
#   regime_multipliers:
#     BULL: 1.5                         # +50% slots in bull market
#     CHOP: 0.75                        # -25% slots in choppy market
#     BEAR: 0.25                        # Defensive: only 1 slot typically

# ==============================================================================
# ADAPTIVE REGIME DETECTION (Phase 1: Logging Only)
# ==============================================================================

adaptive_regime_detection:
  enabled: true                    # Enable regime detection
  logging_only: false              # PHASE 2: Apply adaptive filters based on regime

  # Regime classification thresholds
  bull_score_min: 5.0              # Score >= 5 → BULL
  chop_score_min: -3.0             # Score in [-3, 5] → CHOP
  bear_score_max: -3.0             # Score < -3 → BEAR
  min_confidence: 0.65             # Minimum confidence to classify

  # Hysteresis settings (prevent flip-flopping)
  bull_min_duration_sec: 1800      # 30 min minimum in BULL
  chop_min_duration_sec: 900       # 15 min minimum in CHOP
  bear_min_duration_sec: 1800      # 30 min minimum in BEAR
  hysteresis_buffer: 1.0           # Score buffer for regime exit

  # Logging
  log_regime_changes: true
  log_filter_updates: true

adaptive_filters:
  # Baseline filters (RELAXED for bull market - versoepl voor meer trades)
  baseline:
    rsi_buy_min: 25.0
    rsi_buy_max: 68.0               # 🛡️ Baseline: 68 (voorkom late pumps)
    rsi_extreme_min: 18.0           # 🔧 FIX: 15→18 (less aggressive oversold)
    vwap_max_deviation_pct: 25.0    # 🔧 FIX: 35→25 (reduce trend-chasing)
    max_up_accel_pct: 5.0           # 🚀 3.5→5 (strong momentum)
    max_down_accel_pct: -8.0        # 🔧 FIX: -12→-8 (avoid falling knives)
    atr_min_pct: 0.08               # 🔧 FIX: 0.10→0.08 (align with smart_entry)
    atr_max_pct: 7.0                # 🔧 FIX: 8→7 (safer for SPOT)
    spike_5m_max_pct: 4.0           # 🔧 FIX: 3.5→4.0 (align with smart_entry)
    wick_ratio_min: 0.0
    grid_spacing_mult: 1.0
    max_active_grids: 4             # 🚀 TASK 1.2: 2→4 (was 2)
    entry_confidence_min: 0.65      # 🚀 0.70→0.65 (lower bar for entry)

  # BULL regime: very relaxed filters for bull market
  BULL:
    rsi_buy_max: 72.0               # 🛡️ Bull: 72 (iets ruimer voor momentum)
    vwap_max_deviation_pct: 40.0    # 🚀 30→40 (extreme memecoin pumps)
    max_up_accel_pct: 7.0           # 🚀 5→7 (very strong momentum)
    max_down_accel_pct: -15.0       # 🚀 -6→-15 (deep dips OK in bull)
    atr_min_pct: 0.08               # 🚀 0.10→0.08 (more coins)
    spike_5m_max_pct: 5.0           # 🚀 3.5→5 (big moves OK)
    grid_spacing_mult: 1.2
    max_active_grids: 6             # 🚀 TASK 1.2: 3→6 (was 3)
    entry_confidence_min: 0.55      # 🚀 0.60→0.55 (lower bar)

  # CHOP regime: moderate filters (not too strict)
  CHOP:
    rsi_buy_max: 68.0               # 🛡️ Chop: 68 (gelijk aan baseline)
    vwap_max_deviation_pct: 18.0    # 🚀 10→18 (allow altcoin rotations)
    max_up_accel_pct: 2.5           # 🚀 1.8→2.5 (momentum OK)
    max_down_accel_pct: -4.0        # 🚀 -2.5→-4 (deeper dips OK)
    atr_min_pct: 0.10               # 🚀 0.12→0.10
    spike_5m_max_pct: 3.0           # 🚀 2.5→3 (bigger moves)
    grid_spacing_mult: 0.8
    max_active_grids: 3             # 🚀 TASK 1.2: 2→3 (was 2)
    entry_confidence_min: 0.70      # 🚀 0.75→0.70

  # BEAR regime: relaxed to allow counter-trend altcoin pumps
  BEAR:
    rsi_buy_max: 62.0               # 🛡️ Bear: 62 (strengst)
    vwap_max_deviation_pct: 8.0     # 🔧 FIX: 3.5→8.0 (allow counter-trend pumps)
    max_up_accel_pct: 1.5           # 🔧 FIX: 0.5→1.5 (allow counter-trend momentum)
    max_down_accel_pct: -2.0        # 🔧 FIX: -1.0→-2.0 (allow pullbacks)
    atr_min_pct: 0.12               # 🔧 FIX: 0.15→0.12
    spike_5m_max_pct: 2.0           # 🔧 FIX: 1.0→2.0 (allow bigger moves)
    grid_spacing_mult: 1.5
    max_active_grids: 1             # 🔧 FIX: 0→1 (allow 1 grid even in BEAR)
    entry_confidence_min: 0.80      # 🔧 FIX: 0.90→0.80 (slightly relaxed)
    bear_allow_meanrev: true        # 🔧 FIX: false→true (allow counter-trend trades)

# === EXCHANGE CONFIGURATION ===
paper_trading: false              # Set to true for testing
connector_name: bitget            # Bitget SPOT connector
quote_asset: USDT                 # Quote currency

# ==============================================================================
# BITGET SPOT GRID — LIQUID UNIVERSE PRESET
# Purpose: Stable, high-liquidity trading universe for Bitget
# Reason: Bitget API has no reliable 24h volume via ticker
# Strategy: Manual universe + SmartEntry + MTF protection
# ==============================================================================

use_dynamic_pair_discovery: true   # ❌ Disable dynamic discovery (volume = 0 issue)
max_coins_to_monitor: 30            # Was 25 → 30 (match met top_n)

# ==============================================================================
# STALENESS GUARD (US-008) - Prevent trading on stale data
# ==============================================================================
max_price_age_ms: 35000             # 35 sec (must be > price_update_interval)
max_orderbook_age_ms: 60000          # 60 sec
exclude_expensive_coins: false
min_24h_volume_usdt: 500000         # 🚀 Higher volume = more liquid (was 0, but broken API)

# US-007: Dynamic Pair Manager (two-tier discovery: REST scans all, WebSocket for best)
use_dynamic_pair_manager: true       # Enable two-tier pair discovery
pair_scan_interval_seconds: 300      # Interval between REST scans (5 min)
max_spread_pct: 0.5                  # Maximum bid-ask spread filter

# Bitget-specific fee overrides (Bitget standard fees)
bitget_maker_fee_pct: 0.001  # 0.1% maker fee
bitget_taker_fee_pct: 0.001  # 0.1% taker fee

# Bitget rate limiting
rate_limit_buffer: 0.8  # Use 80% of rate limit (conservative)
order_refresh_time: 30  # Seconds between order refreshes

blacklist:
  - USDC-USDT    # Stablecoin pairs
  - BUSD-USDT
  - DAI-USDT
  - TUSD-USDT
  - FDUSD-USDT
  - USDT-USD
  - BTC-USD      # Wrong quote
  - ETH-USD
  # Non-existent pairs on Bitget (cause API errors)
  - OORT-USDT
  - FIS-USDT
  - NFP-USDT
  # Low liquidity pairs - cause "Can't parse order status" errors
  - IRYS-USDT
  - AXS-USDT
  - IDOL-USDT

# ==============================================================================
# DYNAMIC COIN DISCOVERY - Now works for Bitget!
# ==============================================================================
# Custom Bitget ticker fetcher implemented in _get_bitget_ticker_data()
# Uses Bitget's /api/v2/spot/market/tickers endpoint for volume data
# Empty list = dynamic discovery mode (auto-select top volume USDT pairs)
# ==============================================================================
manual_trading_pairs: []

#   # --- Tier 4 (Optional, still liquid) ---
#   - LTC-USDT
#   - BCH-USDT
#   - ATOM-USDT
#   - UNI-USDT


# ==============================================================================
# MULTI-TIMEFRAME BUY PROTECTION (PREVENT KAS-EUR DISASTER)
# ==============================================================================

use_multi_timeframe_buy: true      # ENABLE multi-timeframe checks voor entries
mtf_1h_min_pct: -3.0               # 🔧 RELAXED: 1h mag -3% pullback (catch strong consensus opportunities)
mtf_4h_min_pct: -2.5               # 🔧 RELAXED: 4h mag -2.5% pullback (allows rotation to better coins)
mtf_24h_min_pct: -2.5              # 🔧 RELAXED: 24h mag -2.5% pullback (STBL-EUR fix: -2.55% was blocked)
mtf_declining_1h_max: -4.0         # Als 1h < -4% EN 4h < -2% → REJECT (crash protection)
mtf_declining_4h_max: -2.0         # (prevents trading during severe crashes)

# ==============================================================================
# WARMUP TREND OVERRIDE – PRO PULLBACK MODE
# ==============================================================================

warmup_override_enabled: true
warmup_4h_strong_min: -2.5        # 🔧 FIX: -0.5→-2.5 (match mtf_4h_min_pct for multi-coin trading)
warmup_1h_min_if_4h_strong: -3.0  # 🔧 FIX: -2.0→-3.0 (match mtf_1h_min_pct for pullback entries)

# ==============================================================================
# FEATURE 1.1: MARKET REGIME FILTER - BTC Trend Following
# ==============================================================================

market_regime:
  enabled: true                    # ✅ ENABLED: BTC trend protection
  btc_symbol: "BTC-USDT"          # USDT pairs for Bitget

  # BTC trend thresholds
  btc_trend_1h_min_pct: -2.0
  btc_trend_4h_min_pct: 0.0
  btc_trend_24h_min_pct: -5.0

  # BTC dump detection
  dump_threshold_pct: -5.0
  dump_pause_minutes: 60

  # Altcoin market breadth
  altcoin_breadth_min_pct: 30.0
  altcoin_breadth_sample_pairs:
    - ETH-USDT
    - SOL-USDT
    - BNB-USDT
    - AVAX-USDT
    - LINK-USDT

  # Recovery detection
  recovery_threshold_pct: 2.0

# ==============================================================================
# FEATURE 1.2: TIME-BASED TRADING RULES
# ==============================================================================

time_based_rules:
  enabled: false

  # Low liquidity hours (UTC)
  low_liquidity_hours: [0, 1, 2]
  low_liquidity_action: "monitor_only"

  # High liquidity window (UTC)
  high_liquidity_hours: [13, 14, 15, 16, 17, 18]
  high_liquidity_bonus_pct: 10.0

  # Size multiplier cap
  max_total_size_multiplier: 1.2

  # Weekend behavior
  weekend_trading_enabled: true
  weekend_risk_multiplier: 0.5

  # Conflict resolution
  low_liquidity_overrides_weekend: true

  # Holidays
  holidays: ["2025-12-25", "2026-01-01"]
  holiday_action: "reduce_size"
  holiday_risk_multiplier: 0.5

# ==============================================================================
# FEATURE 1.2b: LIQUIDITY-AWARE SMART SIZING
# ==============================================================================

liquidity_aware_sizing:
  enabled: true

  sizing_priority: ["low_liquidity", "holiday", "weekend", "time_bonus", "regime_bonus", "volatility_bonus"]
  base_size_calculation: "capital_pct_daily"

  cumulative_check_enabled: true
  cumulative_log_level: "WARNING"

  # Time-based component
  time_bonus_scalar:
    high_liquidity: 1.10
    normal_hours: 1.00
    low_liquidity: 0.70

  # Market regime bonus
  regime_bonus_scalar:
    strong_bull: 1.15
    neutral: 1.00
    weak_bear: 0.60

  # Volatility-based sizing
  volatility_bonus_scalar:
    high_vol: 0.85
    normal_vol: 1.00
    low_vol: 1.10

  # Final cap
  max_cumulative_multiplier: 1.20

  # Logging
  log_sizing_calc: true
  log_format: "JSON"

# ==============================================================================
# FEATURE 1.3: PERFORMANCE TRACKING
# ==============================================================================

performance_tracking:
  enabled: true

  # Performance thresholds
  min_win_rate_pct: 45.0
  min_profit_factor: 1.2
  min_sharpe_ratio: 0.5
  max_drawdown_pct: 5.0

  # Analysis windows
  lookback_trades: 20
  lookback_days: 7

  # Reporting
  report_interval_hours: 4
  save_to_database: true

  # Per-symbol breakdown
  track_per_symbol: true
  min_trades_per_symbol: 3

# ==============================================================================
# ORDERBOOK DEPTH-BASED LIQUIDITY PROXY (Phase 2: LIVE - Active Filtering)
# ==============================================================================

orderbook_liquidity:
  enabled: true                    # ✅ ENABLED: Fixed "unknown ≠ illiquid" bug in trend_calculator
  mode: live                       # 🚀 LIVE MODE: Active depth filtering (unknown data doesn't block)
  regime_aware: true              # Phase 4: adaptive thresholds (BULL=8x, CHOP=5x, BEAR=10x)
  depth_pct_range: 0.5            # ±0.5% around mid price for depth calculation
  depth_levels: 10                # Top N orderbook levels per side to analyze
  min_depth_multiplier: 5.0       # 🔧 FIX: 3→5 (consistent met smart_entry_filter)
  use_for_ranking: true          # Phase 2: disabled (ranking feature)
  use_for_entry: true             # ✅ ENABLED: Only blocks on confirmed insufficient depth (not unknown data)
  log_depth_metrics: true         # Log depth metrics for all evaluated coins

# ==============================================================================
# ORDERBOOK PREFETCH (Phase 2: LIVE - Active Prefetching)
# ==============================================================================

# ==============================================================================
# DYNAMIC SLOT MANAGER (Task 3.1: Account-Size + Regime-Aware Slots)
# ==============================================================================
# Automatically scales max simultaneous trading slots based on:
#   1. Account balance ($350 → 4 slots, $1000 → 6, $2000 → 8)
#   2. Market regime (BULL 1.5x, CHOP 0.75x, BEAR 0.25x)
# ==============================================================================

dynamic_slots:
  enabled: true                       # 🚀 Enable dynamic slot scaling
  min_slots: 1                        # Minimum slots (always trade at least 1)
  max_slots: 12                       # Maximum slots (resource constraint)
  regime_multipliers:
    BULL: 1.5                         # +50% slots in bull market
    CHOP: 0.75                        # -25% slots in choppy market
    BEAR: 0.25                        # Defensive: only 1 slot typically

# ==============================================================================
# SMART ENTRY FILTER v2
# ==============================================================================

use_smart_entry_filter: true

smart_entry_filter:
  # RSI - Use adaptive regime filters instead of static values
  # These are fallback values when adaptive regime detection is disabled
  rsi_buy_max: 68.0                # 🛡️ Fallback: 68 (voorkom late pumps)
  rsi_extreme_low: 15.0            # 🚀 25→15 (catch oversold)
  rsi_block_min: 85.0              # 🚀 80→85 (higher ceiling)

  # VWAP / candles
  vwap_max_deviation_pct: 25.0     # 🔧 FIX: 35→25 (reduce trend-chasing, profiles override)
  min_wick_ratio: 0.0              # Keep 0 (body-dominant OK)

  # Volatiliteit / ATR
  max_atr_pct_for_grid: 7.0        # 🔧 FIX: 8→7 (profiles override for memes)
  min_atr_pct_for_grid: 0.08       # 🚀 0.10→0.08 (more coins qualify)

  # Short-term spikes
  max_5m_spike_pct: 4.0            # 🔧 FIX: 5→4 (profiles override for memes)
  max_down_accel_pct: -8.0         # 🔧 FIX: -12→-8 (avoid falling knives)
  max_up_accel_pct: 5.0            # 🚀 3.5→5 (strong momentum)

  # 24h trend bounds
  max_trend_24h_pct: 25.0          # 🔧 FIX: 40→25 (profiles override for memes)
  min_trend_24h_pct: -10.0

  # Slippage Protection (single source of truth)
  max_entry_spread_pct: 0.5        # 0.3% max spread (tighter for Bitget)
  slippage_check_enabled: true

  # Order Book Depth Protection
  min_depth_multiplier: 5.0       # 🔧 FIX: 3→5 (consistent met orderbook_liquidity)
  depth_check_enabled: true

  # ==============================================================================
  # EPIC v3.4: MOMENTUM HEALTH GUARDS (Stories 1-11)
  # ==============================================================================

  # VWAP Slope Guard (Story 2 + Story 9: Dual-Window Confirmation)
  vwap_slope_guard_enabled: true    # ✅ Enabled in shadow mode
  vwap_slope_guard_shadow_mode: true  # Log decisions without blocking
  vwap_slope_dual_confirmation: true  # ✅ Story 9: Require both 5m AND 15m slopes flat

  # Parabolic Detector + Cooldown (Story 3 + Story 10: Persistence)
  parabolic_detector_enabled: true   # ✅ Enabled in shadow mode
  parabolic_detector_shadow_mode: true  # Log detections without blocking
  parabolic_cooldown_minutes: 60     # 1 hour cooldown after parabolic detection
  parabolic_cooldown_persist: true   # ✅ Story 10: Persist cooldowns to SQLite

  # Market Exhaustion Warning (Story 11)
  market_exhaustion_enabled: true   # ✅ Monitor market-wide parabolic conditions
  market_exhaustion_threshold_pct: 0.70  # 70% of top coins must be parabolic
  market_exhaustion_sample_size: 10      # Evaluate top 10 candidates
  market_exhaustion_cooldown_min: 30     # Rate limit: 1 alert per 30 minutes
  market_exhaustion_telegram: true       # Send Telegram alerts

  # Baseline Thresholds (Story 5 + Story 9: Dual-Window)
  momentum_thresholds:
    baseline:
      slope_min_pct_5m: 0.05         # ✅ Story 9: 0.05% minimum 5m VWAP slope
      slope_min_pct_15m: 0.02        # 0.02% minimum 15m VWAP slope (safety floor)
      slope_max_pct_15m: 0.30        # 0.30% maximum VWAP slope
      dev_max_pct: 5.0               # 5% max deviation from VWAP
      accel_5m_min_pct: 1.0          # 1% minimum 5m acceleration (safety floor)
      accel_5m_max_pct: 5.0          # 5% maximum 5m acceleration
      accel_15m_max_pct: 8.0         # 8% maximum 15m acceleration

    # Regime-aware overrides (Story 5 + Story 9)
    regimes:
      BULL:
        slope_min_pct_5m: 0.00       # Allow flat 5m in bull (lenient)
        slope_min_pct_15m: 0.02      # Slightly higher 15m requirement
        slope_max_pct_15m: 0.40      # Allow steeper slopes in bull
        dev_max_pct: 8.0             # Allow more deviation in bull
        accel_5m_max_pct: 7.0        # Allow faster acceleration
        accel_15m_max_pct: 12.0

      CHOP:
        slope_min_pct_5m: 0.05       # Require some momentum in chop
        slope_min_pct_15m: 0.03
        slope_max_pct_15m: 0.25      # Conservative in chop
        dev_max_pct: 4.0
        accel_5m_max_pct: 4.0
        accel_15m_max_pct: 6.0

      BEAR:
        slope_min_pct_5m: 0.10       # Require strong momentum in bear
        slope_min_pct_15m: 0.05
        slope_max_pct_15m: 0.20      # Very conservative in bear
        dev_max_pct: 3.0
        accel_5m_max_pct: 3.0
        accel_15m_max_pct: 5.0

# ==============================================================================
# COIN PROFILES (Bitget USDT pairs - inherit from Kraken patterns)
# ==============================================================================

coin_profiles:

  SOL-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5
    vwap_max_deviation_pct: 10.0   # 🔧 Tighter for L1
    rsi_extreme_low: 22.0          # ✅ Added
    rsi_block_min: 71.0
    max_trend_24h_pct: 16.0         # ✅ Added - safer than global
    max_5m_spike_pct: 1.8

  AVAX-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7          # 🔧 FIX: 8→7 (L1 stability)
    vwap_max_deviation_pct: 11.0     # 🔧 FIX: 12→11
    rsi_extreme_low: 22.0
    rsi_block_min: 74.0
    max_trend_24h_pct: 20.0          # ✅ Added

  LINK-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 9.0      # 🔧 FIX: 12→9 (stable oracle)
    rsi_extreme_low: 23.0
    rsi_block_min: 72.0
    max_trend_24h_pct: 18.0          # ✅ Added

  SUI-USDT:
    min_wick_ratio: 0.15           # Relaxed from 0.40
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 15.0   # 🔧 FIX: 3.0→15.0 (L1 volatile moves)
    rsi_extreme_low: 18.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 50.0        # 🚀 25.0→50.0 (allow extreme bull moves)

  # === TIER 1: Large Cap Stable (ATR 3-4) ===
  BTC-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 3
    vwap_max_deviation_pct: 6.0
    rsi_extreme_low: 25.0
    rsi_block_min: 68.0
    max_trend_24h_pct: 10.0
    max_5m_spike_pct: 1.2

  ETH-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 4
    vwap_max_deviation_pct: 7.5
    rsi_extreme_low: 24.0
    rsi_block_min: 70.0
    max_trend_24h_pct: 12.0
    max_5m_spike_pct: 1.3

  BNB-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 4
    vwap_max_deviation_pct: 8.0
    rsi_extreme_low: 24.0
    rsi_block_min: 70.0
    max_trend_24h_pct: 14.0

  LTC-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 4
    vwap_max_deviation_pct: 8.0
    rsi_extreme_low: 23.0
    rsi_block_min: 71.0
    max_trend_24h_pct: 14.0

  PAXG-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 2
    vwap_max_deviation_pct: 4.0
    rsi_extreme_low: 28.0
    rsi_block_min: 65.0
    max_trend_24h_pct: 6.0

  XAUT-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 2
    vwap_max_deviation_pct: 4.0
    rsi_extreme_low: 28.0
    rsi_block_min: 65.0
    max_trend_24h_pct: 6.0

  # === TIER 2: Mid-Large Cap (ATR 4-6) ===
  ADA-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 4
    vwap_max_deviation_pct: 9.0
    rsi_extreme_low: 23.0
    rsi_block_min: 72.0
    max_trend_24h_pct: 16.0

  AAVE-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 10.0
    rsi_extreme_low: 22.0
    rsi_block_min: 74.0
    max_trend_24h_pct: 16.0

  ZEC-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 5
    vwap_max_deviation_pct: 9.0
    rsi_extreme_low: 23.0
    rsi_block_min: 72.0
    max_trend_24h_pct: 16.0

  YFI-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 10.0
    rsi_extreme_low: 22.0
    rsi_block_min: 74.0
    max_trend_24h_pct: 18.0

  TRX-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 4
    vwap_max_deviation_pct: 8.0
    rsi_extreme_low: 24.0
    rsi_block_min: 70.0
    max_trend_24h_pct: 14.0

  DOGE-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 16.0
    rsi_extreme_low: 19.0
    rsi_block_min: 78.0
    max_trend_24h_pct: 30.0

  # === TIER 3: Mid Cap DeFi/L1 (ATR 6-7) ===
  STX-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 20.0

  ONDO-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 13.0
    rsi_extreme_low: 21.0
    rsi_block_min: 76.0
    max_trend_24h_pct: 22.0

  UNI-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 22.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 18.0

  COMP-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 22.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 18.0

  TAO-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 76.0
    max_trend_24h_pct: 22.0

  CHZ-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 6
    vwap_max_deviation_pct: 11.0
    rsi_extreme_low: 22.0
    rsi_block_min: 74.0
    max_trend_24h_pct: 18.0

  SUSHI-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 20.0

  API3-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 20.0

  ASTR-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 20.0

  BLUR-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  DYM-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  CFX-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 20.0

  LQTY-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 20.0

  # === TIER 4: Mid-Small Cap Volatile (ATR 7-8) ===
  ZRO-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  JUP-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 15.0
    rsi_extreme_low: 19.0
    rsi_block_min: 78.0
    max_trend_24h_pct: 26.0

  STRK-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  MORPHO-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  HYPE-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 16.0
    rsi_extreme_low: 18.0
    rsi_block_min: 80.0
    max_trend_24h_pct: 30.0

  SONIC-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  BGB-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 20.0

  SWELL-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  ZETA-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  ALT-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  PIXEL-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  # === TIER 5: High Volatility / Memes (ATR 9-10) ===
  WIF-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0
    max_5m_spike_pct: 2.0

  PUMP-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  GOAT-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 16.0
    rsi_block_min: 83.0
    max_trend_24h_pct: 40.0

  FARTCOIN-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 15.0
    rsi_block_min: 85.0
    max_trend_24h_pct: 45.0

  ELON-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 16.0
    rsi_block_min: 83.0
    max_trend_24h_pct: 40.0

  PNUT-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  ACT-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  GRASS-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  BAN-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  HIPPO-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  SNEK-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  # === TIER 6: Microcap / New Coins (ATR 8-10) ===
  SWEAT-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 15.0
    rsi_extreme_low: 19.0
    rsi_block_min: 78.0
    max_trend_24h_pct: 28.0

  HOME-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  ALCH-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  B2-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  SPACE-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  LA-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  H-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  BTR-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  IKA-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  SWCH-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  RIVER-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  WARD-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  BIRB-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  TCOM-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  A47-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  STO-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  US-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  ASTER-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  FF-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  SENT-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  AIA-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  FHE-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  PEAQ-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  LUMIA-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  DBR-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  VELODROME-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  CHESS-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  NKN-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 20.0

  THE-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  IO-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

  NS-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  IOST-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 7
    vwap_max_deviation_pct: 12.0
    rsi_extreme_low: 21.0
    rsi_block_min: 75.0
    max_trend_24h_pct: 20.0

  AVA-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  TRU-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  SOLO-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  PROPS-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 10
    vwap_max_deviation_pct: 20.0
    rsi_extreme_low: 16.0
    rsi_block_min: 84.0
    max_trend_24h_pct: 40.0

  RARE-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 8
    vwap_max_deviation_pct: 14.0
    rsi_extreme_low: 20.0
    rsi_block_min: 77.0
    max_trend_24h_pct: 24.0

  AI-USDT:
    min_wick_ratio: 0.00
    max_atr_pct_for_grid: 9
    vwap_max_deviation_pct: 18.0
    rsi_extreme_low: 17.0
    rsi_block_min: 82.0
    max_trend_24h_pct: 35.0

# ==============================================================================
# GRID CONFIGURATION (Hybrid Grid Engine)
# ==============================================================================

# 🎯 WIDER GRID for trending markets (aangepast voor bull)
grid_range_pct_down: 2.0          # 🚀 0.8→2.0% (wider for pullbacks)
grid_range_pct_up: 5.0            # 🚀 1.2→5.0% (wider for uptrends)

num_grids: 7                      # 🔧 FIX: 10→7 (order math: 6×7×2=84)

use_dynamic_grid_sizer: true

dynamic_grid_sizer:
  min_grids: 5                    # 🔧 FIX: 3→5 (minimum viable grid)
  max_grids: 10                   # 🔧 FIX: 15→10 (order limit safety)
  low_vol_atr_pct: 0.7
  mid_vol_atr_pct: 2.0
  high_vol_atr_pct: 4.0

# ✅ ATR-based dynamic grid ranges
use_atr_grid_ranges: true         # ✅ ENABLED: Dynamic ATR-based grid ranges
atr_multiplier_down: 1.5
atr_multiplier_up: 2.0

use_asymmetric_grids: true
smart_refill_threshold_pct: 3.0

# ==============================================================================
# TREND ENGINE (voor coin selectie)
# ==============================================================================

use_multi_timeframe: true
trend_lookback_short_minutes: 60
trend_lookback_mid_minutes: 240
trend_lookback_long_minutes: 1440

switch_threshold_percent: 3.0
exit_short_threshold: -4.0          # 🔧 FIX: -1.5→-4.0 (was TE gevoelig, premature exits!)
exit_mid_threshold: -3.0            # 🔧 FIX: -1.2→-3.0 (was TE gevoelig, premature exits!)

trend_min_change_pct: 0.0015       # 🔧 FIX: Default 0.5→0.0015 (0.15% - logged as "Looking for trend")
trend_min_entry_strength: 0.0015  # 🔧 FIX: 0.010→0.0015 (0.15% - allow weak trends for more evaluations)

# ==============================================================================
# COIN ROTATION & MONITORING
# ==============================================================================

coin_rotation_threshold: 180        # 🚀 FIX: 180→60 (2 min - faster rotation)
price_update_interval: 30

max_coin_monitoring_seconds: 180   # 🚀 FIX: 300→120 (2 min - faster timeout)
session_blacklist_duration_seconds: 7200

# PERIODIC COIN DISCOVERY: Auto-refresh coin pool during runtime
coin_discovery_refresh_interval_seconds: 3600  # 1 hour (3600s), set to 0 to disable
# 💡 Scant elk uur ALLE beschikbare USDT pairs op Bitget en vernieuwd de pool
# Nieuwe trending coins worden automatisch ontdekt zonder herstart!

# ==============================================================================
# CAPITAL & RISK MANAGEMENT (Grid-Aware)
# ==============================================================================
# 🚀 FULLY DYNAMIC: Bot automatically calculates optimal coins & grids
# based on your ACTUAL available balance. These are MAX values.
# With €79 → 1 coin, 6 grids | With €5000 → 6 coins, 10 grids
# ==============================================================================

max_simultaneous_coins: 6         # 🔧 FIX: 12→6 (order math: 6×7×2=84 < 100)

total_amount_quote: 50000         # 🚀 MAX capital (uses actual balance if lower)
risk_reference_balance_quote: 50000  # Reference for risk calculations
risk_max_daily_loss_pct: 30         # 30% daily loss limit (matches max_daily_loss_pct)
min_order_amount_quote: 10        # $10 per order (Bitget minimum)

risk_max_balance_per_trade_pct: 100.0  # 100% per coin (2 coins = $140 total)
risk_max_total_open_risk_pct: 100.0    # 100% total exposure (2 × $70)

max_exposure_per_coin_pct: 50.0   # Each coin: 50% van $140 = $70
max_total_exposure_pct: 100.0      # Totaal: 100% van $140 = $140 (2 coins × $70)

# Grace period: Give positions time to develop before switching (professional practice)
switch_grace_period_seconds: 180   # 🚀 TASK 1.1: 7min→3min (faster rotations, was 420)

# ==============================================================================
# PROFESSIONAL RISK MANAGEMENT (Grid-Aware v2)
# ==============================================================================
# ✅ Fixed: max→clamp for ATR stops, drawdown-based profit tiers, no-fills check, pause cooldown

use_professional_risk_mgmt: true

# STOP-LOSS UITGESCHAKELD - Grid krijgt ruimte voor DCA/mean-reversion
# Bescherming via: trend exit, emergency exit, time-based exit
stop_loss_pct: null
atr_stop_multiplier: 2.0          # 2×ATR dynamic stop
min_stop_pct: 0.02                # Min -2% (never too tight for BTC)
max_stop_pct: 0.05                # Max -5% (conservative cap for grid trading)
# Examples: BTC 1.2% ATR → -2.4%, RENDER 3.5% ATR → -7%, 10% ATR → capped to -8%

take_profit_pct: 0.05             # 5% TP (realistisch voor huidige markt)

# Context-Aware Time Exits (stall + no fills check)
time_based_stop_minutes: 360      # 6 hours (grids need time!)
time_stop_requires_stall: true    # Only exit if stalled OR no fills
price_stall_threshold_atr: 0.3    # Movement < 0.3×ATR = stalled
min_minutes_since_last_fill: 45   # Dead liquidity: no fills > 45min = exit

# Profit Tiers (HIGH WATERMARK DRAWDOWN logic - grid-safe)
# Format: [peak_pct, required_pullback_pct, lock_pct]
# Peak +1% → drawdown 0.5% → lock breakeven
# Peak +2% → drawdown 1.3% → lock +0.7%
# Peak +3% → drawdown 1.5% → lock +1.5%

# PnL-Driven Pauses (equity-based with cooldown)
min_rolling_pnl_pct: -0.02        # Pause if rolling 20-trade PnL < -2%
min_win_rate_threshold: 0.35      # 35% WR acceptable for grids
pause_cooldown_minutes: 120       # 2-hour pause after trigger
resume_min_pnl_pct: 0.0           # Resume only if last 10 trades >= 0%

min_grid_profit_pct: 0.6          # 0.6% min profit (0.2% fees + 0.2% spread + 0.2% buffer)

# 🛡️ CRASH PROTECTION - Alleen bij flash crash / exchange fuck-up / news-nuke
emergency_exit_pct: -12.0        # 🛡️ Was -4%, nu -12% - alleen bij echte crash
hard_stop_pct: -15.0              # 🛡️ Was -5%, nu -15% - ultiem vangnet

# ==============================================================================
# DRAWDOWN / KILL SWITCH - CRASH PROTECTION (Grid-Aware)
# ==============================================================================

max_daily_loss_pct: 30.0     # TIJDELIJK: Verhoogd naar 30% vanwege PnL tracking bug (20250214)
max_weekly_loss_pct: 8.0     # 🛡️ 8% weekly (tighter than 10%)
max_monthly_loss_pct: 12.0   # 🛡️ 12% monthly (tighter than 15%)

# =============================================================================
# TELEGRAM ALERTS (v2.0)
# ==============================================================================

telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"

# ==============================================================================
# ORDER MANAGEMENT
# ==============================================================================

max_open_orders: 100              # 🔧 FIX: 30→100 (Bitget allows 200/symbol)
order_frequency: 3
# max_entry_spread_pct: removed (handled in smart_entry_filter)

min_switch_interval_seconds: 600    # 🚀 FIX: 1800→600 (10 min - faster switching)
min_hold_time_seconds: 3600         # 🔧 FIX: 7200→3600 (1h - clear progression)
max_hold_time_seconds: 21600        # 🔧 FIX: 14400→21600 (6h - align with hard_hold)

# ==============================================================================
# TREND-AWARE EXIT SYSTEM (Soft/Hard Hold Time)
# ==============================================================================
# Prevents "dom verkopen" after fixed time when trend is still bullish
# After soft_hold: only exit if trend bearish OR pnl too negative
# After hard_hold: always exit (bag-holder prevention)
# ==============================================================================

soft_hold_time_seconds: 7200       # ⏰ 2 uur - trend-aware exit kicks in
hard_hold_time_seconds: 21600      # ⏰ 6 uur - always exit (bag-holder prevention)
soft_exit_min_trend_pct: 0.3       # 📈 Trend must be > 0.3% to extend hold
soft_exit_max_loss_pct: -1.5       # 📉 Exit even with good trend if loss > 1.5%
soft_exit_extend_seconds: 1800     # ⏳ Extend by 30 min if trend bullish

# TIMEOUT LIFECYCLE - prevents stuck positions
no_fill_timeout_sec: 1200         # ⏰ 20 min - no fills → cancel + close (no inventory)
no_progress_timeout_sec: 5400     # ⏰ 1.5 uur - meer ruimte voor herstel
no_progress_min_loss_pct: 2.5     # 🎯 PRO: Only trigger timeout if unrealized loss > 2.5%
no_progress_atr_multiplier: 1.5   # 🎯 PRO: Require adverse move > 1.5×ATR
close_grace_sec: 120              # ⏰ 2 min - graceful close window

min_startup_wait_seconds: 60       # 🚀 FIX: 90→60 (1 min startup delay)

smart_switch_k: 2.0
switch_cost_multiplier: 2.5

# ==============================================================================
# ==============================================================================
# BITGET SPOT - DEPLOYMENT CHECKLIST
# ==============================================================================
#
# VOOR LIVE TRADING:
#
# 1. API KEYS:
#    - Hummingbot CLI: connect bitget
#    - API Key + Secret + Passphrase (3 delen!)
#    - Permissies: Spot Trading + Read
#    - IP Whitelist: Aangeraden
#    - Opgeslagen in: ~/.hummingbot-conf/connectors/bitget.yml
#
# 2. FUNDING:
#    - Transfer USDT naar SPOT wallet (niet Futures!)
#    - Min: $150 USDT (10 orders × $15)
#    - Aangeraden: $500 USDT
#    - Check: Bitget > Assets > Spot Account
#
# 3. TICK & LOT SIZES:
#    - BTC-USDT: tick=$0.01, lot=0.00001 BTC
#    - ETH-USDT: tick=$0.01, lot=0.0001 ETH
#    - SOL-USDT: tick=$0.001, lot=0.01 SOL
#    - Bitget enforces strict - check API
#
# 4. RATE LIMITS:
#    - Spot orders: 10/sec
#    - Market data: 20/sec
#    - Private API: 10/sec
#    - Buffer: 80% (config above)
#
# 5. START COMMAND:
#    # Nieuwe terminal (Kraken blijft draaien)
#    cd ~/repos/hummingbot
#    ./start
#
#    # In Hummingbot:
#    hummingbot >>> start --script spot_grid_bitget.py
#
# 6. MONITORING:
#    - status: Check bot status
#    - balance: Check USDT/coin balances
#    - list: Check active orders
#    - logs: tail -f logs/spot_grid_bitget*.log
#
# 7. PARALLEL BOTS:
#    - Kraken bot: Eigen PID, eigen config
#    - Bitget bot: Eigen PID, eigen config
#    - Check: ps aux | grep hummingbot
#    - Beide bots draaien onafhankelijk
#
# 8. SAFETY FIRST:
#    - Start paper_trading: true
#    - Test 24h zonder echt geld
#    - Dan paper_trading: false
#    - Begin met 1 pair (BTC-USDT)
#    - Monitor eerste 10 trades
#    - Verhoog exposure gradueel
#
# ==============================================================================
```

## Attachment: Config YAML — Bitget Futures (447 lines)

```yaml
controller_name: futures_grid_bitget
log_level: INFO

paper_trading: false  # ← LIVE TRADING
connector_name: bitget_perpetual
quote_asset: USDT

# ============================================================
# TRADE DIRECTION
# ============================================================
# "long"  - Only LONG grids (buy low, sell high) - profit when UP
# "short" - Only SHORT grids (sell high, buy low) - profit when DOWN
# "auto"  - Auto-select based on trend:
#           - trend > +threshold → LONG
#           - trend < -threshold → SHORT
#           - trend in between → SKIP (no trade)
# ============================================================
trade_direction: auto
auto_direction_threshold_pct: 0.5   # Trend moet > +0.5% voor LONG of < -0.5% voor SHORT

# SHORT entry thresholds (used when direction=short or auto selects short)
short_24h_min_pct: -1.0      # 24h trend must be < -1% for SHORT
short_4h_min_pct: -1.0       # 4h trend must be < -1% for SHORT
short_1h_max_pct: 1.0        # 1h trend can be up to +1% (allow small bounces)
short_pump_1h_max: 2.0       # Reject SHORT if 1h > +2% (pump protection)
short_pump_4h_max: 1.0       # AND 4h > +1% (both required for pump reject)

# === CAPITAL MANAGEMENT ===
total_amount_quote: 50
min_order_amount_quote: 5
derivative_leverage: 3
max_exposure_per_coin_pct: 0.8
max_total_exposure_pct: 0.9
max_simultaneous_coins: 1

# ============================================================
# DYNAMIC SLOTS - DISABLED FOR SMALL ACCOUNTS
# ============================================================
# With €50 capital, dynamic slots calculates 4 coins which is too many.
# We disable it to use max_simultaneous_coins instead.
dynamic_slots:
  enabled: false                   # Disable dynamic slots, use max_simultaneous_coins

# Risk reference balance - SET TO YOUR ACTUAL ACCOUNT BALANCE!
# This is used to calculate exposure limits (max_total_exposure_pct applies to this)
risk_reference_balance_quote: 1500   # Jouw Bitget account balans (~€1500 gezien €1122 exposure)

# ============================================================
# RISK MANAGER - THREE-LAYER PROTECTION (Sprint 1)
# ============================================================
# LAAG 1: Per-trade risk (hoeveel je verliest als 1 grid faalt)
# LAAG 2: Portfolio position cap (max aantal grids tegelijk)
# LAAG 3: Notional exposure cap (leverage-aware totaal)
#
# FORMULA: max_trade = risk_reference_balance × (risk_max_balance_per_trade_pct / 100)
#
# Example met huidige settings:
#   reference_balance = 1500 USDT
#   per_trade_risk = 2% = max 30 USDT risk per grid
#   max_open_positions = 4 = max 4 grids tegelijk
#   max_total_risk = 8% = max 120 USDT totale risk (4 × 30)
#   max_notional = 150% = max 2250 USDT notional (bij 5x = 450 margin)
#
# WARNING: If per_order < min_order_amount_quote (5 USDT), orders FAIL silently!
# ============================================================

# LAAG 1: Per-trade risk (verlaagd van 5% naar 2%)
risk_max_balance_per_trade_pct: 2.0     # 2% = max 30 USDT risk per trade (was 5%!)

# Daily loss limit
risk_max_daily_loss_pct: 30.0            # TIJDELIJK: Verhoogd naar 30% vanwege PnL tracking bug (20250214)

# LAAG 2: Portfolio position caps
max_open_positions: 4                    # Max 4 grids tegelijk
max_total_risk_pct: 8.0                  # Max 8% totale risk (4 × 2%)

# LAAG 3: Notional exposure cap (leverage-aware)
max_notional_exposure_pct: 150.0         # Max 150% van balance als notional
                                         # Bij 5x leverage en 1500 balance:
                                         # Max 2250 notional = 450 margin used

# Legacy (wordt nog steeds gebruikt door base controller)
risk_max_total_open_risk_pct: 10.0       # Backup cap

# === POSITION MODE ===
position_mode: HEDGE               # HEDGE omdat bestaande posities in HEDGE mode zijn geopend!

# Trading universe - Top Bitget perpetual pairs (verified)
manual_trading_pairs:
  # === TOP 10 MAJORS ===
  - BTC-USDT
  - ETH-USDT
  - SOL-USDT
  - XRP-USDT
  - BNB-USDT
  - ADA-USDT
  - DOGE-USDT
  - AVAX-USDT
  - DOT-USDT
  - LINK-USDT
  # === LAYER 2 & SCALING ===
  - POL-USDT
  - ARB-USDT
  - OP-USDT
  - IMX-USDT
  - STRK-USDT
  # === NEW GEN L1 ===
  - SUI-USDT
  - SEI-USDT
  - APT-USDT
  - TIA-USDT
  - INJ-USDT
  # === DEFI ===
  - UNI-USDT
  - AAVE-USDT
  - LDO-USDT
  - CRV-USDT
  - COMP-USDT
  # === AI & DATA ===
  - FET-USDT
  - AR-USDT
  - GRT-USDT
  - TAO-USDT
  - WLD-USDT
  # === GAMING & METAVERSE ===
  - AXS-USDT
  - SAND-USDT
  - MANA-USDT
  - GALA-USDT
  - ENJ-USDT
  # === COSMOS ECOSYSTEM ===
  - ATOM-USDT
  - NEAR-USDT
  # === MEMES (hoge volatiliteit = veel kansen!) ===
  - SHIB-USDT
  - PEPE-USDT
  - WIF-USDT

max_coins_to_monitor: 15
min_24h_volume_eur: 500000
exclude_expensive_coins: false

# US-007: Dynamic Pair Manager (two-tier discovery: REST scans all, WebSocket for best)
use_dynamic_pair_manager: true       # Enable two-tier pair discovery
pair_scan_interval_seconds: 300      # Interval between REST scans (5 min)
max_spread_pct: 0.5                  # Maximum bid-ask spread filter

# Trend filtering
trend_lookback_minutes: 1440
trend_lookback_short_minutes: 60
trend_lookback_mid_minutes: 240
trend_lookback_long_minutes: 1440
use_multi_timeframe: false
use_multi_timeframe_buy: false       # MTF protection DISABLED voor SHORT testing
switch_threshold_percent: 1.0
min_switch_interval_seconds: 900
min_hold_time_seconds: 900

# Grids
grid_range_pct_down: 5.0
grid_range_pct_up: 12.0
num_grids: 3
use_atr_grid_ranges: true
atr_multiplier_down: 1.0
atr_multiplier_up: 1.5
use_asymmetric_grids: true
smart_refill_threshold_pct: 3.0

# ============================================================
# DYNAMIC FEATURES - DISABLED FOR SMALL ACCOUNTS (<€100)
# ============================================================
# These features adjust grid count and position size based on volatility.
# With small capital, this can cause orders to fall below minimum.
use_dynamic_grid_sizer: false        # Don't adjust num_grids dynamically
use_volatility_position_sizing: false  # Don't reduce position size for high volatility

# ============================================================
# FUNDING RATE FILTER (Direction-Aware) - Sprint 2
# ============================================================
# Funding is betaald elke 8 uur. Bij hoge funding (0.1% = 0.3%/dag) eet dit winst op.
# MAAR: Funding is niet altijd kosten!
# - Positieve funding rate: LONGS betalen, SHORTS ontvangen
# - Negatieve funding rate: SHORTS betalen, LONGS ontvangen
#
# Deze filter blokkeert alleen als JIJ betaalt, niet als je ontvangt!
funding_rate_filter_enabled: false           # Aan zetten na Sprint 2 implementatie
max_funding_cost_pct: 0.03                   # Skip als JIJ > 0.03% moet betalen
funding_rate_cache_seconds: 300              # Cache funding rate 5 min

# ============================================================
# CORRELATION FILTER - Sprint 2
# ============================================================
# Voorkomt dat je dubbel verliest bij gecorreleerde coins
# (BTC en ETH dumpen vaak samen)
correlation_filter_enabled: false            # Aan zetten na Sprint 2 implementatie
max_correlated_positions: 1                  # Max 1 positie per groep

# Correlation groups (coins die vaak samen bewegen)
correlation_groups:
  major_caps:
    - BTC-USDT
    - ETH-USDT
  layer1_alts:
    - SOL-USDT
    - AVAX-USDT
    - DOT-USDT
    - NEAR-USDT
    - APT-USDT
    - SUI-USDT
  layer2:
    - ARB-USDT
    - OP-USDT
    - POL-USDT
  meme_coins:
    - DOGE-USDT
    - SHIB-USDT
    - PEPE-USDT
    - WIF-USDT
  ai_tokens:
    - FET-USDT
    - TAO-USDT
    - WLD-USDT
  defi:
    - UNI-USDT
    - AAVE-USDT
    - LDO-USDT

# ============================================================
# TRAILING STOP (Sprint 3 - Profit Lock)
# ============================================================
# Lockt winst als grid in profit is. Werkt als volgt:
# 1. Grid heeft +2.5% unrealized PnL
# 2. Trailing stop activeert (threshold = 2%)
# 3. High water mark = +2.5%
# 4. Prijs daalt, PnL = +1.8% (distance = 0.7%, OK)
# 5. Prijs daalt meer, PnL = +1.4% (distance = 1.1% > 1%)
# 6. TRAILING STOP TRIGGERED → close grid met +1.4% profit
#
# BELANGRIJK: Grid-aware - let op dat dit mean-reversion niet killt!
# Zet distance hoog genoeg zodat normale grid bounces niet triggeren.
trailing_stop_enabled: false                 # Aan zetten na testing
trailing_stop_activation_pct: 2.0            # Activeer na +2% profit
trailing_stop_distance_pct: 1.0              # Max 1% teruggeven van top

# ============================================================
# DYNAMIC TIMEOUT (Sprint 3 - Volatility-Based)
# ============================================================
# Past grid timeout aan op basis van volatiliteit:
# - Lage volatiliteit → langere timeout (markt beweegt langzaam)
# - Hoge volatiliteit → kortere timeout (snelle moves verwacht)
#
# Dit voorkomt dat grids te vroeg stoppen in rustige markten,
# of te lang blijven hangen in volatiele markten.
dynamic_timeout_enabled: false               # Aan zetten na testing
base_grid_timeout_seconds: 3600              # 1 uur basis
low_volatility_multiplier: 2.0               # 2 uur bij lage vol
high_volatility_multiplier: 0.5              # 30 min bij hoge vol
volatility_threshold_low: 0.5                # ATR < 0.5% = laag
volatility_threshold_high: 2.0               # ATR > 2.0% = hoog

# Risk
stop_loss_pct: 0.03
take_profit_pct: 0.05
max_open_orders: 4
order_frequency: 30

# PHASE 1: Slippage Protection (Fix #1)
max_entry_spread_pct: 0.5            # reject if spread > 0.5%

# PHASE 1: Drawdown & Loss Limits (Fix #2 & #3)
max_daily_loss_pct: 30.0             # TIJDELIJK: Verhoogd naar 30% vanwege PnL tracking bug (20250214)
max_weekly_loss_pct: 10.0
max_monthly_loss_pct: 15.0
max_daily_loss_eur: 50.0             # USDT for futures

# Discovery
coin_rotation_threshold: 90
trend_min_change_pct: 0.1  # Verlaagd van 0.5 naar 0.1 voor bear markets (futures)
price_update_interval: 30

# ============================================================
# STALENESS THRESHOLDS (verhoogd voor perpetuals)
# ============================================================
# Bitget perps hebben soms tragere websocket updates dan spot
# Default is 2000ms - te strikt voor perps API
max_price_age_ms: 30000              # 30 seconden (was 2s - te strikt)
max_orderbook_age_ms: 60000          # 60 seconden (was 5s)

# ============================================================
# EXCHANGE-SIDE STOP LOSS (SAFETY NET!)
# ============================================================
# Deze orders worden op Bitget zelf geplaatst.
# Als de bot crasht, sluit Bitget de positie automatisch!
#
# BELANGRIJK: Dit is je LAATSTE VERDEDIGINGSLIJN tegen liquidatie.
# ============================================================

exchange_stop_loss_enabled: true     # Plaats SL order op Bitget (AANBEVOLEN!)
exchange_stop_loss_pct: 5.0          # SL trigger bij -5% van entry (voor 5x = -25% van capital)

exchange_take_profit_enabled: true   # Backup TP op exchange (vangnet als bot faalt)
exchange_take_profit_pct: 8.0        # Exchange TP bij +8% (bot probeert eerst +5%)

# ============================================================
# FUTURES-SPECIFIC RISK MANAGEMENT
# ============================================================

# === LIQUIDATION BEVEILIGING ===
# Hoe dit werkt:
# - Bij 10x leverage en -10% = liquidatie
# - liquidation_buffer_pct (20%) = extra veiligheidsmarge
# - liquidation_safety_distance_pct (50%) = stop bij halverwege naar liquidatie
#
# Voorbeeld met 10x leverage:
#   Entry:     $100,000
#   Liquidation: $90,000 (-10%)
#   Warning:   $95,000 (-5%, halverwege)
#   → Als prijs < $95,000 = EMERGENCY STOP!
#
liquidation_buffer_pct: 0.2                  # 20% veiligheidsmarge voor liquidatie
liquidation_safety_distance_pct: 0.5         # Stop bij 50% van afstand tot liquidatie

# === EMERGENCY EXITS (STRAKKER DAN SPOT) ===
# Waarom strakker? Bij 10x leverage:
# - -1.5% grid verlies = -15% op je capital!
# - -2.5% grid verlies = -25% op je capital!
#
futures_emergency_exit_pct: -1.5             # Emergency exit bij -1.5% (ipv -2% spot)
futures_hard_stop_pct: -2.5                  # Hard stop bij -2.5% (ipv -3% spot)

# === ENTRY FILTERS (MULTI-TIMEFRAME) ===
# Alleen traden in DUIDELIJKE TREND!
# Met trade_direction=auto: LONG bij uptrend, SHORT bij downtrend
#
# MTF Thresholds (voor trend richting detectie):
# Deze worden GEÏNVERTEERD voor SHORT trades automatisch
mtf_1h_min_pct: -3.0           # LONG: 1h > -3%, SHORT: 1h < +3%
mtf_4h_min_pct: -2.5           # LONG: 4h > -2.5%, SHORT: 4h < +2.5%
mtf_24h_min_pct: -2.5          # LONG: 24h > -2.5%, SHORT: 24h < +2.5%
mtf_declining_1h_max: -4.0     # Crash (LONG) / Pump (SHORT) protection
mtf_declining_4h_max: -2.0

# Normale trading (24h data beschikbaar):
futures_min_entry_strength_24h: 1.5          # 24h trend > +1.5% VERPLICHT
futures_min_entry_strength_4h: 1.0           # 4h trend > +1.0% VERPLICHT
futures_min_entry_strength_1h: 0.0           # 1h trend ≥ 0.0% VERPLICHT
#
# Warmup mode (24h data nog niet compleet, eerste uur bot draait):
# Versoepeld voor SHORT: 4h hoeft maar -0.3% te zijn (markt daalt langzaam)
warmup_min_4h_trend_pct: 0.3                 # 4h trend > +0.3% (LONG) of < -0.3% (SHORT)
warmup_min_1h_trend_pct: 0.3                 # 1h trend ≥ +0.3% (LONG) of ≤ -0.3% (SHORT)

# Trend confirmation
trend_confirmation_timeframes: 1             # Hoeveel timeframes moeten confirmeren
trend_min_entry_strength: 0.001              # Minimale trendsterkte voor entry

# ============================================================
# RISKGUARD: AUTOMATISCHE KILL-SWITCHES
# ============================================================
# RiskGuard monitort 6 gevaren en stopt grid ONMIDDELLIJK bij trigger.
# Dit beschermt tegen liquidatie en grote verliezen.
#
# BELANGRIJK: RiskGuard heeft VOORRANG op alles!
# ============================================================

risk_guard_enabled: true                     # Schakel RiskGuard in (AANBEVOLEN!)

# --- GUARD 1: HARD LOSS ---
# Stop grid bij maximaal verlies
# Bij 10x leverage: -8% = -80% van je capital!
#
risk_guard_max_loss_pct: -8.0                # Stop bij -8% unrealized PnL
#                                            # Conservatief: -5.0
#                                            # Agressief: -10.0 (GEVAARLIJK!)

# --- GUARD 2: MAX TIME ---
# Stop grid als het te lang draait zonder winst
# Futures grid moet SNEL profit maken (funding fees!)
#
risk_guard_max_grid_time_seconds: 3600       # Stop na 1 uur (3600s)
#                                            # Conservatief: 1800s (30 min)
#                                            # Agressief: 7200s (2 uur)

# --- GUARD 3: GRID DEPTH ---
# Stop als te veel buy orders gevuld zijn
# Veel gevulde buys = prijs daalt = liquidatie gevaar!
#
risk_guard_max_grid_depth_pct: 0.65          # Stop als 65% van levels gevuld
#                                            # Conservatief: 0.50 (50%)
#                                            # Agressief: 0.80 (80%, gevaarlijk!)

# --- GUARD 4: SELL STARVATION ---
# ⚠️  DISABLED: Grid executor tracks sells internally, not via notify_sell_filled()
# Stop als geen sell orders gevuld worden
# Geen sells = geen profit = alleen funding fees betalen
#
risk_guard_sell_starvation_seconds: 0        # 0 = DISABLED (grid tracks internally)
#                                            # Was: 900s (15 min zonder sell)
#                                            # Conservatief: 600s (10 min)
#                                            # Agressief: 1800s (30 min)

# --- GUARD 5: TREND BREAK ---
# Stop als 1h trend negatief wordt
# Uptrend voorbij = grid moet stoppen!
#
risk_guard_trend_break_pct: -1.5             # Stop als 1h trend < -1.5%
#                                            # Conservatief: -1.0
#                                            # Agressief: -2.5

# --- GUARD 6: ATR EXPLOSION ---
# Stop als volatiliteit explodeert
# Hoge volatiliteit + leverage = gevaarlijk!
#
risk_guard_atr_explosion_multiplier: 2.2     # Stop als ATR > 2.2x baseline
#                                            # Conservatief: 1.8x
#                                            # Agressief: 3.0x

# ============================================================
# TUNING PROFILES (UNCOMMENT OM TE GEBRUIKEN)
# ============================================================

# === CONSERVATIEF PROFIEL (BEGINNERS) ===
# Lage leverage, snelle stops, veilig
#
# derivative_leverage: 5
# risk_guard_max_loss_pct: -5.0
# risk_guard_max_grid_time_seconds: 1800       # 30 min
# risk_guard_max_grid_depth_pct: 0.50          # 50%
# risk_guard_sell_starvation_seconds: 600      # 10 min
# risk_guard_trend_break_pct: -1.0
# risk_guard_atr_explosion_multiplier: 1.8

# === AGRESSIEF PROFIEL (EXPERTS, RISICOVOL!) ===
# Hoge leverage, meer ruimte, gevaarlijk!
#
# derivative_leverage: 20                      # GEVAARLIJK!
# risk_guard_max_loss_pct: -10.0
# risk_guard_max_grid_time_seconds: 7200       # 2 uur
# risk_guard_max_grid_depth_pct: 0.75          # 75%
# risk_guard_sell_starvation_seconds: 1800     # 30 min
# risk_guard_trend_break_pct: -2.5
# risk_guard_atr_explosion_multiplier: 3.0

# ============================================================
# MEER INFO:
# Lees RISK_MANAGEMENT.md voor volledige uitleg van alle parameters!
# ============================================================
```

## Attachment: Data Snapshot (2026-03-08)

# Bot Data Snapshot — 8 March 2026

> **Snapshot date**: 2026-03-08 ~15:00 UTC
> **Purpose**: Attach this file as evidence when running a review round.
> **Shelf life**: Data becomes stale within days. Re-run the queries below
> to generate a fresh snapshot before each review round.

---

## How to regenerate this snapshot

Run from the repo root (`/home/mo/repos/hummingbot`):

```bash
# Activate the venv first
source .venv/bin/activate

# ──────────────────────────────────────────────────
# 1. DATABASE QUERIES  (repeat for each .sqlite DB)
# ──────────────────────────────────────────────────

# Per-pair performance
sqlite3 -header -column data/<DB>.sqlite "
SELECT json_extract(config, '\$.trading_pair') as pair,
    COUNT(*) as trades,
    SUM(CASE WHEN net_pnl_quote > 0 THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN net_pnl_quote < 0 THEN 1 ELSE 0 END) as losses,
    SUM(CASE WHEN filled_amount_quote = 0 THEN 1 ELSE 0 END) as zero_fill,
    ROUND(SUM(net_pnl_quote), 4) as total_pnl,
    ROUND(SUM(cum_fees_quote), 4) as fees,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL
GROUP BY json_extract(config, '\$.trading_pair') ORDER BY total_pnl DESC;"

# Close type distribution
sqlite3 -header -column data/<DB>.sqlite "
SELECT close_type, COUNT(*) as cnt,
    ROUND(SUM(net_pnl_quote), 4) as sum_pnl,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL
GROUP BY close_type ORDER BY cnt DESC;"

# Date range + totals
sqlite3 -header -column data/<DB>.sqlite "
SELECT date(MIN(timestamp), 'unixepoch') as first,
    date(MAX(timestamp), 'unixepoch') as last,
    COUNT(*) as total,
    SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) as filled,
    ROUND(100.0 * SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as fill_pct,
    ROUND(SUM(net_pnl_quote), 4) as pnl,
    ROUND(SUM(cum_fees_quote), 4) as fees,
    ROUND(SUM(filled_amount_quote), 2) as vol
FROM Executors WHERE close_type IS NOT NULL;"

# Futures only: filled trades by pair + close type
sqlite3 -header -column data/futures_grid_bitget.sqlite "
SELECT json_extract(config, '\$.trading_pair') as pair, close_type,
    COUNT(*) as cnt,
    SUM(CASE WHEN net_pnl_quote > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(net_pnl_quote), 4) as total_pnl,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL AND filled_amount_quote > 0
GROUP BY pair, close_type ORDER BY total_pnl DESC;"

# ──────────────────────────────────────────────────
# 2. LOG ERROR FREQUENCY
# ──────────────────────────────────────────────────

# Find the most recent log for each bot:
ls -t logs/logs_multi_coin_grid_v2_usd_*.log | head -1   # Kraken USD
ls -t logs/logs_spot_grid_bitget_*.log | head -1          # Bitget Spot
ls -t logs/logs_futures_grid_bitget_*.log | head -1       # Bitget Futures

# Then for each:
grep -oP "(ERROR|WARNING|CRITICAL)" <logfile> | sort | uniq -c | sort -rn
grep "ERROR" <logfile> | grep -oP "ERROR - .*" | sort -u | head -15
grep -c "WSS_ERROR\|WebSocket\|websocket" <logfile>       # WebSocket count

# ──────────────────────────────────────────────────
# 3. WHY-NO-TRADE SUMMARIES
# ──────────────────────────────────────────────────

# Find the most recent report log:
ls -t logs/kraken_*report*.log | head -1
ls -t logs/bitget_*report*.log | head -1

# Extract the last few hours:
grep -B1 -A 15 "WHY-NO-TRADE SUMMARY" <report_log> | tail -60

# ──────────────────────────────────────────────────
# 4. ROTATION TIMEOUT EVENTS
# ──────────────────────────────────────────────────

grep -oP "MONITORING TIMEOUT: \K[A-Z]+-[A-Z]+" <logfile> | sort | uniq -c | sort -rn
grep -i "MONITORING TIMEOUT" <logfile> | tail -20
```

Replace `<DB>` with: `multi_coin_grid_v2.sqlite` (Kraken EUR),
`multi_coin_grid_v2_usd.sqlite` (Kraken USD), `spot_grid_bitget.sqlite`
(Bitget Spot), `futures_grid_bitget.sqlite` (Bitget Futures).

---

## Database files

| Database | Bot | Size | Period |
|----------|-----|------|--------|
| `data/multi_coin_grid_v2.sqlite` | Kraken EUR (retired) | 12 MB | 2025-11-20 → 2026-02-05 |
| `data/multi_coin_grid_v2_usd.sqlite` | Kraken USD (active) | 8.0 MB | 2026-01-21 → 2026-01-23 |
| `data/spot_grid_bitget.sqlite` | Bitget Spot (blocked) | 6.0 MB | 2026-01-06 → 2026-01-12 |
| `data/futures_grid_bitget.sqlite` | Bitget Futures (blocked) | 2.9 MB | 2026-02-01 → 2026-02-10 |

## Close type legend

| Code | Meaning |
|------|---------|
| 3 | TAKE_PROFIT |
| 5 | EARLY_STOP (no-fill, soft stop) |
| 7 | EXPIRED / no-fill timeout |
| 8 | STOP_LOSS |
| 11 | FAILED_TO_OPEN |
| 12 | SMART_SWITCH (rotation exit) |

---

## 1. Kraken EUR (historical, retired)

**Period**: 2025-11-20 → 2026-02-05 (77 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 2,209 | 34 | 1.5% | −€73.39 | €3.71 | €2,236.62 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 5 (EARLY_STOP) | 1,473 | +€11.83 | €1,767.85 |
| 7 (EXPIRED) | 704 | €0.00 | €0.00 |
| 3 (TAKE_PROFIT) | 11 | +€24.49 | €248.48 |
| 8 (STOP_LOSS) | 7 | −€109.72 | €220.29 |
| 11 (FAILED_TO_OPEN) | 11 | €0.00 | €0.00 |
| 12 (SMART_SWITCH) | 3 | €0.00 | €0.00 |

### Per-pair performance (pairs with fills only)
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| STRK-EUR | 10 | 1 | 0 | 9 | +€24.40 | €0.96 | €216.94 |
| TAO-EUR | 45 | 2 | 2 | 41 | +€1.96 | €0.00 | €115.44 |
| XTZ-EUR | 56 | 1 | 1 | 54 | −€0.30 | €0.01 | €139.54 |
| ATOM-EUR | 303 | 0 | 3 | 300 | −€0.32 | €0.01 | €174.54 |
| POL-EUR | 236 | 1 | 3 | 232 | −€0.50 | €0.01 | €279.26 |
| JASMY-EUR | 2 | 0 | 1 | 1 | −€0.68 | €0.00 | €104.09 |
| UNI-EUR | 13 | 0 | 1 | 12 | −€1.11 | €0.97 | €215.79 |
| SOL-EUR | 122 | 1 | 4 | 117 | −€2.32 | €1.73 | €557.85 |
| SUI-EUR | 95 | 0 | 1 | 94 | −€0.01 | €0.00 | €34.96 |
| DOT-EUR | 89 | 0 | 1 | 88 | −€0.02 | €0.00 | €34.95 |
| ALGO-EUR | 4 | 0 | 1 | 3 | −€15.56 | €0.00 | €31.47 |
| RENDER-EUR | 103 | 0 | 2 | 101 | −€15.63 | €0.00 | €66.40 |
| ADA-EUR | 104 | 0 | 1 | 103 | −€15.63 | €0.00 | €31.47 |
| CC-EUR | 26 | 1 | 4 | 21 | −€15.70 | €0.01 | €170.98 |
| AAVE-EUR | 30 | 0 | 1 | 29 | −€15.93 | €0.00 | €31.47 |
| PEPE-EUR | 1 | 0 | 1 | 0 | −€16.02 | €0.00 | €31.47 |

### Per-pair (zero-fill only, no trades — top 10 by executor count)
| Pair | Executors | All zero-fill |
|------|-----------|---------------|
| SAND-EUR | 152 | 152 |
| FIL-EUR | 157 | 157 |
| MANA-EUR | 127 | 127 |
| SNX-EUR | 124 | 124 |
| BNB-EUR | 92 | 92 |
| ZRO-EUR* | — | — |
| DOGE-EUR | 42 | 42 |
| KAS-EUR | 31 | 31 |
| BCH-EUR | 33 | 33 |
| OPEN-EUR | 29 | 29 |

---

## 2. Kraken USD (active, limited data)

**Period**: 2026-01-21 → 2026-01-23 (2 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 212 | 1 | 0.5% | −$0.26 | $0.00 | $33.04 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 7 (EXPIRED) | 210 | $0.00 | $0.00 |
| 11 (FAILED_TO_OPEN) | 1 | $0.00 | $0.00 |
| 5 (EARLY_STOP) | 1 | −$0.26 | $33.04 |

### Per-pair performance
| Pair | Trades | Wins | Losses | Zero-fill | PnL |
|------|--------|------|--------|-----------|-----|
| ZRO-USD | 68 | 0 | 0 | 68 | $0.00 |
| XCN-USD | 48 | 0 | 0 | 48 | $0.00 |
| TAO-USD | 8 | 0 | 0 | 8 | $0.00 |
| SOL-USD | 14 | 0 | 0 | 14 | $0.00 |
| SAND-USD | 8 | 0 | 0 | 8 | $0.00 |
| MANA-USD | 7 | 0 | 0 | 7 | $0.00 |
| AVAX-USD | 7 | 0 | 0 | 7 | $0.00 |
| ADA-USD | 10 | 0 | 0 | 10 | $0.00 |
| AXS-USD | 42 | 0 | 1 | 41 | −$0.26 |

---

## 3. Bitget Spot (capital-blocked)

**Period**: 2026-01-06 → 2026-01-12 (6 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 400 | 6 | 1.5% | −$0.72 | $0.36 | $242.77 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 5 (EARLY_STOP) | 382 | −$0.31 | $132.83 |
| 12 (SMART_SWITCH) | 9 | −$0.41 | $109.93 |
| 11 (FAILED_TO_OPEN) | 9 | $0.00 | $0.00 |

### Per-pair performance (pairs with fills only)
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| AVA-USDT | 99 | 0 | 1 | 98 | −$0.03 | $0.03 | $22.17 |
| ASTR-USDT | 4 | 0 | 1 | 3 | −$0.04 | $0.03 | $22.18 |
| CHZ-USDT | 8 | 0 | 1 | 7 | −$0.08 | $0.07 | $44.39 |
| SWCH-USDT | 57 | 0 | 3 | 54 | −$0.56 | $0.23 | $154.02 |

**Current state**: BLOCKED — $3.62 free capital < $30.00 minimum.
Stuck SONIC LIMIT SELL @ $0.046419 (1533 units) locking ~$71.

---

## 4. Bitget Futures (capital-depleted)

**Period**: 2026-02-01 → 2026-02-10 (9 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 932 | 23 | 2.5% | −$155.39 | −$0.09* | $472.90 |

*Negative fees = maker rebates on some trades.

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 3 (TAKE_PROFIT) | 737 | +$0.57 | $33.85 |
| 7 (EXPIRED) | 171 | $0.00 | $0.00 |
| 8 (STOP_LOSS) | 22 | −$155.96 | $439.05 |
| 11 (FAILED_TO_OPEN) | 2 | $0.00 | $0.00 |

### Per-pair performance
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| SOL-USDT | 101 | 2 | 0 | 99 | +$9.31 | −$0.01 | $67.83 |
| SUI-USDT | 72 | 1 | 1 | 70 | +$0.09 | −$0.01 | $31.53 |
| AVAX-USDT | 113 | 0 | 1 | 112 | −$5.42 | $0.00 | $10.90 |
| LINK-USDT | 175 | 0 | 1 | 174 | −$9.56 | $0.00 | $19.26 |
| DOGE-USDT | 28 | 1 | 3 | 24 | −$10.57 | −$0.01 | $42.33 |
| XRP-USDT | 217 | 1 | 2 | 214 | −$11.96 | −$0.01 | $46.37 |
| OP-USDT | 1 | 0 | 1 | 0 | −$12.61 | −$0.01 | $24.86 |
| ARB-USDT | 116 | 0 | 3 | 113 | −$23.05 | −$0.01 | $45.90 |
| BTC-USDT | 59 | 0 | 3 | 56 | −$28.84 | −$0.01 | $57.73 |
| ETH-USDT | 50 | 0 | 3 | 47 | −$62.78 | −$0.03 | $126.18 |

### Filled trades detail (close type breakdown)
| Pair | Close type | Count | Wins | PnL | Volume |
|------|------------|-------|------|-----|--------|
| SOL-USDT | 8 (STOP_LOSS) | 1 | 1 | +$8.74 | $33.98 |
| SOL-USDT | 3 (TAKE_PROFIT) | 1 | 1 | +$0.57 | $33.85 |
| SUI-USDT | 8 (STOP_LOSS) | 2 | 1 | +$0.09 | $31.53 |
| AVAX-USDT | 8 | 1 | 0 | −$5.42 | $10.90 |
| LINK-USDT | 8 | 1 | 0 | −$9.56 | $19.26 |
| DOGE-USDT | 8 | 4 | 1 | −$10.57 | $42.33 |
| XRP-USDT | 8 | 3 | 1 | −$11.96 | $46.37 |
| OP-USDT | 8 | 1 | 0 | −$12.61 | $24.86 |
| ARB-USDT | 8 | 3 | 0 | −$23.05 | $45.90 |
| BTC-USDT | 8 | 3 | 0 | −$28.84 | $57.73 |
| ETH-USDT | 8 | 3 | 0 | −$62.78 | $126.18 |

**Current state**: BLOCKED — $9.09–$9.41 free capital < $15.00 minimum.
−$155 on $50 capital = −310% return in 9 days.

---

## 5. Combined summary

| Bot | Period | Executors | Filled | Fill % | PnL | Capital | Return |
|-----|--------|-----------|--------|--------|-----|---------|--------|
| Kraken EUR | Nov 25 – Feb 26 | 2,209 | 34 | 1.5% | −€73.39 | €300 | −24.5% |
| Kraken USD | Jan 21–23 | 212 | 1 | 0.5% | −$0.26 | ~$300 | −0.1% |
| Bitget Spot | Jan 6–12 | 400 | 6 | 1.5% | −$0.72 | ~$100 | −0.7% |
| Bitget Futures | Feb 1–10 | 932 | 23 | 2.5% | −$155.39 | ~$50 | −310.8% |
| **Combined** | | **3,753** | **64** | **1.7%** | **≈ −€229** | | |

**Key observations**:
- Not a single bot instance is profitable
- 98.3% of all executors across all bots never get a single fill
- Futures shows highest fill rate (2.5%) but worst outcome (96% stopped out)
- Only 1 of 3 active bots can currently attempt to trade (Kraken USD)

---

## 6. Error frequency from logs

### Kraken USD
**Log**: `logs/logs_multi_coin_grid_v2_usd_2026-03-05-16-20-24.log`
**Session**: 2026-03-05 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 277 |
| ERROR | 225 |

**Unique errors**:
- `MQTT is already stopped!` — MQTT connection management issue
- `Unexpected error while listening to user stream. Retrying after 5 seconds...` — WebSocket instability

**WebSocket-related messages**: 336 occurrences

### Bitget Spot
**Log**: `logs/logs_spot_grid_bitget_2026-03-05-16-42-05.log`
**Session**: 2026-03-05 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 1,664 |
| ERROR | 368 |

**Single error (all 368 occurrences)**:
```
❌ Cannot create grid: Insufficient capital: $3.62 < $30.00 minimum (3 grids × $10)
```

### Bitget Futures
**Log**: `logs/logs_futures_grid_bitget_2026-02-28-13-34-36.log`
**Session**: 2026-02-28 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 37 |
| ERROR | 37 |

**Unique errors (all insufficient capital variations)**:
```
❌ Cannot create grid: Insufficient capital: $9.27 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.29 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.34 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.41 < $15.00 minimum (3 grids × $5)
```

---

## 7. WHY-NO-TRADE summaries

### Kraken USD — 2026-03-08 (3 hourly reports)

**09:29 UTC** | 2,561 intents evaluated | 83.1% denied | 16.9% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 1,137 | 44.4% |
| RSI_OVERBOUGHT | 776 | 30.3% |
| STALE_PRICE | 157 | 6.1% |
| ATR_TOO_LOW | 35 | 1.4% |
| SPREAD_TOO_WIDE | 15 | 0.6% |
| RSI_OVERSOLD | 7 | 0.3% |

**10:30 UTC** | 1,827 intents | 57.0% denied | 43.0% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 666 | 36.5% |
| RSI_OVERBOUGHT | 265 | 14.5% |
| ATR_TOO_LOW | 93 | 5.1% |
| STALE_PRICE | 9 | 0.5% |
| RSI_OVERSOLD | 6 | 0.3% |
| SPREAD_TOO_WIDE | 2 | 0.1% |

**11:30 UTC** | 2,359 intents | 74.8% denied | 25.2% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 971 | 41.2% |
| RSI_OVERBOUGHT | 721 | 30.6% |
| STALE_PRICE | 70 | 3.0% |
| SPREAD_TOO_WIDE | 3 | 0.1% |

**Pattern**: NO_ORDERBOOK_DATA is consistently #1 (36–44%), RSI_OVERBOUGHT #2 (14–31%).

### Bitget Spot — 2026-03-05 to 2026-03-08

**20:42 (Mar 5)** | 99 intents | 70.7% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 40 | 40.4% |
| RSI_OVERBOUGHT | 10 | 10.1% |
| ATR_TOO_LOW | 10 | 10.1% |
| ACCEL_FALLING_KNIFE | 6 | 6.1% |
| VWAP_DEVIATION_TOO_HIGH | 4 | 4.0% |

**22:42 (Mar 5)** | 1,094 intents | 52.7% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 405 | 37.0% |
| RSI_OVERBOUGHT | 97 | 8.9% |
| ACCEL_FALLING_KNIFE | 60 | 5.5% |
| ATR_TOO_LOW | 12 | 1.1% |
| TREND_24H_OUT_OF_RANGE | 3 | 0.3% |

**10:47 (Mar 8)** | ~2,000 intents | ~70% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | ~40% | — |
| RSI_OVERBOUGHT | ~18% | — |
| ACCEL_FALLING_KNIFE | 83 | 4.0% |
| TREND_24H_OUT_OF_RANGE | 61 | 3.0% |
| SPREAD_TOO_WIDE | 37 | 1.8% |

**11:48 (Mar 8)** | 1,883 intents | 72.1% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 746 | 39.6% |
| RSI_OVERBOUGHT | 342 | 18.2% |
| ACCEL_FALLING_KNIFE | 109 | 5.8% |
| WICK_RATIO_LOW | 65 | 3.5% |
| TREND_24H_OUT_OF_RANGE | 54 | 2.9% |
| STALE_PRICE | 35 | 1.9% |
| SPREAD_TOO_WIDE | 6 | 0.3% |

**After 12:48 (Mar 8)**: 0 intents evaluated — Bitget Spot stopped evaluating
(likely capital-blocked, no coins being monitored).

---

## 8. Rotation timeout events

### Kraken USD (current session)
| Coin | Timeouts |
|------|----------|
| SUI-USD | 2 |

### Bitget Spot (current session)
| Coin | Timeouts |
|------|----------|
| SONIC-USDT | 19 |
| HYPE-USDT | 2 |

**SONIC-USDT rotation loop**: Rotates every ~3.1 minutes without progress.
Sample (all from March 8):
```
12:08 → 12:12 → 12:15 → 12:18 → 12:21 → 12:24 → 12:28 → 12:31
→ 12:34 → 12:37 → 12:41 → 12:44 → 12:47 → 12:50 → 12:57 → 13:00
→ 13:03 → 13:07 → ...
```
19 consecutive "monitoring timeout" events for the same coin = rotation
logic doesn't detect that it keeps selecting the same stuck coin.

---

## 9. Critical observations

1. **Fill rate crisis**: 98.3% of executors never fill. This is the #1 problem.
2. **NO_ORDERBOOK_DATA**: #1 rejection reason (35–44%) across all bots. Likely a data pipeline issue, not a strategy issue.
3. **Capital adequacy**: 2 of 3 active bots cannot trade due to insufficient capital.
4. **Futures catastrophe**: −$155 on $50 capital. 96% of filled trades hit stop-loss. Grid + leverage = amplified losses.
5. **Rotation loops**: SONIC-USDT rotates 19 times without progress. The bot doesn't learn.
6. **Kraken WebSocket**: 336 WebSocket-related events in a 3-day session.
7. **Only SOL-USDT** is consistently profitable across all bots (+$9.31 futures, positive on spot).

---

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
