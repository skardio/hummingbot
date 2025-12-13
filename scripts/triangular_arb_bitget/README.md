# Bitget Triangular Arbitrage

Triangular arbitrage tools for Bitget Spot exchange.

## Fee Structure

Bitget Spot (VIP0):
- **Maker fee**: 0.10%
- **Taker fee**: 0.10%
- **Total roundtrip**: 0.30% (3 trades)
- **Target edge**: > 0.35% to be profitable

This is significantly lower than Kraken's API fees (0.26% taker × 3 = 0.78%).

## Scripts

### 1. Route Discovery
```bash
python3 scripts/triangular_arb_bitget/01_discover_routes.py
```
Discovers and ranks triangular routes by 24h volume. Outputs to `logs/bitget_top_routes.json`.

### 2. Profitability Simulation
```bash
python3 scripts/triangular_arb_bitget/02_simulate_profitability.py
```
Tests routes with real order book depth to estimate actual profitability.

### 3. Continuous Monitor
```bash
python3 scripts/triangular_arb_bitget/03_monitor_continuous.py
```
Watches routes in real-time for profitable opportunities. Logs candidates to `logs/bitget_tri_candidates.log`.

Optional: Set Telegram environment variables for notifications:
```bash
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"
```

### 4. Live Executor
```bash
# Set API keys
export BITGET_API_KEY="your_api_key"
export BITGET_SECRET_KEY="your_secret_key"
export BITGET_PASSPHRASE="your_passphrase"

# Dry run (default)
python3 scripts/triangular_arb_bitget/04_execute_live.py

# Live execution (real trades!)
export BITGET_EXECUTE_TRADES=true
python3 scripts/triangular_arb_bitget/04_execute_live.py
```

## Workflow

1. **Discover routes** (run once or daily):
   ```bash
   python3 scripts/triangular_arb_bitget/01_discover_routes.py
   ```

2. **Test profitability** (optional):
   ```bash
   python3 scripts/triangular_arb_bitget/02_simulate_profitability.py
   ```

3. **Start monitor** (runs continuously):
   ```bash
   python3 scripts/triangular_arb_bitget/03_monitor_continuous.py &
   ```

4. **Start executor** (dry run first!):
   ```bash
   python3 scripts/triangular_arb_bitget/04_execute_live.py
   ```

## Configuration

Environment variables for the executor:

| Variable | Default | Description |
|----------|---------|-------------|
| `BITGET_API_KEY` | - | Bitget API key |
| `BITGET_SECRET_KEY` | - | Bitget API secret |
| `BITGET_PASSPHRASE` | - | Bitget API passphrase |
| `BITGET_EXECUTE_TRADES` | `false` | Set `true` for real trades |
| `BITGET_ORDER_SIZE` | `50` | Order size in USDT |
| `BITGET_MIN_PROFIT` | `0.1` | Minimum profit % to execute |

## Differences from Kraken

| Feature | Kraken | Bitget |
|---------|--------|--------|
| API Fees | 0.26% taker | 0.10% taker |
| Total roundtrip | 0.78% | 0.30% |
| Base currency | EUR | USDT |
| USDT pairs | Limited | 600+ |
| Competition | Lower | Higher |

## Expected Profitability

Due to lower fees, Bitget has better profit potential:
- **Kraken**: Need >0.80% theoretical edge → Very rare
- **Bitget**: Need >0.35% theoretical edge → More opportunities

However, Bitget has:
- More competition (faster traders)
- Higher liquidity in majors
- Better API performance

## Risk Warning

⚠️ **Triangular arbitrage is risky:**
- Opportunities are fleeting (milliseconds)
- Slippage can eat profits
- Failed legs can leave you with unwanted assets
- Market orders have no price guarantee

**Recommendations:**
1. Start with small order sizes ($10-50)
2. Run in dry-run mode first
3. Monitor closely for the first days
4. Never risk more than you can afford to lose

## Files

- `logs/bitget_top_routes.json` - Discovered routes
- `logs/bitget_simulation_results.json` - Simulation results
- `logs/bitget_tri_candidates.log` - Real-time opportunities
- `logs/bitget_executions.log` - Execution history
- `logs/bitget_monitor_stats.json` - Monitor statistics
