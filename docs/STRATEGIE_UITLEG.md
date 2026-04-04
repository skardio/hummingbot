# Multi-Coin Grid Trading Strategie — Volledige Uitleg

> **Versie:** v3.3 (Hybrid Grid Config)
> **Exchange:** Kraken (USD)
> **Budget:** $300 trading capital (van $1475 account — rest is long-term investering)
> **Laatste update:** juni 2025

---

## Inhoudsopgave

1. [Overzicht & Filosofie](#1-overzicht--filosofie)
2. [Systeemarchitectuur](#2-systeemarchitectuur)
3. [Fase 1 — Coin Discovery & Selectie](#3-fase-1--coin-discovery--selectie)
4. [Fase 2 — Trend Scoring & Ranking](#4-fase-2--trend-scoring--ranking)
5. [Fase 3 — Entry Gates (7 filters)](#5-fase-3--entry-gates-7-filters)
6. [Fase 4 — Slot Allocatie & Budget](#6-fase-4--slot-allocatie--budget)
7. [Fase 5 — Grid Constructie](#7-fase-5--grid-constructie)
8. [Fase 6 — Positie Monitoring & Exit](#8-fase-6--positie-monitoring--exit)
9. [Risk Management (3 lagen)](#9-risk-management-3-lagen)
10. [Cooldown & Blacklist Systeem](#10-cooldown--blacklist-systeem)
11. [Configuratie Samenvatting](#11-configuratie-samenvatting)
12. [Beslissingsboom (Decision Flow)](#12-beslissingsboom)
13. [Bekende Zwakheden & Aandachtspunten](#13-bekende-zwakheden--aandachtspunten)

---

## 1. Overzicht & Filosofie

De strategie is een **geautomatiseerde multi-coin spot grid trader** die:

- **Dynamisch** de beste coins selecteert uit 30+ Kraken USD-paren
- **Grid orders** plaatst op meerdere prijsniveaus om te profiteren van **mean-reversion** (prijs die heen en weer beweegt)
- **Maximaal 2 coins tegelijk** tradt met $150 per coin
- **7 onafhankelijke entry-filters** passeert voordat er gehandeld wordt
- **3 lagen risicomanagement** toepast (per-positie, per-coin, portfolio-breed)

### Kernprincipe: Mean-Reversion Grid Trading

Grid trading werkt het best in **zijwaarts bewegende markten** (chop). De bot koopt bij dips en verkoopt bij bounces op vooraf bepaalde prijsniveaus. Het is géén trend-following strategie — de bot zoekt coins die **oscilleren** rond een gemiddelde.

```
Prijs
  │     ╭─╮     ╭─╮         ← SELL (take-profit)
  │   ╭─╯ ╰─╮ ╭─╯ ╰─╮
  │ ──╯     ╰─╯     ╰── ← Gemiddelde prijs
  │╭─╮     ╭─╮     ╭─╮
  ││ ╰─╮ ╭─╯ ╰─╮ ╭─╯    ← BUY (grid entry)
  └────────────────────────── Tijd
```

Elke "bounce" genereert een klein rendement (0.8–5%). Over veel trades en coins accumuleert dit.

---

## 2. Systeemarchitectuur

Het systeem bestaat uit 9 modules die samenwerken in een pipeline:

```
┌──────────────────────────────────────────────────────────┐
│                    MAIN DECISION LOOP                     │
│              determine_executor_actions()                  │
│               (elke ~3 seconden)                          │
└───────┬──────────────────────────────────────────────────┘
        │
        ▼
┌───────────────┐    ┌──────────────────┐    ┌──────────────┐
│  Dynamic Pair │───▶│ Trend Calculator │───▶│ Grid Suit.   │
│  Discovery    │    │ (Multi-TF Score) │    │ Scorer       │
│  30+ coins    │    │ 1h/4h/24h blend  │    │ Mean-Rev fit │
└───────────────┘    └──────────────────┘    └──────┬───────┘
                                                     │
        ┌────────────────────────────────────────────┘
        ▼
┌───────────────┐    ┌──────────────────┐    ┌──────────────┐
│ Smart Entry   │───▶│ Budget           │───▶│ Dynamic Slot │
│ Filter (7x)   │    │ Allocator        │    │ Manager      │
│ RSI/VWAP/ATR  │    │ Reservation mdl  │    │ Tier-based   │
└───────────────┘    └──────────────────┘    └──────┬───────┘
                                                     │
        ┌────────────────────────────────────────────┘
        ▼
┌───────────────┐    ┌──────────────────┐    ┌──────────────┐
│ Grid Executor │───▶│ Professional     │───▶│ Global Risk  │
│ Buy/Sell lvls │    │ Risk Manager     │    │ Manager      │
│ 2-phase exit  │    │ ATR stops/profit │    │ Daily caps   │
└───────────────┘    └──────────────────┘    └──────────────┘
```

### Modules

| Module | Bestand | Functie |
|--------|---------|---------|
| **Controller** | `multi_coin_grid_controller.py` | Hoofdloop, coördineert alles |
| **Trend Calculator** | `trend_calculator.py` | Multi-timeframe trend scoring |
| **Smart Entry Filter** | `smart_entry_filter.py` | 7 entry gates + momentum guards |
| **Grid Executor** | `grid_executor.py` | Orderplaatsing, grid levels, exit |
| **Professional Risk Mgr** | `professional_risk_manager.py` | ATR stops, profit tiers, time stops |
| **Global Risk Mgr** | `global_risk_manager.py` | Portfolio caps, cooldowns |
| **Budget Allocator** | `budget_allocator.py` | Kapitaal reservering per executor |
| **Dynamic Slot Manager** | `dynamic_slot_manager.py` | Hoeveel coins tegelijk |
| **Grid Sizer** | `grid_sizer.py` | Hoeveel grid levels op basis van ATR |
| **Grid Suitability Scorer** | `grid_suitability_scorer.py` | Geschiktheidsscore per coin |

---

## 3. Fase 1 — Coin Discovery & Selectie

### Dynamische Pair Discovery

De bot scant Kraken elke **5 minuten** voor alle USD-paren die voldoen aan:

| Filter | Waarde | Doel |
|--------|--------|------|
| Min 24h volume | $500.000 | Voldoende liquiditeit |
| Max spread | 0.5% | Geen te dure execution |
| Max coins monitored | 30 | Performance limiet |

### Blacklist

Coins worden uitgesloten als ze:
- **Stablecoins** zijn (USDT, USDC, DAI, etc.) — geen volatiliteit
- **Wrapped/pegged** zijn (WBTC, WETH) — geen eigen prijsbeweging
- **Problematisch** zijn op Kraken (geen orderbook data, infinite retry loops)
- **NL-restricted** zijn (regelgeving)
- **Handmatig geblacklist** zijn door de operator

Huidige blacklist bevat ~30 coins (zie config).

### Grid Suitability Score

Vóór entry wordt elke coin gescoord op **geschiktheid voor grid trading** (0–1):

```
Score = 0.35 × (1 - Range Efficiency)   ← Hoe minder trending, hoe beter
      + 0.30 × Mean Reversion           ← Hoe meer terugkerend naar gemiddelde
      + 0.20 × Bounce Rate              ← Hoe vaker de richting wisselt
      + 0.15 × ATR Consistency           ← Hoe stabieler de volatiliteit
```

| Metriek | Wat het meet | Ideaal voor grids |
|---------|-------------|-------------------|
| **Range Efficiency** | Directional move / total range | Laag (0.0 = pure chop) |
| **Mean Reversion** | Lag-1 autocorrelatie van returns | Hoog (negatieve autocorrelatie) |
| **Bounce Rate** | % candles met richtingswisseling | Hoog (veel reversals) |
| **ATR Consistency** | Variatie in volatiliteit (CV) | Laag (stabiele vol) |

**Drempel:** Score ≥ 0.50 (actief filteren aan). Lookback: 48 candles (4 uur bij 5-min candles).

---

## 4. Fase 2 — Trend Scoring & Ranking

### Multi-Timeframe Trend Berekening

Elke coin krijgt een **composite trend score** gebaseerd op 3 tijdframes:

```
trend_score = 0.2 × trend_1h + 0.4 × trend_4h + 0.4 × trend_24h
```

| Timeframe | Gewicht | Lookback | Functie |
|-----------|---------|----------|---------|
| 1 uur | 20% | 60 min | Korte-termijn momentum |
| 4 uur | 40% | 240 min | Middellange trend |
| 24 uur | 40% | 1440 min | Hoofdtrend |

### Trend Berekening Methodes

De trend wordt op 4 manieren berekend en gecombineerd tot een **consensus**:

1. **Raw percentage change** — simpele prijsverandering
2. **Volatility-normalized** — trend gecorrigeerd voor volatiliteit
3. **EMA-based** — Exponential Moving Average (smooth)
4. **Linear regression** — richting van de trendlijn

### Warmup Mode

Bij opstarten heeft de bot onvoldoende data (vooral voor 24h):
- **Minimaal 360 candles** (30 uur bij 5-min) voor volledige trend
- Tot die tijd: `TrendStatus.WARMUP`
- Historische OHLCV data wordt geladen bij start (720 candles = 60 uur)
- Warmup override: als 4h trend sterk positief (> -0.5%), begin eerder met traden

### Coin Ranking

Coins worden gerangschikt op `trend_score` (hoogste eerst). Alleen coins met:
- `trend_score ≥ 0.7%` (min entry strength)
- Status ≠ WARMUP
- Voldoende orderbook depth

komen in aanmerking.

---

## 5. Fase 3 — Entry Gates (7 Filters)

Een coin moet **alle 7 gates** passeren voordat er een grid geplaatst wordt. Eén reject = geen entry.

### Gate 1: Market Regime Filter (BTC Trend)

De hele markt wordt beoordeeld via BTC als barometer:

| Check | Drempel | Actie bij fail |
|-------|---------|----------------|
| BTC 1h trend | > -2.0% | Block alle entries |
| BTC 4h trend | > 0.0% | Block alle entries |
| BTC 24h trend | > -5.0% | Block alle entries |
| BTC dump | < -5.0% in 1h | Pause 60 min |
| Altcoin breadth | ≥ 30% positief | Block als te weinig alts stijgen |

**Referentie-alts:** ETH, SOL, BNB, AVAX, LINK

### Gate 2: Multi-Timeframe Buy Protection

Beschermt tegen kopen in een dalende markt:

| Timeframe | Min trend | Functie |
|-----------|-----------|---------|
| 1h | ≥ -2.0% | Geen instap bij korte dip > 2% |
| 4h | ≥ -1.5% | Niet in medium downtrend |
| 24h | ≥ -2.5% | Niet in langdurige daling |
| 1h declining | ≤ -4.0% | Als 1h actief daalt: block |
| 4h declining | ≤ -2.0% | Als 4h actief daalt: block |

### Gate 3: Smart Entry Filter (Technische Indicatoren)

De kern-entryfilter met 9 onafhankelijke checks:

| Check | Parameter | Drempel | Waarom |
|-------|-----------|---------|--------|
| **RSI overbought** | RSI(14) | < 72 (baseline) | Niet kopen op de top |
| **RSI extreme dip** | RSI(14) | > 18 | Falling knife alert |
| **VWAP afwijking** | \|price - VWAP\| / VWAP | < 18% | Niet na extreme move |
| **ATR te hoog** | ATR(14) / price | < 7% | Te chaotisch voor grid |
| **ATR te laag** | ATR(14) / price | > 0.08% | Te stil, geen profit |
| **5m spike** | Laatste 5-min candle | < 4% | Niet bij flash move |
| **Falling knife** | 1h - 4h trend acceleratie | > -6% | Dalende versnelling |
| **Blow-off top** | 1h - 4h trend acceleratie | < 5% | Stijgende versnelling |
| **24h trend sanity** | 24h verandering | -10% tot +25% | Extreme trend filter |
| **Spread** | Bid-ask spread | < 0.5% | Uitvoeringskosten |
| **Orderbook depth** | Depth / order size | ≥ 5× | Liquiditeit garantie |

### Gate 4: Adaptive Regime Filters

De entry-drempels passen zich aan het marktregime aan:

| Parameter | BULL | CHOP | BEAR | Baseline |
|-----------|------|------|------|----------|
| RSI max | 76 | 72 | 66 | 72 |
| VWAP max deviation | 20% | 12% | 10% | 18% |
| ATR min | 0.05% | 0.06% | 0.08% | 0.08% |
| Max active grids | 2 | 2 | 1 | 2 |
| Entry confidence | 0.55 | 0.65 | 0.80 | 0.60 |

### Gate 5: Momentum Health Guards

Geavanceerde detectie van ongezonde marktcondities:

**VWAP Slope Guard:**
- Meet de helling van VWAP op 5m én 15m timeframe
- **Dual confirmation:** beide moeten vlak genoeg zijn
- Blokkeert entry bij steil stijgende/dalende VWAP

**Parabolic Detector (Blow-Off Tops):**
- Triggert als ALLE drie waar zijn:
  - 5m acceleratie ≥ 2.5%
  - 15m acceleratie ≥ 6%
  - VWAP afwijking ≥ 18%
- Na trigger: coin op cooldown voor 60 min (persistent in SQLite)

**Market Exhaustion Warning:**
- Als ≥ 70% van top 10 coins parabolisch zijn → marktbrede waarschuwing
- Telegram alert naar operator

### Gate 6: Coin Profile Overrides

Elke coin kan individuele drempels hebben die de defaults overschrijven:

| Coin type | ATR max | VWAP max | RSI block | 24h trend max |
|-----------|---------|----------|-----------|---------------|
| **BTC** (large cap) | 3% | 6% | 68 | 10% |
| **ETH** (large cap) | 4% | 7.5% | 70 | 12% |
| **PEPE** (meme) | 9% | 20% | 80 | 40% |
| **WIF** (meme) | 11% | 22% | 84 | 45% |
| **LINK** (oracle) | 6% | 9% | 72 | 18% |
| **SOL** (L1) | 5% | 10% | 71 | 16% |

Meme coins krijgen ruimere drempels (hogere volatiliteit is normaal), large caps striktere.

### Gate 7: Staleness & Auto-Quarantine

- **Data staleness:** Block als prijsdata ouder is dan 35 sec of orderbook ouder dan 60 sec
- **Auto-quarantine:** Coins die herhaaldelijk falen worden tijdelijk uit rotatie gehaald
- **Session blacklist:** Na problemen (WebSocket errors, etc.): 2 uur ban

---

## 6. Fase 4 — Slot Allocatie & Budget

### Dynamic Slot Manager

Hoeveel coins tegelijk getraded worden hangt af van account grootte en marktregime:

**Basisslots per account grootte:**

| Balance | Basis slots |
|---------|------------|
| $350 | 4 |
| $700 | 5 |
| $1.000 | 6 |
| $1.500 | 7 |
| $2.000 | 8 |
| $3.000 | 10 |

(Lineaire interpolatie tussen tiers)

**Regime correctie:**
- BULL: × 1.5 (meer slots)
- CHOP: × 0.75 (minder slots)
- BEAR: × 0.25 (minimaal, defensief)

**Huidige config override:** min=1, max=3, maar `max_simultaneous_coins=2` is de harde limiet.

⇒ **In de praktijk: maximaal 2 coins tegelijk** ($300 / 2 = $150 per coin).

### Budget Allocator — Reserveringsmodel

Het budget systeem werkt met **pessimistische reserveringen**:

1. **Check:** Is er genoeg vrij kapitaal?
   ```
   beschikbaar = totaal_balance − gereserveerd − safety_reserve (5%)
   nodig = per_coin_bedrag + fee_buffer
   ```
2. **Reserveer:** Wanneer goedgekeurd, reserveer worst-case bedrag
3. **Vrijgeven:** Wanneer executor stopt, komt budget weer vrij
4. **Cleanup:** Orphaned reserveringen worden na X seconden opgeruimd

**Fee buffer:** 0.2% × bedrag × (grid_levels × 2 trades) = ~$0.60 bij $150 en 3 levels.

### Feasibility Check

Voordat een grid geplaatst wordt, valideert de bot:
```
slots ≤ trading_capital / (min_order_amount × num_grids)

Voorbeeld: $300 / ($15 × 3 levels) = 6.67 → max 6 slots
Maar met max_simultaneous_coins=2: effectief max 2
```

---

## 7. Fase 5 — Grid Constructie

### ATR-Based Grid Ranges

De grid range wordt dynamisch berekend op basis van **ATR (Average True Range)**:

```
start_price = current_price − (ATR × 1.5)    ← ondergrens
end_price   = current_price + (ATR × 2.0)    ← bovengrens
```

| Parameter | Waarde | Effect |
|-----------|--------|--------|
| `atr_multiplier_down` | 1.5 | Buy-side bereik |
| `atr_multiplier_up` | 2.0 | Sell-side bereik (ruimer) |

**Asymmetrische aanpassing:**
- In uptrend (> 1%): sell-side 20% verder uitgerekt
- In downtrend (< -1%): buy-side 20% verder uitgerekt

### Dynamisch Aantal Grid Levels

Het aantal levels hangt af van de **huidige ATR%**:

| ATR % | Grid levels | Reden |
|-------|------------|-------|
| < 0.7% | 3 | Stille markt, weinig kansen |
| 0.7–2.0% | 4–5 | Normaal, geïnterpoleerd |
| 2.0–4.0% | 7 | Ideaal voor grids! |
| > 4.0% | 5 | Te chaotisch, risico reductie |

**Config bounds:** min 3, max 5 (bij $300 budget = max 5 kleine levels).

### Grid Level Structuur

Elk grid level is een onafhankelijke buy-sell cyclus:

```
Level 0:  BUY @ $2.45  → SELL @ $2.47  (take-profit 0.8%)
Level 1:  BUY @ $2.42  → SELL @ $2.44
Level 2:  BUY @ $2.39  → SELL @ $2.41
```

**Per level:**
- `amount_quote` = totaal budget / aantal levels (bijv. $150 / 3 = $50)
- `take_profit` = max(grid step size, configured tp%) = minimaal 0.8%
- Levels zijn **lineair verdeeld** tussen start_price en end_price

### Grid Level States

Elk level doorloopt deze cycle:

```
NOT_ACTIVE → OPEN_ORDER_PLACED → OPEN_ORDER_FILLED → CLOSE_ORDER_PLACED → COMPLETE
     │              │                    │                    │
     │          (wacht op fill)    (positie open)      (wacht op TP)
     │              │                    │                    │
     └──────────────┴── timeout ─────────┴── stale cancel ───┘
```

---

## 8. Fase 6 — Positie Monitoring & Exit

### Timeout Mechanismen

Drie onafhankelijke time-based exits:

| Timeout | Standaardwaarde | Conditie | Actie |
|---------|----------------|----------|-------|
| **No-Fill** | 3600s (1 uur) | Geen enkele fill ontvangen | Cancel grid + exit |
| **No-Progress** | 5400s (1.5 uur) | Geen nieuwe fills, verlies > 2.5% | Start close |
| **Max Hold** | 21600s (6 uur) | Maximale positieduur overschreden | Altijd exit |

### Trend-Aware Exit (Soft/Hard Hold)

Voorkomt "dom verkopen" als de trend nog gunstig is:

```
Tijdlijn:
0h ──── 2h ──── 4h ──── 6h
│       │       │       │
│  Normal hold  │       │
│       │  Soft Hold    │
│       │  (trend OK?   │
│       │   extend 30m) │
│       │       │  Hard Hold
│       │       │  (ALTIJD exit)
```

| Parameter | Waarde | Functie |
|-----------|--------|---------|
| `soft_hold_time` | 7200s (2h) | Trend-check begint |
| `hard_hold_time` | 21600s (6h) | Altijd exit (bag-holder preventie) |
| `soft_exit_min_trend` | 0.3% | Trend moet > 0.3% zijn om te verlengen |
| `soft_exit_max_loss` | -1.5% | Exit toch als verlies > 1.5%, ongeacht trend |
| `soft_exit_extend` | 1800s (30m) | Verlenging per keer bij positieve trend |

### Two-Phase Unwind Protocol

Wanneer een exit getriggerd wordt (door timeout, stop-loss, of risk manager):

```
PHASE 1: GRACEFUL (2 min)              PHASE 2: AGGRESSIVE
┌─────────────────────────┐             ┌──────────────────────┐
│ • Place LIMIT sell      │  timeout    │ • Cancel limit order │
│   orders at TP price    │ ─────────▶  │ • Place MARKET sell  │
│ • Wait for fill         │  (300 sec)  │ • Guaranteed fill    │
│ • Lower slippage        │             │ • Higher slippage    │
└─────────────────────────┘             └──────────────────────┘
```

**Stale Close Order Fix:**
- Als een limit sell order > 300 seconden ongevuld blijft → automatisch canceleren
- In AGGRESSIVE fase: als er geen actieve close order is → onmiddellijk opnieuw plaatsen
- Counter bijhouden per executor: `_stale_close_cancel_count`

### Insufficient Funds Handling

- Maximaal 3 retries na "insufficient balance" error
- Na 3 fails: executor wordt gracefully gestopt
- Balance sync delay: 5 seconden wachten na BUY fill voordat SELL geplaatst wordt (Kraken vertraging)

---

## 9. Risk Management (3 Lagen)

### Laag 1: Professional Risk Manager (Per-Positie)

**ATR-Based Stop-Loss:**
```
initial_stop = atr_stop_multiplier × ATR × price
             = 2.0 × ATR

Begrensd: min 2%, max 5% verlies
```

De stop is volatiliteits-aware: in rustige markten strakker, in volatiele markten ruimer.

**Profit Tier Systeem:**

Lockt winst in bij specifieke pieken:

| Piek bereikt | Bij pullback van | Lock op | Voorbeeld ($150 positie) |
|-------------|------------------|---------|--------------------------|
| +1% | 0.5% | ≥ 0% (breakeven) | Piek $151.50, lock bij $151 |
| +2% | 1.3% | ≥ +0.7% | Piek $153, lock bij $152.05 |
| +3% | 1.5% | ≥ +1.5% | Piek $154.50, lock bij $152.25 |

**Emergency Exits:**

| Niveau | Drempel | Actie |
|--------|---------|-------|
| Stop-loss | -5% | Graceful exit (limit orders) |
| Emergency | -5% | Onmiddellijke market exit |
| Hard stop | -8% | Ultiem vangnet, market exit |

**Time-Based Stop:**
- Na 360 min (6 uur): exit als prijs "stalled" (< 0.3× ATR bewogen)
- Én: geen fill in laatste 45 minuten
- Alleen als BEIDE condities waar zijn (actieve posities niet stoppen)

**Win Rate Pause:**
- Als win rate < 35% over laatste 20 trades → pause voor 120 min
- Als rolling PnL < -2% → pause voor 120 min
- Resume wanneer: PnL van laatste 10 trades ≥ 0%
- Maximum 2 verlengingen, daarna force-resume

### Laag 2: Global Risk Manager (Per-Coin Caps)

| Check | Drempel | Effect |
|-------|---------|--------|
| Max per trade | 55% van $300 = $165 | Cap per coin |
| Max totaal open | 95% van $300 = $285 | Portfolio cap |
| Exit cooldown | Per symbol | Block re-entry na exit |
| Switch cooldown | Global | Tijd tussen nieuwe coins |
| Consecutive loss cooldown | Per coin | Na meerdere verliezen: pauze |

**`can_open_trade()` controleert (in volgorde):**
1. Dagelijks verlieslimiet bereikt? → Block
2. Per-coin consecutive loss cooldown? → Block
3. Exit cooldown actief? → Block
4. Global switch cooldown? → Block
5. Bedrag > max per trade? → Cap omlaag
6. Totaal open + nieuw > max portfolio? → Block

### Laag 3: Kill Switch (Portfolio Breed)

| Limiet | Drempel | Werking |
|--------|---------|---------|
| **Dagelijks verlies** | 3% = $9 | Alle nieuwe entries geblokkeerd |
| **Wekelijks verlies** | 7% = $21 | Extended block |
| **Maandelijks verlies** | 10% = $30 | Full stop |
| **Min grid profit** | 0.8% | Dekt Kraken fees (0.26% × 2) + spread |

De kill switch reset dagelijks om middernacht UTC. Exits zijn altijd toegestaan.

---

## 10. Cooldown & Blacklist Systeem

### 5 Types Cooldowns

| Type | Trigger | Duur | Scope |
|------|---------|------|-------|
| **Exit cooldown** | Na positie sluiten | Config-baar | Per coin |
| **Switch cooldown** | Na toevoegen nieuwe coin | 600s (10 min) | Global |
| **Loss cooldown** | Na opeenvolgende verliezen | Config-baar | Per coin |
| **Session blacklist** | WebSocket error, stuck order | 7200s (2 uur) | Per coin |
| **Parabolic cooldown** | Parabolische prijsbeweging | 60 min | Per coin (SQLite) |

### Auto-Quarantine

Coins die herhaaldelijk problemen veroorzaken (rejected orders, geen data, stuck executors) worden automatisch uit rotatie gehaald voor de sessie.

### Monitoring Cooldown

Een coin wordt maximaal 600 seconden (10 min) gemonitord. Als hij in die tijd niet geselecteerd wordt voor entry, rouleert de bot verder naar de volgende coin.

---

## 11. Configuratie Samenvatting

### Kapitaal & Allocatie

| Parameter | Waarde | Toelichting |
|-----------|--------|-------------|
| Trading budget | $300 | Van $1475 account balance |
| Max coins tegelijk | 2 | $150 per coin |
| Min order | $15 | Kraken minimum |
| Grid levels | 3–5 | Dynamisch op ATR |
| Per level | ~$30–$50 | $150 / 3-5 levels |
| Fee buffer | 0.2% | ~$0.60 per round-trip |

### Timing

| Parameter | Waarde | Toelichting |
|-----------|--------|-------------|
| No-fill timeout | 3600s (1h) | Grid meer tijd geven |
| No-progress timeout | 5400s (1.5h) | Stagnatie detectie |
| Max hold time | 21600s (6h) | Bag-holder preventie |
| Soft hold | 7200s (2h) | Trend-aware exit start |
| Hard hold | 21600s (6h) | Altijd exit |
| Min hold | 3600s (1h) | Geen flipfloppen |
| Stale close timeout | 300s (5m) | Canceleer hangende sell order |
| Close grace period | 120s (2m) | Graceful → Aggressive |
| Startup wait | 60s | Warmup voor decision loop |

### Risk Limieten

| Parameter | Waarde |
|-----------|--------|
| Stop-loss | 5% (ATR-based, min 2%, max 5%) |
| Take-profit | 5% (grid TP: 0.8% per level) |
| Emergency exit | -5% |
| Hard stop | -8% |
| Daily max loss | $9 (3%) |
| Weekly max loss | $21 (7%) |
| Monthly max loss | $30 (10%) |
| Min win rate | 35% |
| Pause cooldown | 120 min |

---

## 12. Beslissingsboom

```
Elke ~3 seconden:
│
├─ Risk state sync
│  └─ Daily loss limiet bereikt? ──YES──▶ BLOCK (alleen exits)
│
├─ Check actieve posities
│  ├─ Professional exit signal? ──▶ Start 2-phase unwind
│  ├─ No-fill timeout? ──▶ Cancel + exit
│  ├─ No-progress timeout? ──▶ Exit als verlies > 2.5%
│  └─ Max hold bereikt? ──▶ Altijd exit
│
├─ Ruimte voor nieuwe coin?
│  └─ current_count < max_slots (2)?
│     └─ NEE ──▶ Skip (wacht tot slot vrijkomt)
│
├─ Best trending coin selecteren
│  ├─ Trend Calculator: rank op trend_score
│  ├─ Grid Suitability: score ≥ 0.50?
│  └─ Niet in cooldown/blacklist?
│
├─ Entry Gates checken
│  ├─ Gate 1: BTC trend OK?
│  ├─ Gate 2: Multi-TF buy protection OK?
│  ├─ Gate 3: Smart Entry (RSI/VWAP/ATR/spike/accel/spread/depth) OK?
│  ├─ Gate 4: Regime filter OK?
│  ├─ Gate 5: Momentum health OK?
│  ├─ Gate 6: Coin profile in range?
│  └─ Gate 7: Data fresh + niet in quarantine?
│     └─ Eén gate FAIL ──▶ Skip coin, probeer volgende
│
├─ Budget check
│  ├─ BudgetAllocator: voldoende vrij kapitaal?
│  └─ GlobalRiskManager: can_open_trade()?
│     └─ FAIL ──▶ Skip
│
└─ CREATE GRID
   ├─ ATR-based range berekenen
   ├─ Dynamic grid levels (3-5)
   ├─ Budget reserveren
   └─ Grid Executor starten
      ├─ Place BUY orders op grid levels
      ├─ Wacht op fills
      ├─ Place SELL orders (take-profit)
      └─ Monitor tot complete of timeout
```

---

## 13. Bekende Zwakheden & Aandachtspunten

### Structurele Beperkingen

1. **Klein budget ($300):** Met 2 slots en 3 levels is er weinig ruimte. Eén slechte trade (-5% = $7.50) is bijna het hele dagbudget voor verlies ($9).

2. **Mean-reversion afhankelijkheid:** De strategie werkt slecht in sterke trends. Bij een aanhoudende dump worden buy orders gevuld maar sell orders nooit, resulterend in losses.

3. **Fee impact:** Kraken neemt 0.26% per trade. Bij 3 grid levels = 6 trades per round-trip = ~1.56% aan fees. Take-profit moet minimaal 0.8% per level zijn om break-even te draaien (cumulatief over levels).

### Operationele Risico's

4. **Shared account:** De operator houdt long-term investments op dezelfde Kraken account. De bot mag NOOIT coins verkopen die hij niet zelf gekocht heeft.

5. **Stale orders:** Limit sell orders kunnen lang ongevuld blijven (XDC-USD case: 2.5+ uur). De stale close timeout fix (300s) lost dit op, maar marktcondities bepalen alsnog of de exit succesvol is.

6. **Risk pause cascade:** Als win rate < 35% → 2 uur pause → herstartende markt gemist. De bot is conservatief by design, maar dit kan momentum missen.

### Schaalbaarheid

7. **Bij opschaling naar €25.000+:**
   - Meer slots (8-10 tegelijk)
   - Grotere grid levels ($500+ per level)
   - Orderbook depth wordt relevanter
   - Slippage op Kraken bij grotere orders
   - Regime detection wordt waardevoller

---

*Dit document beschrijft de strategie zoals geconfigureerd in `spot_grid_kraken_usd.yaml` (v3.3). Configuratie kan wijzigen; raadpleeg altijd het YAML-bestand voor actuele waarden.*
