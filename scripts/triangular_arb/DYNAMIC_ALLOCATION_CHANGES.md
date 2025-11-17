# Dynamic Balance Allocation Implementation

## Summary
The bot has been updated to use **dynamic 100% balance allocation** instead of fixed amounts. This allows the bot to automatically use all available balance for each arbitrage cycle.

## Changes Made

### 1. **CONFIG Updates** (`03_monitor_continuous_24h.py`, lines 107-108)
```python
"order_amount": Decimal("1.0"),  # UNUSED: Set to 1.0 (ignored). Dynamic allocation from available balance is used instead.
"order_amount_pct": Decimal("1.0"),  # Use 100% of available base currency A balance for each arbitrage cycle
```

### 2. **Function Signature Update** (`monitor_loop()`, line 261)
- Added: `order_amount_pct: Decimal = config.get("order_amount_pct", Decimal("1.0"))`
- This safely retrieves the percentage from config (defaults to 100% if not specified)

### 3. **Dynamic Balance Fetching** (`monitor_loop()`, lines 490-503)
For each triple, the bot now:
1. **Extracts base currency** from first pair: `"ETH-USDC"` → `"ETH"`
2. **Fetches available balance** from paper-trade account:
   ```python
   available_balance = Decimal(str(market.get_balance(base_currency)))
   ```
3. **Calculates cycle amount**: `order_amount_for_cycle = available_balance * order_amount_pct`
4. **Skips if insufficient**: If balance ≤ 0, triple is skipped for that poll cycle
5. **Fallback mechanism**: If balance query fails, uses fixed `order_amount` value

### 4. **Order Amount Usage** (line 543)
- Changed from fixed: `amount_a = order_amount`
- To dynamic: `amount_a = order_amount_for_cycle`
- Now uses the dynamically calculated amount for simulation

## Behavior

### Current Flow Per Poll Cycle (Every 5 seconds)
```
For each of the 42 triples:
  1. Extract base currency A from first pair
  2. Query market.get_balance(base_currency)
  3. If balance > 0:
     - Calculate: amount_to_trade = balance * 100%
     - Fetch prices for all 3 pairs
     - Detect arbitrage edges
     - Log candidates with dynamic amount
  4. If balance ≤ 0:
     - Skip this triple (log: "Geen beschikbaar saldo...")
     - Continue to next triple
```

### Log Examples
When balance is unavailable:
```
DEBUG:__main__:Geen beschikbaar saldo voor ETH, sla triple ['ETH-EUR', 'EUR-USD', 'ETH-USD'] over
DEBUG:__main__:Geen beschikbaar saldo voor USDC, sla triple ['USDC-USDT', 'USDT-CHF', 'USDC-CHF'] over
DEBUG:__main__:Geen beschikbaar saldo voor EUR, sla triple ['EUR-GBP', 'GBP-USD', 'EUR-USD'] over
```

When balance is available and trade is detected, the amount will appear in:
```json
{"timestamp":"2025-11-09T...", "triple":[...], "edge_pct":X, "profit_pct_after_fees":Y}
```

## Configuration Options

### Use 100% of Available Balance
```python
"order_amount_pct": Decimal("1.0")  # 100% - default
```

### Use 50% of Available Balance
```python
"order_amount_pct": Decimal("0.5")  # 50%
```

### Use 25% of Available Balance
```python
"order_amount_pct": Decimal("0.25")  # 25%
```

## Expected Results

### With Paper-Trade Account Starting at 0 Balance
- All triples will be skipped with "Geen beschikbaar saldo..." message
- `checked_count` will be 0
- This is **expected behavior** - paper-trade account needs initial funding

### After Adding Balance to Paper-Trade Account
1. Bot will detect available balance for applicable currencies
2. Will calculate dynamic amount = balance * 100%
3. Will proceed with simulation using the dynamic amount
4. Log lines will show actual trade detection with realistic amounts

## Testing

To verify the implementation:

1. **Check bot is running**:
   ```bash
   ps aux | grep "03_monitor_continuous_24h.py" | grep -v grep
   ```

2. **Monitor balance checks**:
   ```bash
   tail -f logs/bot_stdout.log | grep "Geen beschikbaar saldo\|Poll"
   ```

3. **Check for candidates detected**:
   ```bash
   tail -f logs/tri_candidates.log
   ```

## Next Steps (Optional)

To fund the paper-trade account and test with real capital deployment:

1. Edit CONFIG in `03_monitor_continuous_24h.py` to add initial balances
2. Or inject balances via Hummingbot paper-trade configuration
3. Restart bot and monitor for:
   - Balance detection success messages
   - Dynamic amount calculation
   - Actual arbitrage detection with real amounts

## Technical Details

- **Balance Query**: Uses `market.get_balance(currency)` from Hummingbot paper-trade connector
- **Error Handling**: Graceful fallback to fixed amount if balance query fails
- **Precision**: All calculations use Python `Decimal` for precision
- **Logging**: Debug logs show each balance check for monitoring

## Files Modified

1. `scripts/triangular_arb/03_monitor_continuous_24h.py` - Main bot implementation
   - Line 107-108: Added `order_amount_pct` config field
   - Line 261: Added config parameter extraction
   - Lines 490-503: Added balance fetching logic
   - Line 543: Updated to use dynamic amount

2. `scripts/triangular_arb/README.md` - Updated documentation
   - Updated route count from 35 to 42
   - Documented dynamic balance allocation
   - Updated configuration table

## Summary of Behavior Changes

| Before | After |
|--------|-------|
| Fixed `order_amount: 0.03` EUR | Dynamic: `available_balance * 100%` |
| Same amount for all triples | Amount varies per triple based on available balance |
| No balance checking | Checks balance for each base currency before processing |
| No fallback for missing balances | Gracefully skips triples with 0 balance |

---

**Status**: ✅ Implementation complete and running
**Date**: 2025-11-09
**Bot Status**: Running (PID: 743446)
**Uptime**: Continuously monitoring all 42 routes every 5 seconds
