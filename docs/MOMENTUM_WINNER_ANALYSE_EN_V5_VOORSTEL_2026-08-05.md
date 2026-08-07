# Winnaar-analyse & BUY_NOW v5 Voorstel

Snapshot: 2026-08-05
Basis: 54 geëvalueerde BUY_NOW-signalen (18 TP1 / 18 STOP / 18 TIMEOUT)
TP vs STOP analyse pool: n=36
**Geen config-wijzigingen — alleen analyse en voorstel.**

---

## A. Gemiddeld feature-profiel: TP vs STOP

| feature | **TP1 (n=18)** | **STOP (n=18)** | verschil | signal |
|---|---:|---:|---|---|
| volume_ratio | **8.91×** | **25.57×** | 2.87× hoger bij STOP | ← sterkste |
| slippage_100eur | **0.064%** | **0.047%** | TP heeft hoger slip | ← verrassend |
| market_regime | **+0.039** | **-0.015** | +0.054 bij TP | ← duidelijk |
| market_breadth | **49.2** | **47.4** | +1.8 bij TP | ← zwak |
| d5m/d15m ratio | **0.702** | **0.694** | +0.008 bij TP | ← vrijwel nul |
| score | **0.857** | **0.876** | STOP scoort **hoger** | ← inversie |
| spread_pct | **0.0735%** | **0.0737%** | identiek | ← geen signaal |
| d1m/d5m ratio | **0.439** | **0.427** | vrijwel gelijk | ← geen signaal |

**De score-inversie is bevestigd:** STOP-signalen hebben gemiddeld score 0.876 vs TP-signalen 0.857. De huidige scorer is structureel incorrect georiënteerd voor dit doeleinde.

**Spread discrimineert niet.** Bij elke threshold (<0.08%, <0.10%, <0.15%) is de TP/STOP-verhouding exact 50/50. Spread meet hier niets bruikbaars.

---

## B. Single-feature threshold analyse (TP vs STOP pool, n=36)

| feature | threshold | PASS: n | TP% | STOP% | FAIL: n | TP% | STOP% |
|---|---|---:|---:|---:|---:|---:|---:|
| **slippage > 0** | >0% | 18 | **66.7%** | 33.3% | 18 | 33.3% | **66.7%** |
| volume_ratio | <15× | 27 | **55.6%** | 44.4% | 9 | 33.3% | 66.7% |
| volume_ratio | <10× | 26 | **53.8%** | 46.2% | 10 | 40.0% | 60.0% |
| regime | ≥0 | 22 | **54.5%** | 45.5% | 14 | 42.9% | 57.1% |
| d5/d15 | <0.75 | 22 | **54.5%** | 45.5% | 14 | 42.9% | 57.1% |
| breadth | ≥40 | 26 | **53.8%** | 46.2% | 10 | 40.0% | 60.0% |
| score | <0.87 | 21 | 52.4% | 47.6% | 15 | 46.7% | 53.3% |
| spread | <0.08% | 18 | 50.0% | 50.0% | 18 | 50.0% | 50.0% |

### De slippage-bevinding

`slippage_100eur > 0` geeft 66.7% TP vs 33.3% STOP — het sterkste enkelvoudige signaal. Dit is niet wat je intuïtief zou verwachten (meer slippage = betere uitkomst). Mogelijke verklaring: coins met meetbare slippage voor een €100 order zijn **minder liquide**, waardoor:
1. Grote marktpartijen ze niet snel kunnen in- en uitstappen
2. Momentum langer aanhoudt na signaalgeving
3. Er minder sprake is van "institutional blow-off" patroon

Coins met slippage = 0 zijn extreem liquide; grote posities worden direct gedumpt na de pump → stops.

**Caveat:** n=18/18 is een kleine split. De bevinding is statistisch opvallend maar behoeft validatie op meer data.

---

## C. Combinatie-analyse (alle outcomes, voor n≥20 check)

| combinatie | PASS n | TP% | STOP% | TIMEOUT% | EV% |
|---|---:|---:|---:|---:|---:|
| vol<15 + d5/d15<0.75 | **25** | **40.0%** | **28.0%** | 32% | **-0.307%** |
| vol<15 + regime≥0 | **29** | 34.5% | 27.6% | 38% | -0.418% |
| vol<15 + regime≥0 + d5/d15<0.75 | 18 | 38.9% | 22.2% | 39% | -0.233% | n<20 |
| **FAIL voor alle bovenstaande** | 25–36 | 27.6–32.0% | 37.9–40.0% | — | -0.590 tot -0.661% |

**Beste n≥20 combinatie:** `vol<15 + d5/d15<0.75` (n=25): 40% TP, 28% STOP, EV -0.307%.

Toelichting op waarom FAIL-bucket meer timeouts heeft:
- FAIL = hoger volume + spike-structuur
- Deze signalen gaan nergens heen (timeout) of schieten direct terug (stop)
- TP-rate 27.6% in FAIL vs 40.0% in PASS = 12.4pp verschil

---

## D. Diepteanalyse: stop-patronen bij LAGE volumes

Stops met volume_ratio < 10× (n=12 van de 18 STOP-signals):

| slippage | regime | breadth | d5/d15 | outcome |
|---|---|---|---|---|
| 0.316 | +0.031 | 47.3 | 1.00 | STOP — d5/d15 = 1.0 (pure spike) |
| 0 | -0.059 | 46.6 | 0.551 | STOP — OKX extreme vol (144.5×) |
| 0 | +0.023 | 49.2 | 0.843 | STOP — d5/d15 hoog |
| 0 | +0.001 | 50.3 | 0.474 | STOP — regime neutraal, niets extreem |
| 0.007 | -0.224 | 22.9 | 0.338 | STOP — diep bear + lage breadth |
| 0 | +0.079 | 60.8 | 0.814 | STOP — hoge d5/d15 |
| 0 | +0.009 | 39.5 | 0.547 | STOP — lage breadth |
| 0 | +0.041 | 54.6 | 0.499 | STOP — direct reversal, geen duidelijke reden |
| 0 | -0.126 | 30.0 | 0.607 | STOP — lage breadth |
| 0 | -0.191 | 36.0 | 0.795 | STOP — negatief regime + d5/d15 hoog |
| 0 | +0.176 | 78.8 | 0.512 | STOP — goed regime + hoge breadth maar toch stop |
| 0 | -0.207 | 36.3 | 0.658 | STOP — negatief regime + lage breadth |

**Patronen in lage-volume stops:**
- 9 van 12 hebben slippage = 0 (bevestigt bevinding B)
- 7 van 12 hebben d5/d15 > 0.50 én ofwel negatief regime ofwel lage breadth (<40)
- 1 volledig onverklaarbaar (regime +0.176, breadth 78.8, d5/d15 0.512) — mogelijke noise

**Conclusie lage-volume stops:** Er bestaat een resterende onverklaarbare "random" stop-component (~1/12 tot 2/12 van alle signalen) die geen enkel kenmerk laat zien. Dit is fundamentele marktvolatiliteit. De andere stops zijn grotendeels te verklaren door:
1. d5/d15 > 0.75 (spike-patroon)
2. slippage = 0 (extreem liquide, institutioneel gedumpt)
3. Regime < -0.10 + breadth < 40 (combinatie negatieve context)

---

## E. BUY_NOW v5 — Scoreontwerp voorstel

**Principe:** Identificeer de eerste gezonde fase van een beweging. Selecteer voor organisch, breed gedragen momentum op matig volume — niet voor blow-off tops op extreem volume.

### Wat de huidige scorer fout doet

| huidige component | gewicht | probleem |
|---|---|---|
| volume_expansion | 0.20 | beloont hoog volume → selecteert blow-off tops |
| acceleration (hard filter) | vereist 1.0 | selecteert maximale versnelling = exacte blow-off indicator |
| spread | 0.05 | discrimineert niet (EV-split 50/50) |
| trend_1h / trend_4h | 0.55 | niet beschikbaar via REST → altijd 0 |

### Vijf nieuwe score-componenten

#### Component 1 — Volume kwaliteit (vervangt volume_expansion, gewicht ~0.30)

```
Doel: moderate volume = gezond, extreme volume = straf

score = 1.0   als volume_ratio tussen 2× en 8×
score = 1 - (vol_ratio - 8) / 12   als 8× < vol_ratio < 20×    → lineair afnemend
score = 0     als vol_ratio >= 20×
```

Rationale: TP-gemiddelde = 8.9×, STOP-gemiddelde = 25.6×. Boven 15× verschuift de verhouding naar 2:1 stopts. Boven 20× heeft vrijwel geen positieve waarde meer.

#### Component 2 — Momentum structuur (nieuw, gewicht ~0.25)

```
Doel: beloon geleidelijke moves, straf spikes

ratio = price_change_5m_pct / price_change_15m_pct

score = 1.0   als ratio tussen 0.40 en 0.75  (gezonde opbouw)
score = 0.5   als ratio tussen 0.75 en 0.85  (licht versnellend)
score = 0     als ratio > 0.90               (spike, blow-off)
score = 0.7   als ratio < 0.40               (vroeg begonnen = laat entry)
```

Rationale: 0.50–0.75 bucket = 45.0% TP, 30.0% STOP (beste n≥20 bucket). De 0.75–1.0 bucket = 25.0% TP, 43.8% STOP (slechtste).

#### Component 3 — Marktregime context (nieuw, gewicht ~0.20)

```
Doel: beloon bull regime, straf bear regime

score = clamp((regime + 0.20) / 0.40, 0, 1)

→ regime = -0.20  → score 0.0
→ regime = 0.00   → score 0.5
→ regime = +0.20  → score 1.0
```

Rationale: TP-regime +0.039, STOP-regime -0.015. In het bull-regime (≥+0.2) is stop-first slechts 16.7%. In mild-bear (<0) is stop-first 41.2%.

#### Component 4 — Marktbreedte (nieuw, gewicht ~0.15)

```
Doel: beloon breed gedragen markt, straf geïsoleerde moves

score = clamp((breadth - 30) / 40, 0, 1)

→ breadth = 30   → score 0.0
→ breadth = 50   → score 0.5
→ breadth = 70   → score 1.0
```

Rationale: Breadth <30 = 80% TP maar n=5 (insufficient). Breadth 30–45 = 0% TP, 53.8% STOP. Breadth ≥60 = 30.8% TP, 15.4% STOP. De "death zone" 30–45 moet zwaar gestraft worden.

Aanpassing: overweeg een directe disqualificatie-regel als breadth < 35% (in plaats van alleen soft penalty).

#### Component 5 — Liquiditeitskarakter (nieuw, gewicht ~0.10)

```
Doel: prefereer coins met meetbare slippage boven hyper-liquide coins

score = 1.0   als slippage_100eur > 0
score = 0.0   als slippage_100eur = 0
```

Alternatief (minder binair):
```
score = clamp(slippage_100eur / 0.05, 0, 1)
→ slippage=0     → 0.0
→ slippage=0.05% → 1.0
→ slippage=0.10% → 1.0 (capped)
```

Rationale: slippage>0 = 66.7% TP vs 33.3% STOP; slippage=0 = 33.3% TP vs 66.7% STOP. Dit is de sterkste enkelvoudige discriminant in de data, maar berust op n=18/18 — behandel als hypothese, niet als harde regel.

### Samenvatting v5 gewichtenvoorstel

| component | gewicht | inputs |
|---|---|---|
| Volume kwaliteit | 0.30 | volume_ratio |
| Momentum structuur | 0.25 | d5m/d15m ratio |
| Marktregime | 0.20 | market_regime_at_signal |
| Marktbreedte | 0.15 | market_breadth_15m |
| Liquiditeitskarakter | 0.10 | slippage_100eur |
| ~~Spread~~ | ~~0.05~~ | verwijderd (geen discriminant) |

Totaal = 1.00

### Hard filter suggesties (apart van score)

De volgende grenzen zijn gebaseerd op sterk negatieve zones:

| variabele | huidige filter | v5 voorstel | onderbouwing |
|---|---|---|---|
| volume_ratio min | 2× | handhaven | voldoende volume nodig |
| volume_ratio max | geen | ≤20× disqualificatie | boven 20× = 22.2% TP, 44.4% STOP |
| d5/d15 max | geen | >0.90 disqualificatie | spike-patroon, altijd negatief EV |
| breadth min | geen | <35 disqualificatie | 0% TP-first in 30–45 zone |
| acceleration_score | vereist 1.0 (hard filter) | **verwijderen** | discrimineert niet (altijd 1.0 = geen informatie) |

### Simulatie-verwachting v5

Op basis van de gevonden combinaties (vol<15 + d5/d15<0.75 in de volledige pool):

| | baseline | verwacht v5 |
|---|---|---|
| TP% | 34.0% | ~40–45% |
| STOP% | 32.1% | ~22–28% |
| EV/signal | -0.469% | ~-0.10% tot -0.30% |
| Signalen/dag | 7 | 3–5 (strengere filter) |

De v5 scorer zal minder signalen geven (omdat volume >15× en spikes worden geblokkeerd) maar betere ratio. Of positieve EV haalbaar is, hangt af van of de slippage- en breadth-componenten de residuele random stops kunnen reduceren.

---

## Beperkingen

1. **n=36 in de TP+STOP pool** is te klein voor statistisch robuuste parameterkeuze. De gewichten (0.30, 0.25, etc.) zijn richtinggevend, niet geoptimaliseerd.
2. **Slippage-bevinding (66.7% vs 33.7%)** is het sterkste signaal maar gebaseerd op n=18/18 — hoge kans op overfitting. Moet worden gevalideerd op de volgende 100+ signalen.
3. **Acceleration_score als hard filter** verwijderen is inhoudelijk correct (biedt geen informatie, selecteert blow-off), maar vereist een change in de pre-filter pipeline die voor dit rapport buiten scope is.
4. **Market_regime en breadth** zijn gecorreleerd (ze meten beide marktcontext). Dubbel gewicht geven aan gecorreleerde features overschat hun gecombineerde waarde.
5. **Validatie vereist:** minimaal 150–200 nieuwe BUY_NOW outcomes met de v5 classifier voordat live trading verantwoord is.
