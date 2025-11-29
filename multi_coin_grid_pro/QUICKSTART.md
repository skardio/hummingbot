# 🚀 Multi-Coin Grid Bot V2 - Quick Start

## Status
✅ **Code Complete** - All 11 unit tests passing
⏳ **Integration Test** - Ready to test via Hummingbot CLI

## Prerequisites

```bash
# 1. Activate Hummingbot venv
source ~/.venvs/bot/bin/activate

# get_monitored_coins.py
python multi_coin_grid_pro/scripts/get_monitored_coins.py

# 2. Export Kraken API keys
export KRAKEN_API_KEY="ld98d1D80ekCuThGZvFZnPQf4yKmuflpsn3PRLOFazNw2Jd/ECFl/6Sk"
export KRAKEN_SECRET_KEY="4izpj+vDx6wmF6UelTAyVZLH3QwyyqKY3tvO7M9rrOQRjIKm6/It87aWEG/F2xTJnKU8miPn39EGCKockuG6jw=="

# 3. Verify balance
python3 -c "import ccxt; e=ccxt.kraken({'apiKey':'ld98d1D80ekCuThGZvFZnPQf4yKmuflpsn3PRLOFazNw2Jd/ECFl/6Sk','secret':'4izpj+vDx6wmF6UelTAyVZLH3QwyyqKY3tvO7M9rrOQRjIKm6/It87aWEG/F2xTJnKU8miPn39EGCKockuG6jw=='}); b=e.fetch_balance(); print(f'Balance: EUR {b[\"EUR\"][\"free\"]:.2f}')"
```

## Method 1: Via Hummingbot CLI (Recommended)

```bash
# Start Hummingbot
cd /home/mo/repos/hummingbot
bin/hummingbot.py

# In Hummingbot CLI:
>>> start --script multi_coin_grid_v2.py

# Monitor status:
>>> status

# Stop:
>>> stop
```

## Method 2: Direct Script Import

```bash
cd /home/mo/repos/hummingbot

# Run with Python
python3 << 'EOF'
from scripts.multi_coin_grid_v2 import create_strategy
from hummingbot.connector.exchange.kraken.kraken_exchange import KrakenExchange

# Create Kraken connector
# (Note: Full initialization requires Hummingbot application context)
print("Strategy ready - use Hummingbot CLI for full functionality")
EOF
```

## Configuration

Edit: `/home/mo/repos/hummingbot/multi_coin_grid_pro/config/multi_coin_grid.yml`

Key settings:
```yaml
total_amount_quote: 50        # €50 for testing
stop_loss_pct: 0.08           # -8% stop loss
max_coins_to_monitor: 20      # Top 20 coins
trend_lookback_minutes: 30    # 30min trends
```

## What Happens

1. **Coin Discovery** (30 seconds)
   - Scans Kraken for top 20 EUR pairs by volume
   - Excludes BTC/ETH (too expensive)

2. **Trend Tracking** (30 minutes)
   - Collects price data every 30 seconds
   - Calculates 30-minute rolling trends

3. **Grid Creation** (After 30 min)
   - Selects coin with best trend (>0.5%)
   - Creates grid with 3 levels
   - Places buy orders -3% below price
   - Places sell orders +8% above price
   - Sets stop-loss at -8%

4. **Automatic Management**
   - Monitors P&L real-time
   - Refills closed grid levels
   - Switches coins after 1 hour if better trend found
   - Auto-liquidates on stop-loss trigger

## Monitoring

```bash
# Watch logs
tail -f logs/hummingbot.log | grep -i "grid\|coin\|trend"

# Check status (in Hummingbot CLI)
>>> status

# View executors (in Hummingbot CLI)
>>> executors
```

## Expected Behavior

**First 30 minutes:**
- "Discovered 20 coins"
- "Updating trends..." every 30 seconds
- "Best coin: None (insufficient data)"

**After 30 minutes:**
- "Best coin: XRP/EUR (+1.2%)"
- "Creating grid for XRP/EUR"
- "GridExecutor started"
- "Order placed: buy XRP..."

**During operation:**
- "Grid level filled, refilling..."
- "Checking for better coin..."
- "P&L: +0.8%"

## Safety Features

✅ Stop-loss at -8% (auto-liquidate)
✅ Max €50 per grid
✅ Min 1 hour between coin switches
✅ Min €5 per order
✅ Real-time P&L tracking

## Next Steps After Testing

1. ✅ Run for 1 hour with €50
2. ⏳ Verify coin discovery works
3. ⏳ Verify trend calculation accurate
4. ⏳ Verify grid creation correct
5. ⏳ Test stop-loss trigger (optional)
6. ⏳ Implement Daily Risk Limits (Phase 1.5)
7. ⏳ Implement Market-Wide Risk (Phase 1.6)

## Troubleshooting

**Import errors:**
```bash
# Verify symlinks exist
ls -la hummingbot/multi_coin_grid_*

# Should show:
# multi_coin_grid_controllers -> ../multi_coin_grid_pro/controllers
# multi_coin_grid_utils -> ../multi_coin_grid_pro/utils
```

**API errors:**
```bash
# Test Kraken connection
python3 -c "import ccxt; e=ccxt.kraken({'apiKey':'YOUR_KEY','secret':'YOUR_SECRET'}); print(e.fetch_balance())"
```

**No coins found:**
- Check if Kraken EUR pairs have >€50k volume
- Lower `min_24h_volume_eur` in config

**No trend calculated:**
- Wait full 30 minutes for data
- Check logs for price updates

## Files

- **Strategy:** `/home/mo/repos/hummingbot/scripts/multi_coin_grid_v2.py`
- **Config:** `/home/mo/repos/hummingbot/multi_coin_grid_pro/config/multi_coin_grid.yml`
- **Controllers:** `/home/mo/repos/hummingbot/multi_coin_grid_pro/controllers/`
- **Utils:** `/home/mo/repos/hummingbot/multi_coin_grid_pro/utils/`
- **Tests:** `/home/mo/repos/hummingbot/multi_coin_grid_pro/tests/`
- **Docs:** `/home/mo/repos/hummingbot/multi_coin_grid_pro/STATUS.md`

---

**Ready to test!** 🚀
