# Bitget 4-BUY cap en decision-telemetrie

Status op 2026-11-05: **voorbereid, niet geactiveerd**. De live YAML bevat
`max_executed_buy_orders_per_executor: 4`, maar
`buy_cap_activation_timestamp_utc: null`. Daardoor krijgen nieuw aangemaakte
executors nog geen cap. Hummingbot, MCP en de tunnel zijn niet herstart.

## Contract

- Alleen nieuwe `bitget` Spot-executors met `USDT` quote, aangemaakt op of na
  een expliciete UTC-activatietijd, krijgen de limiet.
- De limiet is executor-lifetime: maximaal vier verschillende BUY-order-ID's
  met een positieve execution.
- Een order telt bij zijn eerste positieve partial fill; vervolgpartial fills
  met dezelfde order-ID tellen niet opnieuw.
- Submitted/open orders zonder fill reserveren capaciteit. Daardoor kan de
  executor geen vijfde order submitten terwijl eerdere orders nog in flight zijn.
- Bij herstel van inconsistente/race-state annuleert de executor uitsluitend
  nog niet uitgevoerde BUY-reserveringen via de bestaande cancelroute wanneer
  vier uitgevoerde order-ID's zijn vastgesteld.
- SELL, take-profit, stop-loss, trailing-stop en strengere bestaande
  risicoregels zijn niet veranderd.
- Alle andere connectors/controllers behouden `max_executed_open_orders=None`.

De executor bewaart `executed_open_order_ids` ook in `custom_info`. Dit maakt
reconstructie mogelijk voor een orchestrator die actieve executors herstelt.
De huidige deployment reconstrueert actieve executorobjecten na een volledige
procesrestart echter niet. Daarom mag activatie alleen plaatsvinden wanneer er
geen bestaande Bitget-executors actief zijn; na een restart zijn nieuwe
executor-ID's ook daadwerkelijk nieuwe executors.

## Decision-telemetrie

De generieke writer staat in `observability/decision_telemetry.py`. `emit()`
doet alleen een niet-blokkerende `put_nowait` naar een begrensde queue. Een
daemonworker doet schema- en SQLite-writes, WAL, retentie en health-counters.
Queue-full, ongeldige events en databasefouten beïnvloeden trading niet.

Bitget gebruikt per bot:

`data/trading_decision_telemetry_spot_grid_bitget.db`

Events: `BUY_DECISION_ALLOW`, `BUY_DECISION_BLOCK`, `BUY_ORDER_SUBMITTED`,
`BUY_ORDER_PARTIAL_FILL`, `BUY_ORDER_FILLED`,
`BUY_ORDER_CANCEL_REQUESTED`, `BUY_ORDER_CANCEL_CONFIRMED`,
`BUY_ORDER_CANCEL_FAILED`, `BUY_CAP_REACHED` en `EXECUTOR_EXIT`.

Ontbrekende point-in-time velden blijven SQL `NULL`; er wordt niets achteraf
gereconstrueerd. De regimekoppeling gebruikt de bestaande event-time observer,
die uitsluitend snapshots met `regime_timestamp <= event_timestamp` kiest.
Credentials, API-keys en volledige configpayloads bestaan niet in het schema.

## Gecontroleerde activatie (later, expliciete toestemming vereist)

1. Maak een read-only overzicht van actieve Bitget-executors en wacht tot dit
   nul is. Stop of annuleer niets automatisch.
2. Kies een toekomstige UTC-tijd en zet alleen
   `buy_cap_activation_timestamp_utc` op bijvoorbeeld
   `2030-01-01T00:00:00Z`.
3. Controleer config parsing en de synthetische tests.
4. Restart Hummingbot uitsluitend na expliciete toestemming. Restart MCP/tunnel
   alleen afzonderlijk en na toestemming.
5. Controleer nieuwe executorconfig: cap `4`, configversie
   `bitget-buy-cap-v1`, maximaal vier submitted/reserved order-ID's.
6. Monitor `DecisionTelemetryHealth`, dropped/write failures, cancel failures,
   cap-reached events, SELL-afwikkeling en onverwachte overshoot.

Live experiment is de gekozen validatiemethode; een offline replay is niet
vereist. Start conservatief en vergelijk nieuwe capped executors uitsluitend
met gelijktijdige, duidelijk gescheiden historische referenties.

## Rollback

Zet de activatietijd terug op `null` en restart Hummingbot alleen met expliciete
toestemming. Dit voorkomt de cap voor daarna nieuw aangemaakte executors.
Bestaande in-memory capped executors behouden hun eigen executorconfig tot hun
normale exit; verwijder de limiet niet midden in hun lifecycle. Telemetrie kan
apart met `decision_telemetry_enabled: false` worden uitgezet als de writer
problemen geeft; trading blijft ook bij writer-fouten actief.

## Validatie

Gerichte synthetische tests dekken activatietijd, legacy/default gedrag,
vier reserveringen, blokkeren van de vijfde order, partial-fill-deduplicatie,
cancel-recovery, queue-overflow, idempotentie, SQL-NULLs en database-uitval.
