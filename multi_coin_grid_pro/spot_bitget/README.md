# Bitget SPOT Grid Strategy

Complete multi-coin grid trading strategy voor Bitget SPOT exchange.
Dezelfde bewezen architectuur als je Kraken spot grid bot.

## Features

### ✅ Core Functionaliteit
- **Multi-coin grid trading** - Handel meerdere USDT pairs tegelijk
- **Trend-following entry** - Enter alleen bij bullish trends
- **Dynamic grid sizing** - ATR-based volatility aanpassing
- **Risk management** - Stop loss, take profit, daily limits
- **Rate limiting** - Bitget API compliant (10 orders/sec)
- **Tick/lot size handling** - Automatische price/size aanpassingen

### 🎯 Bitget-Specifiek
- **Connector**: `bitget` (spot)
- **Quote**: USDT (niet EUR zoals Kraken)
- **Fees**: 0.1% maker / 0.1% taker
- **Wallets**: SPOT wallet (gescheiden van Futures)
- **API**: 3 componenten (key + secret + passphrase)

### 🛡️ Risk Controls
- Max daily loss (USD en %)
- Position size limits per coin
- Total exposure cap
- Stop loss / take profit per trade
- Spread/slippage protection

## Architectuur

```
scripts/spot_grid_bitget.py          ← Entry point (start --script)
    ↓
multi_coin_grid_pro/spot_bitget/
    ├── config_schema.py              ← Pydantic config model
    ├── config_manager.py             ← YAML config loader
    ├── controller.py                 ← Main trading logic
    └── config/
        └── spot_grid_bitget.yaml     ← Settings
```

Extends:
- `MultiCoinGridController` - Base grid logic
- `StrategyV2Base` - Hummingbot strategy framework
- `GridExecutor` - Order execution engine

## Quick Start

### 1. API Setup
```bash
# Start Hummingbot
./start

# Connect Bitget
>>> connect bitget
```

Vul in:
- API Key
- Secret Key
- Passphrase

### 2. Fund Account
Transfer USDT naar **SPOT wallet**:
- Min: $150
- Aangeraden: $500

### 3. Config Check
```bash
# Review config
cat multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml

# Key settings:
# - paper_trading: false (voor live)
# - total_amount_quote: 500
# - manual_trading_pairs: [BTC-USDT, ETH-USDT, SOL-USDT]
```

### 4. Launch
```bash
>>> start --script spot_grid_bitget.py
```

### 5. Monitor
```bash
>>> status          # Overview
>>> balance         # Balances
>>> list            # Orders
```

Zie [QUICK_START.md](QUICK_START.md) voor gedetailleerde instructies.

## Configuration

### Conservative Startup (Default)
```yaml
total_amount_quote: 500             # $500 capital
min_order_amount_quote: 15          # $15 per order
max_simultaneous_coins: 1           # 1 coin tegelijk
manual_trading_pairs:
  - BTC-USDT                        # Liquid pairs only
  - ETH-USDT
  - SOL-USDT
```

### After Testing - Scale Up
```yaml
total_amount_quote: 2000            # $2000 capital
min_order_amount_quote: 30          # $30 per order
max_simultaneous_coins: 3           # 3 coins parallel
manual_trading_pairs:               # More pairs
  - BTC-USDT
  - ETH-USDT
  - SOL-USDT
  - BNB-USDT
  - AVAX-USDT
  - LINK-USDT
```

## Grid Settings

### Standard Grid (Spot)
```yaml
grid_range_pct_down: 3.0            # 3% beneden entry
grid_range_pct_up: 8.0              # 8% boven entry (asymmetrisch)
num_grids: 5                        # 5 levels = 10 orders
```

### Aggressive Grid
```yaml
grid_range_pct_down: 5.0            # Groter bereik
grid_range_pct_up: 12.0
num_grids: 7                        # Meer levels
```

### ATR-Based (Dynamic)
```yaml
use_atr_grid_ranges: true           # Volatility-based sizing
atr_multiplier_down: 1.0
atr_multiplier_up: 1.5
use_asymmetric_grids: true          # Meer ruimte voor upside
```

## Risk Management

### Daily Limits
```yaml
max_daily_loss_pct: 3.0             # Max 3% per dag
max_daily_loss_usdt: 30.0           # Max $30 per dag
max_weekly_loss_pct: 8.0
```

### Per-Trade Limits
```yaml
stop_loss_pct: 5.0                  # 5% SL
take_profit_pct: 1.0                # 1% TP
min_profit_pct: 0.25                # 0.25% min (fees + buffer)
```

### Position Limits
```yaml
max_exposure_per_coin_pct: 0.3      # Max 30% per coin
max_total_exposure_pct: 0.9         # Max 90% totaal
max_open_orders: 10                 # Max 10 orders
```

## Trend Filtering

### Entry Criteria
```yaml
min_entry_strength_24h: 1.0         # Min 1% 24h trend
min_entry_strength_4h: 0.5          # Min 0.5% 4h trend
min_entry_strength_1h: 0.0          # 1h mag flat zijn
```

### Coin Rotation
```yaml
switch_threshold_percent: 1.0       # Switch als trend 1% draait
min_switch_interval_seconds: 900    # Min 15min tussen switches
min_hold_time_seconds: 900          # Hold min 15min
```

## Bitget Specifics

### Fees
- **Standard**: 0.1% maker / 0.1% taker
- **VIP 1**: 0.08% (>$50k 30d volume)
- **VIP 2**: 0.06% (>$500k 30d volume)
- **BGB discount**: Extra korting met BGB holdings

### Rate Limits
- **Orders**: 10/sec
- **Public API**: 20 req/sec
- **Private API**: 10 req/sec
- **Buffer**: 80% gebruikt (config: `rate_limit_buffer: 0.8`)

### Tick Sizes (Approximate)
- **BTC-USDT**: $0.01 (price), 0.00001 BTC (size)
- **ETH-USDT**: $0.01 (price), 0.0001 ETH (size)
- **SOL-USDT**: $0.001 (price), 0.01 SOL (size)

Actual tick sizes fetched from exchange API.

### Wallets
Bitget heeft **gescheiden wallets**:
- **SPOT**: Voor spot trading (deze bot)
- **FUTURES**: Voor perpetual contracts
- Transfer via: Assets > Transfer

## Parallel met Kraken

### Beide Bots Tegelijk
```bash
# Check processen
ps aux | grep hummingbot

# Kraken bot (bestaand)
12345  .../hummingbot --script multi_coin_grid_v2.py

# Bitget bot (nieuw)
67890  .../hummingbot --script spot_grid_bitget.py
```

### Onafhankelijke Configs
```
Kraken:  multi_coin_grid_pro/config/config.prod.yaml
Bitget:  multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml
```

### Onafhankelijke Logs
```
Kraken:  logs/multi_coin_grid_*.log
Bitget:  logs/spot_grid_bitget_*.log
```

## Troubleshooting

### Connection Issues
```bash
# Test connector
>>> connect bitget

# Check status
>>> status

# View logs
tail -f logs/spot_grid_bitget_*.log
```

### Balance Issues
```bash
# Check balances
>>> balance limit=bitget

# Ensure USDT in SPOT wallet (not Futures)
# Transfer via Bitget UI if needed
```

### Order Rejections
Meestal tick/lot size issues:
- Controller handelt dit automatisch af
- Check logs voor details
- Verify via Bitget trading rules API

### Rate Limiting
```yaml
# Verlaag frequentie in config:
order_refresh_time: 60              # Was 30
rate_limit_buffer: 0.7              # Was 0.8
price_update_interval: 60           # Was 30
```

## Files Structure

```
multi_coin_grid_pro/spot_bitget/
├── __init__.py                     # Module init
├── config_schema.py                # SpotGridBitgetConfig class
├── config_manager.py               # Config loader
├── controller.py                   # SpotGridBitgetController
├── QUICK_START.md                  # Setup guide
├── README.md                       # This file
└── config/
    └── spot_grid_bitget.yaml       # Main config

scripts/
└── spot_grid_bitget.py             # Strategy entry point
```

## Next Steps

1. ✅ **Test eerst**: `paper_trading: true`
2. ✅ **Start klein**: 1 pair, $15 orders
3. ✅ **Monitor**: Check eerste 10 trades
4. ✅ **Scale up**: Verhoog geleidelijk
5. ✅ **Optimize**: Tune grid parameters

## Support

- **Config**: `multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml`
- **Logs**: `logs/spot_grid_bitget_*.log`
- **Quick Start**: `multi_coin_grid_pro/spot_bitget/QUICK_START.md`
