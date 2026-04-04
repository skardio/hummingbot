# Review Bundles — Gebruiksaanwijzing

Elke round heeft een eigen `.md` bestand met **prompt + alle bijlagen erin**.
Je hoeft alleen te kopiëren en plakken.

## Stap-voor-stap

### Round 1: Strategy & Profitability
1. Open een **verse** Claude Opus sessie
2. Upload als file attachment: `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
3. Plak de volledige inhoud van `round-1-strategy.md` als bericht
4. Wacht op de review

### Round 2: Architecture & Code Quality
1. Open een **verse** Claude Opus sessie
2. Upload als file attachment: `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
3. Plak de volledige inhoud van `round-2-architecture.md` als bericht
4. Wacht op de review

### Round 3: Risk Management & Safety
1. Open een **verse** Claude Opus sessie
2. Plak de volledige inhoud van `round-3-risk.md` als bericht
3. Geen extra uploads nodig — alles zit erin

### Round 4: Production Readiness & Observability
1. Open een **verse** Claude Opus sessie
2. Plak de volledige inhoud van `round-4-production.md` als bericht
3. Geen extra uploads nodig — alles zit erin

## Bestandsgroottes

| Bestand | Regels | Upload nodig? |
|---------|--------|---------------|
| `round-1-strategy.md` | ~3,583 | + controller (9,182 regels) |
| `round-2-architecture.md` | ~4,742 | + controller (9,182 regels) |
| `round-3-risk.md` | ~2,504 | Nee |
| `round-4-production.md` | ~3,764 | Nee |

## Data verversing

De data snapshot is van **2026-03-08**. Om te verversen:
1. Draai de queries uit `.github/data-snapshot-2026-03-08.md` (sectie "How to regenerate")
2. Maak een nieuw snapshot bestand
3. Regenereer de bundles met de scripts in `/tmp/make_round*.sh`

## Tips
- Gebruik **verse** sessies per round — geen carry-over van eerdere rounds
- R1 is de belangrijkste: als de strategie niet werkt, maakt de rest niet uit
- De reviewer heeft het recht om te zeggen "stop met traden" als de data dat uitwijst
