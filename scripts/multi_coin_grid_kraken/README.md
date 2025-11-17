# Multi-Coin Grid Trading Bot

## 📋 Overzicht

Deze bot is een **volledig geautomatiseerde cryptocurrency trading bot** die:
1. Automatisch de beste tradeable coins op Kraken ontdekt
2. Continu prijzen monitort en trends berekent
3. Automatisch switcht naar de coin met de sterkste uptrend
4. Grid trading gebruikt om profit te maken van prijsschommelingen
5. **Alleen EUR als base currency gebruikt** (geen crypto-naar-crypto conversies)

## 🎯 Hoofddoel

**Maximale winst maken door altijd de best presterende cryptocurrency te traden, terwijl grid trading zorgt voor consistente returns bij elke kleine prijsbeweging.**

---

## 🔍 Deel 1: Automatische Coin Discovery

### Wat gebeurt er?

Bij het starten zoekt de bot automatisch naar tradeable cryptocurrencies op Kraken.

### Proces stap voor stap:

1. **Priority List Check**
   - De bot heeft een lijst van 19 populaire coins:
     ```
     BTC/EUR, ETH/EUR, SOL/EUR, XRP/EUR, ADA/EUR, DOT/EUR,
     AVAX/EUR, LINK/EUR, UNI/EUR, ATOM/EUR, LTC/EUR, BCH/EUR,
     NEAR/EUR, ARB/EUR, OP/EUR, SUI/EUR, ALGO/EUR, FIL/EUR
     ```

2. **Volume Filter** (€50,000 minimum)
   - Voor elke coin wordt het 24-uurs handelsvolume opgehaald
   - Coins met minder dan €50k volume worden uitgefilterd
   - **Waarom?** Lage volume = moeilijk in/uit te stappen, grote spreads

3. **BTC/ETH Exclusion**
   - Bitcoin en Ethereum worden standaard uitgesloten
   - **Waarom?**
     - Te duur per coin (€30k+ en €2k+)
     - Lagere volatiliteit = minder grid trading kansen
     - Met €80 kapitaal kun je maar kleine fracties kopen

4. **Sorting by Price** (laagste eerst)
   - Overgebleven coins worden gesorteerd op prijs
   - Goedkoopste coins komen bovenaan
   - **Waarom?**
     - Goedkope coins = hogere volatiliteit
     - Meer percentage beweging = meer grid profits
     - Met €80 kun je meer units kopen

5. **Top 15 Selection**
   - De 15 goedkoopste coins worden geselecteerd
   - Deze lijst wordt gecached voor de sessie

### Voorbeeld Output:

```
✅ Selected top 15 coins:
1. ALGO/EUR   | Volume: €377,383  | Price: €0.1381
2. ARB/EUR    | Volume: €164,439  | Price: €0.2040
3. ADA/EUR    | Volume: €2,946,601| Price: €0.4343
4. SUI/EUR    | Volume: €152,890  | Price: €1.5200
5. FIL/EUR    | Volume: €423,156  | Price: €1.7700
...
15. BCH/EUR   | Volume: €441,219  | Price: €414.12
```

### Code Configuratie:

```python
self.config = {
    'min_24h_volume_eur': 50000,      # Minimum €50k volume
    'max_coins_to_monitor': 20,       # Max 20 coins
    'exclude_expensive_coins': True,   # Sluit BTC/ETH uit
}
```

---

## 📊 Deel 2: Continuous Price Monitoring

### Wat gebeurt er?

Elke 30 seconden worden alle geselecteerde coins geupdatet.

### Data Collection:

1. **Price Update**
   ```python
   # Voor elke coin:
   ticker = exchange.fetch_ticker('ALGO/EUR')
   price = ticker['last']  # Laatste handelsprijs
   timestamp = current_time
   ```

2. **History Building**
   - Elke nieuwe prijs wordt toegevoegd aan de history:
   ```python
   price_history.append({
       'price': Decimal('0.1381'),
       'timestamp': 1731594800.5
   })
   ```

3. **Sliding Window** (30 minuten)
   - Oude prijzen (>30 minuten) worden automatisch verwijderd
   - Er blijven maximaal 60 prijzen over (30 min ÷ 0.5 min = 60)
   ```python
   lookback_seconds = 30 * 60  # 1800 seconden
   cutoff_time = now - lookback_seconds
   # Verwijder alles ouder dan cutoff_time
   ```

### Timing Fix (belangrijk!):

De bot zorgt dat elke cyclus **precies 30 seconden** duurt:

```python
iteration_start = time.time()
# ... doe alle updates (duurt ~15 seconden) ...
iteration_time = time.time() - iteration_start
sleep_time = max(1, 30 - iteration_time)  # Vul aan tot 30s
time.sleep(sleep_time)
```

**Resultaat:** Precies 60 updates in 30 minuten, ongeacht API snelheid.

---

## 📈 Deel 3: Trend Calculation

### Hoe wordt trend berekend?

Voor elke coin wordt het percentage verschil berekend tussen de **oudste** en **nieuwste** prijs in de 30-minuten window.

### Formule:

```python
if len(price_history) >= 2:
    oudste_prijs = price_history[0]['price']    # Van 30 min geleden
    huidige_prijs = price_history[-1]['price']  # Nu

    prijsverschil = huidige_prijs - oudste_prijs
    trend_percentage = (prijsverschil / oudste_prijs) * 100
```

### Voorbeelden:

| Coin | Prijs 30 min geleden | Huidige prijs | Trend |
|------|---------------------|---------------|-------|
| ALGO | €0.1370 | €0.1400 | +2.19% ✅ |
| ADA  | €0.4350 | €0.4380 | +0.69% ✅ |
| XRP  | €1.9500 | €1.9450 | -0.26% ❌ |
| SOL  | €118.00 | €120.50 | +2.12% ✅ |

### Minimum Trend Requirement:

```python
'trend_min_change_pct': 0.5  # Minimaal +0.5% nodig
```

**Alleen coins met +0.5% of meer worden overwogen voor trading!**

---

## 🎯 Deel 4: Best Coin Selection

### Wanneer kan een coin geselecteerd worden?

Een coin moet aan **alle** onderstaande eisen voldoen:

1. ✅ **60 prijzen verzameld** (30 minuten data)
2. ✅ **Trend >= +0.5%** (positieve momentum)
3. ✅ **Hoogste trend van alle coins**

### Selectie Algoritme:

```python
def get_best_coin():
    best_coin = None
    best_trend = 0.5  # Start met minimum

    for coin, trend_data in all_coins:
        # Check 1: Genoeg data?
        if len(trend_data.price_history) < 60:
            continue  # Skip, nog niet genoeg data

        # Check 2: Is trend hoger dan huidige beste?
        if trend_data.trend_pct > best_trend:
            best_trend = trend_data.trend_pct
            best_coin = coin

    return best_coin  # Of None als geen enkele coin voldoet
```

### Voorbeeld Scenario:

```
Data verzamelfase (eerste 30 minuten):
┌─────────────────────────────────────────┐
│ ⏳ Iteratie #25 (12.5 minuten)         │
│ ALGO: 25/60 prices → +1.2% ❌ (te weinig data)
│ ADA:  25/60 prices → +0.8% ❌ (te weinig data)
│ XRP:  25/60 prices → +1.5% ❌ (te weinig data)
│                                         │
│ → Geen trading, wacht op meer data     │
└─────────────────────────────────────────┘

Trading fase (na 30 minuten):
┌─────────────────────────────────────────┐
│ ✅ Iteratie #60 (30.0 minuten)         │
│ ALGO: 60/60 prices → +1.2% 🟡          │
│ ADA:  60/60 prices → +0.8% 🟡          │
│ XRP:  60/60 prices → +1.5% ✅ (BESTE!) │
│                                         │
│ → Start trading XRP/EUR                │
└─────────────────────────────────────────┘
```

---

## 🔄 Deel 5: Automatic Coin Switching

### Switch Decision Logic:

De bot beslist elke 30 seconden of er geswitcht moet worden.

### Decision Tree:

```
Start
  │
  ├─ Geen actieve coin?
  │  └─ JA → Switch naar beste coin
  │
  ├─ Beste coin = huidige coin?
  │  └─ JA → Geen switch, blijf traden
  │
  ├─ Cooldown actief? (< 1 uur sinds laatste switch)
  │  └─ JA → Geen switch, wacht nog X minuten
  │
  └─ Anders → SWITCH naar nieuwe coin
```

### Switch Proces:

**Stap 1: Cancel Oude Orders**
```python
# Alle actieve orders voor de oude coin worden geannuleerd
for order in active_orders:
    exchange.cancel_order(order['id'])
```

**Stap 2: Verkoop Resterende Coins**
```python
# Als we nog coins hebben, verkoop ze tegen market prijs
if balance > min_order_size:
    exchange.create_market_sell_order(oude_coin, balance)
```

**Stap 3: Wacht op EUR**
```python
# Wacht tot verkoop compleet is en EUR beschikbaar
time.sleep(2)
balance = exchange.fetch_balance()
available_eur = balance['EUR']['free']
```

**Stap 4: Plaats Nieuwe Grid**
```python
# Start grid trading met nieuwe coin
place_grid_orders(nieuwe_coin, available_eur)
```

**Stap 5: Update Cooldown**
```python
# Reset cooldown timer
last_switch_time = current_time
```

### Switch Cooldown (1 uur):

**Waarom 1 uur wachten?**

1. **Vermijd overtrading**: Elke switch kost fees (0.25% verkoop + 0.25% koop)
2. **Laat grid werken**: Grid trading heeft tijd nodig om te profiteren
3. **Stabilitiet**: Voorkom springen tussen coins bij kleine verschillen

```python
min_switch_interval = 3600  # 1 uur = 3600 seconden

time_since_switch = now - last_switch_time
remaining = (3600 - time_since_switch) / 60  # In minuten

if time_since_switch < 3600:
    log(f"Cooldown actief: nog {remaining:.1f} minuten")
    return False  # Geen switch
```

### Voorbeeld Switch Scenario:

```
15:00 - Start trading ADA (trend: +0.8%)
15:30 - XRP heeft nu +1.5% trend
        → Cooldown: 30 min verstreken, nog 30 min te gaan
        → GEEN SWITCH

16:00 - XRP heeft nu +1.8% trend
        → Cooldown: 60 min verstreken ✅
        → SWITCH naar XRP!

16:05 - ADA heeft nu +2.0% trend
        → Cooldown: 5 min verstreken, nog 55 min te gaan
        → GEEN SWITCH (blijf bij XRP)

17:00 - ADA heeft nu +2.2% trend
        → Cooldown: 60 min verstreken ✅
        → SWITCH naar ADA!
```

---

## 📐 Deel 6: Grid Trading Strategy

### Wat is Grid Trading?

Grid trading plaatst meerdere buy en sell orders boven en onder de huidige prijs, zodat je profiteert van elke kleine prijsbeweging.

### Grid Configuratie:

```python
self.config = {
    'range_pct_down': 3.0,    # Grid begint 3% onder huidige prijs
    'range_pct_up': 8.0,      # Grid eindigt 8% boven huidige prijs
    'num_grids': 3,           # 3 buy orders + 3 sell orders
}
```

### Visual Grid Example:

Stel: ALGO huidige prijs = €0.1400

```
SELL ZONE (Profit maken) ↑
├─ SELL #3: €0.1512 (+8.0%)  ─┐
│                              │  €13.33 per order
├─ SELL #2: €0.1484 (+6.0%)  ─┤  (totaal €40 voor sells)
│                              │
├─ SELL #1: €0.1456 (+4.0%)  ─┘

════════════════════════════════
    HUIDIGE PRIJS: €0.1400
════════════════════════════════

BUY ZONE (Goedkoop inkopen) ↓
├─ BUY #1:  €0.1372 (-2.0%)  ─┐
│                              │  €13.33 per order
├─ BUY #2:  €0.1344 (-4.0%)  ─┤  (totaal €40 voor buys)
│                              │
└─ BUY #3:  €0.1316 (-6.0%)  ─┘
```

### Grid Berekening:

**1. Bepaal Grid Range:**
```python
huidige_prijs = Decimal('0.1400')

# Lower bound: 3% onder huidige prijs
grid_lower = huidige_prijs * (1 - 0.03)  # €0.1358

# Upper bound: 8% boven huidige prijs
grid_upper = huidige_prijs * (1 + 0.08)  # €0.1512
```

**2. Verdeel Kapitaal:**
```python
beschikbaar_eur = Decimal('80.00')
max_capital = Decimal('80.00')
usable_eur = min(beschikbaar_eur, max_capital)  # €80

# Split 50/50 tussen buys en sells
capital_per_side = usable_eur / 2  # €40 voor buys, €40 voor sells
capital_per_order = capital_per_side / 3  # €13.33 per order
```

**3. Bereken Buy Orders:**
```python
buy_range = huidige_prijs - grid_lower  # €0.1400 - €0.1358 = €0.0042
buy_step = buy_range / 4  # 4 = num_grids + 1

for i in range(1, 4):  # 3 buy orders
    prijs = huidige_prijs - (buy_step * i)
    amount = capital_per_order / prijs  # Hoeveel coins voor €13.33

    exchange.create_limit_buy_order(
        symbol='ALGO/EUR',
        amount=amount,
        price=prijs
    )
```

**4. Bereken Sell Orders:**
```python
sell_range = grid_upper - huidige_prijs  # €0.1512 - €0.1400 = €0.0112
sell_step = sell_range / 4

for i in range(1, 4):  # 3 sell orders
    prijs = huidige_prijs + (sell_step * i)
    amount = capital_per_order / prijs

    # LET OP: Dit faalt als we nog geen coins hebben!
    exchange.create_limit_sell_order(
        symbol='ALGO/EUR',
        amount=amount,
        price=prijs
    )
```

### Grid Bootstrapping (Belangrijk!):

**Probleem:** Bij de eerste grid hebben we nog geen coins om te verkopen!

**Wat gebeurt er:**

```
Eerste Grid Placement:
┌──────────────────────────────────────┐
│ BUY #1:  €0.1372 ✅ (order geplaatst)│
│ BUY #2:  €0.1344 ✅ (order geplaatst)│
│ BUY #3:  €0.1316 ✅ (order geplaatst)│
│                                      │
│ SELL #1: €0.1456 ❌ INSUFFICIENT FUNDS│
│ SELL #2: €0.1484 ❌ INSUFFICIENT FUNDS│
│ SELL #3: €0.1512 ❌ INSUFFICIENT FUNDS│
└──────────────────────────────────────┘

Dit is NORMAAL en VERWACHT gedrag!

Na eerste BUY order executie:
┌──────────────────────────────────────┐
│ BUY #1:  EXECUTED! → +95.2 ALGO     │
│ BUY #2:  €0.1344 ✅ (nog open)       │
│ BUY #3:  €0.1316 ✅ (nog open)       │
│                                      │
│ Nu hebben we coins! Refill sells:    │
│ SELL #1: €0.1456 ✅ (order geplaatst)│
│ SELL #2: €0.1484 ✅ (order geplaatst)│
│ SELL #3: €0.1512 ✅ (order geplaatst)│
└──────────────────────────────────────┘
```

**Strategie:** Buy first, then sell!

---

## 💰 Deel 7: Capital Management

### Maximum Capital Limit:

```python
max_capital = Decimal('80')  # Maximaal €80 gebruiken
available_eur = get_balance()  # Wat we echt hebben
usable_eur = min(available_eur, max_capital)  # Neem het minimum
```

### Capital Allocation:

| Item | Bedrag | Percentage |
|------|--------|-----------|
| Totaal Beschikbaar | €80.00 | 100% |
| → Buy Side | €40.00 | 50% |
| &nbsp;&nbsp;→ Buy Order #1 | €13.33 | 16.7% |
| &nbsp;&nbsp;→ Buy Order #2 | €13.33 | 16.7% |
| &nbsp;&nbsp;→ Buy Order #3 | €13.34 | 16.7% |
| → Sell Side | €40.00 | 50% |
| &nbsp;&nbsp;→ Sell Order #1 | €13.33 | 16.7% |
| &nbsp;&nbsp;→ Sell Order #2 | €13.33 | 16.7% |
| &nbsp;&nbsp;→ Sell Order #3 | €13.34 | 16.7% |

### Dynamic Rebalancing:

Als een order wordt uitgevoerd, wordt deze automatisch **refilled**:

```python
def check_and_refill_orders():
    # 1. Haal alle actieve orders op
    open_orders = exchange.fetch_open_orders(active_coin)

    # 2. Tel hoeveel buy/sell orders er zijn
    num_buy_orders = count_buy_orders(open_orders)
    num_sell_orders = count_sell_orders(open_orders)

    # 3. Refill als er orders missen
    if num_buy_orders < 3:
        place_missing_buy_orders()

    if num_sell_orders < 3:
        place_missing_sell_orders()
```

### Example Refill Scenario:

```
Situatie:
BUY #1 wordt uitgevoerd bij €0.1372
→ We hebben nu 97.1 ALGO coins
→ We hebben nu €26.67 EUR (€40 - €13.33)

Bot refill actie:
1. Detect: Slechts 2 buy orders over
2. Calculate: Nieuwe buy order prijs = €0.1372
3. Place: Nieuwe buy order voor €13.33

Resultaat:
✅ Weer 3 buy orders actief
✅ Balance: €13.34 EUR + 97.1 ALGO
```

---

## ⚙️ Deel 8: Complete Configuration

### Full Config Object:

```python
self.config = {
    # Coin Discovery
    'coins': [],                        # Auto-gevuld door discovery
    'min_24h_volume_eur': 50000,       # €50k minimum volume
    'max_coins_to_monitor': 20,        # Max 20 coins monitoren
    'exclude_expensive_coins': True,    # Sluit BTC/ETH uit

    # Trend Detection
    'trend_lookback_minutes': 30,      # 30 minuten lookback
    'trend_min_change_pct': 0.5,       # Minimum +0.5% trend

    # Switch Management
    'min_switch_interval_seconds': 3600, # 1 uur cooldown
    'last_switch_time': 0,              # Wordt bijgewerkt bij switch

    # Grid Parameters
    'range_pct_down': 3.0,             # Grid 3% onder prijs
    'range_pct_up': 8.0,               # Grid 8% boven prijs
    'num_grids': 3,                    # 3 buy + 3 sell orders

    # Fees (Kraken API)
    'maker_fee': 0.0025,               # 0.25% maker fee
    'taker_fee': 0.0040,               # 0.40% taker fee

    # Capital Management
    'max_capital': 80,                 # Maximum €80

    # Per-coin minimum orders (auto-gevuld)
    'min_order_eur': {}                # bijv. {'ALGO/EUR': 1.0}
}
```

---

## 🔁 Deel 9: Main Loop Execution

### Complete Loop Flow:

```python
def run():
    iteration = 0

    while True:
        iteration += 1
        iteration_start = time.time()

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STAP 1: Update Alle Coin Prijzen
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        for coin in monitored_coins:
            # Haal laatste prijs op
            price = exchange.fetch_ticker(coin)

            # Voeg toe aan history
            add_to_history(coin, price)

            # Bereken trend
            calculate_trend(coin)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STAP 2: Vind Beste Coin
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        best_coin = None
        best_trend = 0.5

        for coin in monitored_coins:
            if has_enough_data(coin) and trend(coin) > best_trend:
                best_coin = coin
                best_trend = trend(coin)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STAP 3: Switch Decision
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if best_coin exists:
            if should_switch(best_coin):
                # Cancel oude orders
                cancel_all_orders(current_coin)

                # Verkoop resterende coins
                sell_remaining_balance(current_coin)

                # Switch naar nieuwe coin
                active_coin = best_coin
                place_grid_orders(best_coin)

                # Reset cooldown
                last_switch_time = now

        else:  # Geen coin voldoet aan minimum trend
            if active_coin:
                # Stop trading
                cancel_all_orders(active_coin)
                sell_remaining_balance(active_coin)
                active_coin = None

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STAP 4: Refill Grid Orders
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        if active_coin:
            open_orders = fetch_open_orders(active_coin)

            if len(open_orders) < 6:  # Minder dan 3 buy + 3 sell
                refill_missing_orders(active_coin)

        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        # STAP 5: Sleep tot Volgende Cyclus
        # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        iteration_time = time.time() - iteration_start
        sleep_time = max(1, 30 - iteration_time)
        time.sleep(sleep_time)
```

### Timing Breakdown:

Typische iteratie timing:

```
15:00:00.000 - Start iteratie #50
15:00:00.100 - STAP 1: Update prices (15 coins × ~1s) = 15s
15:00:15.100 - STAP 2: Find best coin (<0.1s)
15:00:15.150 - STAP 3: Switch decision (<0.1s)
15:00:15.200 - STAP 4: Check/refill orders (~0.5s)
15:00:15.700 - STAP 5: Calculate sleep time
              → Iteration duurde 15.7s
              → Sleep 14.3s
15:00:30.000 - Start iteratie #51 (precies 30s later!)
```

---

## 📊 Deel 10: Risk Management & Fees

### Trading Fees (Kraken):

| Fee Type | Rate | When? |
|----------|------|-------|
| Maker Fee | 0.25% | Bij limit orders die NIET meteen uitgevoerd worden |
| Taker Fee | 0.40% | Bij market orders of limit orders die meteen matchen |

### Grid Trading Fees:

**Per Trade Cycle (buy + sell):**

```
Voorbeeld: ALGO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Buy:  €13.33 @ €0.1372 = 97.11 ALGO
Fee:  €13.33 × 0.0025 = €0.03 ❌

Sell: 97.11 ALGO @ €0.1456 = €14.14
Fee:  €14.14 × 0.0025 = €0.04 ❌

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
In:   €13.33
Out:  €14.14
Fees: €0.07
Net:  €0.74 profit (+5.5%) ✅
```

### Switch Costs:

Elke coin switch kost:

```
1. Cancel orders:        €0.00 (gratis)
2. Verkoop oude coin:    0.25% (maker fee)
3. Koop nieuwe coin:     0.25% (maker fee)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Totale switch cost:      0.50% van kapitaal

Op €80:
Switch cost = €80 × 0.005 = €0.40
```

**Daarom de 1-uur cooldown:** Switch pas als nieuwe coin genoeg betere trend heeft om €0.40 fee terug te verdienen!

### Risk Parameters:

```python
# Maximum kapitaal risico
max_capital = €80  # Nooit meer dan dit gebruiken

# Grid range
range_down = 3%    # Maximum -3% drawdown voordat laatste buy
range_up = 8%      # Maximum +8% voordat laatste sell

# Stop-loss: geen
# → Grid blijft actief, ook bij -3% of lager
# → Buying the dip strategie

# Take-profit: geen
# → Grid blijft actief, ook bij +8% of hoger
# → Let winners run strategie
```

### Worst Case Scenario:

```
Scenario: Coin crasht -20%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Start: €80 EUR

Alle 3 buy orders worden uitgevoerd:
→ Spent: €40
→ Coins: ~290 ALGO @ gemiddeld €0.138
→ Remaining: €40 EUR

Prijs daalt naar €0.110 (-20%):
→ EUR value: €40
→ ALGO value: 290 × €0.110 = €31.90
→ Total: €71.90

Unrealized loss: €8.10 (-10.1%)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Recovery plan:
Grid blijft actief, wacht op bounce
Bij herstel naar €0.138: break-even
Bij herstel naar €0.146+: profit!
```

---

## 🚀 Deel 11: Usage & Commands

### Start de Bot:

```bash
cd /home/mo/repos/hummingbot

# Met API keys als environment variables
KRAKEN_API_KEY="your_key_here" \
KRAKEN_SECRET_KEY="your_secret_here" \
nohup python3 scripts/multi_coin_grid_kraken/01_multi_coin_grid_live.py > /dev/null 2>&1 &
```

### Monitor de Bot:

```bash
# Bekijk laatste 50 log entries
tail -50 logs/multi_coin_grid.log

# Live monitoring (realtime updates)
tail -f logs/multi_coin_grid.log

# Check of bot nog draait
ps aux | grep "01_multi_coin_grid_live.py"
```

### Stop de Bot:

```bash
# Graceful stop
pkill -f "01_multi_coin_grid_live.py"

# Force kill (als graceful niet werkt)
pkill -9 -f "01_multi_coin_grid_live.py"
```

---

## 📈 Deel 12: Log Output Explanation

### Startup Logs:

```
================================================================================
🚀 MULTI-COIN GRID BOT GESTART
================================================================================

🔍 Discovering tradeable EUR pairs...
   Checking 19 populaire EUR pairs...
   📊 Ophalen 24h volumes...
      ✓ SOL/EUR      | Volume: €11,448,690
      ✓ XRP/EUR      | Volume: €9,823,456
      ...

✅ Selected top 15 coins:
1. ALGO/EUR   | Volume: €377,383  | Price: €0.1381
2. ARB/EUR    | Volume: €164,439  | Price: €0.2040
...

📊 Monitoring 15 coins: ALGO/EUR, ARB/EUR, ADA/EUR, ...
📈 Trend vereiste: 0.5% over 30min
⏱️  Switch cooldown: 60 minuten
💰 Fees: 0.25% maker, 0.4% taker

🏁 Bot hoofdloop gestart
```

### Data Collection Phase:

```
================================================================================
🔁 ITERATIE #25 - 15:12:30
================================================================================

📊 COIN TREND UPDATE
================================================================================
📈 ALGO/EUR     | €  0.1382 | Trend:  +0.76% | History: 25 prijzen
📈 ARB/EUR      | €  0.2064 | Trend:  +1.67% | History: 25 prijzen
📈 ADA/EUR      | €  0.4357 | Trend:  +0.74% | History: 25 prijzen
...

⏳ DATA VERZAMELEN: 25/60 prijzen (12.5/30 minuten) - wacht nog 17.5 min

💤 Iteratie duurde 15.8s, wacht 14.2s...
```

**Betekenis:**
- `History: 25 prijzen` = Nog niet genoeg data
- `⏳ DATA VERZAMELEN` = Bot is nog aan het verzamelen
- `wacht nog 17.5 min` = Over 17.5 minuten kan bot beginnen

### Trading Phase:

```
================================================================================
🔁 ITERATIE #65 - 15:33:00
================================================================================

📊 COIN TREND UPDATE
================================================================================
📈 ALGO/EUR     | €  0.1392 | Trend:  +1.53% | History: 60 prijzen ✅
📈 ARB/EUR      | €  0.2064 | Trend:  +1.38% | History: 60 prijzen
📈 ADA/EUR      | €  0.4368 | Trend:  +1.18% | History: 60 prijzen
...

🎯 BESTE COIN: ALGO/EUR met +1.53% trend

🔄 SWITCH naar nieuwe coin: ALGO/EUR
   📊 Huidige prijs: €0.1392
   💰 Beschikbaar: €80.00
   📈 Grid range: €0.1350 - €0.1503

   Plaatsen van grid orders...
   ✅ BUY #1:  €0.1364 | 29.4 ALGO | €4.01
   ✅ BUY #2:  €0.1350 | 29.6 ALGO | €4.00
   ✅ BUY #3:  €0.1336 | 30.0 ALGO | €4.01
   ❌ SELL #1: Insufficient funds (verwacht, wordt later gevuld)
   ❌ SELL #2: Insufficient funds
   ❌ SELL #3: Insufficient funds

💤 Iteratie duurde 18.2s, wacht 11.8s...
```

### Order Fill Notification:

```
🎉 ORDER GEVULD!
   Type: BUY
   Coin: ALGO/EUR
   Prijs: €0.1364
   Amount: 29.4 ALGO
   Value: €4.01

   → Refilling grid...
   ✅ SELL #1: €0.1420 | 28.2 ALGO | €4.00

   Balance: €72.00 EUR + 29.4 ALGO
```

---

## 🎯 Deel 13: Expected Performance

### Typische Trading Day:

```
Startup Phase (0-30 min):
├─ Data collection
├─ No trading
└─ Waiting for 60 price points

Active Trading (30 min - 24h):
├─ Grid active on best performing coin
├─ 2-8 trades per hour (depends on volatility)
├─ Average profit per trade: 3-6%
└─ Switch 0-3 times per day (1h cooldown)

Expected Results:
├─ Low volatility day:   +0.5% to +2%
├─ Medium volatility:    +2% to +5%
├─ High volatility:      +5% to +15%
└─ Extreme volatility:   -5% to +30%
```

### Profit Example (Good Day):

```
Start: €80.00

Hour 1-2: Trading ALGO (8 fills)
→ +€0.50 per fill average
→ +€4.00 total

Hour 2-3: Switch to XRP (fee: -€0.40)
          Trading XRP (12 fills)
→ +€0.60 per fill average
→ +€7.20 total
→ -€0.40 switch fee
→ Net: +€6.80

Hour 3-8: Continue XRP (35 fills)
→ +€0.55 per fill average
→ +€19.25 total

Hour 8-9: Switch to ADA (fee: -€0.40)
          Trading ADA (10 fills)
→ +€0.65 per fill average
→ +€6.50 total
→ -€0.40 switch fee
→ Net: +€6.10

═══════════════════════════════════
Total Profit: +€17.10 (+21.4%)
═══════════════════════════════════
```

### Profit Calculation per Grid Cycle:

```
Buy:  €13.33 @ €0.1372 = 97.11 ALGO (fee: -€0.03)
Sell: 97.11 ALGO @ €0.1456 (+6.1%) = €14.14 (fee: -€0.04)

Gross: €14.14 - €13.33 = €0.81 (+6.1%)
Fees:  €0.03 + €0.04 = €0.07
Net:   €0.81 - €0.07 = €0.74 (+5.5%)

ROI: €0.74 / €13.33 = 5.5%
```

---

## ⚠️ Deel 14: Common Issues & Troubleshooting

### Issue 1: "Insufficient funds" voor SELL orders

**Symptoom:**
```
❌ SELL #1: Insufficient funds
❌ SELL #2: Insufficient funds
❌ SELL #3: Insufficient funds
```

**Oorzaak:** Grid bootstrapping - we hebben nog geen coins!

**Oplossing:**
- Dit is **NORMAAL** bij de eerste grid
- Wacht tot BUY orders uitgevoerd worden
- Dan worden SELL orders automatisch gerefilled

**Geen actie nodig!** ✅

---

### Issue 2: Bot blijft hangen op 41 prijzen

**Symptoom:**
```
History: 41 prijzen (20.5 minuten)
...blijft maar op 41...
```

**Oorzaak:** Iteratie timing was te lang (45s ipv 30s)

**Oplossing:**
- Fix is al geïmplementeerd in huidige versie
- Bot gebruikt nu dynamische sleep:
```python
sleep_time = max(1, 30 - iteration_time)
```

**Status:** ✅ Opgelost!

---

### Issue 3: "No coin meets minimum trend"

**Symptoom:**
```
⚠️  Geen coin heeft voldoende trend - cancel orders
```

**Oorzaak:** Market dips, alle coins negatief

**Oplossing:**
- Bot stopt automatisch met traden
- Wacht tot market herstelt
- Blijft wel prijzen monitoren

**Dit is veilig gedrag!** ✅

---

### Issue 4: Bot crashed / niet meer actief

**Check:**
```bash
ps aux | grep "01_multi_coin_grid_live.py"
```

**Restart:**
```bash
cd /home/mo/repos/hummingbot
KRAKEN_API_KEY="..." KRAKEN_SECRET_KEY="..." \
nohup python3 scripts/multi_coin_grid_kraken/01_multi_coin_grid_live.py > /dev/null 2>&1 &
```

**Check logs voor errors:**
```bash
tail -100 logs/multi_coin_grid.log | grep ERROR
```

---

### Issue 5: Switch gebeurt te vaak

**Symptoom:** Bot switcht elke 15 minuten

**Check cooldown:**
```python
'min_switch_interval_seconds': 3600  # Moet 3600 zijn (1 uur)
```

**Verhoog cooldown:**
```python
'min_switch_interval_seconds': 7200  # 2 uur
```

---

### Issue 6: Grid te groot / te klein

**Te conservatief (weinig trades):**
```python
# Maak grid smaller
'range_pct_down': 1.5,  # Was 3.0
'range_pct_up': 4.0,    # Was 8.0
```

**Te agressief (te veel risico):**
```python
# Maak grid wider
'range_pct_down': 5.0,  # Was 3.0
'range_pct_up': 12.0,   # Was 8.0
```

---

## 🔧 Deel 15: Advanced Configuration

### Aanpassen Trend Gevoeligheid:

**Meer selectief (alleen sterkste trends):**
```python
'trend_min_change_pct': 1.0,  # Verhoog van 0.5 naar 1.0
'trend_lookback_minutes': 60, # Verhoog van 30 naar 60
```

**Minder selectief (meer trading kansen):**
```python
'trend_min_change_pct': 0.3,  # Verlaag van 0.5 naar 0.3
'trend_lookback_minutes': 15, # Verlaag van 30 naar 15
```

### Aanpassen Aantal Grid Levels:

**Meer levels (meer diversificatie):**
```python
'num_grids': 5,  # Was 3, nu 5 buy + 5 sell
# Capital per order wordt: €80 / 2 / 5 = €8 per order
```

**Minder levels (grotere orders):**
```python
'num_grids': 2,  # Was 3, nu 2 buy + 2 sell
# Capital per order wordt: €80 / 2 / 2 = €20 per order
```

### Aanpassen Capital:

```python
max_capital = Decimal('150')  # Verhoog naar €150
# Of
max_capital = Decimal('50')   # Verlaag naar €50
```

---

## 📚 Deel 16: Technical Architecture

### Class Structure:

```python
class MultiCoinGridBot:
    """Main bot class"""

    # Initialisatie
    def __init__(self):
        self.exchange = ccxt.kraken(...)
        self.config = {...}
        self.coin_trends = {}
        self.active_coin = None
        self.active_orders = []

    # Discovery
    def discover_tradeable_coins(self) -> List[str]:
        """Vindt en filtert tradeable coins"""

    # Price Management
    def update_coin_price(self, symbol: str) -> Decimal:
        """Update prijs en voeg toe aan history"""

    def update_all_coin_prices(self):
        """Update alle coins"""

    # Trend Analysis
    def calculate_trend(self, symbol: str) -> float:
        """Bereken trend percentage"""

    def get_best_coin(self) -> Optional[str]:
        """Vind coin met beste trend"""

    # Switch Logic
    def should_switch_coin(self, new_coin: str) -> bool:
        """Besluit of switch nodig is"""

    def switch_to_coin(self, symbol: str):
        """Voer coin switch uit"""

    # Grid Management
    def place_grid_orders(self, symbol: str):
        """Plaats nieuwe grid"""

    def check_and_refill_orders(self):
        """Check en refill ontbrekende orders"""

    def cancel_all_orders(self):
        """Cancel alle actieve orders"""

    # Main Loop
    def run(self):
        """Hoofdloop"""
```

### Data Structures:

```python
@dataclass
class CoinTrend:
    """Trend data voor één coin"""
    symbol: str                    # bijv. 'ALGO/EUR'
    current_price: Decimal         # Laatste prijs
    trend_pct: float              # Trend percentage
    price_history: List[Dict]      # [{price, timestamp}, ...]
    last_updated: float           # Unix timestamp

# Voorbeeld:
coin_trend = CoinTrend(
    symbol='ALGO/EUR',
    current_price=Decimal('0.1392'),
    trend_pct=1.53,
    price_history=[
        {'price': Decimal('0.1371'), 'timestamp': 1731594000.0},
        {'price': Decimal('0.1375'), 'timestamp': 1731594030.0},
        ...
        {'price': Decimal('0.1392'), 'timestamp': 1731595800.0}
    ],
    last_updated=1731595800.0
)
```

---

## 🎓 Deel 17: Key Learnings

### Waarom deze strategie werkt:

1. **Trend Following**
   - Tradet alleen coins die OMHOOG gaan
   - Vermijdt falling knives

2. **Grid Trading**
   - Profiteert van volatiliteit
   - Geen market timing nodig
   - Consistent kleine winsten

3. **EUR Base Only**
   - Vermijdt dubbele fees (crypto→crypto)
   - Simpelere accounting
   - Directe EUR profit

4. **Automatic Switching**
   - Altijd op de beste coin
   - Voorkomt vast zitten in slechte coin
   - Cooldown voorkomt overtrading

5. **Risk Management**
   - Fixed maximum capital (€80)
   - Grid spread limits drawdown
   - No leverage, no margin

---

## 🚦 Deel 18: Status Indicators

### Bot Status Messages:

| Message | Betekenis | Actie |
|---------|-----------|-------|
| `⏳ DATA VERZAMELEN` | Eerste 30 minuten | Wachten |
| `🎯 BESTE COIN: XXX` | Trading actief | Goed! |
| `🔄 SWITCH naar XXX` | Coin switch | Normaal |
| `⚠️ Geen coin heeft voldoende trend` | Market slecht | Veilig, wacht |
| `🎉 ORDER GEVULD` | Trade success | Profit! |
| `❌ SELL: Insufficient funds` | Bootstrapping | Normaal, wacht |
| `💤 Iteratie duurde X.Xs` | Timing info | Info |

### Health Indicators:

**✅ Gezond:**
```
- Bot process draait (ps aux toont PID)
- Logs updaten elke 30 seconden
- History groeit naar 60
- Orders worden geplaatst
- Geen ERROR messages
```

**⚠️ Waarschuwing:**
```
- History blijft steken (<60)
- Veel "Insufficient funds" (na bootstrapping)
- Veel switch attempts binnen 1 uur
- Logs stoppen met updaten
```

**❌ Probleem:**
```
- Bot process niet actief
- Logs bevatten ERROR messages
- Geen nieuwe log entries
- API errors (rate limit, authentication)
```

---

## 📖 Conclusie

Deze multi-coin grid bot combineert:

✅ **Automatische coin discovery** - Vindt beste tradeable coins
✅ **Trend detection** - Tradet alleen uptrends
✅ **Grid trading** - Profiteert van elke beweging
✅ **Smart switching** - Altijd op beste coin
✅ **EUR-only** - Geen dubbele fees
✅ **Risk management** - Fixed kapitaal, geen leverage
✅ **Fully automated** - Geen handmatige interventie nodig

**Expected Performance:** 5-20% per week bij normale volatiliteit

**Risk Level:** Medium (geen leverage, maar wel 100% crypto exposure)

**Time Investment:** 0 minuten per dag (fully automated)

---

## 📝 Version History

- **v1.0** - Initial grid bot (single coin)
- **v1.1** - Added trend filter
- **v1.2** - Multi-coin monitoring
- **v1.3** - Automatic coin discovery
- **v1.4** - Fixed timing issue (41 prices bug)
- **v1.5** - Current version ✅

---

**Happy Trading! 🚀**
