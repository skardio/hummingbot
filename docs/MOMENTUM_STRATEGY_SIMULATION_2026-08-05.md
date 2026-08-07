# Strategie Simulatie — BUY_NOW Varianten

Snapshot: 2026-08-05
Database: `data/momentum_signals.sqlite` (venster: 2026-07-29 – 2026-08-05)
Type analyse: **read-only simulatie op bestaande signalen, geen codewijziging**

---

## Methodologische aantekening — LEZEN VOOR RESULTATEN

**Kritieke beperking:** `acceleration_score = 1.0` voor alle 53 BUY_NOW-signalen zonder uitzondering. Dit is een harde pre-filter in de huidige classifier. Varianten A (accel < 0.8) en B (accel 0.3–0.7) leveren **nul BUY_NOW-signalen** op als ze op de huidige BUY_NOW-pool worden toegepast.

**Oplossing voor de simulatie:** De varianten zijn toegepast op de **TOO_LATE_EXTENDED_MOVE-pool** (857 signalen), die wél varierende acceleration scores heeft (0 – 1.0). Outcomes zijn **synthetisch**: TP1 = entry × 1.007, STOP = entry × 0.980, venster 30 minuten na signaal. Entry = `entry_max` indien aanwezig, anders `price`.

Alle resultaten op de TOO_LATE-pool zijn dus **indicatief, niet equivalent** aan real-service outcomes. De baseline BUY_NOW gebruikt echte geëvalueerde outcomes.

**n < 20 regels:** Dagelijkse n-waarden < 20 worden gerapporteerd maar zijn niet bruikbaar voor conclusies. Overkoepelende totalen met n ≥ 20 tellen als basis voor conclusies.

---

## Variant overzicht

| variant | pool | filters (samenvatting) | n | TP% | STOP% | TIMEOUT% | avg EV/signaal |
|---|---|---|---:|---:|---:|---:|---:|
| **Baseline BUY_NOW** | BUY_NOW (echt) | huidige classifier | 53 | 34.0% | 32.1% | 34.0% | **-0.469%** |
| BUY_NOW vol<5 | BUY_NOW (echt) | enkel vol_ratio<5 | 13 | 53.8% | 23.1% | 23.1% | -0.190% | n<20 |
| **Variant A** | TOO_LATE (synth) | vol<5 + accel<0.8 + d15m 6-12% | 458 | 63.3% | 24.9% | 11.8% | **-0.146%** |
| **Variant B** | TOO_LATE (synth) | vol<5 + accel 0.3-0.7 + d15m 6-12% | 214 | 61.7% | 28.5% | 9.8% | **-0.230%** |
| **Var A + regime≥0** | TOO_LATE (synth) | Var A + regime ≥ 0 | 361 | 64.5% | 23.3% | 12.2% | **-0.103%** |
| **Var A + breadth≥60** | TOO_LATE (synth) | Var A + breadth ≥ 60 | 147 | 70.1% | 16.3% | 13.6% | **+0.096%** |
| **Var A + regime≥0 + breadth≥45** | TOO_LATE (synth) | Var A + beide context-filters | 299 | 64.9% | 22.4% | 12.7% | **-0.082%** |

Enige variant met positief EV en n ≥ 20: **Var A + breadth≥60** (+0.096% per signaal).

---

## Variant A — detail

**Filters:** `volume_ratio < 5` · `acceleration_score < 0.8` · `price_change_15m_pct` tussen 6% en 12%
**Pool:** TOO_LATE synthetisch · **n = 458** · avg vol: 1.0× · avg d15m: 7.64% · avg accel: 0.265

| metric | waarde |
|---|---:|
| n | 458 |
| TP% | 63.3% |
| STOP% | 24.9% |
| TIMEOUT% | 11.8% |
| avg EV/signaal | -0.146% |
| signalen/dag | ~57 |

**Versus baseline BUY_NOW:** TP +29.3pp, STOP -7.2pp, EV verbeterd van -0.469% naar -0.146%.
**Nog steeds negatief** door de grote asymmetrie: STOP = -2.00%, TP = +0.70%. Bij 25% stops: 0.25 × 2.0 = 0.50% verlies per trade gemiddeld; bij 63% TP: 0.63 × 0.70 = 0.44% winst. Netto: -0.06%, plus timeout-drag.

### Per-dag stabiliteit Variant A

| dag | n | TP% | STOP% | avg EV/sig | noot |
|---|---:|---:|---:|---:|---|
| 2026-07-29 | 19 | 57.9% | 10.5% | +0.006% | |
| 2026-07-30 | 96 | **78.1%** | 17.7% | +0.176% | ← beste dag |
| 2026-07-31 | 48 | 62.5% | 31.3% | -0.257% | |
| 2026-08-01 | 82 | 63.4% | 30.5% | -0.188% | |
| 2026-08-02 | 29 | 31.0% | 41.4% | -0.837% | ← slechte dag (Aug crash) |
| 2026-08-03 | 81 | 67.9% | 21.0% | -0.034% | |
| 2026-08-04 | 53 | 37.7% | 28.3% | -0.597% | ← slechte dag |
| 2026-08-05 | 50 | **76.0%** | 22.0% | +0.054% | |

**Stabiel?** Niet echt: 3 van 8 dagen zijn negatief > -0.20%, 2 zijn sterk negatief (Aug 2, Aug 4). Beste dagrange: +0.006% tot +0.176%. Slechtste: -0.837% (Aug 2). De slecht-dag-patroon correspondeert 1-op-1 met marktcorrectiemomenten.

**Max drawdown (avg EV per signaal):** -0.837% op Aug 2. Dat is de dag dat de crypto-markt een scherpe correctie maakte. Als je 10 trades per dag doet is de dagverlies dan 10 × 0.837% = 8.37% van je positiegrootte.

---

## Variant B — detail

**Filters:** `volume_ratio < 5` · `acceleration_score` tussen 0.3 en 0.7 · `price_change_15m_pct` tussen 6% en 12%
**Pool:** TOO_LATE synthetisch · **n = 214** · avg vol: 1.3× · avg d15m: 7.66% · avg accel: 0.567

| metric | waarde |
|---|---:|
| n | 214 |
| TP% | 61.7% |
| STOP% | 28.5% |
| TIMEOUT% | 9.8% |
| avg EV/signaal | -0.230% |
| signalen/dag | ~27 |

Variant B scoort iets slechter dan Variant A op alle metrics. De accel-range 0.3–0.7 selecteert een subset van Variant A die meer stops heeft. De stop-first is 3.6pp hoger bij vergelijkbare TP-first.

### Per-dag stabiliteit Variant B

| dag | n | TP% | STOP% | avg EV/sig | noot |
|---|---:|---:|---:|---:|---|
| 2026-07-29 | 8 | 50.0% | 25.0% | -0.289% | n<20 |
| 2026-07-30 | 53 | 71.7% | 24.5% | -0.006% | |
| 2026-07-31 | 30 | 56.7% | 36.7% | -0.434% | |
| 2026-08-01 | 32 | 62.5% | 34.4% | -0.290% | |
| 2026-08-02 | 9 | 22.2% | 33.3% | -1.073% | n<20 ← slechte dag |
| 2026-08-03 | 35 | 65.7% | 20.0% | -0.048% | |
| 2026-08-04 | 22 | 40.9% | 36.4% | -0.647% | |
| 2026-08-05 | 25 | 76.0% | 24.0% | +0.052% | |

**Conclusie:** Variant B is consistent slechter dan Variant A. De restrictievere accel-range (0.3–0.7 vs <0.8) haalt betere signalen *en* slechtere signalen eruit, maar per saldo meer slechte. Geen toegevoegde waarde ten opzichte van Variant A.

---

## Variant C — Vergelijking huidig vs best-gevonden

### Volledige vergelijkingstabel

| variant | n | TP% | STOP% | EV/sig | signalen/dag | noot |
|---|---:|---:|---:|---:|---:|---|
| **Baseline (huidig BUY_NOW)** | 53 | 34.0% | 32.1% | -0.469% | 7 | echt |
| Var A (basis) | 458 | 63.3% | 24.9% | -0.146% | 57 | synth |
| Var A + regime≥0 | 361 | 64.5% | 23.3% | -0.103% | 45 | synth |
| Var A + regime≥0 + breadth≥45 | 299 | 64.9% | 22.4% | -0.082% | 37 | synth |
| **Var A + breadth≥60** | **147** | **70.1%** | **16.3%** | **+0.096%** | **18** | synth |

### Beste variant: Var A + breadth≥60

**Filters:** `volume_ratio < 5` + `acceleration_score < 0.8` + `d15m 6–12%` + `market_breadth_15m ≥ 60`

| metric | waarde |
|---|---:|
| n (8 dagen) | 147 |
| TP% | 70.1% |
| STOP% | 16.3% |
| TIMEOUT% | 13.6% |
| avg EV/signaal | **+0.096%** |
| signalen/dag | ~18 |

### Per-dag stabiliteit — Var A + breadth≥60

| dag | n | TP% | STOP% | avg EV/sig | noot |
|---|---:|---:|---:|---:|---|
| 2026-07-29 | 12 | 75.0% | 0.0% | **+0.381%** | n<20 |
| 2026-07-30 | 37 | **81.1%** | 16.2% | **+0.240%** | ← beste dag |
| 2026-07-31 | 4 | 50.0% | 25.0% | -0.523% | n<20 |
| 2026-08-01 | 21 | 76.2% | 19.0% | **+0.152%** | |
| 2026-08-02 | 7 | 71.4% | 14.3% | **+0.155%** | n<20 |
| 2026-08-03 | 30 | 70.0% | 16.7% | **+0.111%** | |
| 2026-08-04 | 21 | 28.6% | 28.6% | -0.600% | ← slechtste dag |
| 2026-08-05 | 15 | **93.3%** | 6.7% | **+0.520%** | n<20 |

**6 van 8 dagen positief EV** (n ≥ 20: 3 van 3 positief).
Enige negatieve n≥20-dag: Aug 4 (-0.600%). Dat correspondeert met een marktdaling.

**Max drawdown (slechtste dag):** -0.600% per signaal (Aug 4). Bij 18 trades per dag: dagverlies van ~10.8% van positiegrootte op Aug 4. Aug 3 was positief (+0.111%), dus de Aug 4-dag is een geïsoleerde slechte dag, niet de staart van een slechte streak.

### Directe vergelijking op dezelfde 8 dagen

| dag | baseline EV | Var A+breadth60 EV | verschil |
|---|---:|---:|---:|
| Jul 29 | +0.700% (n=1) | +0.381% (n=12) | n<20 voor beide |
| Jul 30 | +0.077% | **+0.240%** | +0.163pp |
| Jul 31 | -0.968% | -0.523% (n=4) | baseline slechter, n<20 voor variant |
| Aug 1 | +0.162% | **+0.152%** | ≈ gelijk |
| Aug 2 | +0.304% (n=3) | +0.155% (n=7) | n<20 voor beide |
| Aug 3 | **-1.311%** | +0.111% | variant **+1.422pp beter** |
| Aug 4 | -0.994% | -0.600% | variant 0.394pp beter |
| Aug 5 | -0.279% | +0.520% (n=15) | n<20 voor variant |

**Meest opvallend: Aug 3.** Baseline BUY_NOW had 0% TP en 67% stops (-1.311% EV). Var A + breadth≥60 had 70% TP en 16.7% stops (+0.111% EV). De breadth≥60-filter heeft die dag exact de correcte signalen eruit gehouden.

---

## Maximale drawdown samenvatting

| variant | slechtste dag avg EV | slechtste dag datum | n op die dag |
|---|---:|---|---:|
| Baseline BUY_NOW | -1.311% | Aug 3 | 9 |
| Variant A | -0.837% | Aug 2 | 29 |
| Variant B | -1.073% | Aug 2 (n<20) | 9 |
| Var A + regime≥0 | niet apart gemeten | — | — |
| **Var A + breadth≥60** | **-0.600%** | Aug 4 | **21** |

Var A + breadth≥60 heeft de kleinste max drawdown op de slechtste dag (n≥20).

---

## Conclusies

### Wat werkt wel

1. **Volume cap op <5×** is de sterkste enkelvoudige verbetering. BUY_NOW vol<5 geeft al 53.8% TP vs 34% totaal (n=13, indicatief). In de TOO_LATE-pool bevestigt dit patroon op grote schaal.

2. **Breadth≥60 is een krachtige dag-filter.** De enige positief-EV variant in deze simulatie is Var A + breadth≥60. Dit veld filtert actief de slechtste marktomstandigheden eruit (Aug 3, Aug 4 worden deels gedempt).

3. **d15m 6–12% als entry-zone** (de TOO_LATE-pool) presteert structureel beter dan d15m 2.5–5.5% (huidige BUY_NOW), bij vergelijkbare andere condities.

### Wat niet werkt

4. **Acceleration 0.3–0.7 (Variant B) voegt niets toe** ten opzichte van accel<0.8 (Variant A). De smallere accel-range selecteert geen betere subgroep.

5. **Regime≥0 is minder krachtig dan breadth≥60.** Regime toevoegen aan Variant A verbetert EV van -0.146% naar -0.103%, maar geeft geen positieve EV. Breadth≥60 geeft wel positieve EV.

### Kritieke beperkingen van deze simulatie

- **Alle TOO_LATE-outcomes zijn synthetisch**: de scan bevat tickers van ~80 seconden oud, niet de werkelijke order-execution prijzen. Werkelijke slippage bij entry kan het EV-voordeel deels neutraliseren.
- **De TOO_LATE-pool is nooit echt gehandeld**: survivorship-bias is onbekend (mogelijk zijn de slechtste moves niet terug te zien in de scan-data).
- **7 dagen data**: Aug 3–4 waren bijzondere correctiedagen. In een bull-regime zou de simulatie er anders uitzien.
- **n=147 voor de beste variant over 8 dagen** is nog te weinig voor statistisch robuuste conclusies. Minimaal 4–6 weken data met de nieuwe classifier is nodig voor validatie.
- **De score-kolom is 0 voor alle TOO_LATE**: een eventueel toekomstige classifier die ook TOO_LATE-candidates scoort zou een andere verdeling kunnen tonen.
