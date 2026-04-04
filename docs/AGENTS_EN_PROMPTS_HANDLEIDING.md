# Agents & Prompts — Handleiding

> Hoe gebruik je de custom Copilot agents en slash-prompts voor je trading bot?

---

## Wat zijn Agents en Prompts?

**Agents** (`@agent-naam`) zijn gespecialiseerde Copilot-modi. Elke agent heeft eigen tools, regels en een vaste focus. Je schakelt ze in door `@agent-naam` te typen in de Copilot chat.

**Prompts** (`/prompt-naam`) zijn voorgebakken opdrachten die automatisch de juiste agent aanroepen met de juiste stappen. Eén slash-commando → compleet resultaat.

---

## Overzicht

| Type | Naam | Wanneer gebruiken |
|------|------|-------------------|
| 🤖 Agent | `@log-analyzer` | Logs bekijken, fouten zoeken, diagnose |
| 🤖 Agent | `@performance` | PnL, trades, statistieken uit database |
| 🤖 Agent | `@config-tuner` | YAML config aanpassen |
| 🤖 Agent | `@planner` | Nieuwe features plannen |
| 🤖 Agent | `@implementer` | Code schrijven/fixen |
| 🤖 Agent | `@reviewer` | Code reviewen |
| 📋 Prompt | `/analyze-bot` | Volledige sessie-analyse |
| 📋 Prompt | `/check-health` | Snelle gezondheidscheck |
| 📋 Prompt | `/performance-report` | Uitgebreid prestatierapport |
| 📋 Prompt | `/tune-filters` | Entry filter analyse + tuning |

---

## Prompts (Slash-Commando's)

### `/check-health`

**Wat:** Snelle traffic-light check — draaien de bots, zijn er errors, stuck orders?

**Gebruik:**
```
/check-health
/check-health kraken-usd
```

**Resultaat:** Per bot een 🟢🟡🔴 status met uitleg bij problemen.

**Wanneer:** Dagelijks als routine-check, of als je twijfelt of alles goed draait.

---

### `/analyze-bot`

**Wat:** Diepe analyse van de laatste N uur — errors, fills, stuck orders, risk pauses, timeline.

**Gebruik:**
```
/analyze-bot kraken-usd 12
/analyze-bot kraken-eur 24
/analyze-bot bitget 6
```

**Resultaat:** Gestructureerd rapport met key findings, trade summary, root cause analyse, en aanbevelingen.

**Wanneer:** Na een nacht draaien, bij vreemde resultaten, of als de bot gestopt is met traden.

---

### `/performance-report`

**Wat:** Prestatierapport uit de SQLite database — PnL per coin, fees, win rates, hold times.

**Gebruik:**
```
/performance-report kraken-usd 7days
/performance-report bitget 30days
/performance-report kraken-eur deze-run
```

**Resultaat:** Per-coin breakdown, top/bottom performers, fee impact, hold time analyse.

**Wanneer:** Wekelijks om te zien welke coins het beste presteren, of voor/na config changes.

---

### `/tune-filters`

**Wat:** Analyseert welke entry filters de meeste trades blokkeren en stelt tuning voor.

**Gebruik:**
```
/tune-filters kraken-usd
/tune-filters bitget
```

**Resultaat:** Ranking van rejection reasons, per-regime breakdown, concrete config-suggesties.

**Wanneer:** Als de bot weinig tradet en je wilt weten waarom, of na marktveranderingen.

---

## Agents (Direct Aanspreken)

### `@log-analyzer` — Log Diagnose

Leest logs, zoekt errors, bouwt timelines, checkt cooldowns.

**Voorbeelden:**
```
@log-analyzer waarom tradt de EUR bot niet meer?
@log-analyzer zijn er stuck orders in de laatste 6 uur?
@log-analyzer wat ging er mis vannacht bij kraken-usd?
@log-analyzer hoeveel fills had de bot vandaag?
```

**Kan:** Logs lezen, grep, SQLite cooldown queries, timeline bouwen.
**Kan niet:** Code aanpassen, bot herstarten.

---

### `@performance` — Trade Statistieken

Queriet de SQLite databases voor PnL, fees, win rates, per-coin stats.

**Voorbeelden:**
```
@performance hoe presteren de trades deze run?
@performance welke coins zijn het meest winstgevend?
@performance wat is mijn totale PnL deze week?
@performance vergelijk FET-USD vs LINK-USD performance
```

**Kan:** SELECT queries op trade databases, berekeningen, tabellen.
**Kan niet:** Data wijzigen, code aanpassen.

---

### `@config-tuner` — Config Aanpassen

Past YAML configuratie veilig aan op basis van analyse of verzoek.

**Voorbeelden:**
```
@config-tuner zet RSI max naar 74 voor kraken-usd
@config-tuner verlaag de no-fill timeout naar 2400 seconden
@config-tuner voeg BONK-USD toe aan de blacklist
@config-tuner pas de entry filters aan op basis van de tune-filters analyse
```

**Kan:** YAML config lezen en aanpassen, safety checks.
**Kan niet:** Code wijzigen, bot herstarten.

**Veiligheidsregels:**
- Wijzigt nooit `paper_trading` zonder bevestiging
- Verhoogt risk limieten nooit >50% in één keer
- Maakt altijd een backup-notitie van de oude waarde

---

### `@planner` — Feature Planning

Plant nieuwe features met risk-first aanpak en testbare stappen.

**Voorbeelden:**
```
@planner plan een trailing stop-loss feature
@planner hoe kan ik multi-exchange support toevoegen?
@planner plan de migratie naar dynamic grid sizing
```

---

### `@implementer` — Code Implementatie

Schrijft code, fixt bugs, voegt tests toe.

**Voorbeelden:**
```
@implementer fix de bug in grid_executor waar stale orders niet gecanceld worden
@implementer voeg een Telegram alert toe bij risk pause
@implementer schrijf unit tests voor de budget allocator
```

---

### `@reviewer` — Code Review

Reviewt code op veiligheid, correctheid en edge cases.

**Voorbeelden:**
```
@reviewer review mijn laatste changes in grid_executor.py
@reviewer check of de stop-loss logica correct is
@reviewer is deze PR veilig om te mergen?
```

---

## Typische Workflows

### Dagelijkse Routine

```
1. /check-health                          ← Draait alles?
2. /performance-report kraken-usd 1day    ← Hoe ging het?
3. (Bij problemen) /analyze-bot kraken-usd 24
```

### Na Slechte Resultaten

```
1. /analyze-bot kraken-usd 24             ← Wat ging er mis?
2. /tune-filters kraken-usd               ← Filteren we te veel/weinig?
3. @config-tuner [pas parameters aan]     ← Config tweaken
```

### Nieuwe Feature Bouwen

```
1. @planner plan [feature beschrijving]
2. @implementer [implementatie stappen]
3. @reviewer review de changes
```

### Debug Sessie

```
1. @log-analyzer [beschrijf het probleem]
2. @performance [check impact op trades]
3. @implementer [fix als het een bug is]
```

---

## Tips

- **Wees specifiek** over welke bot je bedoelt (kraken-usd, kraken-eur, bitget)
- **Geef tijdsperiodes** mee als dat relevant is (6 uur, vandaag, deze week)
- **Combineer agents** — gebruik de output van `@log-analyzer` als input voor `@config-tuner`
- **Prompts zijn sneller** voor standaard taken — gebruik `/check-health` in plaats van handmatig aan `@log-analyzer` te vragen
- **Nederlands of Engels** — beide agents begrijpen beide talen

---

## Bestanden

| Bestand | Locatie |
|---------|---------|
| Agent definities | `.github/agents/*.agent.md` |
| Prompt definities | `.github/prompts/*.prompt.md` |
| Analyse context (log paden, DB locaties) | `.github/analysis-context.md` |
| Copilot basisinstructies | `.github/copilot-instructions.md` |
