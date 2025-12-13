# 🛡️ Futures Grid Risk Management

## 📋 Overzicht

Dit document legt uit hoe de **RiskGuard** en liquidation beveiliging werken voor de Bitget futures grid controller.

---

## 🎯 Core Principe

**Futures trading met leverage = je kunt je HELE account verliezen in één trade.**

Daarom heeft deze controller **3 lagen beveiliging**:

1. **Entry Filters**: Alleen traden bij goede trends (24h + 4h + 1h)
2. **RiskGuard**: 6 automatische kill-switches
3. **Liquidation Monitor**: Emergency stop vóór exchange liquidatie

---

## 📊 Config Parameters (ALLE UITGELEGD)

### 1️⃣ Leverage & Position Mode

```yaml
derivative_leverage: 10      # 1-125x (start conservatief met 5-10x!)
position_mode: ONEWAY        # ONEWAY (simpel) of HEDGE (advanced)
```

**Wat is leverage?**
- **1x**: Je trade met je eigen capital (zoals spot)
- **10x**: Je kunt 10x je capital traden, maar verlies gaat ook 10x sneller
- **20x**: Bij 5% daling = 100% verlies = liquidatie!

**Voorbeelden:**
```
Entry: BTC @ $100,000 met $1000 capital

1x leverage:  Max verlies = $1000 (100% daling)
10x leverage: Max verlies = $1000 bij 10% daling ($90,000)
20x leverage: Max verlies = $1000 bij 5% daling ($95,000)
```

**Position Mode:**
- **ONEWAY**: Één positie per symbol (long OF short)
- **HEDGE**: Tegelijk long EN short mogelijk (voor hedging strategieën)

**Advies**: Start met ONEWAY en 5-10x leverage.

---

### 2️⃣ Liquidation Beveiliging

```yaml
liquidation_buffer_pct: 0.2               # 20% veiligheidsmarge
liquidation_safety_distance_pct: 0.5      # Stop bij 50% van afstand
```

**Hoe werkt dit?**

1. **Controller berekent liquidation price:**
   ```
   Entry: $100,000 met 20x leverage
   Liquidation: $95,000 (-5%)
   ```

2. **Liquidation buffer (20%):**
   ```
   Buffer price = $100,000 × (1 - 0.20) = $80,000
   ```
   *(Dit is een extra veiligheidsmarge)*

3. **Safety distance (50%):**
   ```
   Distance to liquidation = $100,000 - $95,000 = $5,000
   Warning price = $100,000 - ($5,000 × 0.5) = $97,500
   ```

4. **Als prijs daalt naar $97,500 → EMERGENCY STOP!**

**Waarom?**
Als we wachten tot liquidation ($95,000) = **te laat**!
Bij $97,500 hebben we nog tijd om veilig te exiten.

**Log output:**
```
🛡️ BTC/USDT liquidation guard set:
   entry=100000.0000
   liquidation≈95000.0000
   warning_exit=97500.0000
```

---

### 3️⃣ Emergency Exits (Tighter dan Spot)

```yaml
futures_emergency_exit_pct: -1.5   # Emergency bij -1.5%
futures_hard_stop_pct: -2.5        # Hard stop bij -2.5%
```

**Waarom strakker dan spot?**

| Grid Type | Emergency | Hard Stop | Reden |
|-----------|-----------|-----------|-------|
| **Spot** | -2.0% | -3.0% | Geen liquidatie risico |
| **Futures** | -1.5% | -2.5% | Liquidatie risico! |

Met **20x leverage**:
- -1.5% grid verlies = -30% op je capital!
- -2.5% grid verlies = -50% op je capital!

**Bij 10x leverage is dit minder extreem, maar nog steeds gevaarlijk.**

---

### 4️⃣ Entry Filters (Multi-Timeframe)

```yaml
# Normale modus (24h data beschikbaar)
futures_min_entry_strength_24h: 1.5   # 24h trend > +1.5%
futures_min_entry_strength_4h: 1.0    # 4h trend > +1.0%
futures_min_entry_strength_1h: 0.0    # 1h trend ≥ 0.0%

# Warmup modus (24h data nog niet compleet, eerste uur bot draait)
warmup_min_4h_trend_pct: 1.0    # 4h trend > +1.0%
warmup_min_1h_trend_pct: 0.5    # 1h trend ≥ +0.5%
```

**Logica:**

**Spot grid** kan traden in bear market omdat:
- Geen liquidatie risico
- Grid kan maanden draaien
- DCA (Dollar Cost Average) werkt

**Futures grid** moet **alleen in uptrend** omdat:
- Liquidatie risico = positie moet snel profit maken
- Downtrend met leverage = verliezen stapelen op
- Funding fees kosten geld bij lange posities

**Entry voorbeeld:**
```
BTC trends:
- 24h: +2.1% ✅ (> +1.5%)
- 4h:  +1.3% ✅ (> +1.0%)
- 1h:  +0.2% ✅ (≥ 0.0%)

→ ALLE checks passed → Grid mag starten!
```

**Rejected voorbeeld:**
```
BTC trends:
- 24h: +1.8% ✅ (> +1.5%)
- 4h:  +0.8% ❌ (< +1.0%)  ← BLOCKED!
- 1h:  -0.3% ❌ (< 0.0%)   ← BLOCKED!

→ Grid start NIET (trend niet sterk genoeg)
```

**Log output:**
```
[FUTURES] ❌ BTC/USDT entry blocked: 4h +0.8% ≤ +1.0%; 1h -0.3% < 0.0%
```

---

## 🛡️ RiskGuard Parameters

```yaml
risk_guard_enabled: true  # ALTIJD AAN LATEN!
```

### Guard 1: Hard Loss

```yaml
risk_guard_max_loss_pct: -8.0  # Stop bij -8% verlies
```

**Wat doet dit?**
Als unrealized PnL ≤ -8.0% → **onmiddellijke stop**

**Waarom -8%?**
- Bij 10x leverage = -80% van je capital!
- Bij 20x leverage = -160% = zou liquidatie zijn!

**Log output:**
```
💥 BTC/USDT hard loss: PnL -8.5% <= -8.0%
🛑 RiskGuard STOP voor BTC/USDT: hard_loss
```

**Tuning:**
- **Conservatief**: -5.0% (stop eerder)
- **Agressief**: -10.0% (meer ruimte, maar riskanter!)

---

### Guard 2: Max Time

```yaml
risk_guard_max_grid_time_seconds: 3600  # Stop na 1 uur
```

**Wat doet dit?**
Als grid >1 uur draait zonder profit → **stop**

**Waarom?**
- Futures grid moet **snel** profit maken (liquidatie + funding fees)
- Als na 1 uur geen winst = waarschijnlijk verkeerde markt conditie
- Spot grid mag dagen draaien, futures NIET

**Log output:**
```
⏰ BTC/USDT max time: 3847s > 3600s
🛑 RiskGuard STOP voor BTC/USDT: max_time
```

**Tuning:**
- **Conservatief**: 1800s (30 min)
- **Normaal**: 3600s (1 uur) ← default
- **Agressief**: 7200s (2 uur)

---

### Guard 3: Grid Depth

```yaml
risk_guard_max_grid_depth_pct: 0.65  # Stop als 65% buy orders gevuld
```

**Wat doet dit?**
Als ≥65% van buy orders gevuld → **stop**

**Waarom?**
- Veel gevulde buy orders = prijs is **sterk gedaald**
- In spot grid is dit OK (je DCA in)
- In futures grid met leverage = **liquidatie gevaar**!

**Voorbeeld:**
```
Grid: 22 levels
Filled: 15 buy orders (68.2%)

→ Te diep in dalende markt → RiskGuard stopt!
```

**Log output:**
```
📊 BTC/USDT grid depth: 68.2% >= 65.0% (15/22 levels)
🛑 RiskGuard STOP voor BTC/USDT: grid_depth
```

**Tuning:**
- **Conservatief**: 0.50 (50% max)
- **Normaal**: 0.65 (65% max) ← default
- **Agressief**: 0.80 (80% max, gevaarlijk!)

---

### Guard 4: Sell Starvation

```yaml
risk_guard_sell_starvation_seconds: 900  # Stop na 15 min zonder sell
```

**Wat doet dit?**
Als >15 min geen sell order gevuld → **stop**

**Waarom?**
- Sell order = profit!
- Geen sells = grid maakt geen geld
- Grid zonder profit betaalt alleen funding fees = verlies

**Voorbeeld:**
```
Grid gestart: 14:00
Laatste sell: 14:05
Huidige tijd: 14:22 (17 minuten later)

→ Geen sells in 17 min > 15 min threshold → Stop!
```

**Log output:**
```
🚫 BTC/USDT sell starvation: 1023s > 900s sinds laatste sell
🛑 RiskGuard STOP voor BTC/USDT: sell_starvation
```

**Tuning:**
- **Conservatief**: 600s (10 min)
- **Normaal**: 900s (15 min) ← default
- **Agressief**: 1800s (30 min)

---

### Guard 5: Trend Break

```yaml
risk_guard_trend_break_pct: -1.5  # Stop als 1h trend < -1.5%
```

**Wat doet dit?**
Als 1h trend < -1.5% → **stop** (markt keert om!)

**Waarom?**
- We zijn long (bullish) in grid
- Als 1h trend negatief wordt = uptrend voorbij
- Futures grid in downtrend = liquidatie risico

**Voorbeeld:**
```
Entry: 1h trend = +0.8% (OK)
Later:  1h trend = -1.7% (DANGER!)

→ Trend break detected → Stop grid!
```

**Log output:**
```
📉 BTC/USDT trend break: 1h -1.7% < -1.5%
🛑 RiskGuard STOP voor BTC/USDT: trend_break
```

**Tuning:**
- **Conservatief**: -1.0% (stop bij kleine daling)
- **Normaal**: -1.5% ← default
- **Agressief**: -2.5% (meer ruimte voor correctie)

---

### Guard 6: ATR Explosion

```yaml
risk_guard_atr_explosion_multiplier: 2.2  # Stop als ATR > 2.2x baseline
```

**Wat doet dit?**
Als ATR (volatiliteit) >2.2x de baseline → **stop**

**Wat is ATR?**
- Average True Range = volatiliteit indicator
- Hoge ATR = grote price swings
- Bij grid start wordt ATR baseline opgeslagen

**Waarom?**
- Grid werkt bij **stabiele volatiliteit**
- Plotseling hoge volatiliteit = gevaarlijk (flash crash, news event)
- Futures met leverage + hoge volatiliteit = **liquidatie risico**!

**Voorbeeld:**
```
Grid start: ATR = 0.05% (baseline)
Later:      ATR = 0.12% (2.4x baseline)

→ ATR explosion detected (2.4x > 2.2x) → Stop!
```

**Log output:**
```
💥 BTC/USDT ATR explosion: 0.1200 > 0.0500 × 2.2 = 0.1100
🛑 RiskGuard STOP voor BTC/USDT: atr_explosion
```

**Tuning:**
- **Conservatief**: 1.8x (stop bij kleine volatiliteit stijging)
- **Normaal**: 2.2x ← default
- **Agressief**: 3.0x (meer ruimte, maar riskanter)

---

## 🔄 Lifecycle: Wanneer triggeren guards?

### Grid Start
```
1. Entry filters checked ✅
2. Grid created
3. Leverage applied (10x)
4. Liquidation buffer calculated
5. RiskGuard.notify_grid_started() → timestamps reset
```

### During Trading
```
Every control loop (5-30s):

1. RiskGuard.evaluate()
   ├─ Check _hard_loss()
   ├─ Check _max_time()
   ├─ Check _grid_depth()
   ├─ Check _sell_starvation()
   ├─ Check _trend_break()
   └─ Check _atr_explosion()

2. Als ANY guard triggers → StopExecutorAction
3. Anders: _monitor_liquidation_risk()
4. Anders: normale grid logic
```

### Grid Stop
```
RiskGuard triggered:
1. Log critical message
2. Return StopExecutorAction
3. Grid stops ONMIDDELLIJK
4. RiskGuard.notify_grid_stopped() → cleanup
```

---

## 📈 Monitoring & Logs

### Normale Operatie

```
[FUTURES] ✅ BTC/USDT entry confirmed:
24h=+2.1%, 4h=+1.3%, 1h=+0.2%

🛡️ BTC/USDT liquidation guard set:
entry=100000.0000
liquidation≈95000.0000
warning_exit=97500.0000
```

### RiskGuard Warnings

```
💥 BTC/USDT hard loss: PnL -8.5% <= -8.0%
📊 BTC/USDT grid depth: 68.2% >= 65.0%
🛑 RiskGuard STOP voor BTC/USDT: hard_loss, grid_depth
```

**Dit is GOED!** RiskGuard beschermt je tegen grotere verliezen.

### Liquidation Emergency

```
🚨 BTC/USDT at 97450.0000 breached liquidation buffer (97500.0000);
liquidation≈95000.0000. Initiating emergency stop.
```

**Dit is een CRITICAL situatie** - grid stopt om liquidatie te voorkomen!

---

## ⚙️ Tuning Guide

### Conservatief Profiel (Beginners)

```yaml
derivative_leverage: 5               # Lage leverage
risk_guard_max_loss_pct: -5.0       # Stop snel bij verlies
risk_guard_max_grid_time_seconds: 1800  # 30 min max
risk_guard_max_grid_depth_pct: 0.50     # Max 50% gevuld
risk_guard_sell_starvation_seconds: 600  # 10 min zonder sell
risk_guard_trend_break_pct: -1.0        # Stop bij kleine daling
```

### Normaal Profiel (Ervaren)

```yaml
derivative_leverage: 10              # Default config
risk_guard_max_loss_pct: -8.0
risk_guard_max_grid_time_seconds: 3600
risk_guard_max_grid_depth_pct: 0.65
risk_guard_sell_starvation_seconds: 900
risk_guard_trend_break_pct: -1.5
```

### Agressief Profiel (Experts, RISICOVOL!)

```yaml
derivative_leverage: 20              # Hoge leverage!
risk_guard_max_loss_pct: -10.0      # Meer ruimte
risk_guard_max_grid_time_seconds: 7200  # 2 uur
risk_guard_max_grid_depth_pct: 0.75     # 75% gevuld OK
risk_guard_sell_starvation_seconds: 1800  # 30 min
risk_guard_trend_break_pct: -2.5        # Meer correctie ruimte
```

**⚠️ WARNING**: Agressief profiel kan leiden tot liquidatie!

---

## 🐛 Troubleshooting

### RiskGuard stopt te vaak

**Symptoom**: Grid start, draait 5-10 min, RiskGuard stopt

**Diagnose**:
```
Check logs voor welke guard triggered:
- hard_loss: Verliezen te hoog → verhoog max_loss_pct of verlaag leverage
- max_time: Grid te langzaam → verhoog max_grid_time
- grid_depth: Prijs daalt snel → verhoog max_grid_depth_pct
- sell_starvation: Geen sells → controleer grid spacing
- trend_break: Markt keert → wacht op betere trend
- atr_explosion: Te volatiel → trade alleen stabiele coins
```

### Grid stopt te laat (grote verliezen)

**Symptoom**: Grid verliest -15% voordat het stopt

**Diagnose**:
- Leverage te hoog? → verlaag naar 5-10x
- RiskGuard disabled? → zet `risk_guard_enabled: true`
- Parameters te los? → gebruik conservatief profiel

### Liquidation warnings

**Symptoom**: Regelmatig `🚨` liquidation warnings

**GEVAAR!** Dit betekent:
1. Leverage is TE HOOG voor deze market
2. Entry filters zijn niet strikt genoeg
3. Grid spacing is te breed

**Oplossing**:
- Verlaag leverage onmiddellijk (naar 5x)
- Verhoog entry thresholds (+2.0% 24h, +1.5% 4h)
- Verklein grid spacing (meer levels, minder per level)

---

## 📚 Advanced: RiskGuard API

### Notificaties

```python
# In je custom code
risk_guard.notify_grid_started(coin)    # Reset timestamps
risk_guard.notify_sell_filled(coin)     # Update sell timestamp
risk_guard.notify_grid_stopped(coin)    # Cleanup tracking
```

### Custom Guards

Je kunt RiskGuard uitbreiden:

```python
class MyCustomRiskGuard(FuturesGridRiskGuard):
    def _funding_rate_check(self, coin: str) -> bool:
        # Stop als funding rate > 0.1%
        funding = self.c.get_funding_rate(coin)
        return funding > 0.001

    def evaluate(self, coin: str):
        # Roep parent aan
        result = super().evaluate(coin)
        if result:
            return result

        # Custom check
        if self._funding_rate_check(coin):
            return StopExecutorAction(reason="funding_too_high")

        return None
```

---

## 🚀 Best Practices

### ✅ DO

1. Start met 5-10x leverage (NIET hoger!)
2. Test eerst met kleine bedragen ($10-20 per grid)
3. Monitor de eerste 10 trades handmatig
4. Laat RiskGuard ALTIJD enabled
5. Trade alleen in duidelijke uptrends
6. Check liquidation warnings dagelijks

### ❌ DON'T

1. Leverage > 20x gebruiken (liquidatie risico te hoog!)
2. RiskGuard disabled zetten
3. Traden tegen de trend in
4. Grid tijdens high volatility (ATR spikes)
5. Multiple grids tegelijk (spreidt risico niet!)
6. Liquidation warnings negeren

---

## 📞 Support

Bij vragen over risk management:
1. Check je logs voor RiskGuard messages
2. Vergelijk je config met conservatief profiel
3. Test eerst met 1x-2x leverage (bijna spot)
4. Open een issue met volledige logs

---

**⚠️ DISCLAIMER**: Deze risk management features VERMINDEREN risico maar ELIMINEREN het NIET. Futures trading met leverage blijft zeer risicovol. Trade alleen met geld dat je kunt verliezen!
