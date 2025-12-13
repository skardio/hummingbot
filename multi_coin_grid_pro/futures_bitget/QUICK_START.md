# 🚀 Quick Start Guide: Bitget Futures Grid

## ⚡ Snelle Start (5 minuten)

### Stap 1: API Keys Setup

**Bitget Perpetual API Keys aanmaken:**
1. Ga naar Bitget → API Management
2. Maak nieuwe API key aan met permissies:
   - ✅ Read
   - ✅ Trade
   - ✅ WebSocket
3. Kopieer: API Key, Secret Key, Passphrase

**Exporteer keys in terminal:**
```bash
export BITGET_PERPETUAL_API_KEY="jouw_api_key"
export BITGET_PERPETUAL_SECRET_KEY="jouw_secret_key"
export BITGET_PERPETUAL_PASSPHRASE="jouw_passphrase"
```

**Of in .env file:**
```bash
# .env
BITGET_PERPETUAL_API_KEY=jouw_api_key
BITGET_PERPETUAL_SECRET_KEY=jouw_secret_key
BITGET_PERPETUAL_PASSPHRASE=jouw_passphrase
```

### Stap 2: Config Aanpassen (BELANGRIJK!)

**Minimale aanpassingen** in `multi_coin_grid_pro/futures_bitget/config/futures_grid_bitget.yaml`:

```yaml
# === PAPER TRADING EERST! ===
paper_trading: true              # Start ALTIJD met paper trading!

# === CAPITAL ===
total_amount_quote: 50           # Start klein ($50)
derivative_leverage: 5           # Conservatief (5x, niet 10x!)

# === RISKGUARD (LAAT AAN!) ===
risk_guard_enabled: true         # VERPLICHT!
```

**Optioneel - Conservatief Profiel:**
Uncomment deze regels onderaan de config:
```yaml
# === CONSERVATIEF PROFIEL (BEGINNERS) ===
derivative_leverage: 5
risk_guard_max_loss_pct: -5.0
risk_guard_max_grid_time_seconds: 1800       # 30 min
risk_guard_max_grid_depth_pct: 0.50          # 50%
risk_guard_sell_starvation_seconds: 600      # 10 min
risk_guard_trend_break_pct: -1.0
```

### Stap 3: Bot Starten

**In Hummingbot:**
```bash
# Start Hummingbot
cd /home/mo/repos/hummingbot
bin/hummingbot.py

# In Hummingbot console:
>>> start --script futures_grid_bitget.py
```

**Of direct met Python:**
```bash
cd /home/mo/repos/hummingbot
python scripts/futures_grid_bitget.py
```

### Stap 4: Monitor Logs

**Watch logs in real-time:**
```bash
# In nieuwe terminal
tail -f logs/futures_grid_bitget_*.log
```

**Check voor RiskGuard triggers:**
```bash
grep "🛑 RiskGuard" logs/futures_grid_bitget_*.log
grep "🚨" logs/futures_grid_bitget_*.log  # Liquidation warnings
grep "ERROR" logs/futures_grid_bitget_*.log
```

---

## ⚠️ KRITIEKE CHECKS

### ✅ Voor Paper Trading Start:

- [ ] `paper_trading: true` in config
- [ ] `total_amount_quote: 50` (klein bedrag)
- [ ] `derivative_leverage: 5` (niet hoger!)
- [ ] `risk_guard_enabled: true`
- [ ] API keys geëxporteerd
- [ ] Config saved

### ✅ Voor Live Trading (na 1-2 dagen paper):

- [ ] Paper trading win rate > 50%
- [ ] Geen crashes in logs
- [ ] RiskGuard werkt (triggers gezien)
- [ ] Geen liquidation warnings `🚨`
- [ ] Config change: `paper_trading: false`

---

## 🎯 Wat Verwachten?

### Normale Startup Output:

```
[FUTURES] Bitget Futures Grid Strategy Started
Controller: futures_grid_bitget
Connector: bitget_perpetual
Leverage: 5x
Capital: $50 USDT
Risk Guard: ENABLED

Scanning markets...
[FUTURES] ✅ BTC/USDT entry confirmed:
24h=+2.1%, 4h=+1.3%, 1h=+0.2%

🛡️ BTC/USDT liquidation guard set:
entry=100000.0000
liquidation≈96000.0000
warning_exit=98000.0000

Grid started: BTC/USDT
```

### RiskGuard Trigger (GOED!):

```
⏰ BTC/USDT max time: 3847s > 3600s
🛑 RiskGuard STOP voor BTC/USDT: max_time

Grid stopped: BTC/USDT
Scanning for next opportunity...
```

Dit is **normaal** en **gewenst** - RiskGuard beschermt je!

### Error Output (SLECHT!):

```
❌ Failed to connect to bitget_perpetual
❌ API key invalid
🚨 BTC/USDT breached liquidation buffer
```

Als je dit ziet → **STOP BOT ONMIDDELLIJK!**

---

## 🐛 Troubleshooting

### "Failed to connect"

**Check API keys:**
```bash
echo $BITGET_PERPETUAL_API_KEY
echo $BITGET_PERPETUAL_SECRET_KEY
```

Als leeg → export keys opnieuw

### "Invalid trading pair format"

**Config fix:**
```yaml
manual_trading_pairs:
  - BTC-USDT    # Correct (dash)
  # NOT: BTC/USDT (slash is fout voor config!)
```

### "RiskGuard not working"

**Check logs:**
```bash
grep "RiskGuard" logs/futures_grid_bitget_*.log
```

Als geen output → RiskGuard werkt niet, check:
1. `risk_guard_enabled: true` in config
2. Geen Python errors in logs

### Bot crashed met Python error

**Check dependencies:**
```bash
cd /home/mo/repos/hummingbot
grep "ERROR" logs/futures_grid_bitget_*.log | tail -20
```

Most common:
- Missing `volatility_calculator` → Guards 1,3,6 disabled (OK)
- Missing `position_manager` → Guard 1 disabled (OK)
- Missing `trend_calculator` → CRITICAL, bot won't work

### Liquidation warnings verschijnen

**GEVAAR! Te hoge leverage of verkeerde markt.**

**Onmiddellijke actie:**
```bash
# In Hummingbot console
>>> stop

# Edit config
derivative_leverage: 3  # Verlaag leverage!

# Restart
>>> start --script futures_grid_bitget.py
```

---

## 📊 Monitoring Checklist

### Elke 30 minuten (eerste dag):

- [ ] Check bot nog draait (`ps aux | grep futures_grid`)
- [ ] Geen ERROR in logs
- [ ] Geen 🚨 liquidation warnings
- [ ] RiskGuard triggers < 20% van grids

### Elke paar uur:

- [ ] Check P&L (positive trend?)
- [ ] Win rate > 50%
- [ ] Max drawdown < 10%
- [ ] Funding fees onder controle

### Daily:

- [ ] Backup logs (`cp logs/futures_grid*.log backup/`)
- [ ] Check total P&L vs fees
- [ ] Adjust config als needed
- [ ] Review RiskGuard triggers (false positives?)

---

## 🎓 Learning Path

### Week 1: Paper Trading
- Doel: Leer hoe bot werkt
- Leverage: 5x
- Capital: $50 paper money
- Focus: Begrijp logs, RiskGuard triggers, entry filters

### Week 2: Micro Live
- Doel: Test met echt geld
- Leverage: 5x
- Capital: $50 real USDT
- Focus: Funding fees, slippage, echte orders

### Week 3: Scale Up (if success)
- Doel: Verhoog capital als profitable
- Leverage: 5-10x (niet hoger!)
- Capital: $100-200
- Focus: Optimize parameters, track stats

### Week 4+: Optimization
- Doel: Fine-tune voor jouw risk profile
- Test conservatief vs normaal vs agressief
- Track alles in spreadsheet
- Adjust based on data

---

## 🔥 Pro Tips

1. **Start ALTIJD paper trading** - zelfs als je ervaren bent
2. **Max 5-10x leverage** - hoger = liquidatie garantie
3. **RiskGuard nooit disablen** - hij beschermt je capital
4. **Monitor eerste 10 trades** - handmatige checks
5. **Liquidation warnings = STOP** - verlaag leverage onmiddellijk
6. **Trade niet tijdens high volatility** - ATR spikes = gevaar
7. **Backup logs daily** - voor analyse later
8. **Test 1 coin eerst** - niet hele lijst tegelijk

---

## 📞 Support Checklist

Als je hulp nodig hebt, verzamel:

1. **Config file**: `futures_grid_bitget.yaml`
2. **Last 100 lines logs**:
   ```bash
   tail -100 logs/futures_grid_bitget_*.log > debug.txt
   ```
3. **RiskGuard triggers**:
   ```bash
   grep "🛑" logs/futures_grid_bitget_*.log > riskguard.txt
   ```
4. **Errors**:
   ```bash
   grep "ERROR\|CRITICAL" logs/futures_grid_bitget_*.log > errors.txt
   ```
5. **Trade stats**: P&L, win rate, aantal trades

---

## ✅ Final Checklist Before Start

- [ ] Heb je de RISK_MANAGEMENT.md gelezen?
- [ ] Begrijp je wat leverage doet?
- [ ] Weet je wat liquidatie betekent?
- [ ] API keys correct geëxporteerd?
- [ ] Config op `paper_trading: true`?
- [ ] `derivative_leverage: 5` (niet hoger)?
- [ ] `risk_guard_enabled: true`?
- [ ] Terminal open voor log monitoring?
- [ ] Ready om bot te stoppen als needed?

**Als alle checks ✅ → je bent klaar!**

```bash
# START!
bin/hummingbot.py
>>> start --script futures_grid_bitget.py
```

**Good luck! 🚀**

---

**⚠️ REMEMBER**: Futures trading is ZEER risicovol. Verlies meer dan je investeert is mogelijk met leverage. Trade alleen met geld dat je kunt verliezen!
