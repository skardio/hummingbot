# Bitget SPOT Grid Strategy - Quick Start

## Overzicht
Volledige multi-coin grid strategie voor **Bitget SPOT** met USDT pairs.
Gebruikt dezelfde bewezen architectuur als je Kraken bot.

## Setup (5 minuten)

### 1. API Keys Configureren
```bash
cd ~/repos/hummingbot
./start

# In Hummingbot CLI:
>>> connect bitget
```

Je wordt gevraagd om:
- **API Key**: Van Bitget website
- **Secret Key**: Van Bitget website
- **Passphrase**: Die je hebt ingesteld bij API key creatie

**Permissies nodig:**
- ✅ Spot Trading
- ✅ Read Account Info
- ❌ Withdrawal (NIET nodig)

### 2. Funding Check
Transfer USDT naar **SPOT wallet** (niet Futures!):
- **Minimum**: $150 USDT
- **Aangeraden**: $500 USDT
- Check: Bitget > Assets > Spot Account

### 3. Config Controleren
```bash
cat multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml
```

Belangrijkste settings:
```yaml
paper_trading: false              # true = test, false = live
connector_name: bitget
quote_asset: USDT
total_amount_quote: 500           # $500 capital
min_order_amount_quote: 15        # $15 per order
max_simultaneous_coins: 1         # 1 coin tegelijk

manual_trading_pairs:
  - BTC-USDT
  - ETH-USDT
  - SOL-USDT
```

### 4. Start Bot
```bash
# In Hummingbot CLI:
>>> start --script spot_grid_bitget.py
```

### 5. Monitoring
```bash
# Status check
>>> status

# Balances
>>> balance

# Active orders
>>> list

# Logs (andere terminal)
tail -f logs/spot_grid_bitget*.log
```

## Parallel met Kraken Bot

### Beide bots draaien naast elkaar:
```bash
# Check beide processen
ps aux | grep hummingbot

# Output:
# 12345  ... hummingbot  (Kraken bot)
# 67890  ... hummingbot  (Bitget bot)
```

Elke bot heeft:
- ✅ Eigen PID
- ✅ Eigen config
- ✅ Eigen connector
- ✅ Eigen logs
- ✅ Onafhankelijke execution

## Config Aanpassingen

### Meer exposure:
```yaml
total_amount_quote: 1000          # $1000 i.p.v. $500
max_simultaneous_coins: 2         # 2 coins tegelijk
```

### Meer trading pairs:
```yaml
manual_trading_pairs:
  - BTC-USDT
  - ETH-USDT
  - SOL-USDT
  - BNB-USDT      # Add
  - AVAX-USDT     # Add
  - LINK-USDT     # Add
```

### Agressievere grid:
```yaml
grid_range_pct_down: 5.0          # Groter bereik
grid_range_pct_up: 12.0
num_grids: 7                      # Meer levels
```

## Belangrijke Verschillen Bitget vs Kraken

| Aspect | Kraken | Bitget |
|--------|--------|--------|
| **Quote** | EUR | USDT |
| **Fees** | 0.16%/0.26% | 0.1%/0.1% |
| **Rate Limit** | 15-20/sec | 10/sec |
| **API Keys** | 2 componenten | 3 componenten (+ passphrase) |
| **Tick Size** | Flexibel | Strict enforced |

## Troubleshooting

### "Bitget connector not found"
```bash
# Check connectors
>>> connect

# Reconnect
>>> connect bitget
```

### "Insufficient balance"
```bash
# Check balances
>>> balance limit=bitget

# Transfer via Bitget UI:
# Assets > Transfer > Futures → Spot
```

### "Order rejected - tick size"
Orders moeten exact tick size zijn. Controller handelt dit automatisch af.

### "Rate limit exceeded"
```yaml
# In config verhoog:
order_refresh_time: 60            # Was 30
rate_limit_buffer: 0.7            # Was 0.8
```

## Safety First

### Test Flow:
1. **Paper Trading**: `paper_trading: true` → Test 24h
2. **Single Pair**: Start met alleen BTC-USDT
3. **Small Size**: Begin met $15 orders
4. **Monitor**: Check eerste 10 trades nauwkeurig
5. **Scale Up**: Verhoog gradueel na success

### Stop Bot:
```bash
# In Hummingbot:
>>> stop

# Of force kill:
kill <PID>
```

## Geavanceerde Features

### Dynamic Pair Discovery
```yaml
use_dynamic_pair_discovery: true
max_coins_to_monitor: 20
min_24h_volume_usdt: 2000000      # $2M min volume
```

### Trend Filtering
```yaml
min_entry_strength_24h: 1.5       # Min 1.5% 24h trend
min_entry_strength_4h: 1.0
min_entry_strength_1h: 0.0
```

### Risk Limits
```yaml
max_daily_loss_usdt: 50           # Max $50/dag
stop_loss_pct: 5.0                # 5% SL
take_profit_pct: 1.0              # 1% TP
```

## Support

Check logs voor details:
```bash
tail -100 logs/spot_grid_bitget_$(date +%Y-%m-%d).log
```

Config path:
```
multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml
```

Controller:
```
multi_coin_grid_pro/spot_bitget/controller.py
```

Strategy script:
```
scripts/spot_grid_bitget.py
```
