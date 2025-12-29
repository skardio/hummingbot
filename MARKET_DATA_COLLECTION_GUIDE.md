# MarketData Collection Guide

## Wat is het?

De **MarketData** tabel verzamelt real-time market data (prices, order book) van je exchanges. Dit is nuttig voor:

- 📊 **Backtesting**: Historische market data voor strategie testing
- 📈 **Analysis**: Spread analysis, liquidity patterns, price movements
- 🔍 **Research**: Orderbook depth over tijd bekijken
- 🎯 **Optimization**: Strategie parameters optimaliseren met echte data

## Database Schema

```sql
CREATE TABLE MarketData (
    timestamp BIGINT PRIMARY KEY,      -- Millisecond timestamp
    exchange TEXT NOT NULL,             -- bijv. "kraken"
    trading_pair TEXT NOT NULL,         -- bijv. "BTC-EUR"
    mid_price DECIMAL(18) NOT NULL,     -- Mid price
    best_bid DECIMAL(18) NOT NULL,      -- Best bid price
    best_ask DECIMAL(18) NOT NULL,      -- Best ask price
    order_book JSON                     -- Order book snapshot {"bid": [...], "ask": [...]}
);
```

## Configuratie

### Via Hummingbot Config Command

```bash
# In Hummingbot terminal
config market_data_collection_enabled True
config market_data_collection_interval 60    # seconds (default)
config market_data_collection_depth 20       # order book levels (default)
```

### Via conf_client.yml

Bewerk `/conf/conf_client.yml`:

```yaml
market_data_collection:
  market_data_collection_enabled: true
  market_data_collection_interval: 60   # Elke 60 seconden
  market_data_collection_depth: 20      # Top 20 order book levels
```

### Programmatisch (voor custom strategies)

```python
from hummingbot.client.config.client_config_map import MarketDataCollectionConfigMap

market_data_config = MarketDataCollectionConfigMap(
    market_data_collection_enabled=True,
    market_data_collection_interval=30,   # Elke 30 seconden
    market_data_collection_depth=50       # Top 50 levels
)
```

## Hoe werkt het?

1. **Start**: Wanneer enabled, start een async task die elke X seconden draait
2. **Collect**: Voor elk trading pair op elke exchange:
   - Mid price
   - Best bid/ask
   - Order book snapshot (top N levels)
3. **Store**: Data wordt opgeslagen in SQLite database

## Data Query Examples

### Recent prices

```sql
SELECT
    datetime(timestamp/1000, 'unixepoch') as time,
    trading_pair,
    mid_price,
    best_bid,
    best_ask,
    (best_ask - best_bid) as spread
FROM MarketData
WHERE exchange = 'kraken'
  AND trading_pair = 'BTC-EUR'
ORDER BY timestamp DESC
LIMIT 100;
```

### Spread analysis

```sql
SELECT
    trading_pair,
    AVG(best_ask - best_bid) as avg_spread,
    MIN(best_ask - best_bid) as min_spread,
    MAX(best_ask - best_bid) as max_spread,
    COUNT(*) as samples
FROM MarketData
WHERE exchange = 'kraken'
  AND timestamp > (strftime('%s', 'now') - 86400) * 1000  -- Last 24h
GROUP BY trading_pair
ORDER BY avg_spread DESC;
```

### Order book depth over time

```python
import sqlite3
import json
import pandas as pd

conn = sqlite3.connect('/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite')

query = """
SELECT timestamp, order_book
FROM MarketData
WHERE trading_pair = 'BTC-EUR'
  AND exchange = 'kraken'
ORDER BY timestamp DESC
LIMIT 100
"""

df = pd.read_sql(query, conn)
df['order_book'] = df['order_book'].apply(json.loads)

# Analyze bid/ask depth
for idx, row in df.iterrows():
    bids = row['order_book']['bid']
    asks = row['order_book']['ask']
    bid_volume = sum([float(b[1]) for b in bids])  # b[1] is quantity
    ask_volume = sum([float(a[1]) for a in asks])
    print(f"Time: {row['timestamp']}, Bid Vol: {bid_volume:.2f}, Ask Vol: {ask_volume:.2f}")
```

## Performance Impact

⚠️ **Let op**:
- Elke snapshot schrijft ~1-5KB data (afhankelijk van depth)
- Bij 10 trading pairs, elke 60s = ~60-300KB/hour = ~1.5-7.2MB/day
- Bij high frequency (elke 10s) met veel pairs kan dit significant zijn

**Aanbevelingen**:
- Start met interval van 60 seconden
- Gebruik depth van 20 voor normale analysis
- Verhoog depth naar 50-100 alleen voor specifieke orderbook research
- Clean oude data periodiek:
  ```sql
  DELETE FROM MarketData
  WHERE timestamp < (strftime('%s', 'now') - 2592000) * 1000;  -- Older than 30 days
  ```

## Gebruik Cases

### 1. Backtest met historische spreads

```python
# Get historical spreads to optimize bid/ask placement
spreads = conn.execute("""
    SELECT AVG(best_ask - best_bid) as avg_spread
    FROM MarketData
    WHERE trading_pair = ? AND exchange = ?
""", (pair, exchange)).fetchone()[0]

optimal_spread = spreads * 0.8  # Place orders inside average spread
```

### 2. Liquidity monitoring

```python
# Check if enough liquidity before placing large order
def check_liquidity(pair, min_volume):
    orderbook = conn.execute("""
        SELECT order_book FROM MarketData
        WHERE trading_pair = ? AND exchange = ?
        ORDER BY timestamp DESC LIMIT 1
    """, (pair, exchange)).fetchone()[0]

    ob = json.loads(orderbook)
    total_bid_vol = sum(float(b[1]) for b in ob['bid'][:10])
    return total_bid_vol >= min_volume
```

### 3. Price impact analysis

```python
# Calculate expected price impact of order size
def estimate_price_impact(pair, size):
    ob_data = get_latest_orderbook(pair)
    cumulative = 0
    weighted_price = 0

    for price, qty in ob_data['ask']:
        if cumulative >= size:
            break
        take_qty = min(qty, size - cumulative)
        weighted_price += price * take_qty
        cumulative += take_qty

    avg_fill_price = weighted_price / cumulative if cumulative > 0 else 0
    mid_price = get_mid_price(pair)
    impact_pct = ((avg_fill_price - mid_price) / mid_price) * 100
    return impact_pct
```

## Enable voor jouw bot

```bash
# Stop bot
cd /home/mo/repos/hummingbot
./stop

# Edit config
nano conf/conf_client.yml
# Set market_data_collection_enabled: true

# Start bot
./start
```

Of via Hummingbot command line na start:
```
config market_data_collection_enabled
> True
```

## Data Export voor Analysis

```python
#!/usr/bin/env python3
import sqlite3
import pandas as pd
import matplotlib.pyplot as plt

conn = sqlite3.connect('/home/mo/repos/hummingbot/data/multi_coin_grid_v2.sqlite')

# Export to CSV
df = pd.read_sql("""
    SELECT
        datetime(timestamp/1000, 'unixepoch') as time,
        exchange, trading_pair, mid_price, best_bid, best_ask
    FROM MarketData
    ORDER BY timestamp
""", conn)

df.to_csv('market_data_export.csv', index=False)

# Plot spreads over time
for pair in df['trading_pair'].unique():
    pair_data = df[df['trading_pair'] == pair]
    pair_data['spread'] = pair_data['best_ask'] - pair_data['best_bid']
    plt.plot(pair_data['time'], pair_data['spread'], label=pair)

plt.xlabel('Time')
plt.ylabel('Spread')
plt.legend()
plt.savefig('spreads_over_time.png')
```

## 🎯 Waar dit DIRECT voordeel oplevert voor Multi-Coin Grid Bot

### 1. Grid-parameters data-driven maken (i.p.v. "gevoel")

**Probleem**: Je weet niet of je grid spacing optimaal is.

**Oplossing**: Meet echte spread + volatility per pair:

```sql
-- Kernmetric: spread in % (lower = better for grid trading)
SELECT
  trading_pair,
  AVG((best_ask-best_bid)/mid_price)*100 AS avg_spread_pct,
  MAX((best_ask-best_bid)/mid_price)*100 AS max_spread_pct,
  STDEV((best_ask-best_bid)/mid_price)*100 AS spread_volatility,
  COUNT(*) AS samples
FROM MarketData
WHERE exchange='kraken'
  AND timestamp > (strftime('%s','now')-86400)*1000  -- Last 24h
GROUP BY trading_pair
ORDER BY avg_spread_pct ASC;
```

**Wat je ermee doet**:
- Grid spacing = `avg_spread_pct * 1.5` (je wilt net boven spread zitten)
- Als `spread_volatility` > 50% van avg: coin is te chaotisch, skip
- Maker orders "net binnen" de spread plaatsen bij lage spread pairs

### 2. Multi-coin selectie verbeteren (echt onderbouwen)

**Probleem**: Je kiest coins op "gevoel" of RSI, maar vergeet microstructuur.

**Oplossing**: Score coins op:
- ✅ Lage spread
- ✅ Hoge liquiditeit (depth)
- ✅ Genoeg beweging (volatility)
- ✅ Weinig slippage risk

```sql
-- Coin ranking voor grid trading
SELECT
  trading_pair,
  AVG((best_ask-best_bid)/mid_price)*100 AS spread_pct,
  (MAX(mid_price)-MIN(mid_price))/AVG(mid_price)*100 AS price_range_pct,
  AVG(CAST(json_extract(order_book, '$.bid[0][1]') AS REAL)) AS avg_top_bid_size,
  COUNT(*) AS samples,
  -- Score: laag spread + moderate volatility + goede liquidity
  (1.0 / AVG((best_ask-best_bid)/mid_price)) *
  ((MAX(mid_price)-MIN(mid_price))/AVG(mid_price)) *
  AVG(CAST(json_extract(order_book, '$.bid[0][1]') AS REAL)) AS grid_score
FROM MarketData
WHERE exchange='kraken'
  AND timestamp > (strftime('%s','now')-86400)*1000
  AND order_book IS NOT NULL
GROUP BY trading_pair
HAVING samples > 100
ORDER BY grid_score DESC
LIMIT 10;
```

### 3. Slippage & Panic Exit optimaliseren

**Probleem**: Market orders tijdens panic kosten veel (slippage).

**Oplossing**: Meet orderbook depth → besluit market vs limit order:

```python
def should_use_market_order(pair, order_size_eur):
    """Determine if market order is safe or will cause massive slippage"""
    ob_data = conn.execute("""
        SELECT order_book FROM MarketData
        WHERE trading_pair = ? AND exchange = 'kraken'
        ORDER BY timestamp DESC LIMIT 1
    """, (pair,)).fetchone()

    if not ob_data:
        return False  # No data, use limit order

    ob = json.loads(ob_data[0])

    # Calculate depth for order size
    cumulative_eur = 0
    levels_needed = 0
    for price, qty in ob['bid'][:10]:  # Top 10 levels
        cumulative_eur += float(price) * float(qty)
        levels_needed += 1
        if cumulative_eur >= order_size_eur:
            break

    # Safe if size < 50% of top 10 levels depth
    return cumulative_eur > order_size_eur * 2
```

**Wat je ermee doet**:
- Panic exit: check depth → market order alleen als safe
- Max position size = `orderbook_depth * 0.3` (risk control)
- Stop-loss wordt limit order bij dunne orderbook

### 4. "Waarom trade ik niet?" debuggen met market context

**Probleem**: Bot trade niet, logs zeggen "NO BUY" maar je weet niet waarom.

**Oplossing**: Join bot logs met MarketData timestamps:

```python
# Example: analyze why bot didn't buy at specific times
no_buy_times = [1735481234000, 1735481294000, 1735481354000]  # from logs

for ts in no_buy_times:
    market_ctx = conn.execute("""
        SELECT
            trading_pair,
            (best_ask-best_bid)/mid_price*100 AS spread_pct,
            mid_price,
            CAST(json_extract(order_book, '$.bid[0][1]') AS REAL) AS top_bid_size
        FROM MarketData
        WHERE timestamp BETWEEN ? AND ?
    """, (ts - 5000, ts + 5000)).fetchall()  # ±5 sec window

    print(f"Timestamp: {ts}")
    for pair, spread, price, depth in market_ctx:
        print(f"  {pair}: spread={spread:.3f}%, price={price:.4f}, depth={depth:.2f}")
        if spread > 0.5:
            print(f"    → Spread te groot!")
        if depth < 10:
            print(f"    → Liquiditeit te laag!")
```

### 5. Realistische Backtests met echte spreads

**Probleem**: Backtest gebruikt vaste 0.26% fee, maar echte kosten variëren.

**Oplossing**: Gebruik real spreads uit MarketData:

```python
def backtest_with_real_spreads(trades_df, market_data_df):
    """Add realistic fill costs based on actual spreads"""
    for idx, trade in trades_df.iterrows():
        # Find nearest market data point
        ts = trade['timestamp']
        market_snap = market_data_df[
            (market_data_df['timestamp'] >= ts - 30000) &  # 30s window
            (market_data_df['timestamp'] <= ts + 30000) &
            (market_data_df['trading_pair'] == trade['pair'])
        ].iloc[0]

        if trade['side'] == 'BUY':
            # Pay ask + slippage
            fill_price = market_snap['best_ask']
        else:
            # Get bid - slippage
            fill_price = market_snap['best_bid']

        trades_df.at[idx, 'realistic_fill_price'] = fill_price
        trades_df.at[idx, 'realistic_cost'] = abs(fill_price - trade['expected_price'])

    return trades_df
```

## 📊 3 Scripts die METEEN waarde geven

### Script A — Welke pairs zijn het best gridbaar?

<function_calls>
<invoke name="create_file">
<parameter name="filePath">/home/mo/repos/hummingbot/find_best_grid_pairs.py
