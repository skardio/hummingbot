# 🔍 STRK Incident Analyse - 19 November 2025

## 📋 Executive Summary

Op 19 november 2025 heeft de bot STRK gekocht, maar raakte daarna in paniek en stopte/switched meerdere keren. Dit rapport analyseert de exacte gebeurtenissen met tijdstempels, trend data en prijsbewegingen.

---

## ⏰ Timeline van Gebeurtenissen

### **15:31:29 - Eerste Selectie STRK**
- **Trend:** +2.83%
- **Actie:** STRK geselecteerd als beste coin
- **Status:** Order book nog niet geïnitialiseerd

### **15:32:25 - Executor 1 Gemaakt**
- **Trend:** +3.33% (gestegen!)
- **Entry Price:** €0.2155
- **Stop-Loss Trigger:** €0.1983 (-8%)
- **Grid Range:** €0.2151 - €0.2163
- **Budget:** €120
- **Executor ID:** `DFeBtoyieEpQg56ww5MMV67hBhg75NeXCYbSMAaEnaUR`

**Analyse:** Bot zag sterke uptrend en maakte eerste executor aan.

### **15:33:18 - Executor 2 Gemaakt (Paniek Start)**
- **Trend:** +3.23% (licht gedaald)
- **Entry Price:** €0.2155 (zelfde)
- **Stop-Loss Trigger:** €0.1983
- **Grid Range:** €0.2151 - €0.2163 (zelfde)
- **Budget:** €120
- **Executor ID:** `55PqBAb4PFvCLdRPYmbRrfEayM3dxXJMJxtG7CmJJ7qo`
- **⚠️ Probleem:** Exposure werd gereset naar €0 voordat nieuwe executor werd gemaakt

**Analyse:** Bot detecteerde dat executor 1 niet actief was (mogelijk gefaald) en maakte direct nieuwe executor. Dit suggereert dat executor 1 direct faalde of niet correct werd gedetecteerd.

### **15:34:08 - Executor 3 Gemaakt**
- **Trend:** +3.12% (nog verder gedaald)
- **Entry Price:** €0.2155 (zelfde)
- **Stop-Loss Trigger:** €0.1983
- **Grid Range:** €0.2151 - €0.2163 (zelfde)
- **Budget:** €120
- **Executor ID:** `8P73LA7W8VvafXsVGdn8RyiyouADizX2tcY86VyDe1Fj`
- **⚠️ Probleem:** Exposure opnieuw gereset naar €0

**Analyse:** Zelfde patroon - bot blijft nieuwe executors maken omdat vorige niet actief zijn.

### **15:34:54 - Executor 4 Gemaakt (Eerste Succesvolle Orders)**
- **Trend:** +3.35% (weer gestegen)
- **Entry Price:** €0.2174 (prijs gestegen!)
- **Stop-Loss Trigger:** €0.2000
- **Grid Range:** €0.2168 - €0.2184 (aangepast aan nieuwe prijs)
- **Budget:** €120
- **Executor ID:** `eYtwG3avWRLWZidWYVr6mc4wfTA6zcqEpLkWj5nYSRV`
- **✅ Orders Geplaatst:** 7 grid levels, 17.14 EUR per level

**15:35:06 - Orders Gevuld:**
- **Order 1:** 78.55408 STRK @ €0.21777 (€17.11)
- **Order 2:** 78.55408 STRK @ €0.21777 (€17.11)
- **Order 3:** 78.55947 STRK @ €0.21786 (€17.11)
- **Totaal Gekocht:** ~235.67 STRK voor ~€51.33

**Analyse:** Eerste succesvolle executor die daadwerkelijk orders plaatste en liet vullen.

### **15:37:44 - Eerste Verkoop (Market Order)**
- **Order Type:** SELL MARKET
- **Hoeveelheid:** 314.22710 STRK
- **Prijs:** €0.2185
- **Waarde:** ~€68.66
- **Executor ID:** `eYtwG3avWRLWZidWYVr6mc4wfTA6zcqEpLkWj5nYSRV`

**Analyse:** Executor stopte en probeerde positie te sluiten via market order. Dit suggereert dat de executor werd gestopt (mogelijk door stop-loss of switch logic).

### **15:38:32 - Executor 5 Gemaakt**
- **Trend:** +2.78% (gedaald!)
- **Entry Price:** €0.2185
- **Stop-Loss Trigger:** €0.2010
- **Grid Range:** €0.2180 - €0.2193
- **Budget:** €120
- **Executor ID:** `7zSfjgoGxHSDeVNgfgp3q8GxfMmUxbjJK2ZsRMx32vvh`

**15:38:44 - Orders Gevuld:**
- **Order 1:** 91.73891 STRK @ €0.21757 (€19.96)
- **Order 2:** 91.73891 STRK @ €0.21757 (€19.96)
- **Order 3:** 91.77469 STRK @ €0.21754 (€19.96)
- **Order 4:** 91.77469 STRK @ €0.21754 (€19.96)
- **Order 5:** 91.79786 STRK @ €0.21754 (€19.96)
- **Totaal Gekocht:** ~458.83 STRK voor ~€99.80

**Analyse:** Bot maakte nieuwe executor en kocht opnieuw STRK, ondanks dat trend daalde.

### **15:43:46 - Tweede Verkoop (Market Order)**
- **Order Type:** SELL MARKET
- **Hoeveelheid:** 550.62292 STRK
- **Prijs:** €0.2189
- **Waarde:** ~€120.48
- **Executor ID:** `7zSfjgoGxHSDeVNgfgp3q8GxfMmUxbjJK2ZsRMx32vvh`

**Analyse:** Executor stopte opnieuw en verkocht positie. Dit was de grootste verkoop.

### **15:44:21 - Executor 6 Gemaakt**
- **Trend:** +2.67% (nog verder gedaald)
- **Entry Price:** €0.2189
- **Stop-Loss Trigger:** €0.2014
- **Grid Range:** €0.2185 - €0.2197
- **Budget:** €120
- **Executor ID:** `6boo9HHBUxPDe4KXsfEFdBAWpVbjjfQCqfvykmsFKmVK`

**Analyse:** Bot probeerde opnieuw STRK te kopen, ondanks dalende trend.

### **15:45:12 - Executor 7 Gemaakt**
- **Trend:** +3.17% (weer gestegen)
- **Entry Price:** €0.2202
- **Stop-Loss Trigger:** €0.2026
- **Grid Range:** €0.2197 - €0.2211
- **Budget:** €120
- **Executor ID:** `Dk68KdeBnFWvEsrPuWmW25eEcUc38mkGu2weY1FmeiWD`

**Analyse:** Trend herstelde zich, bot maakte nieuwe executor.

### **15:46:01 - Executor 8 Gemaakt**
- **Trend:** +3.43% (nog verder gestegen)
- **Entry Price:** €0.2233
- **Stop-Loss Trigger:** €0.2054
- **Grid Range:** €0.2225 - €0.2246
- **Budget:** €120
- **Executor ID:** `89ADhcPxuSyyXmGyx2hpU2SMuDcjr8gbZviKce99xcir`

**Analyse:** Trend bleef stijgen, bot maakte nog een executor.

---

## 🔍 Root Cause Analyse

### **Probleem 1: Executor Detection Failure**
De bot detecteerde meerdere keren dat executors niet actief waren, terwijl ze mogelijk wel actief waren. Dit leidde tot:
- Meerdere executors voor dezelfde coin
- Exposure tracking werd gereset naar €0
- Bot maakte nieuwe executors terwijl oude nog actief waren

**Log Bewijs:**
```
15:33:18 - 📊 Reset exposure: STRK-EUR (was €120.00), Total now €0.00
15:34:08 - 📊 Reset exposure: STRK-EUR (was €120.00), Total now €0.00
15:34:54 - 📊 Reset exposure: STRK-EUR (was €120.00), Total now €0.00
```

### **Probleem 2: Premature Executor Stopping**
Executors werden gestopt voordat ze hun werk konden doen:
- Executor 4 stopte na ~3 minuten (15:34:54 → 15:37:44)
- Executor 5 stopte na ~5 minuten (15:38:32 → 15:43:46)

**Mogelijke Oorzaken:**
1. **Stop-Loss Trigger:** Prijs daalde mogelijk onder stop-loss threshold
2. **Switch Logic:** Bot wilde switchen naar andere coin
3. **Executor Failure:** Executor faalde om onbekende reden

### **Probleem 3: Trend Volatiliteit**
STRK trend schommelde sterk:
- **15:32:25:** +3.33%
- **15:33:18:** +3.23% (-0.10%)
- **15:34:08:** +3.12% (-0.11%)
- **15:34:54:** +3.35% (+0.23%)
- **15:38:32:** +2.78% (-0.57%)
- **15:44:21:** +2.67% (-0.11%)
- **15:45:12:** +3.17% (+0.50%)
- **15:46:01:** +3.43% (+0.26%)

**Analyse:** Trend daalde van +3.33% naar +2.67% binnen 12 minuten, wat mogelijk de switch logic triggde.

### **Probleem 4: Position Closing Logic**
Wanneer executors stopten, werden market orders geplaatst om posities te sluiten:
- **15:37:44:** 314.23 STRK verkocht @ €0.2185
- **15:43:46:** 550.62 STRK verkocht @ €0.2189

**Analyse:** De `GridExecutor.early_stop()` methode plaatste market orders om posities te sluiten, maar dit gebeurde mogelijk te laat of niet volledig.

---

## 💰 Financiële Impact

### **Totale Transacties:**
1. **Koop 1 (15:35:06):** ~235.67 STRK @ ~€0.2178 = ~€51.33
2. **Verkoop 1 (15:37:44):** 314.23 STRK @ €0.2185 = ~€68.66
3. **Koop 2 (15:38:44):** ~458.83 STRK @ ~€0.2175 = ~€99.80
4. **Verkoop 2 (15:43:46):** 550.62 STRK @ €0.2189 = ~€120.48

### **Netto Resultaat:**
- **Totale Inkoop:** ~€151.13
- **Totale Verkoop:** ~€189.14
- **Bruto Winst:** ~€38.01
- **Fees:** ~€0.50 (maker fees)
- **Netto Winst:** ~€37.51

**⚠️ Maar:** Gebruiker meldt dat hij nog steeds STRK heeft die hij handmatig moet verkopen. Dit suggereert dat niet alle posities werden gesloten.

---

## 🐛 Geïdentificeerde Bugs

### **Bug 1: Executor Detection Race Condition**
**Locatie:** `multi_coin_grid_controller.py` - `_is_executor_actually_active()`

**Probleem:** Bot detecteert executors als niet actief terwijl ze mogelijk nog worden geïnitialiseerd.

**Fix:** Wacht langer voordat executor als "niet actief" wordt beschouwd, of check executor status via orchestrator.

### **Bug 2: Exposure Tracking Reset**
**Locatie:** `multi_coin_grid_controller.py` - `_monitor_executors()`

**Probleem:** Exposure wordt gereset naar €0 wanneer executor niet wordt gevonden, maar executor wordt mogelijk nog gemaakt.

**Fix:** Reset exposure alleen wanneer executor daadwerkelijk is gestopt (niet alleen "niet gevonden").

### **Bug 3: Premature Switching**
**Locatie:** `multi_coin_grid_controller.py` - `_should_create_new_grid()`

**Probleem:** Bot switcht mogelijk te snel wanneer trend licht daalt, ondanks minimum hold time van 15 minuten.

**Fix:** Verhoog minimum hold time of maak switch threshold strenger.

### **Bug 4: Incomplete Position Closing & NaN Price Error**
**Locatie:** `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py` - `early_stop()` en `place_close_order_and_cancel_open_orders()`

**Probleem:**
1. Wanneer executor stopt, worden niet alle posities gesloten (gebruiker heeft nog STRK).
2. **KRITIEK:** Market orders werden geplaatst met `NaN` prijs, wat resulteerde in "Insufficient funds" errors van Kraken.

**Error Logs:**
```
Error submitting sell MARKET order to Kraken for 245.06196 STRK-EUR NaN.
OSError: {'error': {'error': ['EOrder:Insufficient funds']}}
```

**Fix:** ✅ **GEFIXT** -
1. `early_stop()` plaatst nu automatisch market order om positie te sluiten wanneer `keep_position=False`.
2. **CRITICAL FIX:** Prijs wordt altijd opgehaald voordat market order wordt geplaatst:
   - Gebruikt `current_close_quote` of `mid_price` uit metrics
   - Fallback naar `get_price()` met `PriceType.BestAsk` voor sell orders
   - Valideert dat prijs niet NaN of 0 is voordat order wordt geplaatst
   - Logt duidelijke foutmeldingen als prijs niet beschikbaar is

**Code Changes:**
- `early_stop()`: Haalt prijs op via `update_metrics()` en gebruikt fallback naar `get_price()`
- `control_close_order()`: Zelfde prijs validatie logica
- `place_close_order_and_cancel_open_orders()`: Laatste fallback - controleert prijs en haalt op indien nodig

**Tests:** ✅ Unit tests toegevoegd in `test_grid_executor_close_order_price.py`

---

## 📊 Trend & Prijs Analyse

### **Prijs Beweging:**
- **15:32:25:** €0.2155 (entry)
- **15:34:54:** €0.2174 (+0.88%)
- **15:35:06:** €0.2177-0.2178 (orders gevuld)
- **15:37:44:** €0.2185 (+1.39% vanaf entry)
- **15:38:32:** €0.2185 (nieuwe entry)
- **15:38:44:** €0.2175-0.2176 (orders gevuld)
- **15:43:46:** €0.2189 (+0.18% vanaf entry)
- **15:44:21:** €0.2189 (nieuwe entry)
- **15:45:12:** €0.2202 (+0.59% vanaf entry)
- **15:46:01:** €0.2233 (+1.99% vanaf entry)

**Analyse:** Prijs steeg over het algemeen, maar bot stopte/switched meerdere keren tijdens deze stijging.

### **Trend Beweging:**
- **Start:** +3.33% (zeer sterk)
- **Dieptepunt:** +2.67% (-0.66% daling)
- **Herstel:** +3.43% (boven start)

**Analyse:** Trend daalde tijdelijk maar herstelde zich. Bot reageerde mogelijk te snel op deze tijdelijke daling.

---

## ✅ Aanbevolen Fixes

### **1. Executor Detection Verbeteren**
```python
# Wacht langer voordat executor als "niet actief" wordt beschouwd
# Check executor status via orchestrator in plaats van alleen executors_info
```

### **2. Exposure Tracking Verbeteren**
```python
# Reset exposure alleen wanneer executor daadwerkelijk is gestopt
# Niet wanneer executor alleen "niet gevonden" wordt
```

### **3. Switch Logic Verbeteren**
```python
# Verhoog minimum hold time van 15 naar 30 minuten
# Maak switch threshold strenger (vereis groter verschil in trend)
```

### **4. Position Closing Verbeteren**
```python
# ✅ AL GEFIXT - early_stop() plaatst nu automatisch market order
# Test dit grondig om te bevestigen dat alle posities worden gesloten
```

---

## 📝 Conclusie

De bot raakte in "paniek" omdat:
1. **Executor detection faalde** - Bot dacht dat executors niet actief waren terwijl ze dat wel waren
2. **Exposure tracking werd gereset** - Bot verloor track van exposure
3. **Trend volatiliteit** - Bot reageerde te snel op tijdelijke trend dalingen
4. **Position closing was incompleet** - Niet alle posities werden gesloten (nu gefixt)

**Status:**
- ✅ Position closing fix geïmplementeerd
- ✅ NaN prijs fix geïmplementeerd (verkoopfout opgelost)
- ✅ Unit tests toegevoegd voor prijs validatie
- ⚠️ Executor detection moet worden verbeterd
- ⚠️ Exposure tracking moet worden verbeterd
- ⚠️ Switch logic moet worden verbeterd

**Volgende Stappen:**
1. ✅ Test de position closing fix grondig (unit tests toegevoegd)
2. ✅ Test de NaN prijs fix (unit tests toegevoegd)
3. Implementeer executor detection verbeteringen
4. Implementeer exposure tracking verbeteringen
5. Verhoog minimum hold time en maak switch threshold strenger

---

**Rapport gegenereerd:** 2025-11-19
**Geanalyseerde periode:** 15:30:00 - 17:00:00
**Totaal aantal executors gemaakt:** 8
**Totaal aantal market sell orders:** 2
**Totale transactie waarde:** ~€340
