# Momentum Signal Analysis Report

Snapshot: 2026-08-05 13:35 Europe/Berlin
Database: `data/momentum_signals.sqlite`
Periode: 2026-07-29 – 2026-08-05 (7-daagse retentievenster)
Config versie: 4 (enige versie in venster)

## Methode

Net EV fee-model (zelfde als vorige rapporten):

- `TP1`: `+0.70%`
- `TP2`: `+2.00%`
- `STOP`: `-2.00%`
- `TIMEOUT`: `best_exit_pct - 0.50%`

Drempel voor voldoende data: n ≥ 15. Rijen met `n < 15` worden gemarkeerd als onvoldoende.

---

## 1. Data kwaliteit

| metric | waarde |
|---|---:|
| signals_total | 1.506.670 |
| labeled_signals | 58 |
| BUY_NOW signals | 53 |
| WATCH signals | 5 |
| TOO_LATE signals | 865 |
| evaluated_outcomes_total | 1.320 |
| evaluated_outcomes_joinable | 52 |
| orphan_evaluated_outcomes | 1.263 |
| min_signal_ts | 2026-07-29 13:35 |
| max_signal_ts | 2026-08-05 13:34 |
| pending BUY_NOW (geen outcome) | 0 |

**Interpretatie:** De 7-daagse retentie heeft alle data vóór 29 juli verwijderd. De 52 joinable outcomes zijn volledig current. Het orphan-probleem (1.263 rijen) is structureel ongewijzigd — die outcomes wijzen naar gesignalen die buiten het retentievenster vallen. Van de 53 BUY_NOW-signalen hebben 52 een evaluated outcome; de 53e is vandaag binnengekomen en nog niet geëvalueerd.

**Let op vergeleken met het rapport van 24 juli:** Die had 49 joinable outcomes over Jul 17–24. Dit rapport heeft 52 over Jul 29–Aug 5 — meer signalen, lagere kwaliteit (zie §2).

---

## 2. BUY_NOW performance — hoofdconclusie

```
n=52 | TP-first: 32.7% | STOP-first: 34.6% | Avg net EV: -0.525%
```

| first_hit | n | pct | avg_net_ev_pct |
|---|---:|---:|---:|
| TP1 | 17 | 32.7% | +0.700 |
| STOP | 18 | 34.6% | -2.000 |
| TIMEOUT | 17 | 32.7% | -0.189 |

**Samenvatting:**

| n | tp_n | tp_pct | stop_n | stop_pct | timeout_n | avg_best_exit | avg_worst_dd | avg_net_ev |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 52 | 17 | 32.7% | 18 | 34.6% | 17 | 1.288% | -1.922% | -0.525% |

**⚠️ Ernstige regressie ten opzichte van vorig rapport:**

| metric | Jul 24 | Aug 5 | verschil |
|---|---:|---:|---:|
| TP-first | 44.9% | 32.7% | **-12.2pp** |
| STOP-first | 16.3% | 34.6% | **+18.3pp** |
| Avg net EV | -0.169% | -0.525% | **-0.356%** |

De stop-first rate is meer dan verdubbeld. Dit is de slechtste periode in alle beschikbare data. De stops drukken het gemiddelde zwaar neer; de timeouts zijn licht negatief maar niet de hoofdoorzaak.

---

## 3. Score kalibratie

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit | avg_net_ev | noot |
|---|---:|---:|---:|---:|---:|---|
| 0.80–0.85 | 15 | 46.7% | 6.7% | 1.487% | **+0.102%** | ← enige positieve bucket |
| 0.85–0.90 | 26 | 23.1% | 46.2% | 1.272% | -0.809% | |
| >=0.90 | 11 | 36.4% | 45.5% | 1.053% | -0.710% | onvoldoende |

**⚠️ Kritieke bevinding: hoge score = meer stops.**

De 0.85–0.90 bucket heeft een stop-first rate van **46.2%** — bijna de helft van de signalen loopt direct in de stop. De >=0.90 bucket is vergelijkbaar slecht. Alleen de laagste scorebucket (0.80–0.85) is break-even positief.

Dit is het omgekeerde van wat een goede scorer zou moeten doen. Mogelijke verklaringen:
1. De scorer reageert op extreme momentum-moves (hoge Δ15m + hoog volume) die juist het meest reversal-gevoelig zijn.
2. Hogere scores worden toegewezen aan "mooiere" setups die in werkelijkheid blow-off tops zijn.

**Implicatie voor gebruik:** Een score-cutoff van >=0.85 verergert de selectie actief. De bruikbare zone is momenteel **0.80–0.85**, niet hoger.

---

## 4. Exchange performance

| exchange | n | tp_first_pct | stop_first_pct | avg_best_exit | avg_worst_dd | avg_net_ev |
|---|---:|---:|---:|---:|---:|---:|
| bitget | 20 | 35.0% | 35.0% | 1.184% | -2.150% | -0.481% |
| bitvavo | 16 | 31.3% | 31.3% | 0.955% | -1.534% | -0.537% |
| kraken | 13 | 38.5% | 30.8% | 1.951% | -1.739% | -0.350% |
| okx | 3 | 0.0% | 66.7% | 0.888% | -3.269% | -1.519% | onvoldoende |

Alle exchanges zijn negatief EV in deze periode. Kraken presteert het minst slecht (-0.350%) met de hoogste avg_best_exit (1.951%). OKX is een ramp maar heeft slechts 3 rows. Bitget en Bitvavo zijn nagenoeg gelijk negatief.

---

## 5. Δ15m buckets

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit | avg_net_ev | noot |
|---|---:|---:|---:|---:|---:|---|
| 2.5–4% | 44 | 29.5% | 34.1% | 1.164% | -0.549% | |
| 4–5.5% | 8 | 50.0% | 37.5% | 1.967% | -0.396% | onvoldoende |

Het dominante 2.5–4% bucket is negatief EV. De 4–5.5% bucket toont betere TP-first maar ook hogere stop-first; netto marginaal minder slecht. Met n=8 is dit onvoldoende voor een harde conclusie. Er zijn geen signalen buiten deze twee buckets (filter werkt).

---

## 6. Volume ratio buckets

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit | avg_net_ev | noot |
|---|---:|---:|---:|---:|---:|---|
| 3–5x | 12 | 50.0% | 25.0% | 1.019% | -0.264% | onvoldoende |
| 5–10x | 24 | 29.2% | 37.5% | 1.136% | -0.633% | |
| >=10x | 16 | 25.0% | 37.5% | 1.717% | -0.559% | |

**Bevinding:** Het 3–5x bucket is veruit het beste: 50% TP-first, 25% stop-first, -0.264% EV. Het >=5x gebied is consistent slechter. Dit suggereert dat extreem hoog volume (5x+) correlreert met blow-off moves die daarna hard corrigeren. Het 2–3x bucket ontbreekt — dat is volledig gefilterd vóór signaalgeving.

---

## 7. Spread buckets

| bucket | n | tp_first_pct | stop_first_pct | avg_net_ev |
|---|---:|---:|---:|---:|
| <0.10% | 34 | 35.3% | 35.3% | -0.520% |
| 0.10–0.20% | 18 | 27.8% | 33.3% | -0.536% |

Geen enkel spread-effect in deze periode: beide buckets zijn nagenoeg identiek negatief EV. De eerdere "lage spread = schoner" bevinding uit het Juli-rapport houdt niet stand in deze week. Dit kan het gevolg zijn van het marktregime (stops worden overal geraakt ongeacht spread).

---

## 8. Market breadth (nieuw veld)

`market_breadth_15m` = % van gescande coins dat in 15m positief is (0–100 schaal).

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit | avg_net_ev | noot |
|---|---:|---:|---:|---:|---:|---|
| <30% (brede selloff) | 5 | 80.0% | 20.0% | 1.802% | +0.160% | onvoldoende |
| 30–45% (zwak) | 13 | 0.0% | 53.8% | 0.126% | -1.168% | |
| 45–60% (neutraal) | 21 | 42.9% | 38.1% | 1.752% | -0.522% | |
| >=60% (brede rally) | 13 | 30.8% | 15.4% | 1.502% | -0.150% | |

**⚠️ Kritieke bevinding: breadth 30–45% is catastrofaal.**

Een markt waarbij 30–45% van de coins stijgt is de gevaarlijkste zone: **0% TP-first, 53.8% stop-first**. Dit is een "valse munt rotatie" omgeving — een paar coins lijken te bewegen maar de markt ondersteunt niet. Signalen in deze zone zijn aantoonbaar waardeloos.

**Meest veelbelovende bevinding:** `>=60%` breed stijgende markt = slechts 15.4% stop-first, en de laagste negatieve EV (-0.150%). Dit is de meest tradeable zone.

**Implicatie:** Een breadth-filter van `>=45%` of liever `>=60%` zou de gevaarlijkste signalen uitsluiten.

---

## 9. Market regime bij signaal

`market_regime_at_signal` = gewogen score van marktrichting (-1 tot +1).

| bucket | n | tp_first_pct | stop_first_pct | avg_best_exit | avg_net_ev | noot |
|---|---:|---:|---:|---:|---:|---|
| <-0.2 (bear) | 4 | 50.0% | 50.0% | 0.933% | -0.650% | onvoldoende |
| -0.2–0 (mild bear) | 17 | 23.5% | 41.2% | 0.799% | -0.729% | |
| 0–0.2 (neutraal) | 25 | 36.0% | 32.0% | 1.648% | -0.484% | |
| >=0.2 (bull) | 6 | 33.3% | 16.7% | 1.408% | -0.037% | onvoldoende |

Het mild-bear regime (-0.2 tot 0) is het giftigst: 41.2% stop-first, -0.729% EV. Bull (>=0.2) heeft de laagste stop-first rate (16.7%) en benadert break-even (-0.037%). Neutraal is het meest voorkomend en middelmatig negatief.

---

## 10. Gecombineerde filter kandidaat

Combinatie: `regime >= 0` + `score < 0.85` + `breadth >= 45%`:

| n | tp_first_pct | stop_first_pct | avg_net_ev |
|---:|---:|---:|---:|
| 8 | 50.0% | 0.0% | **+0.285%** | onvoldoende |

Dit is een klein maar opvallend positief EV-subset. Met n=8 kan hier geen harde conclusie aan worden verbonden, maar de richting is duidelijk: schrap de hogere score buckets, schrap de bear-regime signalen, en eis voldoende marktbreedte.

---

## 11. Slippage (nieuw veld)

`slippage_100eur` = geschat slippage voor een €100 order (0–0.382%, gem. 0.039%).

| bucket | n | tp_first_pct | stop_first_pct | avg_net_ev |
|---|---:|---:|---:|---:|
| <0.05% | 40 | 32.5% | 37.5% | -0.599% |
| NULL | 3 | 0.0% | 33.3% | -0.513% | onvoldoende |
| 0.05–0.10% | 3 | 33.3% | 33.3% | -0.542% | onvoldoende |
| >=0.10% | 6 | 50.0% | 16.7% | -0.031% | onvoldoende |

Verrassend: hogere slippage (>=0.10%) heeft betere TP-first en lagere stop-first. Mogelijke verklaring: coins met hoge slippage zijn kleiner/minder liquide, maar hun moves zijn echte breakouts in plaats van washed-out institutional moves. Met n=6 is dit onvoldoende — bewaken in volgend rapport.

---

## 12. TOO_LATE validatie (synthetisch)

TOO_LATE: TP1 = entry × 1.007 (+0.7%), STOP = entry × 0.980 (-2.0%), venster 30 min.

| n | tp_first_pct | stop_first_pct | avg_best_exit | avg_worst_dd |
|---:|---:|---:|---:|---:|
| 810 | 61.9% | 27.4% | 2.867% | -1.976% |

**Opmerkelijke bevinding:** TOO_LATE-signalen presteren in deze periode *beter* dan BUY_NOW:
- TOO_LATE TP-first: 61.9% vs BUY_NOW TP-first: 32.7%
- TOO_LATE stop-first: 27.4% vs BUY_NOW stop-first: 34.6%

Dit is de inverse van de bedoeling. De TOO_LATE-filter blokkeert momenteel betere moves dan die hij doorlaat. Mogelijk is de 15m-move drempel voor TOO_LATE te laag ingesteld, waardoor moves die eigenlijk al "rijp" zijn voor entry onterecht worden geblokkeerd.

---

## 13. Dagelijks regime

| dag | n | tp_first_pct | stop_first_pct | avg_best_exit | avg_net_ev | noot |
|---|---:|---:|---:|---:|---:|---|
| 2026-07-29 | 3 | 33.3% | 33.3% | 0.622% | -0.456% | onvoldoende |
| 2026-07-30 | 11 | 54.5% | 9.1% | 1.798% | +0.077% | onvoldoende |
| 2026-07-31 | 8 | 25.0% | 50.0% | 0.771% | -0.968% | onvoldoende |
| 2026-08-01 | 7 | 71.4% | 14.3% | 3.728% | +0.162% | onvoldoende |
| 2026-08-02 | 3 | 33.3% | 0.0% | 0.984% | +0.304% | onvoldoende |
| 2026-08-03 | 9 | 0.0% | 66.7% | 0.281% | -1.311% | onvoldoende |
| 2026-08-04 | 7 | 14.3% | 57.1% | 0.552% | -0.994% | onvoldoende |
| 2026-08-05 | 4 | 25.0% | 25.0% | 0.928% | -0.583% | onvoldoende |

Twee cluster-patronen:
- **Goede dagen:** Jul 30, Aug 1, Aug 2 — positieve tot break-even EV, lage stop-first
- **Slechte dagen:** Jul 31, Aug 3, Aug 4 — 0–25% TP-first, 50–67% stop-first

Aug 3 is de slechtste dag ooit gemeten: 0% TP-first, 66.7% stop-first. Dit is geen toeval — 3 augustus was een sterke correctiedag op de crypto-markt. De service blijft signaleren terwijl de markt daalt, wat direct resulteert in stops.

---

## 14. Stop-hit timing

Van de 18 STOP-first signals (stop_hit_at_seconds beschikbaar):

| timing | n | avg_worst_dd |
|---|---:|---:|
| <5 minuten | 4 | -3.983% |
| 5–15 minuten | 6 | -4.494% |
| 15–30 minuten | 8 | -3.004% |

**Bevinding:** Stops die snel raken (<5 min) zijn explosief negatief. Dit zijn directe reversals na entry — het signaal is gevangen op een intra-candle top. De langzamere stops (15–30 min) zijn minder diep (-3.0%), maar nog steeds ver voorbij de -2% model-aanname. Het EV-model (STOP = -2.00%) onderschat de werkelijke stop-verliezen stelselmatig.

**Let op:** De gemiddelde worst drawdown voor stops is -3.5% tot -4.5%, terwijl het model uitgaat van -2.0%. De werkelijke EV is dus slechter dan de tabel suggereert.

---

## 15. Ergste drawdowns

| exchange | pair | score | d15m | vol_ratio | spread | first_hit | worst_dd | best_exit |
|---|---|---:|---:|---:|---:|---|---:|---:|
| bitget | UAI-USDT | 0.863 | 3.01% | 8.8x | 0.107% | STOP | **-9.6%** | -0.283% |
| okx | SATS-EUR | 0.867 | 3.05% | 5.9x | 0.129% | STOP | -6.1% | -0.210% |
| kraken | QUID-USD | 0.903 | 4.75% | 6.3x | 0.057% | STOP | -5.7% | -0.200% |
| bitget | RSOXS-USDT | 0.885 | 3.82% | 4.3x | 0.017% | STOP | -4.4% | -0.200% |
| bitget | RSOXS-USDT | 0.893 | 3.13% | 4.5x | 0.033% | STOP | -4.2% | -0.033% |
| bitvavo | NIL-EUR | 0.910 | 3.42% | **72.6x** | 0.033% | STOP | -4.1% | +0.797% |
| bitvavo | MMT-EUR | 0.886 | 4.89% | **15.2x** | 0.101% | STOP | -3.8% | -0.044% |

**Patroon in de ergste drawdowns:**
- UAI-USDT (Bitget): -9.6% worst_dd met best_exit van -0.28% — dit pair is direct na entry geïmplodeerd
- NIL-EUR (Bitvavo): 72.6x volume ratio → extreme pump/dump, score 0.91 maar -4.1% drawdown
- Bitvavo NIL en MMT: extreme volume ratios zijn prominent in de top-drawdowns

---

## Samenvatting & aanbevelingen voor gebruik

### Wat klopt niet in deze periode

1. **Stop-first verdubbeld (34.6%):** De service signaleert in dalende markten alsof het een stijgende markt is. Aug 3–4 tonen dit het scherpst.
2. **Hogere score = meer stops:** De 0.85+ buckets hebben stop-first rates van 45–46%. Dit is een inversie die suggereert dat de scorer blow-off tops promoted.
3. **Stop-verliezen dieper dan model:** Werkelijke stop-drawdowns zijn -3.5% tot -4.5%, niet -2.0%. Het EV-model flattert de werkelijkheid.

### Wat bruikbaar is (voorzichtig)

| filter | bevinding | n |
|---|---|---|
| Score 0.80–0.85 | Enige positieve EV bucket (+0.102%) | 15 |
| Volume 3–5x | Beste volume bucket (-0.264%, 50% TP) | 12 |
| Breadth >=60% | Laagste stop-first (15.4%), -0.150% EV | 13 |
| Regime >=0 | Stop-first 16.7% in bull zone | 6 |
| Gecombineerd (regime≥0 + score<0.85 + breadth≥45) | 50% TP, 0% stop, **+0.285% EV** | 8 |

### Concrete filter-aanpassingen voor volgende config versie

1. **Score: gebruik 0.80–0.85 venster, niet >=0.85.** Verhoog min_score naar 0.80 maar voeg ook een max_score van 0.85 toe. Alternatief: verlaag min_score naar 0.80 en filter de hogere scores niet actief maar monitor het effect.

2. **Market breadth filter (nieuw):** Voeg filter toe: `market_breadth_15m >= 45` of liever `>= 60`. Dit zou de Aug 3-4 ramp grotendeels hebben voorkomen.

3. **Regime filter (nieuw):** Voeg filter toe: `market_regime_at_signal >= -0.1` (sluit de mild-bear zone uit). Dit elimineert de 17 signalen met 41.2% stop-first.

4. **Volume cap:** Overweeg hard cap op `volume_ratio <= 15x` — extreme volumes (72.6x, 144.5x in OKX) zijn consistent de slechtste setups.

5. **TOO_LATE drempel review:** TOO_LATE-moves presteren beter dan BUY_NOW in deze periode. Overweeg de Δ15m drempel voor TOO_LATE te verhogen (minder agressief blokkeren).

### Wanneer is de data bruikbaar voor live trading?

De huidige 52 outcomes zijn **niet voldoende** voor live deployment met de huidige configuratie. Redenen:
- Negatief EV in totaal
- Slechts 8 rows in de meest belovende gefilterde subset
- Sterke regime-afhankelijkheid (Aug 3–4 vs Jul 30, Aug 1)

**Vereiste voor live gebruik:** Minimaal 150 outcomes in de gecombineerde filter-subset (regime≥0 + breadth≥45 + score 0.80–0.85). Met de huidige signaalfrequentie (~7/dag) en een hit-rate voor die filters van ~15%, duurt dat 2–3 maanden. Alternatief: verhoog de signaalfrequentie door de Δ15m drempel lichtelijk te verlagen.

### Volgende rapport aanraden op

Na ≥ 100 nieuwe BUY_NOW outcomes (verwacht: eind augustus 2026), of eerder als de config versie wordt gewijzigd.
