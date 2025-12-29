# 🎯 MarketData Analysis Toolkit

## Quick Start

MarketData collection is nu **ENABLED** in je bot config!

Na een paar uur data collection kan je deze scripts gebruiken:

## 📊 Available Scripts

**Alle scripts detecteren automatisch je database!**
- Zonder argument: gebruikt meest recente .sqlite in data/
- Met argument: specifieke database

### 1. Find Best Grid Pairs
**Vind de beste coins voor grid trading op basis van spread, volatility en depth**

```bash
# Auto-detect database
python3 find_best_grid_pairs.py

# Specifieke database
python3 find_best_grid_pairs.py data/multi_coin_grid_v2.sqlite
```

**Output**:
- Top 15 pairs ranked op grid suitability
- Concrete config recommendations (grid spacing, profit target)
- Expected daily returns

**Wanneer gebruiken**: Elke dag of week om je coin selectie te optimaliseren

---

### 2. Calculate Slippage Risk
**Bereken echte slippage voor je order sizes**

```bash
# Auto-detect database
python3 calculate_slippage_risk.py BTC-EUR 1000 SELL

# Specifieke database
python3 calculate_slippage_risk.py MATIC-EUR 500 BUY data/my_bot.sqlite
```

**Output**:
- Average, min, max slippage %
- Aantal levels needed
- Risk assessment (LOW/MODERATE/HIGH)
- Recommended max order size

**Wanneer gebruiken**:
- Voor je panic exit sizes instelt
- Als je position size wil verhogen
- Bij nieuwe trading pairs

---

### 3. Explain No-Trade Decisions
**Debug waarom bot niet tradede op specifiek moment**

```bash
# Auto-detect database
python3 explain_no_trade_decisions.py 1735481234000

# Specifiek pair
python3 explain_no_trade_decisions.py 1735481234000 BTC-EUR

# Specifieke database
python3 explain_no_trade_decisions.py 1735481234000 BTC-EUR data/my_bot.sqlite
```

**Output**:
- Market conditions op dat moment (spread, depth)
- Waarschijnlijke redenen (spread te hoog, lage liquidity, etc)
- Orderbook snapshot analyse

**Wanneer gebruiken**:
- Bot trade niet en je weet niet waarom
- Debugging filter logic
- Verifying market conditions

---

### 4. Optimize Database
**Maak database sneller met indexes**

```bash
# Auto-detect database
python3 optimize_market_data_db.py

# Specifieke database
python3 optimize_market_data_db.py data/multi_coin_grid_v2.sqlite
```

**Output**:
- Creates performance indexes
- Shows DB size and statistics
- Suggests cleanup if needed

**Wanneer gebruiken**: Eenmalig na eerste data collection

---

### 5. Cleanup Old Data
**Verwijder oude data om ruimte te besparen**

**Default retention: 30 dagen** (pas aan via command line)

```bash
# Dry run - default 30 dagen
python3 cleanup_old_market_data.py

# Override: keep 14 days (dry run)
python3 cleanup_old_market_data.py 14

# Actually delete (default 30 dagen)
python3 cleanup_old_market_data.py --execute

# Keep 14 days en execute
python3 cleanup_old_market_data.py 14 --execute

# Specifieke database
python3 cleanup_old_market_data.py 30 --execute data/my_bot.sqlite
```

**Output**:
- Shows records to delete
- Estimated space savings
- Vacuums DB to reclaim space

**Wanneer gebruiken**: Maandelijks of bij diskspace issues

---

## 🚀 Workflow Example

### Day 1: Enable Collection
```bash
# Already done! Config is updated
./start  # or restart bot
```

### Day 2: First Analysis
```bash
# After 24h of data
python3 find_best_grid_pairs.py
```

**Output example**:
```
🎯 BEST PAIR: MATIC-EUR
   • Avg Spread: 0.142%
   • Volatility: 4.2% (24h)
   • Liquidity: 127.3 units

📋 SUGGESTED GRID CONFIG:
   grid_spacing_percentage: 0.504
   profit_per_grid: 0.213
   number_of_grids: 8
```

### Day 3: Optimize Position Sizes
```bash
# Test your typical order sizes
python3 calculate_slippage_risk.py MATIC-EUR 500 SELL
python3 calculate_slippage_risk.py BTC-EUR 1000 SELL
```

**Output example**:
```
💧 SLIPPAGE ANALYSIS: MATIC-EUR

📊 SLIPPAGE STATISTICS:
   • Average Slippage: 0.087%
   • Max Slippage: 0.234%

💡 RISK ASSESSMENT:
   🟢 LOW RISK: Market orders are safe for this size
```

### Ongoing: Debug Issues
```bash
# When bot doesn't trade, check logs for timestamp
# Example: 2024-12-29 15:30:45 - NO BUY signal

# Convert to timestamp (15:30:45 = 1735481445000)
python3 explain_no_trade_decisions.py 1735481445000 MATIC-EUR
```

---

## 💡 Pro Tips

### Daily Routine
```bash
# Morning: Check best pairs
python3 find_best_grid_pairs.py > daily_report.txt

# Adjust bot config based on results
```

### Weekly Routine
```bash
# Optimize database
python3 optimize_market_data_db.py

# Check if cleanup needed
python3 cleanup_old_market_data.py 30  # dry run
```

### Before Increasing Position Size
```bash
# Always check slippage first!
python3 calculate_slippage_risk.py YOUR-PAIR YOUR-NEW-SIZE SELL
```

---

## 📚 Full Documentation

See [MARKET_DATA_COLLECTION_GUIDE.md](MARKET_DATA_COLLECTION_GUIDE.md) for:
- Detailed SQL queries
- Python analysis examples
- Configuration options
- Performance tuning

---

## ⚙️ Current Config

```yaml
market_data_collection:
  market_data_collection_enabled: true   ✅
  market_data_collection_interval: 60    # Every 60 seconds
  market_data_collection_depth: 20       # Top 20 levels
```

**Database**: `/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite`

---

## 🆘 Troubleshooting

### No data yet?
Wait at least 1 hour after enabling collection. Check:
```bash
sqlite3 data/multi_coin_grid_v2.sqlite "SELECT COUNT(*) FROM MarketData"
```

### Scripts not working?
Make sure you're using the bot's Python environment:
```bash
source /home/mo/.venvs/bot/bin/activate
python3 find_best_grid_pairs.py
```

### Database too large?
```bash
python3 cleanup_old_market_data.py 14 --execute  # Keep only 2 weeks
```

---

**Ready to profit! 🚀**
