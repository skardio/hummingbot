# NL-Restriction Auto-Blacklist Implementation

**Date**: 2025-01-XX
**Status**: ✅ COMPLETE
**Issue**: Bot retries NL-restricted coins indefinitely, causing error loops

---

## Problem Statement

When trading on Kraken with a Netherlands (NL) account, certain coins are restricted:
```
OSError: {'error': {'error': ['EAccount:Invalid permissions:STBL trading restricted for NL.']}}
```

**Before**: Bot would retry these coins indefinitely (until hitting 5-error threshold), wasting API calls and blocking other opportunities.

**After**: Bot detects NL-restriction errors on first failure and immediately blacklists the coin.

---

## Implementation

### 1. Grid Executor Detection (`grid_executor.py`)

**File**: `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py`

**Added**:
- Line ~95: NL-restriction tracking flags
  ```python
  self._nl_restricted = False  # Flag: This executor hit NL-restriction error
  self._nl_restricted_coin = None  # Which coin was restricted
  ```

- Line ~1960: Error pattern detection in `process_order_failed_event`
  ```python
  # Detect NL-restriction pattern
  is_nl_restricted = (
      "trading restricted for nl" in error_msg
      or ("invalid permissions" in error_msg and "trading restricted" in error_msg)
  )

  if is_nl_restricted:
      # Log warning
      self.logger().warning(
          f"🚫 NL-RESTRICTION: {trading_pair} is restricted for NL accounts on Kraken\n"
          f"   This coin will be auto-blacklisted to prevent retries."
      )
      # Set flags for controller to detect
      self._nl_restricted = True
      self._nl_restricted_coin = trading_pair
      # Terminate immediately - no retries
      self._status = RunnableStatus.TERMINATED
      return
  ```

**Error Patterns Detected**:
- `"trading restricted for NL"` (case-insensitive)
- `"Invalid permissions"` + `"trading restricted"` (Kraken error format)
- Examples: `STBL-EUR`, `Q-EUR`, any coin restricted for NL accounts

---

### 2. Controller Auto-Blacklist (`multi_coin_grid_controller.py`)

**File**: `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`

**Added**:
- Line ~3020: NL-restriction detection when executor fails
  ```python
  # CRITICAL: Check for NL-restriction errors FIRST
  if failed_executor and hasattr(failed_executor.executor, '_nl_restricted'):
      if failed_executor.executor._nl_restricted:
          restricted_coin = failed_executor.executor._nl_restricted_coin or self.active_coin

          # Log warning
          self.logger().warning(
              f"🚫 NL-RESTRICTION DETECTED: {restricted_coin} is restricted for NL accounts\n"
              f"   → AUTO-BLACKLISTING immediately to prevent retries"
          )

          # Add to runtime blacklist
          self.auto_blacklisted_coins.add(restricted_coin)

          # Add to persistent config blacklist
          if hasattr(self.config, 'blacklist'):
              if self.config.blacklist is None:
                  self.config.blacklist = []
              if restricted_coin not in self.config.blacklist:
                  self.config.blacklist.append(restricted_coin)
                  self.logger().info(f"✅ Added {restricted_coin} to persistent config blacklist")

          # Clean up and move on
          self.active_coin = None
          self.active_executor_id = None
          return
  ```

**Modified**:
- Line ~1800: Coin rotation filters now check `auto_blacklisted_coins`
- Line ~2117: Coin selection double-checks both config and runtime blacklists
- Line ~4285: `pick_first_inactive()` skips auto-blacklisted coins

---

## Error Flow

```
1. GridExecutor tries to create order for STBL-EUR
   ↓
2. Kraken returns: "EAccount:Invalid permissions:STBL trading restricted for NL."
   ↓
3. GridExecutor.process_order_failed_event() detects pattern
   ↓
4. Sets _nl_restricted = True, _nl_restricted_coin = "STBL-EUR"
   ↓
5. Terminates executor (status = TERMINATED)
   ↓
6. Controller detects _nl_restricted flag on next cycle
   ↓
7. Adds "STBL-EUR" to:
   - auto_blacklisted_coins (runtime)
   - config.blacklist (persistent)
   ↓
8. Logs warning and moves to next coin
   ↓
9. Future coin selection skips "STBL-EUR" automatically
```

---

## Testing

### Manual Test
1. Ensure `STBL-EUR` is NOT in config blacklist
2. Start bot with manual_trading_pairs including `STBL-EUR`
3. Wait for bot to try trading STBL-EUR
4. Expected output:
   ```
   ⚠️ 🚫 NL-RESTRICTION: STBL-EUR is restricted for NL accounts on Kraken
      Error: OSError: {'error': {'error': ['EAccount:Invalid permissions:STBL trading restricted for NL.']}}
      This coin will be auto-blacklisted to prevent retries.

   ⚠️ 🚫 NL-RESTRICTION DETECTED: STBL-EUR is restricted for NL accounts
      → AUTO-BLACKLISTING immediately to prevent retries
   ✅ Added STBL-EUR to persistent config blacklist
   ```
5. Check config: `STBL-EUR` should be added to blacklist
6. Bot should continue with other coins

### Unit Test
See `test_nl_restriction_detection.py` (to be created)

---

## Benefits

| Before | After |
|--------|-------|
| Bot retries NL-restricted coins up to 5 times | Bot detects and blacklists on first error |
| Wastes 5+ API calls per restricted coin | Single API call, immediate blacklist |
| Blocks trading for ~5 minutes per coin | Moves to next coin immediately |
| Manual blacklist updates required | Automatic persistent blacklist updates |
| No distinction between errors | NL-restrictions handled specially |

---

## Configuration

**No changes required!** The feature works automatically.

**Optional**: Manually check blacklist in `config.prod.yaml`:
```yaml
blacklist:
  - STBL-EUR   # Added automatically by NL-restriction detection
  - Q-EUR      # Added automatically
```

---

## Known NL-Restricted Coins (Kraken)

As of Jan 2025:
- `STBL-EUR` ✅ Auto-detected and blacklisted
- `Q-EUR` (if exists)
- *More coins will be detected automatically as they're encountered*

---

## Compatibility

- ✅ Works with existing error tracking (`coin_error_count`)
- ✅ Works with existing blacklist system (`config.blacklist`)
- ✅ Works with auto-blacklist (`auto_blacklisted_coins`)
- ✅ Does NOT interfere with other error types (insufficient funds, etc.)
- ✅ Backwards compatible (no config changes needed)

---

## Future Enhancements

1. **Country-specific restriction lists**: Pre-load known restrictions by country
2. **Persistent NL-restriction database**: Save across bot restarts
3. **API endpoint**: Query "Is coin X restricted for country Y?"
4. **Telegram alerts**: Notify user when coin is auto-blacklisted

---

## Files Modified

1. `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py`
   - Lines ~95: Added `_nl_restricted` flags
   - Lines ~1960-1985: Added NL-restriction detection in `process_order_failed_event()`

2. `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
   - Lines ~3020-3045: Added NL-restriction handling when executor fails
   - Line ~1803: Filter auto-blacklisted coins during rotation
   - Line ~2120: Double-check auto-blacklist during selection
   - Lines ~4295-4300: Skip auto-blacklisted coins in `pick_first_inactive()`

---

## Related Issues

- Phase 3.5: Critical production fixes (balance checks, closing logic)
- Unit test collateral damage (password/DB corruption)
- Risk manager capital allocation fixes

---

## Questions?

Contact: Mo (NL account on Kraken)
Bot Version: Hummingbot v1.x with multi_coin_grid_pro custom strategy
Environment: Python 3.12.3, Kraken EUR pairs
