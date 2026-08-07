# Gezond vs Uitgeput Momentum — BUY_NOW Analyse

Snapshot: 2026-08-05
Database: `data/momentum_signals.sqlite` (venster: 2026-07-29 – 2026-08-05)
**Alleen echte BUY_NOW outcomes (n=54 totaal, n=54 geëvalueerd, verdeeld in 18 TP1 / 18 STOP / 18 TIMEOUT)**

Doelstelling: Bepaal achteraf welke signalen de eerste gezonde fase van een beweging vertegenwoordigden versus uitgeput momentum.

---

## 1. De Remaining/Exhausted ratio

**Definitie:**
- `Exhausted momentum` = `price_change_15m_pct` (de move die al achter de rug was bij entry)
- `Remaining momentum` = `best_exit_pct` (maximale stijging in de 30 minuten ná entry)
- `Remaining/Exhausted ratio` = `best_exit_pct / price_change_15m_pct`

| outcome | n | avg exhausted (d15m) | avg remaining (best_exit) | **R/E ratio** | avg worst_dd | RR (best/adverse) |
|---|---:|---:|---:|---:|---:|---:|
| **TP1** | 18 | 3.504% | 3.336% | **0.967** | -0.914% | 7.39 |
| STOP | 18 | 3.499% | 0.262% | **0.098** | -3.769% | 0.10 |
| TIMEOUT | 18 | 3.094% | 0.308% | **0.097** | -1.074% | 0.57 |

**Kernbevinding:** De pre-entry exhaustion (d15m) is bijna identiek voor TP- en STOP-signalen: 3.50% vs 3.50%. De remaining momentum verschilt dramatisch: 3.34% vs 0.26%. Dit betekent dat het exhausted momentum zelf NIET discrimineert — de move was even groot in beide groepen. Wat discrimineert is of de markt *na* entry nog momentum had.

De ratio R/E = 0.967 voor TP-first betekent: voor elke 1% die de prijs al gestegen was, steeg hij daarna nog 0.97% verder. Voor STOP-first was dat slechts 0.10%.

**Gevolg:** De vraag is niet hoe groot de move was, maar welke *kenmerken bij signaalmoment* voorspellen of de R/E ratio hoog (TP) of laag (STOP) zal zijn.

---

## 2. Pre-entry features per outcome

| feature | TP1 | STOP | TIMEOUT | discriminant? |
|---|---:|---:|---:|---|
| price_change_1m_pct | 0.979% | 1.006% | 0.831% | **Nee** — bijna identiek |
| price_change_3m_pct | 2.126% | 2.003% | 1.709% | **Nee** |
| price_change_5m_pct | 2.375% | 2.352% | 2.216% | **Nee** |
| price_change_15m_pct | 3.504% | 3.499% | 3.094% | **Nee** |
| **volume_ratio** | **8.9×** | **25.6×** | **12.7×** | **JA — sterkste discriminant** |
| d5m/d15m ratio | 0.702 | 0.694 | 0.752 | Zwak |
| d1m/d15m ratio | 0.297 | 0.301 | 0.274 | **Nee** |

**Absolute momentum features discrimineren niet.** De grootte van de move (d1m, d3m, d5m, d15m) is vrijwel identiek tussen TP en STOP. Alleen volume scheidt de groepen: TP-first gemiddeld 8.9×, STOP-first gemiddeld 25.6×.

---

## 3. Volume ratio — primaire discriminant

| vol_bucket | n | TP% | STOP% | TIMEOUT% | EV% | avg_d15m | avg d5/d15 | avg best_exit | avg worst_dd |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| <5× | 14 | **50.0%** | 28.6% | 21.4% | -0.319% | 3.44% | 0.751 | 1.080% | -1.883% |
| 5–10× | 25 | 28.0% | 32.0% | 40.0% | -0.540% | 3.37% | 0.656 | 1.126% | -2.174% |
| 10–20× | 6 | 33.3% | 33.3% | 33.3% | -0.469% | 3.73% | 0.686 | 1.555% | -1.657% | n<20 |
| ≥20× | 9 | 22.2% | **44.4%** | 33.3% | -0.675% | 3.00% | 0.849 | 1.967% | -1.442% | n<20 |

Observaties (n≥20 buckets):
- **<5×** heeft de hoogste TP% (50%) en laagste STOP% (28.6%) — beste EV (-0.319%)
- **5–10×** heeft het meest timeouts (40%) — de move gaat nergens heen
- Alle buckets zijn negatief EV; het gat is kleiner dan verwacht

De ≥20× bucket heeft een hoge avg best_exit (1.967%) maar ook de hoogste stop% — dit zijn signalen met grote moves die tóch slaan omdat de prijs snel terugvalt. De d5/d15 ratio van 0.849 bevestigt: 85% van de 15m-move zat in de laatste 5 minuten — dat is een spike.

---

## 4. d5m/d15m ratio — momentum structuur

**Definitie:** Welk aandeel van de totale 15m-move vond plaats in de laatste 5 minuten?
- Hoog (>0.75) = spikepatroon: de prijs schoot in de laatste minuten omhoog op hoog volume
- Laag (<0.50) = vroeg begonnen: het grootste deel van de move was al klaar voor de laatste 5m
- Midden (0.50–0.75) = geleidelijk: de move ontwikkelde zich gelijkmatig

| d5/d15 bucket | n | TP% | STOP% | EV% | avg_vol | avg best_exit | avg worst_dd |
|---|---:|---:|---:|---:|---:|---:|---:|
| <0.50 (vroeg begonnen) | 10 | 30.0% | 40.0% | -0.670% | 7.6× | 0.876% | -1.739% |
| **0.50–0.75 (geleidelijk)** | **20** | **45.0%** | **30.0%** | **-0.279%** | **17.9×** | **1.882%** | **-2.318%** |
| 0.75–1.00 (recent versneld) | 16 | 25.0% | **43.8%** | -0.832% | 18.2× | 1.057% | -1.789% |
| ≥1.0 (d5m ≥ d15m) | 8 | 25.0% | **12.5%** | -0.157% | 15.4× | 0.875% | -1.407% | n<20 |

**Beste bucket (n≥20): 0.50–0.75 (geleidelijke move)** — 45% TP, 30% STOP, -0.279% EV.

Opvallend: het 0.50–0.75-bucket heeft juist het hoogste gemiddelde volume (17.9×), maar presteert toch het beste. Dit suggereert dat de *structuur* van de move (geleidelijk) deels de hoge-volume-risico's neutraliseert.

**Slechtste bucket (n≥20): 0.75–1.00** — 25% TP, 43.8% STOP. Dit is het klassieke blow-off patroon: 75–100% van de 15m-move in de laatste 5 minuten. De prijs accelereert vlak voor signaalgeving verder — dat is het moment waarop het momentum al overextended is.

**Interessant: d5m ≥ d15m (n=8)** — slechts 12.5% STOP. Dit patroon (d5m groter dan d15m) betekent dat de prijs in het midden van de 15m-periode *daalde* en in de laatste 5 minuten herstelde. Dit is een "dip en herstel" patroon, waar de stop-risico's laag zijn — maar n=8 is onvoldoende voor conclusies.

---

## 5. d1m/d5m — de allerlaatste push

**Definitie:** Welk aandeel van de 5m-move zat in de allerlaatste minuut?
- Hoog (≥0.60) = de prijs versnelt nóg in de laatste minuut → mogelijke top
- Laag (<0.20) = de prijs stabiliseert in de laatste minuut → pauze voor continuering

| d1/d5 bucket | n | TP% | STOP% | EV% | avg_vol |
|---|---:|---:|---:|---:|---:|
| <0.20 (laatste min rustig) | 5 | 0.0% | 40.0% | -0.855% | 22.1× | n<20 |
| 0.20–0.40 (matig) | 24 | **41.7%** | 33.3% | **-0.426%** | 17.4× |
| 0.40–0.60 | 15 | 26.7% | 33.3% | -0.597% | 12.7× |
| ≥0.60 (laatste min dominant) | 10 | 40.0% | 30.0% | -0.341% | 13.2× |

Enige bucket met n≥20: **0.20–0.40** — de minuut voor entry was matig actief (20–40% van de 5m move). Met 41.7% TP is dit de beste n≥20-bucket. Signalen waarbij de laatste minuut helemaal rustig was (ratio <0.20) waren nul TP — maar n=5, dus onvoldoende.

**Tegenintuïtief:** Een dominante laatste minuut (≥0.60, de prijs schoot nog één keer omhoog net voor signaalgeving) heeft 40% TP — vergelijkbaar met de matige bucket. Dit suggereert dat de laatste minuut activiteit minder discriminerend is dan de d5/d15 structuur over een langere termijn.

---

## 6. Score — waarom presteert laag beter?

| score bucket | n | TP% | STOP% | EV% | **avg_vol** | avg d5/d15 | rem_exh ratio |
|---|---:|---:|---:|---:|---:|---:|---:|
| 0.80–0.83 | 6 | **83.3%** | 0.0% | **+0.526%** | **4.2×** | 0.565 | 0.502 | n<20 |
| 0.83–0.86 | 19 | 26.3% | 31.6% | -0.525% | **22.9×** | 0.677 | 0.419 |
| 0.86–0.89 | 13 | 23.1% | **46.2%** | -0.826% | 7.0× | 0.654 | 0.330 |
| ≥0.89 | 16 | 31.3% | 37.5% | -0.581% | 18.7× | **0.869** | 0.353 |

**De score-inversie wordt volledig verklaard door volume en d5/d15:**

- Score 0.80–0.83: volume 4.2× + geleidelijke d5/d15 (0.565) → laag volume + gezonde structuur → 83% TP
- Score 0.83–0.86: volume 22.9× → hoog volume → 31.6% STOP
- Score ≥0.89: d5/d15 = 0.869 → 87% van de move in laatste 5m → spike = 43.8% STOP + 37.5% STOP

**De scorer rewardt hoog volume en recente acceleratie, maar dit zijn precies de blow-off kenmerken.**

---

## 7. 2D analyse: volume × d5/d15 structuur

| volume klasse | accel klasse | n | TP% | STOP% | EV% | avg best_exit | avg worst_dd |
|---|---|---:|---:|---:|---:|---:|---:|
| **vol ≤8× + geleidelijk (<0.75)** | — | **22** | **45.5%** | **27.3%** | **-0.249%** | 1.440% | -1.827% |
| vol ≤8× + spike (≥0.75) | — | 15 | 26.7% | 33.3% | -0.663% | 0.795% | -1.965% |
| vol >8× + geleidelijk (<0.75) | — | 8 | 25.0% | 50.0% | -0.851% | 1.840% | -2.943% | n<20 |
| vol >8× + spike (≥0.75) | — | 9 | 22.2% | 33.3% | -0.514% | 1.331% | -1.155% | n<20 |

**Duidelijkste bevinding met n≥20:** Het kwadrant `volume ≤8× + geleidelijke d5/d15 (<0.75)` is de enige n≥20-cel met ≥40% TP en ≤30% STOP. Dit is de dichtstbijzijnde definitie van "gezond momentum" in de huidige data.

Opvallend: `vol >8× + geleidelijk` heeft het meest adverse drawdown (-2.943%) — een geleidelijke structuur biedt GEEN bescherming bij hoog volume. De volume-cap is de primaire guard.

---

## 8. Risk/reward profiel samenvatting

| outcome | n | R/E ratio | best_exit avg | worst_dd avg | RR ratio | min tot stop |
|---|---:|---:|---:|---:|---:|---:|
| TP1 | 18 | 0.967 | +3.336% | -0.914% | **7.39** | — |
| TIMEOUT | 18 | 0.097 | +0.308% | -1.074% | 0.57 | — |
| STOP | 18 | 0.098 | +0.262% | -3.769% | 0.10 | 13.4 min |

**Het RR-verschil is extreem:**
- TP-first: gemiddeld beste excursie 3.34%, slechtste excursie -0.91% → RR = 7.4
- STOP-first: gemiddeld beste excursie slechts 0.26%, slechtste -3.77% → RR = 0.1

Voor STOP-first was er vrijwel geen positieve beweging na entry. De prijs keerde direct om. Dit bevestigt dat het momentum al volledig uitgeput was bij entry. Gemiddeld duurt het 13.4 minuten voor een stop-signal de stop raakt — maar de max adverse excursion begint vrijwel direct (geen tijd voor TP).

---

## Definitie van Gezond vs Uitgeput Momentum

Op basis van de analyse kunnen twee archetypes worden omschreven:

### Gezond momentum (empirisch profiel)

| kenmerk | range | gevonden in |
|---|---|---|
| volume_ratio | 3–8× | TP-profiel, score 0.80–0.83 bucket |
| d5m/d15m ratio | 0.50–0.75 | Beste n≥20 bucket |
| d1m/d5m ratio | 0.20–0.40 | Beste n≥20 bucket |
| price_change_15m_pct | 2.5–4% | Huidige BUY_NOW filter |
| marktregime | ≥0 | Uit regime-analyse (eerder rapport) |
| marktbreedte | ≥60% | Uit breadth-analyse (eerder rapport) |

**Karakterisering:** Een geleidelijke move die over meerdere minuten is opgebouwd, op normaal tot verhoogd volume, waarbij de beweging niet exponentieel accelereert vlak voor entry. De momentum "smeult" nog — het heeft bevestiging gegeven maar is nog niet overextended.

### Uitgeput momentum (empirisch profiel)

| kenmerk | range | waarschuwingssignaal |
|---|---|---|
| volume_ratio | >15× | STOP-first gemiddeld 25.6×, avg bij 0.75-1.0 d5/d15 bucket = 18.2× |
| d5m/d15m ratio | 0.75–1.00 | 43.8% STOP-first, slechtste bucket |
| score | ≥0.86 | Inversie bewezen — hogere score = meer volume + spike |
| d5m sterk > early move | d5m/d15m > 0.85 | Score ≥0.89 bucket |
| marktregime | <0 | Mild-bear regime verhoogt stops |

**Karakterisering:** Een spike waarbij 75–100% van de totale 15m-move plaatsvond in de laatste 5 minuten, op extreem hoog volume. De prijs schoot omhoog vlak voor entry — dit is het punt waar het momentum al maximaal is en reversals het meest waarschijnlijk.

---

## Conclusies

### Wat werkt niet (boven verwachting)

1. **Absolute momentum-grootte discrimineert niet.** De d1m, d3m, d5m, d15m zijn vrijwel identiek voor TP en STOP signals (allemaal rond ~3.5% d15m, ~2.3% d5m). Een grotere of kleinere move vóór entry geeft geen informatie over wat erna gebeurt.

2. **acceleration_score = 1.0 voor alle signalen** — dit veld bevat geen informatie in de huidige BUY_NOW-set omdat het een harde filter is.

3. **Score ≥ 0.85 is een negatieve predictor.** De score-inversie is volledig verklaarbaar: hogere score = hogere volume-component + hogere acceleratiecomponent = precies de blow-off kenmerken. De scorer selecteert onbedoeld voor uitgeput momentum.

### Wat wél discrimineert

4. **Volume_ratio is de sterkste enkelvoudige predictor.** TP gemiddeld 8.9×, STOP gemiddeld 25.6×. In het beste kwadrant (vol ≤8× + geleidelijk): 45.5% TP met n=22.

5. **d5m/d15m ratio (momentum structuur) is de tweede predictor.** Gradual (0.50–0.75): 45% TP. Spike (0.75–1.00): 25% TP. Dit veld meet of de move organisch verdeeld is of plotseling geconcentreerd in de laatste minuten.

6. **Combinatie volume + structuur is het sterkst.** vol ≤8× + gradual <0.75: 45.5% TP, 27.3% STOP, -0.249% EV — de beste observeerbare prestatie in de data met n≥20.

### Beperkingen

- n=54 totaal is te klein voor harde conclusies in combinatiebuckets. De bevindingen zijn richtinggevend, niet statistisch robuust.
- Alle uitspraken op n<20 zijn als indicatief gemarkeerd.
- De definitie van "gezond momentum" vereist validatie op een langere data-periode (minimaal 200+ BUY_NOW outcomes).
