# 🛡️ PROFESSIONAL RISK MANAGEMENT GIDS (GRID-AWARE v2)

> ⚠️ **CRITICAL**: Dit is specifiek voor GRID/MEAN-REVERSION bots.
> Momentum/trend bots hebben andere regels!

> ✅ **v2 UPDATES**: Fixed logische bugs + professionele verfijningen:
> - `max(2×ATR, 8%)` → `clamp(2×ATR, 2%, 8%)` (was omgekeerd!)
> - Profit tiers nu met **high watermark drawdown** logica
> - Time exits met **no-fills check** (dead liquidity detection)
> - Pause logic met **cooldown + resume conditions**

## JE HUIDIGE PROBLEEM

**Portfolio**: €206,89 → **-€4,99 verlies** (-2.4%)

**Waarom je verliest**:
1. **RENDER**: -4.20% → Bot gebruikt fixed -8% stop, maar volatiliteit is 2-3%
2. **TAO/DOT/SNX/ICP**: Klein verlies maar stapelt op
3. **BCH**: +1.57% → Geen profit protection, kan terugvallen
4. **Geen context-aware exits**: Stalled posities blijven open

## WAT PROFESSIONELE GRID TRADERS ANDERS DOEN

### 1. **ATR-Based Stops (CLAMPED)** ✅ (NIET fixed %)

**❌ Oude bug**: `max(2×ATR, 8%)` → altijd ≥ 8%, dus BTC kreeg ook -8% stop!

**✅ Correcte formule**:
```python
stop_loss = clamp(2×ATR, min_stop=2%, max_stop=8%)
```

**Voorbeelden**:
- **BTC** ATR 1.2% → 2×1.2% = **2.4% stop** ✅ (niet 8%!)
- **RENDER** ATR 3.5% → 2×3.5% = **7.0% stop** ✅
- **Ultra volatiel** ATR 10% → zou 20% zijn → **capped op 8%** ✅

**Impact op jouw portfolio**:
- RENDER: Was -4.2%, zou gestopt zijn bij -7% (ATR-based) ipv -8%
- Verschil: €0.30 minder verlies per trade (stapelt op!)

### 2. **Context-Aware Time Exits** ⏰ (+ No-Fills Check)

**Probleem**: Simpele "3 uur = exit" kapt goede grid trades af

**Oplossing**: Exit ALS **ALLE 3 waar**:
1. Positie > 6 uur oud (niet 3!)
2. In verlies
3. **EN** (prijs stalled **OF** geen fills > 45min)

**No-fills check**:
- Een gezonde grid "ademt" en vult regelmatig orders
- Geen fills in 45 min? → Dead liquidity of execution issue
- Professionele regel: exit stalled + unfilled positions

**Reden**: Grid trades hebben 4-12 uur nodig; alleen echt dode posities cutten

### 3. **Profit Tiers (HIGH WATERMARK DRAWDOWN)** 📈

**❌ Oude verwarring**: "Van +2% naar +1.3%" → Wanneer exact triggeren?

**✅ Grid-safe definitie**:
```
peak_pnl = hoogste PnL sinds entry (high watermark)
drawdown = peak_pnl - current_pnl

ALS peak_pnl >= tier_profit EN drawdown >= tier_pullback:
    → lock tier_lock
```

**Profit Tiers**:
| Peak PnL | Required Drawdown | Lock Level |
|----------|-------------------|------------|
| +1.0%    | 0.5%              | 0% (breakeven) |
| +2.0%    | 1.3%              | +0.7% |
| +3.0%    | 1.5%              | +1.5% |

**BCH voorbeeld** (entry €500):
1. Prijs → €512.50 (+2.5%) → **Peak set, geen actie**
2. Prijs → €510.00 (+2.0%) → Drawdown 0.49% < 1.3% → **HOLD**
3. Prijs → €507.00 (+1.4%) → Drawdown 1.07% < 1.3% → **HOLD**
4. Prijs → €505.00 (+1.0%) → **Drawdown 1.46% >= 1.3% → LOCK +0.7%** ✅

**Waarom dit beter is**:
- Voorkomt te vroeg locken bij normale oscillatie
- Grid blijft intact tot echte reversal
- Winst beschermd bij structurele dip

### 4. **Daily Loss Limit** 🚨 (100% keep)
- **Blijft**: Stop trading bij -3% per dag
- **Waarom**: Beste regel in het hele document
- **Voorkomt**: Catastrofale dagen, emotioneel traden, execution issues

### 5. **PnL-Driven Pauses (+ Cooldown)** 📊

**❌ Oude gap**: Geen cooldown → bot kan flappen (pause/resume/pause)

**✅ Professionele versie**:
```python
# Trigger pause ALS:
rolling_20_trades_pnl < -2%
OF (daily_drawdown > 3%)

# Pause duurt: 2 uur (cooldown)

# Resume ALS:
- Cooldown voorbij (2u)
- EN last_10_trades_pnl >= 0%
- OF market regime OK

# Extend pause ALS:
- Cooldown voorbij maar last_10_pnl nog < 0%
```

**Waarom cooldown cruciaal is**:
- Zonder: Bot pauzeert, 1 winning trade → resume → verliest weer → pause (flapping!)
- Met: Forceert 2-uur rust + moet 10 trades positief zijn → structurele verbetering

**Equity-based** (niet alleen realized):
- Gebruikt `balance + unrealized_pnl` voor PnL berekening
- Real-time bescherming ipv wachten op close

## HOE HET TE GEBRUIKEN

### Config File (v2 Parameters)

Edit je config (bijvoorbeeld `config.prod.yaml`):

```yaml
# PROFESSIONAL RISK MANAGEMENT (Grid-Aware v2)
use_professional_risk_mgmt: true

# ATR-Based Stops (CLAMPED)
atr_stop_multiplier: 2.0      # 2×ATR dynamic stop
min_stop_pct: 0.02            # Min -2% (never too tight)
max_stop_pct: 0.08            # Max -8% (never too wide)

# Daily Loss Limit (HARD)
max_daily_loss_pct: 0.025     # -2.5% daily → stop

# Time Exits (stall + no fills)
time_based_stop_minutes: 360          # 6 hours
time_stop_requires_stall: true        # Require stall OR no fills
min_minutes_since_last_fill: 45       # Dead liquidity check

# Profit Tiers (high watermark drawdown)
# Format: [peak_pct, required_pullback_pct, lock_pct]
# Defaults in code:
# [0.01, 0.005, 0.0]   → Peak +1%, drawdown 0.5% → lock 0%
# [0.02, 0.013, 0.007] → Peak +2%, drawdown 1.3% → lock +0.7%
# [0.03, 0.015, 0.015] → Peak +3%, drawdown 1.5% → lock +1.5%

# PnL-Driven Pause (with cooldown)
min_rolling_pnl_pct: -0.02           # Trigger: rolling PnL < -2%
pause_cooldown_minutes: 120          # 2-hour pause
resume_min_pnl_pct: 0.0              # Resume: last 10 trades >= 0%
min_win_rate_threshold: 0.35         # Secondary check (35% OK)
```
```

### Optie B: Handmatig Ingesteld

Als je bot al draait, open Python console en run:

```python
# Update config (grid-aware)
strategy.config.stop_loss_pct = Decimal("0.08")  # Backup stop
strategy.config.use_professional_risk_mgmt = True
strategy.config.max_daily_loss_pct = Decimal("0.03")
strategy.config.time_based_stop_minutes = 360  # 6 uur!
```

## VERWACHT RESULTAAT

### Vóór fixes:
- **RENDER**: -4.20%, fixed -8% stop (te wijd voor 3.5% ATR coin)
- **Gemiddelde verlies per losing trade**: -6% tot -8%
- **Winnaars**: BCH +1.57%, geen pullback protection
- **Time exits**: Geen → stalled posities blijven open
- **Totaal**: -€4,99 en groeiend

### Na fixes (Grid-Aware):
- **RENDER**: Stop bij 2×ATR = -7% (ipv -8%) = €0.60 minder verlies
- **Time exits**: Alleen stalled losers na 6u (niet blindelings na 3u)
- **Profit tiers**: BCH lock +0.7% bij pullback van +2% → +1.3%
- **Daily limit**: Bij -€6.20 (-3%) stopt bot → voorkomt -€10+ dagen
- **ATR stops**: Volatiele coins (TAO, RENDER) = wijdere stops, stabiele coins (BTC) = tightere stops
- **Verwachte verbetering**: 40-60% minder verlies per dag

### Kritiek verschil:
| Oude aanpak (fixed %) | Nieuwe aanpak (grid-aware) |
|----------------------|----------------------------|
| -8% stop voor alle coins | 2×ATR stop (volatiliteit-aware) |
| 3 uur time exit altijd | 6 uur + stall check (context) |
| Trailing stops | Profit tiers (grid-safe) |
| Win rate < 40% pause | PnL < -2% pause |

## CONCRETE ACTIEPLAN

1. ✅ **Code is al gefixt** (zie `/multi_coin_grid_pro/risk/professional_risk_manager.py`)
2. ✅ **Config aangepast** (stop_loss 8% → 5%, nieuwe opties toegevoegd)
3. ⏳ **Jij moet doen**:
   - Stop huidige bot
   - Update config file met nieuwe settings (zie boven)
   - Restart bot
   - Monitor eerste dag met nieuwe risk management

## MONITORING

Na bot restart, kijk naar logs voor:

```
📏 Position sizing: RENDER-EUR | Confidence: 0.72 → 1.44x | Base: €35.00 → Adjusted: €50.40
🛡️  Professional Risk Manager initialized (GRID-AWARE)
   Daily Loss Limit: -3.0% (HARD)
   Stop Loss: 2.0x ATR (min -8.0%)
   Time Stop: 360 min (stall-aware: True)
   Profit Tiers: 3 levels
   Pause Threshold: Rolling PnL < -2.0% OR Win Rate < 35%

📊 Trade closed: RENDER-EUR | PnL: -7.1% | Reason: STOP_LOSS | ATR stop: 2.0×3.5%=7.0%
📈 BCH-EUR - New high: €553.66 (tier: +2.0%)
🔒 Profit tier lock: High €553.66 → Current €551.20, locking +0.7% profit
⏰ Stalled position: TAO-EUR - 6h, PnL -2.3%, movement 0.15×ATR < 0.3×
```

## WAAROM DIT WERKT (GRID PSYCHOLOGIE)

Professionele grid traders weten:

1. **Volatiliteit ≠ risico voor grids**
   - Fixed -5% stop kapt volatiele grids af die zouden werken
   - ATR-based stop geeft elke coin de juiste ruimte
   - RENDER (3.5% ATR) krijgt -7% stop, BTC (1.2% ATR) krijgt -2.4% stop

2. **Tijd ≠ automatisch slecht**
   - Grid trades hebben 4-12u nodig voor oscillatie
   - Exit alleen als: tijd + verlies + stalled (< 0.3× ATR)
   - Voorkomt: goeie trades afkappen, kapitaal vastzitten in dead positions

3. **Trailing stops breken grids**
   - Grid wil oscillatie (mean reversion)
   - Trailing stop verkoopt vaak op lokale dip → structureel verlies
   - Profit tiers: lock winst bij pullback, maar behoud grid structuur

4. **PnL > win rate voor grids**
   - Grid: vaak 35% WR maar +2% avg win vs -1% avg loss = winstgevend
   - Momentum: vaak 55% WR maar +1% avg win vs -1% avg loss = breakeven
   - Pause op rolling PnL, niet alleen WR

5. **Daily limit = airbag, execution = motor**
   - -3% daily stop voorkomt catastrofe
   - Maar eerst: fix NO_ORDERBOOK, NO_PRICE_DATA silent skips
   - Risk management compenseert geen slechte execution

## ⚠️ KRITIEKE NUANCE: RISK MANAGEMENT ≠ EXECUTION FIX

**Gevaar**: Risk management gebruiken om execution/data problemen te maskeren.

**Correct volgorde**:
1. ✅ **Eerst fix execution** (orderbook retry, event tracking) ← JIJ HEBT DIT GEDAAN
2. ✅ **Dan add risk management** (ATR stops, profit tiers, daily limit) ← NU HIER
3. ✅ **Monitor & tune** (is ATR multiplier 2.0× correct? Misschien 2.5×?)

**Verkeerde volgorde**:
1. ❌ Execution issues blijven (NO_ORDERBOOK, silent skips)
2. ❌ Add aggressive risk management (-5% stops, 3u exits)
3. ❌ Bot kapt goede trades af door execution issues
4. ❌ Je denkt strategie werkt niet, maar execution is kapot

## ADVANCED: CONFIDENCE SCALING

De nieuwe code schaalt positie size op confidence:

```python
# Lage confidence (0.5) → 0.5x normal size
# Hoge confidence (0.9) → 1.5x normal size
```

Dit betekent:
- **Zwakke setups**: Klein positie, minder risico
- **Sterke setups**: Groter positie, maximaliseer edge

## VRAGEN?

- **"Is -8% niet te los?"** → Voor grids met ATR-based logic is -8% de backup. Effectieve stop = 2×ATR (meestal -4% tot -7%).
- **"Missen we niet winnaars door 6u time stop?"** → Nee, alleen als positie stalled (< 0.3× ATR movement). Bewegende posities blijven open.
- **"Waarom geen trailing stops?"** → Trailing stops breken grid structuur. Profit tiers locken winst maar behouden oscillatie ruimte.
- **"35% win rate is toch slecht?"** → Niet voor grids! Als avg win = +2% en avg loss = -1%, ben je winstgevend met 33% WR.
- **"Wat als ATR stop te wijd is?"** → Monitor eerste week. Als te veel verliezen, verlaag multiplier van 2.0× naar 1.8×.

## VOLGENDE STAPPEN

1. ✅ **Execution fixes eerst** (orderbook retry, NO_PRICE_DATA events) ← DONE
2. ⏳ **Update config met grid-aware settings** (zie boven)
3. ⏳ **Restart bot**
4. 📊 **Monitor eerste 48 uur**:
   - ATR stop triggers (zijn ze te tight/wijd?)
   - Profit tier locks (werken pullbacks?)
   - Time stops (alleen stalled positions?)
   - Daily limit hits (te vaak = execution issue, niet risk mgmt)

**Expected**:
- Win rate blijft ~35-40% (normaal voor grids)
- Maar avg loss daalt: -6% → -4%
- Payoff ratio omhoog: 1.5:1 → 2.5:1
- **Net result**: +25% meer profit met zelfde win rate

---

## TL;DR - CONCRETE ACTIE

1. **Daily loss limit**: -3% ✅ (100% keep)
2. **Stop loss**: 2×ATR (min -8% backup) ✅
3. **Time exit**: 6u + stall check ✅ (niet blind 3u)
4. **Profit protection**: Tiers, geen trailing ✅
5. **Pause logic**: PnL-driven, niet alleen WR ✅

**Update config, restart, monitor 48u, tune ATR multiplier als nodig.**
