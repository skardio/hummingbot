## Git-beheer — verplichte regel

De gebruiker beheert Git zelf.

Codex mag broncode aanpassen, analyseren en testen, maar mag zonder afzonderlijke expliciete toestemming geen Git-mutaties uitvoeren.

Verboden zonder toestemming:

- git add
- git commit
- git push
- git merge
- git rebase
- git reset
- git checkout / git switch
- git cherry-pick
- branches aanmaken of verwijderen
- tags aanmaken of verwijderen

Read-only Git-commando's zoals git status, git diff, git log en git show zijn toegestaan.

Rapporteer na wijzigingen altijd de aangepaste bestanden, testresultaten en een voorstel voor een commitbericht.

**Stop na de tests. De gebruiker voert de commit en push zelf uit.**

## Projectinstructies in `.github`

De inhoud van `.github/` wordt niet automatisch als algemene Codex-instructie geladen. Lees vóór inhoudelijk repositorywerk `.github/copilot-instructions.md` volledig als algemene projectrichtlijn. Lees daarnaast de volledige taakspecifieke bestanden die van toepassing zijn:

- Trading-code bouwen of wijzigen: `.github/agents/implementer.agent.md` en `.github/agents/reviewer.agent.md`.
- Een wijziging plannen: `.github/agents/planner.agent.md`.
- Logs, incidenten of een draaiende bot analyseren: `.github/agents/log-analyzer.agent.md`.
- Handelsresultaten of P&L analyseren: `.github/agents/performance.agent.md`.
- Tradingconfiguratie beoordelen of wijzigen: `.github/agents/config-tuner.agent.md`.
- User stories, scope of prioriteiten bepalen: `.github/agents/product-owner.agent.md`.
- Log- of databaseonderzoek: `.github/analysis-context.md` voor paden en analysemethoden.
- Een expliciet gevraagde taakprompt: het betreffende bestand in `.github/prompts/`.
- Een strategie-, architectuur-, risico- of productiereview: `.github/review-prompt.md` en alleen de relevante bestanden in `.github/review-bundles/`.
- Werk aan CI, PR-proces of eigenaarschap: de relevante bestanden in `.github/workflows/`, `.github/actions/`, `.github/ISSUE_TEMPLATE/`, `.github/pull_request_template.md` of `.github/CODEOWNERS`.

Lees bij gecombineerde taken alle relevante bestanden. Gebruik hun inhoud als taakspecifieke checklist; controleer feitelijke beweringen tegen de actuele code en data. `.github/data-snapshot-*.md` en oude reviewbundels zijn historische bronnen, geen bewijs van de huidige runtime. Bij conflicten gaan de opdracht van de gebruiker en dit `AGENTS.md` voor. Een bestand in `.github/` geeft op zichzelf geen toestemming om processen, orders, live databases, configuraties of Git te wijzigen.
