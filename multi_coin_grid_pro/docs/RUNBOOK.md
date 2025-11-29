# Runbook - Operational Guide

## What to Do When...

### 🛑 Stop-Loss Triggered

**Symptoms:**
- Telegram alert: "STOP-LOSS TRIGGERED"
- Log shows: "🛑 STOP-LOSS TRIGGERED for {coin}!"
- Executor stopped

**Actions:**
1. ✅ **Verify:** Check Telegram/logs for confirmation
2. ✅ **Check Position:** Verify position was closed (check exchange)
3. ✅ **Review:** Check why stop-loss triggered (market crash? normal volatility?)
4. ✅ **Resume:** Bot will automatically continue with next coin
5. ⚠️ **If Position Not Closed:** Manually sell on exchange

**Prevention:**
- Adjust `stop_loss_pct` if too tight
- Check market conditions before resuming

---

### ⚡ Circuit Breaker Activated

**Symptoms:**
- Telegram alert: "Circuit breaker activated"
- Log shows: "⚡ CIRCUIT BREAKER: High volatility detected"
- Trading paused

**Actions:**
1. ✅ **Verify:** Check logs for volatility details
2. ✅ **Check Market:** Is there unusual market activity?
3. ✅ **Wait:** Let volatility settle (usually 5-15 minutes)
4. ✅ **Reset:** Send `/reset_circuit_breaker` to Telegram bot OR restart bot
5. ✅ **Monitor:** Watch for continued high volatility

**Prevention:**
- Adjust `circuit_breaker_threshold` if too sensitive
- Monitor market news/events

---

### ❌ API Errors >3

**Symptoms:**
- Telegram alert: "API errors exceeded threshold"
- Log shows: "❌ Consecutive API errors: {count}"
- Trading paused

**Actions:**
1. ✅ **Check Exchange:** Is Kraken API down? (check status.kraken.com)
2. ✅ **Check Network:** Is your internet connection stable?
3. ✅ **Check Rate Limits:** Are you hitting rate limits?
4. ✅ **Reset:** Send `/reset_api_errors` to Telegram bot OR restart bot
5. ✅ **Monitor:** Watch for continued errors

**Prevention:**
- Ensure stable internet connection
- Monitor API rate limits
- Use exponential backoff (already implemented)

---

### 💰 Position Not Closed on Switch

**Symptoms:**
- Bot switched coins but old position still open
- Log shows: "⚠️ Executor has open position but will be stopped"

**Actions:**
1. ✅ **Check Exchange:** Verify position on Kraken
2. ✅ **Manual Close:** Sell position manually if needed
3. ✅ **Check Logs:** Look for errors in GridExecutor
4. ✅ **Report:** This should not happen - GridExecutor should close position

**Prevention:**
- Ensure `keep_position=False` in stop action (already implemented)
- Monitor executor status

---

### 📉 Bot Stuck on Declining Coin

**Symptoms:**
- Bot trading coin with negative trend
- Not switching despite better options available

**Actions:**
1. ✅ **Check Hold Time:** Is `min_hold_time_seconds` blocking switch?
2. ✅ **Check Trend:** Verify trend data is updating
3. ✅ **Manual Override:** Stop bot, manually select better coin
4. ✅ **Adjust Config:** Reduce `min_hold_time_seconds` if needed

**Prevention:**
- Early exit for negative trends (already implemented)
- Monitor trend data quality

---

### ⏰ Bot Not Trading After Startup

**Symptoms:**
- Bot started but no trades executed
- Log shows: "⏰ Startup delay active - waiting X more minutes"
- Bot is collecting data but not trading

**Actions:**
1. ✅ **Check Startup Delay:** This is normal behavior - bot waits before first trade
2. ✅ **Check Config:** Verify `min_startup_wait_seconds` value (default: 3600 = 1 hour)
3. ✅ **Wait:** Bot will start trading automatically after delay expires
4. ✅ **Monitor Logs:** Check logs for "✅ Startup delay passed" message
5. ⚠️ **If Too Long:** Adjust `min_startup_wait_seconds` in config (e.g., 1800 for 30 minutes)

**Configuration:**
```yaml
# In multi_coin_grid.yml
min_startup_wait_seconds: 3600  # Wait 1 hour (3600 seconds) before first trade
```

**Note:** Startup delay only applies to the FIRST trade. Coin switches are not affected by this delay.

**Prevention:**
- Set appropriate startup delay based on your needs
- Longer delay = more time for market data collection
- Shorter delay = faster start but less data

---

### 🔴 Bot Crashed/Stopped

**Symptoms:**
- No Telegram alerts
- No log updates
- Process not running

**Actions:**
1. ✅ **Check Process:** `ps aux | grep hummingbot`
2. ✅ **Check Logs:** Look for crash/error in logs
3. ✅ **Restart:** Restart bot
4. ✅ **Verify:** Check Telegram for status after restart

**Prevention:**
- Use systemd/service manager for auto-restart
- Monitor process health
- Set up alerts for process death

---

### 📊 Unusual P&L Swings

**Symptoms:**
- Large losses in short time
- Unexpected gains
- P&L doesn't match expectations

**Actions:**
1. ✅ **Check Positions:** Verify all positions on exchange
2. ✅ **Check Fees:** Are fees higher than expected?
3. ✅ **Check Slippage:** Are fills at unexpected prices?
4. ✅ **Review Logs:** Check for errors or unusual behavior
5. ✅ **Pause:** Consider pausing bot to investigate

**Prevention:**
- Monitor P&L regularly
- Set up alerts for large swings
- Review trades daily

---

### 🔧 Configuration Issues

**Symptoms:**
- Validation errors on startup
- Config not loading
- Wrong values being used

**Actions:**
1. ✅ **Check Config File:** Verify YAML syntax
2. ✅ **Check Environment:** Verify `BOT_ENV` is set correctly
3. ✅ **Check Overrides:** Verify environment variable overrides
4. ✅ **Validate:** Run config validation manually
5. ✅ **Restart:** Restart bot after fixing config

**Prevention:**
- Validate config before deployment
- Use version control for configs
- Test config changes in dev environment

---

## Daily Checklist

- [ ] Check Telegram for alerts
- [ ] Review bot status (via `/status` command)
- [ ] Check P&L (via dashboard or exchange)
- [ ] Review logs for errors
- [ ] Verify positions match expectations
- [ ] Check exchange balance

## Weekly Checklist

- [ ] Review performance metrics
- [ ] Check win rate
- [ ] Review max drawdown
- [ ] Analyze best/worst performing coins
- [ ] Review and adjust configuration if needed
- [ ] Backup configuration and logs

## Emergency Contacts

- **Kraken Support:** support.kraken.com
- **Kraken Status:** status.kraken.com
- **Bot Logs:** `logs/logs_multi_coin_grid_v2.log`
- **Dashboard:** http://localhost:5000 (if running)

## Quick Commands

```bash
# Check bot status
ps aux | grep hummingbot

# View recent logs
tail -n 100 logs/logs_multi_coin_grid_v2.log

# Check for errors
grep -i error logs/logs_multi_coin_grid_v2.log | tail -n 20

# Restart bot
# (depends on your setup - systemd, screen, etc.)

# View monitoring dashboard
curl http://localhost:5000/status

# Send Telegram command
# (via Telegram bot interface)
```
