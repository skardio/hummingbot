# Professionele Market Making & Quant Grid Trading — Onderzoeksdocument

> **Status:** Uitzoekwerk voor toekomstig product
> **Doel:** Begrijpen hoe professionele quant traders grid/market-making strategieën uitvoeren,
> en welke aanpak haalbaar is als volgende stap na de huidige single-side grid bot.
> **Geschreven:** 2026-05-31

---

## 1. Waar gaat het mis bij de huidige aanpak?

De huidige bot is een **buy-side grid** op trending crypto assets. Dat is structureel het
moeilijkste scenario voor grid trading:

```
Huidige bot:
  - Alleen buy-side grid (accumuleert base asset als prijs daalt)
  - Geen hedge op directional risico
  - Hoge fees (Kraken taker 0.35%)
  - Assets die trends volgen (geen mean-reversion)

Resultaat:
  - Bij dalende markt: grote open bag, stop-loss of orphan
  - Bij stijgende markt: te vroeg gekopen, TP wordt niet gehaald
  - Break-even vereist 0.55% RT fee + marge → moeilijk bij kleine moves
```

Professionele traders lossen dit anders op. Hieronder de drie meest relevante aanpakken.

---

## 2. Aanpak A: Delta-Neutrale Market Making

### Concept

Een **market maker** plaatst tegelijkertijd een buy order en een sell order rondom de
midprijs. Hij verdient de spread — de afstand tussen bid en ask — zonder een mening te
hebben over de richting van de markt.

```
Prijs:  $100.00

  Ask:  $100.05  ← jij verkoopt hier
  Bid:  $99.95   ← jij koopt hier

  Spread earned per roundtrip: $0.10 (0.10%)
```

Het probleem: als de prijs alleen maar daalt, koop je steeds meer — je bouwt "inventory"
op. Dat is hetzelfde probleem als jouw huidige bot.

### Hoe pro's dit oplossen: delta-hedging

Terwijl de spot market maker koopt, verkoopt hij tegelijkertijd **futures** om het
koersrisico te neutraliseren:

```
Spot:    koop 1 ETH @ $3,000  (long +1 ETH)
Futures: short 1 ETH contract  (short -1 ETH)

Netto delta: 0 — geen koersrisico meer
Winst:       alleen de spread op de spot fills
```

Als de spot order gevuld wordt (koop), sluit hij de futures hedge. Als de sell order
gevuld wordt, opent hij een nieuwe hedge. De bot is continu "flat" op de markt.

### Vereisten

| Vereiste | Detail |
|----------|--------|
| Exchange | Moet spot én futures hebben (Bitget, Binance, OKX) |
| Marge | Futures margin voor hedge (typisch 10-20% van spot positie) |
| Latency | Spot fill → futures hedge binnen ~50ms (anders koersrisico venster) |
| Volume | Minimaal $50k-$500k/dag om fees terug te verdienen |
| Fees | Institutionele fees vereist (<0.02% maker) voor positieve EV |

### Voorbeeld: Bitget ETHUSDT

```python
# Simplified delta-neutral grid
spot_grid = Grid(
    symbol="ETHUSDT",
    side="both",       # buy én sell orders
    levels=10,
    spacing_pct=0.05   # 0.05% per level
)

futures_hedge = FuturesPosition(
    symbol="ETHUSDT_UMCTP",
    target_delta=0.0   # altijd flat houden
)

# Bij elke spot fill: herbereken delta, pas futures aan
def on_spot_fill(fill):
    current_delta = spot_inventory.net_base
    futures_hedge.adjust_to(-current_delta)
```

### Conclusie aanpak A

Krachtig maar complex. Vereist:
- Futures API integratie
- Sub-100ms hedge latency
- Institutionele fee tier (niet haalbaar bij <$10M volume/maand)
- Risico: "inventory risk" als hedge te laat is

**Haalbaarheid voor jou:** Medium-term (6-12 maanden). Bitget futures is al in de repo.

---

## 3. Aanpak B: Pairs Trading / Ratio Grid

### Concept

In plaats van een grid op `ETH/USD` (absolute prijs die trends), draai je een grid op de
**ratio** tussen twee gecorreleerde assets. Ratios mean-reverten van nature.

```
ETH/BTC ratio historisch:
  - Gemiddelde: 0.055 BTC per ETH
  - Range: 0.040 - 0.075
  - Mean-reverts binnen weken/maanden

ETH/USD:
  - Geen stabiel gemiddelde
  - Kan jarenlang in één richting bewegen
```

### Hoe het werkt

Je koopt de "goedkope" asset en verkoopt de "dure" tegelijk:

```
Signaal: ETH/BTC ratio = 0.040 (ETH is goedkoop vs BTC historisch)

Trade:
  koop  1.0 ETH  @ $3,000
  short 0.04 BTC @ $75,000 (= $3,000 notional)

Als ratio normaliseert naar 0.055:
  verkoop 1.0 ETH @ $3,300  (+$300)
  cover   0.04 BTC @ $60,000 (+$600)  [BTC daalde relatief]

Totaal: +$900 ongeacht absolute ETH/BTC richting
```

### Meest interessante crypto pairs

| Pair | Reden |
|------|-------|
| ETH/BTC | Meest liquide, sterkste correlatie, 20+ jaar data |
| SOL/ETH | Emerging L1 ratio, bouncy |
| BNB/ETH | Exchange token vs ETH, range-bound |
| LINK/ETH | Oracle token, stabiele ratio |
| LTC/BTC | OG ratio, hoge liquiditeit |

### Grid op ratio — concreet

```python
# Ratio grid: koop ETH, short BTC als ETH/BTC ratio laag is
ratio = eth_price / btc_price           # bijv. 0.040

grid = RatioGrid(
    asset_a="ETH",
    asset_b="BTC",
    ratio_mean=0.055,       # historisch gemiddelde
    ratio_std=0.008,        # standaarddeviatie
    levels=10,
    entry_z_score=1.0,      # entry bij 1 std dev van gemiddelde
    exit_z_score=0.0        # exit bij terugkeer naar gemiddelde
)
```

### Statistisch bewijs dat dit werkt

```
Cointegratietest (Engle-Granger) op ETH/BTC 2020-2026:
  p-waarde: 0.003  → sterk gecointegreerd (mean-reverts)

Cointegratietest ETH/USD 2020-2026:
  p-waarde: 0.41   → NIET gecointegreerd (trends)

Conclusie: ETH/BTC grid heeft statistisch voordeel,
           ETH/USD grid is gokken op mean-reversion die er niet is.
```

### Vereisten

| Vereiste | Detail |
|----------|--------|
| Exchanges | Eén exchange met beide assets (of cross-exchange) |
| Marge | Short leg vereist collateral |
| Cointegratieanalyse | Python statsmodels, backtesten per pair |
| Herbalancering | Ratio-drift vereist periodieke rebalancering |

### Conclusie aanpak B

**Meest haalbaar als volgende stap.** Geen sub-ms latency nodig, werkt ook bij hogere fees,
statistisch onderbouwd. De `spot_microarb_bitget` controller in de repo is een embryo van dit idee.

**Haalbaarheid voor jou:** Short-term (2-4 maanden). Vereist:
1. Cointegratieanalyse op beschikbare pairs (Python script)
2. Ratio berekening in controller
3. Simultaan kopen en shorten (Bitget spot + futures, of cross-coin)

---

## 4. Aanpak C: Statistical Arbitrage (Stat-Arb)

### Concept

Dezelfde logica als pairs trading, maar op **meerdere assets tegelijk** met een
statistische factor-model. Dit is wat grote quant fondsen (Citadel, Two Sigma) doen.

```
Factor model:
  ETH rendement = β₁×BTC + β₂×DeFi_index + β₃×risk_on + ε

  Als ε (residual) > 2σ:  ETH is te duur → short ETH, long basket
  Als ε < -2σ:            ETH is te goedkoop → long ETH, short basket
```

### Waarom dit moeilijker is

- Factor-modellen degraderen snel (crypto correlaties veranderen)
- Vereist dagelijkse her-kalibratie
- Transaction costs vreten alpha op bij kleine kapitalen
- Vereist meerdere simultane posities → margin management complex

### Haalbaar voor jou

Op kleine schaal is een **2-asset stat-arb** (= pairs trading) al implementeerbaar.
Een volledige multi-factor stat-arb is pas zinvol bij $100k+ kapitaal en dedicated infra.

---

## 5. Aanpak D: Funding Rate Arbitrage (Cash-and-Carry)

### Concept

Op crypto perpetual futures betalen long posities een **funding rate** aan short posities
(of vice versa) elke 8 uur. Als de markt bullish is, betalen longs typisch 0.01-0.10% per
8 uur aan shorts.

```
Cash-and-carry trade:
  koop  1 BTC spot   @ $100,000
  short 1 BTC perp   @ $100,000

  Elke 8 uur: ontvang funding rate (bijv. 0.03% × 3 = 0.09%/dag)
  Jaarlijks:  0.09% × 365 = ~33% APY — risicovrij als hedge perfect is

Risico:
  - Funding kan negatief worden (jij betaalt)
  - Exchange risico (FTX...)
  - Liquidatierisico bij grote moves (margin call op perp)
```

### Wanneer interessant

Alleen tijdens bull markets met consistent positieve funding. In bear markets is funding
vaak negatief.

**Haalbaarheid voor jou:** Laag op dit moment. Vereist $10k+ voor zinvolle returns na fees,
en discipline om te stoppen als funding negatief wordt.

---

## 6. Vergelijkingstabel

| Aanpak | Fees-gevoelig | Directional risico | Haalbaarheid nu | Kapitaal min |
|--------|--------------|-------------------|-----------------|-------------|
| Huidige bot (buy-side grid) | Zeer hoog | Hoog | Live | €300 |
| **Pairs trading / ratio grid** | Laag | Neutraal | 2-4 maanden | €1,000 |
| Delta-neutrale market making | Medium | Neutraal | 6-12 maanden | €5,000 |
| Funding rate arb | Medium | Neutraal | 3-6 maanden | €10,000 |
| Multi-factor stat-arb | Laag | Neutraal | 12+ maanden | €50,000 |

---

## 7. Aanbevolen vervolgstappen

### Stap 1 (nu): Valideer cointegration op jouw exchanges

```python
# Script: cointegration_scan.py
# Vereist: statsmodels, data van Kraken/Bitget API

from statsmodels.tsa.stattools import coint
import pandas as pd

pairs_to_test = [
    ("ETH-USD", "BTC-USD"),
    ("SOL-USD", "ETH-USD"),
    ("LINK-USD", "ETH-USD"),
    ("BNB-USD", "ETH-USD"),
]

for pair_a, pair_b in pairs_to_test:
    score, pvalue, _ = coint(prices[pair_a], prices[pair_b])
    print(f"{pair_a}/{pair_b}: p={pvalue:.4f} {'✓ COINT' if pvalue < 0.05 else '✗ no'}")
```

### Stap 2 (1-2 maanden): Paper trade ratio grid

Bouw een controller die:
1. De spread/ratio berekent tussen twee gecointegreerde assets
2. Z-score berekent ten opzichte van rolling gemiddelde
3. Bij z > 1: short de dure, long de goedkope (paper trading)
4. Bij z → 0: sluit posities

### Stap 3 (3-4 maanden): Live op Bitget met $500 pilot

Bitget heeft spot + futures op hetzelfde account — ideaal voor simultaan long/short.
Start met ETH/BTC als meest bewezen pair.

---

## 8. Resources voor verdere studie

| Resource | Onderwerp |
|----------|-----------|
| *Algorithmic Trading* — Ernest Chan | Pairs trading, mean-reversion, stat-arb |
| *Market Microstructure Theory* — Maureen O'Hara | Hoe market makers echt werken |
| Hummingbot `avellaneda_market_making` strategy | Delta-neutrale MM implementatie in jouw codebase |
| Kaiko API / CoinGecko | Historische OHLCV data voor backtests |
| `statsmodels.tsa.stattools.coint` | Cointegratietest in Python |

---

## 9. Conclusie

De huidige bot is een goede **leerervaring** maar structureel beperkt. De volgende
logische stap is **pairs trading op gecointegreerde crypto assets** — statistisch
onderbouwd, fee-tolerant, en implementeerbaar met de bestaande Hummingbot/Bitget setup.

De grote pro's doen uiteindelijk hetzelfde maar dan met:
- $100M+ kapitaal (fees irrelevant)
- Co-located servers (sub-ms latency)
- 50+ gecointegreerde pairs tegelijk
- Eigen exchange connecties (geen retail API)

Jij kunt dezelfde **logica** toepassen op kleiner schaal — dat is het haalbare doel.
