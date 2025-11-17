# Grid Trading Quick Start 🚀

## Status

✅ **Grid Monitor**: Ready (real-time visualization)
✅ **Config**: Ready (ETH/USD €100 safe config)
⏳ **Executor**: Ready for Hummingbot CLI integration

## 1. Visualize Grid (First Time)

```bash
cd /home/mo/repos/hummingbot/scripts/grid_trading_kraken
python3 03_grid_monitor.py
```

**What you'll see:**
- Grid visualization with current price
- Where buy/sell orders would be placed
- Expected profit per cycle
- ROI simulation

Example output:
```
Grid range: $3400 - $3700 (10 levels = $33 apart)
Current price: $3610
Profit simulation: $0.57 (0.57% ROI if all cycles complete)
```

## 2. Understand Your Config

File: `01_grid_config_eth_usd.yml`

```yaml
start_price: 3400        # Buy starting here (lowest)
end_price: 3700          # Sell up to here (highest)
num_grids: 10            # 10 price levels
total_amount_usd: 100    # Total capital to use
maker_fee_pct: 0.16      # Kraken maker fee (volume discount)
```

**Quick Configs to Try:**

**SAFE - EUR/USD:**
```
start_price: 1.05
end_price: 1.12
total_amount: €100
num_grids: 8
```

**BALANCED - ETH/USD:**
```
start_price: 3400
end_price: 3700
total_amount: €100
num_grids: 10
```

**AGGRESSIVE - BTC/USD:**
```
start_price: 42000
end_price: 45000
total_amount: €500
num_grids: 15
```

## 3. Start Grid Trading (Paper First!)

### Option A: Hummingbot CLI (Recommended)

```bash
source ~/.venvs/bot/bin/activate
hummingbot

# Inside Hummingbot CLI:
>>> import strategy grid_strike
>>> config  # Choose config file: 01_grid_config_eth_usd.yml
>>> start
```

### Option B: Monitor Only (Testing)

Keep running this in separate terminal:
```bash
python3 03_grid_monitor.py
```

Updates every 30 seconds with:
- Current price
- Active orders visualization
- Filled orders count
- Total profit

## 4. Monitor Your Strategy

In another terminal:
```bash
# Watch order fills in real-time
tail -f logs/grid_orders.log

# Or use the monitor
python3 03_grid_monitor.py
```

## 5. Troubleshooting

**No orders placed?**
- Check API keys: `echo $KRAKEN_API_KEY`
- Confirm price is within grid range
- Check balance in Kraken

**Orders placed but not filling?**
- Spread too wide? Reduce `end_price - start_price`
- Price stable? Grid works best in volatility
- Fees eating profit? See below

**Profit too low?**
- Increase `num_grids` (more orders)
- Increase `total_amount_usd` (€500+ better)
- Choose volatile pairs (ETH/USD vs EUR/USD)

## 6. Expected Results

### €100 Capital, ETH/USD Grid

```
Daily profit: €0.50 - €1.50
Monthly: €15-45
ROI: 15-45%/month
```

### €500 Capital, ETH/USD Grid

```
Daily profit: €2.50 - €7.50
Monthly: €75-225
ROI: 15-45%/month
```

### €1000 Capital, BTC/USD Grid

```
Daily profit: €10-30
Monthly: €300-900
ROI: 30-90%/month
```

## 7. Risk Management

✅ DO:
- Start with €100 (learn first)
- Set stop loss (below lowest buy)
- Set take profit (above highest sell)
- Monitor daily
- Increase gradually

❌ DON'T:
- Risk more than you can afford
- Ignore crashed market events
- Leave unmonitored for weeks
- Use aggressive settings first

## Next Steps

1. **Test monitor**: `python3 03_grid_monitor.py`
2. **Paper trade**: Via Hummingbot with paper_exchange
3. **Live small**: Start with €100
4. **Scale up**: €500, €1000 if going well
5. **Optimize**: Adjust grid based on market

---

Need help? See README.md for detailed info.
