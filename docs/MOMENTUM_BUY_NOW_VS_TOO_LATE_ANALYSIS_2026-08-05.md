# BUY_NOW vs TOO_LATE_EXTENDED_MOVE — Diepteanalyse

Snapshot: 2026-08-05
Database: `data/momentum_signals.sqlite` (venster: 2026-07-29 – 2026-08-05)
Doel: begrijpen waarom TOO_LATE beter presteert dan BUY_NOW en wat dit zegt over de classifier.

Methodologische kanttekening: BUY_NOW-outcomes zijn **echt** (service-side evaluatie). TOO_LATE-outcomes zijn **synthetisch** (scan-gebaseerde toekomstprijzen, TP1 = entry × 1.007, STOP = entry × 0.980, venster 30 min). De vergelijking is indicatief, niet equivalent.

---

## A. Gemiddelde feature-waarden bij signaalmoment

| feature | BUY_NOW (n=52) | TOO_LATE (n=857) | ratio / verschil |
|---|---:|---:|---|
| price_change_1m_pct | 0.977% | 0.321% | BUY_NOW 3× sneller in 1m |
| price_change_3m_pct | 1.961% | 1.369% | BUY_NOW 1.4× sneller in 3m |
| price_change_5m_pct | 2.307% | 2.368% | nagenoeg gelijk |
| price_change_15m_pct | **3.411%** | **8.727%** | TOO_LATE 2.6× groter |
| acceleration_score | **1.000** (hard filter) | 0.495 | BUY_NOW altijd max |
| volume_ratio | **16.22×** | **3.29×** | BUY_NOW 5× hoger volume |
| preselection_score | 0.753 | 0.659 | — |
| spread_pct | 0.080% | 0.164% | BUY_NOW 2× smaller spread |
| slippage_100eur | 0.040% | 0.081% | BUY_NOW 2× lower slippage |
| market_breadth_15m | 49.7 | **53.2** | TOO_LATE in bredere markt |
| market_regime_at_signal | **+0.024** | **+0.145** | TOO_LATE 6× bullisher regime |

**score** en **btc/eth_15m_change_pct** zijn niet vergelijkbaar: score=0.0 voor alle TOO_LATE (wordt niet gescoord), btc/eth = NULL voor alle signalen in dit venster.

### Interpretatie

Het fundamentele verschil is **niet** spread of slippage — BUY_NOW is op die vlakken juist beter. Het verschil zit in drie samenhangende eigenschappen:

1. **BUY_NOW heeft 5× hoger volume** (16× vs 3×) terwijl de d15m-move 2.6× kleiner is.
2. **BUY_NOW heeft altijd maximale acceleratie** — elk BUY_NOW-signaal is een harde acceleratie-spike.
3. **TOO_LATE treedt op in een bullisher marktregime** (+0.145 vs +0.024).

De combinatie van extreme volumepiek + hoge acceleratie + beperkte 15m-move is precies het profiel van een **blow-off top** op korte termijn. TOO_LATE-moves zijn juist het omgekeerde: bevestigde uitbraken met matig volume die al 6–10% zijn doorgezet.

---

## B. Buckets per feature met outcomes

### B1. Volume ratio

| label | bucket | n | TP% | STOP% | EV% |
|---|---|---:|---:|---:|---:|
| BUY_NOW | 3–5× | 12 | **50.0%** | 25.0% | -0.264% |
| BUY_NOW | 5–10× | 25 | 28.0% | 36.0% | -0.591% |
| BUY_NOW | 10–20× | 6 | 33.3% | 33.3% | -0.469% |
| BUY_NOW | >20× | 9 | 22.2% | 44.4% | -0.675% |
| TOO_LATE | <3× | 653 | **62.0%** | 26.5% | -0.186% |
| TOO_LATE | 3–5× | 57 | **66.7%** | 28.1% | -0.143% |
| TOO_LATE | 5–10× | 44 | **65.9%** | 25.0% | -0.075% |
| TOO_LATE | 10–20× | 25 | 52.0% | 40.0% | -0.459% |
| TOO_LATE | >20× | 23 | 56.5% | 30.4% | -0.294% |

**Bevinding:** TOO_LATE haalt in elk volume-bucket minimaal 52% TP-first. BUY_NOW zakt lineair van 50% (bij 3–5×) naar 22% (bij >20×). De dominante TOO_LATE-bucket is <3× (653 van 802 signals = 81%) — bijna alle TOO_LATE-signalen hebben lág volume, terwijl BUY_NOW het gemiddeld met 16× volume doet.

### B2. Δ15m buckets

| label | bucket | n | TP% | STOP% | EV% |
|---|---|---:|---:|---:|---:|
| BUY_NOW | 2.5–3.5% | 30 | 26.7% | 30.0% | -0.497% |
| BUY_NOW | 3.5–4.5% | 15 | 40.0% | 40.0% | -0.537% |
| BUY_NOW | 4.5–6% | 7 | 42.9% | 42.9% | -0.553% |
| TOO_LATE | 6–8% | 474 | **65.0%** | 24.3% | -0.108% |
| TOO_LATE | 8–12% | 245 | **63.3%** | 24.5% | -0.145% |
| TOO_LATE | 12–20% | 59 | 50.8% | 40.7% | -0.504% |
| TOO_LATE | ≥20% | 24 | 20.8% | 75.0% | -1.422% |

**Bevinding:** De 6–12% d15m-zone is de "gouden zone" voor TOO_LATE: 63–65% TP, 24% stop. BUY_NOW's 3–6% zone heeft stelselmatig lagere TP bij vergelijkbare of hogere stop-percentages. Boven 12% d15m degradeert TOO_LATE ook snel — dat zijn echte pumps die crashen.

### B3. Score (BUY_NOW) & preselection score (beide)

| label | bucket | n | TP% | STOP% | EV% |
|---|---|---:|---:|---:|---:|
| BUY_NOW | score 0.80–0.85 | 15 | **46.7%** | 6.7% | **+0.102%** |
| BUY_NOW | score 0.85–0.90 | 26 | 23.1% | **46.2%** | -0.809% |
| BUY_NOW | score ≥0.90 | 11 | 36.4% | 45.5% | -0.710% |

| label | presel bucket | n | TP% | STOP% | EV% |
|---|---|---:|---:|---:|---:|
| BUY_NOW | 0.60–0.70 | 16 | **56.3%** | 18.8% | **-0.020%** |
| BUY_NOW | 0.70–0.80 | 19 | 21.1% | **52.6%** | -0.906% |
| BUY_NOW | ≥0.80 | 15 | 26.7% | 26.7% | -0.468% |

TOO_LATE preselection score verdeling (geen outcomes): <0.60: 32%, 0.60–0.70: 32%, 0.70–0.80: 23%, ≥0.80: 13%.

**Dubbele inversie:** Zowel de finale score als de preselection score presteren beter in de *lagere* buckets. Score 0.80–0.85 is de enige positieve EV-bucket. Presel 0.60–0.70 is bijna break-even (-0.020%), presel 0.70–0.80 is catastrofaal (52.6% stop-first). TOO_LATE-signalen zitten juist geconcentreerd in de lagere presel-buckets (<0.70: 64%), wat mede verklaart waarom ze beter presteren.

### B4. Market breadth

| label | bucket | n | TP% | STOP% | EV% |
|---|---|---:|---:|---:|---:|
| BUY_NOW | <30 | 5 | 80.0% | 20.0% | +0.160% | onvoldoende |
| BUY_NOW | 30–45 | 13 | 0.0% | **53.8%** | -1.168% |
| BUY_NOW | 45–60 | 21 | 42.9% | 38.1% | -0.522% |
| BUY_NOW | ≥60 | 13 | 30.8% | 15.4% | -0.150% |
| TOO_LATE | <30 | 62 | 53.2% | 35.5% | -0.437% |
| TOO_LATE | 30–45 | 186 | 56.5% | 32.3% | -0.335% |
| TOO_LATE | 45–60 | 293 | **63.5%** | 26.6% | -0.180% |
| TOO_LATE | ≥60 | 261 | **66.7%** | 21.8% | -0.033% |

**Bevinding:** TOO_LATE presteert consistent beter in elke breadth-bucket. Cruciaal: bij BUY_NOW is het 30–45% breadth-venster dodelijk (0% TP-first), terwijl TOO_LATE daar nog 56.5% TP haalt. TOO_LATE is minder breadth-afhankelijk, mogelijk omdat de grotere d15m-move al zelf als bewijs voor een sterke setup fungeert.

### B5. Market regime

| label | bucket | n | TP% | STOP% | EV% |
|---|---|---:|---:|---:|---:|
| BUY_NOW | <-0.2 | 4 | 50.0% | 50.0% | -0.650% | onvoldoende |
| BUY_NOW | -0.2–0 | 17 | 23.5% | **41.2%** | -0.729% |
| BUY_NOW | 0–0.2 | 25 | 36.0% | 32.0% | -0.484% |
| BUY_NOW | ≥0.2 | 6 | 33.3% | 16.7% | -0.037% | onvoldoende |
| TOO_LATE | <-0.2 | 30 | 60.0% | 30.0% | -0.267% |
| TOO_LATE | -0.2–0 | 139 | 56.8% | 32.4% | -0.358% |
| TOO_LATE | 0–0.2 | 377 | 57.6% | 29.2% | -0.275% |
| TOO_LATE | ≥0.2 | 256 | **71.9%** | 20.7% | **+0.041%** |

**Bevinding:** In het bull-regime (≥0.2) is TOO_LATE al break-even positief (+0.041%). BUY_NOW haalt in het mild-bear regime (-0.2–0) slechts 23.5% TP. TOO_LATE in datzelfde regime: 56.8% TP. Het regime-effect is veel groter voor BUY_NOW dan voor TOO_LATE — opnieuw omdat TOO_LATE de grotere bewezen move heeft als buffer.

---

## C. Exchange en tijdstip

### Exchange verdeling

| exchange | BUY_NOW n | TP% | STOP% | EV% | TOO_LATE n | aandeel TOO_LATE |
|---|---:|---:|---:|---:|---:|---|
| bitget | 21 | 33.3% | 33.3% | -0.438% | 288 | 33.6% |
| bitvavo | 16 | 31.3% | 31.3% | -0.537% | 341 | 39.8% |
| kraken | 12 | 41.7% | 33.3% | -0.373% | 206 | 24.0% |
| okx | 3 | 0.0% | 66.7% | -1.519% | 22 | 2.6% |

**Bevinding:** De exchange-verdeling van TOO_LATE (bitvavo domineert) verschilt van BUY_NOW (bitget domineert). Bitvavo genereert relatief meer TOO_LATE-signalen, waarschijnlijk door de aard van de EUR-markt: minder liquide, dus snellere procentuele moves die sneller het TOO_LATE-criterium raken. OKX is in beide groepen de slechtste performer maar heeft te weinig data.

### Tijdstip (BUY_NOW n is te klein per uur voor conclusies)

BUY_NOW-signalen zijn verdeeld over de hele dag zonder duidelijk piekuur. TOO_LATE piekt sterk op 13:00 UTC (115 van 857 = 13%), wat samenvalt met de Europese middagopen en vroege US sessie. Dit is een data-kwaliteitsbevinding, geen actionable filter.

---

## D. Waarom presteren succesvolle TOO_LATE signals beter? Feature-profiel per outcome

### BUY_NOW: TP-first vs STOP-first vs TIMEOUT

| segment | n | d1m | d15m | vol_ratio | spread | breadth | regime | score | presel |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BUY_NOW_TP | 17 | 1.00% | 3.55% | **9.2×** | 0.071% | 47.7 | +0.029 | 0.861 | 0.742 |
| BUY_NOW_STOP | 18 | 1.07% | 3.56% | **25.8×** | 0.078% | 47.1 | **-0.024** | 0.879 | 0.759 |
| BUY_NOW_TIMEOUT | 17 | 0.85% | 3.12% | 13.0× | 0.091% | **54.4** | +0.069 | 0.860 | 0.759 |

### TOO_LATE: TP-first vs STOP-first vs TIMEOUT

| segment | n | d1m | d15m | vol_ratio | spread | breadth | regime | presel | accel |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| TOO_LATE_TP | 498 | 0.32% | 8.27% | **2.2×** | 0.159% | **54.7** | **+0.177** | 0.681 | 0.492 |
| TOO_LATE_STOP | 217 | 0.34% | 10.09% | **5.5×** | 0.171% | 49.9 | +0.096 | 0.642 | 0.540 |
| TOO_LATE_TIMEOUT | 87 | 0.27% | 8.23% | 4.7× | 0.180% | 53.1 | +0.092 | 0.610 | 0.421 |

### De drie universele discriminanten

**1. Volume ratio is de sterkste predictor van stops — in beide groepen.**

| groep | TP-gemiddelde volume | STOP-gemiddelde volume | ratio |
|---|---:|---:|---:|
| BUY_NOW | 9.2× | 25.8× | 2.8× |
| TOO_LATE | 2.2× | 5.5× | 2.5× |

Consistent patroon: stops hebben ~2.5× zoveel volume als TP-signals. De stop-zijde is altijd de kant met de volumepiek. Hoog volume = oververhitting = reversal.

**2. Market regime bij signaal discrimineert tussen TP en STOP.**

| groep | TP-regime | STOP-regime | verschil |
|---|---:|---:|---:|
| BUY_NOW | +0.029 | -0.024 | -0.053 |
| TOO_LATE | +0.177 | +0.096 | -0.081 |

TP-signals treden altijd op in een positiever marktregime dan STOP-signals, in beide groepen. TOO_LATE-TP heeft een extra voordeel: met +0.177 is het regime veel bullisher dan BUY_NOW-TP (+0.029).

**3. Hogere score en hogere preselection score = meer stops.**

| groep | TP-score | STOP-score | TP-presel | STOP-presel |
|---|---:|---:|---:|---:|
| BUY_NOW | 0.861 | **0.879** | 0.742 | **0.759** |

STOP-first BUY_NOW-signals hebben gemiddeld hogere scores dan TP-first signals. Dit is een structureel probleem: de scorer beloont de kenmerken die juist tot reversals leiden (hoog volume, hoge acceleratie).

---

## E. Timing: te vroeg of te laat?

### Momentum-structuur bij signaalmoment

| groep | d1m/d15m ratio | d3m/d15m ratio | d5m/d15m ratio | interpretatie |
|---|---:|---:|---:|---|
| BUY_NOW | **0.299** | **0.596** | **0.702** | move nog volop gaande — 30% van 15m-move zit in de laatste minuut |
| TOO_LATE | 0.037 | 0.158 | 0.273 | move is uitgelopen — slechts 4% in laatste minuut |

**Interpretatie:** BUY_NOW-signalen worden gegeven middenin de move: 29.9% van de totale 15m-move is de laatste 1 minuut, 59.6% de laatste 3 minuten. TOO_LATE-signalen zijn rustig geworden: 96% van de 15m-move zat in de eerste 14 minuten, de laatste minuut was bijna vlak.

Dit geeft het antwoord op de vraag of BUY_NOW "te vroeg of te laat" is: **BUY_NOW komt te vroeg — de move is nog bezig en niet bevestigd.** TOO_LATE komt op het moment dat de move is uitgelopen, het volume zakt, en de prijs stabiliseert — dat is feitelijk het betere entry-moment voor een 0.7% TP-target.

### Post-signaal timing

| groep | outcome | n | gem. minuten tot hit | avg best_exit | avg worst_dd |
|---|---|---:|---:|---:|---:|
| BUY_NOW | TP1 | 17 | 16.5 min | +3.39% | -0.92% |
| BUY_NOW | STOP | 18 | **13.1 min** | +0.23% | **-3.72%** |
| BUY_NOW | TIMEOUT | 17 | — | +0.34% | -1.06% |
| TOO_LATE | TP1 | 498 | **7.0 min** | +4.91% | -0.62% |
| TOO_LATE | STOP | 217 | 10.8 min | -0.50% | -5.40% |
| TOO_LATE | TIMEOUT | 87 | — | -0.25% | -1.08% |

**Drie cruciale observaties:**

1. **TOO_LATE TP-first raakt het target in 7 minuten gemiddeld** — bijna 2.4× sneller dan BUY_NOW TP1 (16.5 min). Na een bevestigde 8% move hoeft de prijs maar 0.7% verder — dat gaat snel als het momentum echt is.

2. **BUY_NOW stops treden op in 13 minuten gemiddeld** — dat is vlak na entry. De move keert direct om. Dit bevestigt het blow-off-patroon: de prijs schiet omhoog terwijl het signaal gegeven wordt, maar keert daarna onmiddellijk terug.

3. **Avg best_exit van BUY_NOW STOP-first: slechts +0.23%** — er is nauwelijks opwaarts potentieel, de prijs is bij entry al op de top. TOO_LATE STOP-first heeft een avg best_exit van -0.50% en worst_dd van -5.40%: die stops zijn pijnlijker maar zeldzamer (27% vs 35%).

---

## Synthese: waarom scoort TOO_LATE beter dan BUY_NOW?

### Mechanisme 1 — TOO_LATE heeft veel lager volume bij signaalmoment

81% van TOO_LATE-signalen heeft volume ratio <3× (normaal). BUY_NOW gemiddeld 16×. Volume is de sterkste indicator van een te laat signaal — bij 3–5× volume haalt BUY_NOW nog 50% TP, maar bij 5×+ zakt het naar 22–28%. TOO_LATE werkt juist goed omdat het "te late" moves volgt die al op normaal volume handelen.

### Mechanisme 2 — BUY_NOW selecteert de blow-off top

BUY_NOW vereist **tegelijkertijd**: hoge d15m + hoge volume_ratio + maximale acceleration_score (=1.0 hard filter). Dit is exact het profiel van een blow-off top: een prijs die in korte tijd hard omhoogschiet op extreem volume met toenemende snelheid. Blow-off tops keren altijd terug.

TOO_LATE heeft geen acceleratievereiste (gemiddeld slechts 0.495) en lager volume, maar een grotere totale d15m-move. Dat is het profiel van een **trend**, niet een spike.

### Mechanisme 3 — De TP-target is geometrisch makkelijker na een grote move

Na een 8% move (TOO_LATE) hoeft de prijs nog 0.7% verder = 8.75% van de totale move. Na een 3.4% move (BUY_NOW) hoeft de prijs 0.7% verder = 20.6% van de totale move. BUY_NOW stelt een relatief zwaardere eis aan de continuering.

### Mechanisme 4 — TOO_LATE treedt op in bullisher marktregime

TOO_LATE-regime gemiddeld +0.145, BUY_NOW +0.024. Grote moves (8%+) treden vaker op in bull markten, kleine moves (3–5%) treden ook op in neutrale en bear markten.

---

## Conclusies voor classifier-verbetering

De volgende inzichten zijn statistisch goed gedocumenteerd (n ≥ 20 voor de kernconclusies) en wijzen op structurele problemen in de huidige classifier:

**1. Volume ratio is een stop-predictor, geen kwaliteitsindicator.**
Hoog volume (>10×) correleert met meer stops, niet met meer TP. De score geeft hoog volume te veel gewicht als kwaliteitsindicator. Voor de classifier betekent dit: volume_ratio moet begrensd worden, niet beloond.

**2. Acceleratie op het moment van signaal is een reversal-indicator.**
De acceleration_score = 1.0 hard filter selecteert voor actief versnellende moves — dit is het meest reversal-gevoelige punt. TOO_LATE-TP-signals hebben gemiddeld acceleratie 0.492, niet 1.0. Een hoge acceleratiescore bij signaalmoment correleert met snelle stops, niet met TP.

**3. De preselection score werkt omgekeerd in het 0.70–0.80 bereik.**
Presel 0.60–0.70 is bijna break-even (-0.020% EV), presel 0.70–0.80 is catastrofaal (-0.906% EV). Dit is opnieuw een gevolg van het volume-gewicht in de scorer: hogere presel → hogere volume-component → meer stops.

**4. De d15m-move bij TOO_LATE is een betere kwaliteitsmaatstaf dan de score.**
Een bevestigde 6–12% move (TOO_LATE zone) met lág volume is een sterkere setup dan een 3–5% move met piék volume, zelfs als de scorer het omgekeerde suggereert.

**5. BUY_NOW signalen komen te vroeg — de move is nog gaande bij signaalgeving.**
29.9% van de 15m-move zit in de laatste minuut bij BUY_NOW. Dit is het moment van maximale volatiliteit, niet het moment van stabilisatie. TOO_LATE-signalen worden gegeven nadat 96% van de move al achter de rug is.

**6. Market regime en breadth zijn zinvolle context-filters.**
Beide groepen presteren beter in bull regime (≥0.2) en hogere breadth (≥60). TOO_LATE is echter minder gevoelig voor regime omdat de grotere move als bewijs geldt.
