# ARBI Analytics — MCP handover & operations guide

**Documentversie:** 1.0
**Peildatum:** 5 november 2026
**Project:** `arbi` / Hummingbot
**Status:** ChatGPT ↔ ARBI MCP-verbinding werkt; database-uitbreiding is **in uitvoering bij Codex**, niet geverifieerd als afgerond.

> **Doel.** ChatGPT moet live, maar uitsluitend read-only, historische Hummingbot-analysedata kunnen onderzoeken zonder telkens SQLite-bestanden te uploaden of Codex-rapporten te kopiëren. De MCP is nadrukkelijk **geen** trading-interface.

## 1. Samenvatting / waar we gebleven zijn

- Hummingbot draait op Linux-server `vmi2785131`; repository `/home/mo/repos/hummingbot`, branch `branch_20251109`.
- De bestaande afzonderlijke MCP-service staat op `/home/mo/arbi-mcp` en biedt Streamable HTTP op `http://127.0.0.1:8765/mcp`. Hij luistert uitsluitend op `127.0.0.1`.
- Officiële OpenAI `tunnel-client` versie `0.0.19` staat in `/home/mo/tunnel-client`. De tunnel is via een **uitgaande** verbinding gekoppeld: geen publieke inbound-poort nodig.
- De ChatGPT-plugin heet **ARBI Analytics**; de tunnel heet **ARBI Hummingbot MCP**.
- Op 5 november is `get_database_overview` **daadwerkelijk vanuit deze ChatGPT-conversatie aangeroepen**, met resultaten uit drie databases. De verbinding werkt dus end-to-end.
- Codex werkt momenteel aan uitbreiding naar meer relevante databronnen. **Die wijzigingen zijn nog niet beoordeeld en de MCP-server is daarvoor nog niet gecontroleerd herstart.**
- De live Bitget-bot, exchange-orders, tradingconfiguraties en live SQLite-data mogen door het MCP-project nooit worden aangepast.

## 2. Architectuur

```text
ChatGPT / ARBI Analytics (custom plugin)
        |
        | OpenAI Secure MCP Tunnel (geauthenticeerde control plane)
        v
OpenAI tunnel-client v0.0.19 op vmi2785131
        |
        | localhost HTTP
        v
http://127.0.0.1:8765/mcp
        |
        v
/home/mo/arbi-mcp (Python MCP-service)
        |
        | alleen vaste, geparameteriseerde SELECT-query's
        | SQLite URI mode=ro + query_only + authorizer + timeouts
        v
/home/mo/repos/hummingbot/data/*.db / *.sqlite (allowlist)
```

**Scheiding:** de API-key van de tunnel-client is een **runtime-authenticatiesleutel**, niet een sleutel waarmee de MCP zelfstandig betaalde OpenAI-modelaanroepen uitvoert. ChatGPT-abonnements- en API-billing zijn gescheiden; eventuele tunnelkosten of gebruikslimieten moeten via het actuele Platform-dashboard worden gecontroleerd. Geen onbewezen belofte van €0.

## 3. Operationele parameters

| Onderdeel | Waarde |
|---|---|
| Linux-host | `vmi2785131` |
| Hummingbot | `/home/mo/repos/hummingbot` |
| Hummingbot-branch | `branch_20251109` |
| MCP-project | `/home/mo/arbi-mcp` |
| MCP-protocol | Streamable HTTP |
| MCP-endpoint | `http://127.0.0.1:8765/mcp` |
| MCP-startscript | `/home/mo/arbi-mcp/scripts/start.sh` |
| MCP-stopscript | `/home/mo/arbi-mcp/scripts/stop.sh` |
| Tunnel-client | `/home/mo/tunnel-client/tunnel-client` |
| Tunnel-clientversie | `0.0.19` (`x86_64` / AMD64) |
| Tunnel-profiel | `arbi` |
| Tunnel-profielbestand | `/home/mo/.config/tunnel-client/arbi.yaml` |
| Tunnel-ID | `tunnel_6aec67e058888191a729707c868ccb96` *(identifier, geen secret)* |
| Runtime-keybestand | `/home/mo/.config/arbi-tunnel/runtime.key` *(geheime inhoud niet delen)* |
| Health URL | `http://127.0.0.1:8080` |
| ChatGPT-plugin | `ARBI Analytics` |

> **Secretbeleid:** zet nooit API-keys, exchange-credentials, tokens, `.env`-waarden of volledige credentialhoudende logs in documentatie, git, chat of screenshots. Eerder per ongeluk gedeelde API-keys moeten worden ingetrokken; gebruik alleen een vervangende sleutel. Controleer dat de runtime-key de benodigde **Tunnels Read + Use**-rechten heeft.

## 4. Wat al end-to-end is bewezen

`./tunnel-client doctor --profile arbi --explain` rapporteerde `RESULT ok`, inclusief juiste tunnel-ID, bereikbare lokale MCP-service, en een toegestane `HTTP 406` bij een MCP-verzoek zonder volledige protocolheaders.

De draaiende tunnel-client logde `poller started`, `tunnel metadata fetched` en `tunnel-client started`.

`curl -fsS http://127.0.0.1:8080/readyz` retourneerde `ready`.

Vervolgens is vanuit ChatGPT `get_database_overview` uitgevoerd en was de respons:

| Databron | Executors | TradeFill | Orders |
|---|---:|---:|---:|
| `spot_grid_bitget` | 1.110 | 4.598 | 10.411 |
| `multi_coin_grid_v2_usd` | 610 | 4.100 | 23.481 |
| `fill_risk_snapshots` | n.v.t. | 330 `FillRiskSnapshot` | 3.128 `PostFillRiskSnapshot` |

**Peilmoment data:** laatste geregistreerde Bitget-fill 4 november 2026, 21:46:19 UTC. Deze aantallen zijn een **momentopname**, geen vaste verwachting. De tool rapporteerde tevens `sqlite_mode=ro`, `query_only=true`, `allowlisted_sources_only=true`.

## 5. Bestaande MCP-tools (bewezen zichtbaar in ChatGPT)

1. `get_database_overview` — toegestane bronnen, tabellen, aantallen en laatste datums.
2. `get_performance_summary` — conservatief gereconcilieerde performance, met afzonderlijke aantallen uitgesloten records.
3. `get_closed_trades` — paginering over beëindigde executors; niet gelijkstellen aan bewezen afgesloten round trips.
4. `get_trade_dossier` — order-/fillinformatie, accountingclassificatie en risicodata per executor.
5. `get_risk_snapshots` — historische fill- en post-fill-risicometingen.
6. `get_entry_analysis` — entryvelden gerelateerd aan **bewezen** gerealiseerde uitkomsten, met datadekkingswaarschuwingen.

**Nog niet bewezen als beschikbaar:** `get_regime_history` en toekomstige tools voor momentum, operationele status of datakwaliteit. Pas na nieuwe tool-discovery en test als afgerond markeren.

## 6. Database-inventaris — 32 bestanden

Inventaris van **30 SQLite-bestanden direct in `data/` en 2 in `data/backup/`**, door de lokale Codex-inventarisatie vastgesteld. Niet alle bestanden mogen automatisch in de MCP-allowlist.

### 6.1 Trading en executors

- `config.hybrid_grid.yaml.sqlite` — Hummingbot-database gekoppeld aan hybrid grid; inhoud eerst classificeren.
- `futures_grid_bitget.sqlite` — Bitget Futures Grid.
- `multi_coin_grid_v2.db`, `multi_coin_grid_v2.sqlite`, `multi_coin_grid_v2_usd.sqlite` — verschillende Multi-Coin Grid-recorders; overlapping/dubbele data niet veronderstellen.
- `spot_grid_bitget.sqlite` — Bitget Spot Grid.
- `spot_grid_kraken_eur.sqlite`, `spot_grid_kraken_usd.sqlite` — Kraken Spot.
- `spot_grid_okx.sqlite` — OKX Spot.
- `spot_micro_arb_bitget.sqlite` — Bitget micro-arbitrage.
- `triangular_arb_native_bitget.sqlite` — Bitget triangular arbitrage.
- `hummingbot_trades.db`, `hummingbot_trades.sqlite`, `trading_data.db` — eigenaar en inhoud valideren; enkele eerder als leeg gerapporteerd.

### 6.2 Risk, regime en operationele status

- `fill_risk_snapshots.db` — fill-/post-fill-risicosnapshots.
- `regime_telemetry.db` — regime-events.
- `cooldowns.db`, `cooldowns_eur.db`, `cooldowns_usd.db` — operationele cooldown-state.
- `entry_prices.db`, `entry_prices_eur.db`, `entry_prices_usd.db` — persistente entryprijzen.
- `monitoring.db` — monitoring.

### 6.3 Accounting, research, labels

- `realised_pnl_ledger.db`, `realised_pnl_ledger_usd.db` — processed/exactly-once register, **geen onafhankelijke FIFO-bron**.
- `trade_labels_eur.db`, `trade_labels_usd.db`, `trade_labels_usdt.db` — analyse- en handelslabels.
- `momentum_signals.sqlite` — momentum-signalen/resultaten.
- `v5_paper_ledger.sqlite` — papertrades, **nooit mengen met live gerealiseerde P&L**.

### 6.4 Historische back-ups (standaard uitsluiten)

- `backup/fill_risk_snapshots_pre_ownership_fix_20260919_114956.db`.
- `backup/multi_coin_grid_v2_backup_20251203_184950.sqlite`.

`-wal` en `-shm` zijn SQLite-sidecars, geen afzonderlijke databases. Laat deze bij actieve databases ongemoeid. Let op: eerder onderzochte trade-databases gebruikten DELETE journaling; risk-/regimedatabases WAL.

## 7. Accountingcontract en onderzoeksbeperkingen

In fase 1 is `SqliteDecimal(8)` met `Decimal` gedecodeerd bij de SQLite-grens (geen dubbele conversie). De MCP gebruikt vier accountingcategorieën:

- `realized`: verkoop en verkrijging van inventory uit bewezen, reconcilieerbare fills, kosten en fees.
- `estimated`: schatting, niet authoritative.
- `unrealized`: open inventory met waarderingsvoorwaarden.
- `unknown_unreconciled`: ontbrekend/onvolledig bewijs of externe handmatige trades zonder herkomst.

Een `FAILED` executor, resterende inventory, ontbrekende fills, third-token-fees zonder conversie of een manual sell zijn **niet automatisch gerealiseerd verlies**. `Executors.net_pnl_quote` is een gerapporteerde executorwaarde, niet universeel een gerealiseerde-P&L-bron.

De read-only validatie van 4 november 2026 vond bij Bitget:

| Status | Aantal executors |
|---|---:|
| `realized` | 4 |
| `estimated` | 453 |
| `unrealized` | 1 |
| `unknown_unreconciled` | 652 |
| **Totaal** | **1.110** |

Van 505 executors met volume waren slechts 4 (`0,79%`) volledig authoritative reconcilieerbaar; gezamenlijke netto-P&L **−0,197723586475 USDT**. Dit is **niet representatief voor de complete strategie**.

Belangrijke resterende vraagstukken:

- 430 van 453 estimated executors hadden een gerapporteerde restwaarde ≤ 0,01 USDT; niet zonder exchange-rule-bewijs als dust afschrijven.
- Partial FIFO-realization voor verkochte inventory, zelfs als de executor nog open inventory heeft.
- Externe/manual sells en inventarisoverdracht tussen executors.
- Base-token BUY-fees: bij vier gecontroleerde executors verschilde opgeslagen executor-P&L ten opzichte van gereconcilieerde P&L met −0,155036168616 USDT; niet generaliseren zonder extra bewijs.
- Multi-SELL-completeness nog niet aangetoond met voldoende echte dossiers.

### Regime-telemetrie

Tijdens de eerdere audit (4 november) werden 4 `RegimeBuyFill` en 2 `RegimeExecutor` records gezien; een afzonderlijk geüpload `regime_telemetry.db`-bestand liet destijds 0 rijen zien. Dat verschil moet als **onopgelost datakwaliteits-/snapshotprobleem** behandeld worden. Regimegegevens zijn event-gebaseerd, geen gegarandeerd doorlopende marktregimehistorie. Kwaliteitsstatus tonen en eventdekking tegen echte BUY-fills verifiëren voordat conclusies volgen.

## 8. Read-only veiligheidscontract

- Gebruik **uitsluitend** een expliciete database-allowlist (geen vrij padargument, geen query over willekeurige bestandsnamen).
- SQLite openen met URI `mode=ro`, `PRAGMA query_only=ON` en een SQLite read-only authorizer.
- Alleen vooraf gedefinieerde geparameteriseerde SELECT-query's; geen vrije SQL in ChatGPT.
- Limieten voor resultaten, paginering, input, databaseconnecties en queryduur.
- Korte transacties zodat readers live writers minimaal hinderen.
- `immutable=1` **niet** gebruiken bij actieve WAL-databases; `-wal` en `-shm` moeten beschikbaar blijven.
- Nooit rechtstreeks authgegevens, exchange-configs, connectorbestanden of ongefilterde logs blootstellen.
- Geen tool die orders plaatst/annuleert, strategieconfiguratie wijzigt, databases schrijft of een proces beheert.
- Oude VS Code `mcp-server-sqlite`-servers zijn **niet read-only** en mogen niet aan ARBI/ChatGPT worden gekoppeld.

## 9. Herstelprocedure na herstart — alleen MCP-laag

### 9.1 Controleer bestaande service (veilig)

```bash
ss -ltnp | grep 8765
ss -ltnp | grep 8080
```

### 9.2 Start MCP-service uitsluitend indien gestopt

```bash
cd /home/mo/arbi-mcp
./scripts/start.sh
ss -ltnp | grep 8765
```

### 9.3 Controleer tunnelprofiel

```bash
cd /home/mo/tunnel-client
CONTROL_PLANE_API_KEY="$(cat ~/.config/arbi-tunnel/runtime.key)" \
  ./tunnel-client doctor --profile arbi --explain
```

**Nooit de terminaluitvoer van een secret-opdracht of een API-key zelf kopiëren.** `doctor` geeft doorgaans metadata en status; controleer de uitvoer vóór delen.

### 9.4 Start tunnel-client alleen als deze niet draait

```bash
cd /home/mo/tunnel-client
CONTROL_PLANE_API_KEY="$(cat ~/.config/arbi-tunnel/runtime.key)" \
  ./tunnel-client run --profile arbi
```

Dit draait op de **voorgrond**: terminal open laten. Voor duurzame supervisie kan later `tunnel-client runtimes connect` of een passende service worden ingericht na separate verificatie. Geen tweede tunnel-client met dezelfde tunnel starten zolang de eerste gezond draait.

### 9.5 Health en ChatGPT-test

In tweede terminal:

```bash
curl -fsS http://127.0.0.1:8080/readyz
```

Verwacht: `ready`. Vervolgens in ChatGPT de bestaande plugin `ARBI Analytics` openen/inschakelen en `get_database_overview` uitvoeren. Pas een succesvolle call vanuit ChatGPT bewijst de gehele keten.

## 10. Na de huidige Codex-implementatie

1. Vraag Codex om **gewijzigde bestanden, nieuwe allowlist, nieuwe tools, testresultaten, uitgesloten bronnen en security-diff** te tonen. Geen tradingcode wijzigen.
2. Controleer dat tests slagen, geen vrije SQL- of schrijftools toegevoegd zijn, de secrets buiten responses blijven en iedere tool dataprovenance en paginalimieten heeft.
3. Controleer of de MCP nog steeds alleen op `127.0.0.1:8765` luistert.
4. Plan een **gecontroleerde herstart van uitsluitend `/home/mo/arbi-mcp`**, niet van de live Hummingbot-bot. Gebruik de bestaande scripts en vermijd wijzigingen aan WAL-bestanden.
5. Controleer opnieuw `doctor`, `readyz` en de ChatGPT-toolregistratie. Mogelijk is plugin-refresh/herkoppeling nodig om toegevoegde tools zichtbaar te maken.
6. Test vanuit ChatGPT `get_database_overview`, `get_regime_history` (indien daadwerkelijk beschikbaar), data quality en een beperkt voorbeeld per nieuwe bron.
7. Documenteer de feitelijk ondersteunde bronnen en toolversies in een update van dit document; beschouw Codex-claims als **nog niet geverifieerd** totdat ChatGPT ze heeft gebruikt.

## 11. Gewenste vervolgvragen aan ChatGPT

- “Toon alle beschikbare ARBI-databronnen, laatste update en kwaliteitsstatus.”
- “Analyseer de laatste 100 Bitget-executors en splits authoritative realized, estimated en unknown.”
- “Vergelijk stop-loss-resultaten met extra BUY-fills, zonder de niet-reconcilieerbare executors als verliezen te tellen.”
- “Bepaal de dekking van regime-events ten opzichte van BUY-fills sinds de implementatiedatum.”
- “Vergelijk resultaten van Bitget en Kraken, maar rapporteer verschillen in fees en datadekking.”

## 12. Referenties

- Officiële client: https://github.com/openai/tunnel-client
- Release: https://github.com/openai/tunnel-client/releases/tag/v0.0.19
- Onboarding: https://github.com/openai/tunnel-client/blob/v0.0.19/docs/onboarding.md
- Tunnelbeheer: https://platform.openai.com/settings/organization/tunnels
- Runtime API-keys: https://platform.openai.com/settings/organization/api-keys
- ChatGPT plugininstellingen: https://chatgpt.com/#settings/Connectors
- MCP README lokaal: `/home/mo/arbi-mcp/README.md`

---

**Handover-principe:** bij een volgende sessie hoeft de gebruiker uitsluitend dit document en de eventuele nieuwe Codex-release-notes te delen. De assistent moet **eerst de verbonden ARBI Analytics-tools proberen**, niet opnieuw om SQLite-uploads, terminalrapporten of een nieuwe MCP-implementatie vragen.
