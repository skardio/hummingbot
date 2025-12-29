# Quick Reference: NL-Restriction Auto-Blacklist

## What Was Done

✅ **Automatic detection** of Kraken NL-restriction errors
✅ **Immediate blacklisting** (no 5-error threshold)
✅ **Persistent blacklist** updates in config
✅ **Runtime blacklist** to skip future selections

---

## How It Works

```
Order fails → GridExecutor detects "trading restricted for NL"
           → Sets _nl_restricted flag
           → Terminates executor
           → Controller detects flag
           → Adds to auto_blacklisted_coins
           → Adds to config.blacklist
           → Moves to next coin
```

---

## Files Changed

1. **`grid_executor.py`** (2 changes)
   - Line 99-100: Added NL-restriction flags
   - Line 1960-1985: Added error detection

2. **`multi_coin_grid_controller.py`** (4 changes)
   - Line 3029-3047: NL-restriction handler
   - Line 1803: Filter auto-blacklisted during rotation
   - Line 2120: Check auto-blacklist during selection
   - Line 4297-4298: Skip auto-blacklisted in picker

---

## Example Output

When bot encounters STBL-EUR:

```log
⚠️ 🚫 NL-RESTRICTION: STBL-EUR is restricted for NL accounts on Kraken
   Error: OSError: {'error': {'error': ['EAccount:Invalid permissions:STBL trading restricted for NL.']}}
   This coin will be auto-blacklisted to prevent retries.

⚠️ 🚫 NL-RESTRICTION DETECTED: STBL-EUR is restricted for NL accounts
   → AUTO-BLACKLISTING immediately to prevent retries
✅ Added STBL-EUR to persistent config blacklist
```

---

## Testing Commands

```bash
# 1. Check syntax
cd /home/mo/repos/hummingbot
source ~/.venvs/bot/bin/activate
python -m py_compile hummingbot/strategy_v2/executors/grid_executor/grid_executor.py
python -m py_compile multi_coin_grid_pro/controllers/multi_coin_grid_controller.py

# 2. Run unit tests (optional - see test file)
python test_nl_restriction_detection.py

# 3. Start bot and monitor logs
./start_bot.sh
tail -f logs/hummingbot_*.log | grep -i "nl-restriction\|blacklist"
```

---

## What to Monitor

1. **First error**: Bot detects NL-restriction immediately
2. **Blacklist update**: Coin added to config and runtime blacklist
3. **Future selection**: Coin is skipped automatically
4. **No retries**: Bot moves to next coin without delays

---

## Known Restricted Coins

- `STBL-EUR` ✅ Will auto-blacklist
- `Q-EUR` (if exists) ✅ Will auto-blacklist
- *Any future NL-restricted coins* ✅ Will auto-blacklist

---

## Rollback (If Needed)

```bash
cd /home/mo/repos/hummingbot
git diff hummingbot/strategy_v2/executors/grid_executor/grid_executor.py
git diff multi_coin_grid_pro/controllers/multi_coin_grid_controller.py
# Review changes, then:
git checkout hummingbot/strategy_v2/executors/grid_executor/grid_executor.py
git checkout multi_coin_grid_pro/controllers/multi_coin_grid_controller.py
```

---

## Next Steps

1. ✅ Code complete
2. ⏳ Test with real NL-restricted coin (STBL-EUR)
3. ⏳ Verify blacklist updates in config
4. ⏳ Confirm bot continues to other coins
5. ✅ Deploy to production

---

## Questions?

**Q: Will this remove STBL-EUR from config.prod.yaml?**
A: No, it ADDS to the blacklist. Manual entries stay.

**Q: What if I remove STBL-EUR from blacklist manually?**
A: Bot will try again, detect restriction, and re-blacklist.

**Q: Does this work for other exchanges (Binance, Bitget)?**
A: Pattern is Kraken-specific, but can be extended for other exchanges.

**Q: Can I test without real Kraken error?**
A: Yes, see `test_nl_restriction_detection.py` for unit tests.
