# Gerichte Hummingbot-implementatie — 2026-11-02

## Samenvatting

De drie gevraagde fasen zijn geïmplementeerd zonder live bot-, order-, YAML- of
databasemutaties en zonder brede upstreammerge:

1. ambigue orderplaatsing blijft gevolgd en wordt via Bitget `clientOid` of
   Kraken `userref` gereconcilieerd;
2. Bitget Spot ondersteunt `LIMIT_MAKER` met `force="post_only"`, terwijl de
   actieve configuratie op `use_post_only_orders: false` blijft;
3. een afzonderlijk offline FIFO-ledger en conservatieve candle-replay leveren
   currency-safe realized/unrealized P&L en deterministische golden tests.

De live custom `GridExecutor`, entry-/exitregels, sizing, risk limits en actieve
YAML-parameters zijn niet gewijzigd. Er zijn geen dependencies toegevoegd.

## A. Ghost-orderveiligheid

### Root cause

De lokale `ExchangePyBase._create_order` riep bij `asyncio.CancelledError`
`_on_order_failure()` aan. Daarmee ging een al vóór de netwerkcall aangemaakt
`InFlightOrder` van `PENDING_CREATE` naar `FAILED`, ook als de exchange het
request mogelijk al had geaccepteerd. `ClientOrderTracker` verwijdert een failed
order uit de actieve tracking. Een laat WebSocket-/REST-event kon daardoor een
live exchangeorder missen en de strategie kon een vervangingsorder plaatsen.

Een lokale coroutine-cancel of timeout bevat geen bewijs over exchangeacceptatie.
Een expliciete API-rejectie, lokale validatiefout of herhaald bevestigd
"not found" bevat dat bewijs wel.

### Wijzigingen

- `CancelledError` wordt opnieuw opgegooid om normale asyncio-cancellation te
  behouden, maar het order blijft `PENDING_CREATE`.
- Een placement-`TimeoutError` laat het order eveneens `PENDING_CREATE`.
- Tijdelijke status-/REST-fouten verhogen voor Bitget en Kraken de not-found-
  teller niet.
- Alleen connectorantwoorden die als echt not-found worden geclassificeerd,
  gebruiken de bestaande begrensde `lost_order_count_limit`.
- Andere connectors behouden via een opt-in capability hun bestaande
  lost-orderbeleid; de nieuwe statusfoutsemantiek is dus beperkt tot Bitget en
  Kraken.
- `PENDING_CREATE` blijft in `tracking_states` aanwezig en wordt na restart
  hersteld.

### State transitions

| Gebeurtenis | Nieuwe toestand/actie |
|---|---|
| Lokale validatiefout vóór verzending | `FAILED`; geen exchangeacceptatie mogelijk. |
| Expliciete exchange-rejectie | `FAILED`. |
| Create-taak geannuleerd | `PENDING_CREATE`; cancellation wordt doorgegeven. |
| Create-timeout | `PENDING_CREATE`; statuspolling reconcileert. |
| Tijdelijke status-/REST-fout | Blijft actief; waarschuwing, volgende pollingcyclus. |
| Herhaald bevestigd not-found | Bestaande begrensde lost-orderflow naar `FAILED`/lost. |
| Late acceptatie | Exchange-ID wordt op hetzelfde clientorder gezet; `OPEN`. |
| Late partial fill | Trade-ID idempotent verwerkt; `PARTIALLY_FILLED`. |
| Late volledige fill | Exacte fills/fees verwerkt; `FILLED`. |
| Exchangecancel/post-only-cancel | `CANCELED`; partial fills blijven bewaard. |

### Bitget-reconciliatie

Bitget [Get Order Info](https://www.bitget.com/docs/catalog/classic-spot-trade/classic-spot-trade)
wordt al met `clientOid` bevraagd. Het antwoord levert nu ook
het ontbrekende `orderId` aan de `OrderUpdate`, zodat een order waarvan de
create-response verloren ging volledig wordt hersteld. Order-, fill- en REST-
events blijven door `tradeId` gededupliceerd.

### Kraken-reconciliatie

Kraken gebruikt de numerieke Hummingbot clientorder-ID als `userref`:

1. zonder txid: query `OpenOrders(userref)`;
2. niet open: query `ClosedOrders(userref)`;
3. gevonden: herstel txid en status;
4. gekoppelde trade-ID's worden via `QueryTrades` opgehaald en inclusief exacte
   quote-fee verwerkt vóór een terminale status tracking beëindigt;
5. beide gezonde queries leeg: bevestigd not-found en de begrensde teller mag
   oplopen.

De officiële Kraken-specificaties ondersteunen filtering op `userref` voor
[OpenOrders](https://docs.kraken.com/api/docs/rest-api/get-open-orders) en
[ClosedOrders](https://docs.kraken.com/api/docs/rest-api/get-closed-orders).

`ClosedOrders` is aan Kraken's private endpoint-throttling toegevoegd. Netwerk-
of authenticatiefouten zijn geen not-foundbewijs.

### Reconciliation, retries en alerts

Iedere connectorrequest blijft begrensd door de bestaande requesttimeout en
connectorretry. Kraken gebruikt maximaal vijf API-pogingen met bestaande
backoff. Onzekere orders blijven vervolgens door de normale statuspolling
gereconcilieerd en produceren waarschuwingen. Bevestigd not-found gebruikt de
bestaande limiet van vier waarnemingen (`lost_order_count_limit + 1`) voordat
het order lost/failed wordt. Zo is iedere requestreeks bounded, terwijl een
onzekere exchange-uitkomst niet door tijdsverloop alleen als failure eindigt.

### Resterende risico's

- Een langdurige exchange-outage kan een `PENDING_CREATE` lang actief houden.
  Dit is bewust fail-closed voor nieuwe vervangingsorders en vereist monitoring.
- Kraken ClosedOrders retourneert een begrensde recente historie. De poller moet
  dus tijdig herstellen; de lokale persistente clientorder-ID blijft essentieel.
- Niet-onderzochte connectors behouden hun oude statusfoutbeleid.
- Een hard procesverlies vóór de eerstvolgende recorderpersist kan nooit alleen
  door in-memory tracking worden opgelost; startup-open-orderreconciliatie blijft
  noodzakelijk.

## B. Bitget post-only

### Connectorwijzigingen

De spotdelen van upstream-commit `950303ceaa` zijn gericht overgenomen:

- `POST_ONLY_TIME_IN_FORCE = "post_only"`;
- `OrderType.LIMIT_MAKER` mappt naar Bitget `orderType="limit"`;
- `supported_order_types()` bevat `LIMIT_MAKER`;
- `LIMIT_MAKER` verstuurt `force="post_only"`;
- gewone `LIMIT` blijft `force="gtc"`;
- `MARKET` is ongewijzigd.

### Lifecycle

Een marketable post-only order wordt als normale exchangecancel verwerkt, niet
als placement failure. Een partial fill gevolgd door cancel bewaart executed
base, quote en fee. Feehoeveelheid en feevaluta komen uit Bitgets payload; de
connector veronderstelt geen makerfee. Gelijke REST- en WebSocketfills worden op
trade-ID eenmaal geboekt.

De connector plaatst na een cancel zelf geen order. De bestaande GridExecutor-
guards bepalen of en wanneer een level opnieuw beschikbaar is en voorkomen
parallelle duplicaten. Die cancel-, zombie- en partial-fillguards zijn in de
relevante regressiesuite meegenomen.

### Productiestatus

`multi_coin_grid_pro/spot_bitget/config/spot_grid_bitget.yaml` is niet gewijzigd
en bevat nog `use_post_only_orders: false`. De capability is dus beschikbaar,
maar niet actief. De bestaande comment in dat YAML-bestand zegt nog dat de
connector `LIMIT_MAKER` mist; het bestand is bewust volledig ongemoeid gelaten
omdat het een actieve tradingconfiguratie is.

Verwacht effect na een latere expliciete activering: minder takerfills, maar
waarschijnlijk meer cancels en mogelijk een lagere fillrate. Er is geen bewijs
voor hogere winstgevendheid.

## C. Backtesting en P&L

### Architectuur

`multi_coin_grid_pro/backtesting` is een pure offline laag zonder connector- of
live-executorcalls:

- `ledger.py`: immutable fillinputs, FIFO inventorylots, realized matches,
  equitycurve en rapportagemetrics;
- `replay.py`: niveau-A candle-replay van vooraf berekende orderintents;
- de custom live `GridExecutor` is niet gewijzigd of vervangen;
- de oude smoke-testengine blijft compatibel, maar verwijst voor financieel
  onderzoek naar de nieuwe laag.

### P&L-contract

FIFO is gekozen omdat gridlots en partial sells daarmee deterministisch blijven
en de resterende kostprijs rechtstreeks herleidbaar is.

```text
equity = quote_cash + base_inventory * mark_price

realized_gross = matched_sell_proceeds - matched_buy_cost
realized_net = realized_gross - allocated_entry_fees - exit_fees

unrealized_gross = inventory_mark_value - remaining_cost_basis
unrealized_net = unrealized_gross - remaining_entry_fees - estimated_exit_cost

actual_total_net = equity - initial_cash
projected_total_net = realized_net + unrealized_net
```

Werkelijke fees beïnvloeden cash/inventory exact eenmaal. Geschatte toekomstige
exitfee/slippage staan apart, wijzigen cash/equity niet en zitten alleen in
`unrealized_net`/`projected_total_net`.

- BUY-fee in base: ontvangen inventory en resterende bruto kostprijs worden
  verlaagd; de fee wordt tegen fillprijs in quote geregistreerd.
- BUY/SELL-fee in quote: quote-cash daalt direct.
- fee in een derde token: expliciete quote-conversiekoers verplicht.
- duplicate trade-ID: genegeerd en geteld.
- sell boven gevolgde inventory: alleen gevolgde inventory toegerekend, met
  datakwaliteitswaarschuwing.
- handmatige sell: hetzelfde ledger met `source="manual"`.

### Golden fixtures

Deterministische tests dekken:

- volledige BUY/SELL;
- meerdere buys met FIFO-sell;
- partial BUY en SELL;
- BUY-fee in base en SELL-fee in quote;
- post-only-cancel zonder fill;
- partial fill gevolgd door cancel;
- duplicate REST/WebSocket-fill;
- open eindinventory en geschatte exitkosten;
- handmatige en te grote externe sell;
- final-tick-fill;
- nul fills met `win_rate=None`/`profit_factor=None`;
- maker-/takerfeecombinaties;
- research/validation-split en gelijke scenario-inputs.

De legacy test eist nu `num_trades > 0` waar de fixture een uitvoering verwacht;
de eerdere altijd-ware `>= 0`-assertie is verwijderd. De BUY-fee wordt daar nu
in quote berekend en het inzetbare bedrag reserveert de fee.

### Ondersteunde simulatie

Niveau A ondersteunt:

- vooraf berekende grid/orderintents zonder look-ahead;
- limitpenetratie (strikt `<`/`>` standaard, touch alleen is geen fill);
- marketable post-only-cancel;
- expliciete partial-fillfractie en volume-participatie;
- maker/takerfee, spread en marketslippage;
- tick size en min notional;
- open inventory en final-tick-accounting;
- equitycurve, realized/unrealized/net P&L, fee-impact, drawdown, winrate,
  profit factor, fill/open-positioncount, exitreden en waarschuwingen;
- gelijke dataset, kapitaalbasis en kostenmodel voor meerdere scenario's;
- chronologische, niet-overlappende research- en validatieperioden.

Niveau B is niet geïmplementeerd omdat geen echte historische trade-/orderboek-
en latencydataset in scope beschikbaar was. De simulator verzint die data niet.
De candle-uitkomst is daarom geen bewijs dat een makerorder werkelijk gevuld zou
zijn en geen bewijs voor winstgevendheid.

## D. Algemene kwaliteit

### Tests

Gecombineerde relevante suite:

- **216 passed**;
- geen failures;
- 185 bestaande warnings, hoofdzakelijk Pydantic-v2-deprecations in ongewijzigde
  modellen;
- Bitget+Kraken connectorsuite afzonderlijk: **98 passed**;
- eerste nieuwe core/ledgerbatch: **34 passed**.

De gecombineerde suite bevat ClientOrderTracker, core cancellation,
Bitget/Kraken connectortests, late BUY/SELL-fillrecovery, Bitget post-only-
lifecycle, alle backtests en bestaande partial-fill/cancel-, zombie- en stale-
orderguards.

Kwaliteitscontroles:

- `flake8` op alle gewijzigde Pythonbestanden: geslaagd;
- `git diff --check`: geslaagd;
- strategiedocumentatiecheck: geslaagd.

### Gewijzigde productiecode

- `hummingbot/connector/exchange_py_base.py`
- `hummingbot/connector/exchange/bitget/bitget_constants.py`
- `hummingbot/connector/exchange/bitget/bitget_exchange.py`
- `hummingbot/connector/exchange/kraken/kraken_constants.py`
- `hummingbot/connector/exchange/kraken/kraken_exchange.py`
- `hummingbot/connector/exchange/kraken/kraken_utils.py`
- `multi_coin_grid_pro/backtesting/__init__.py`
- `multi_coin_grid_pro/backtesting/ledger.py`
- `multi_coin_grid_pro/backtesting/replay.py`

Daarnaast zijn uitsluitend tests en documentatie aangepast. Geen dependency,
schema, migratie, actieve YAML of database is gewijzigd.

### Gelijktijdige Git-wijziging

Tijdens de implementatie veranderde HEAD buiten deze sessie van
`d111a16f180f` naar `d05374aacfd0` (`feat: add upstream audit report for branch
20251109`). De branch staat daardoor één commit voor op `origin`. De implementatie
is tegen de nieuwe HEAD verdergegaan; er was geen overlapconflict en er is door
deze opdracht niet gecommit, gemerged, gestasht of gepusht.

### Productie-impact

- Een reeds draaiend proces laadt deze bestanden niet vanzelf opnieuw; er is
  geen bot gestart, gestopt of herstart.
- Na een toekomstige operatorrestart verandert de veilige behandeling van
  ambigue Bitget/Kraken-orderplaatsingen.
- Bitget post-only blijft inactief door de ongewijzigde configvlag.
- De backtestinglaag is uitsluitend offline.

### Rollback

Er zijn geen data- of schemamigraties terug te draaien. Rollback bestaat uit het
terugdraaien van de genoemde code-, test- en documentatiepatch als één eenheid.
Als alleen Bitget post-only wordt teruggedraaid, moeten constant, ordertypemap,
supported types en payloadtest samen worden verwijderd. Als Kraken-reconciliatie
wordt teruggedraaid, moeten ClosedOrders-endpoint, throttlerregel, recoverycode en
tests samen worden verwijderd. Laat de actieve YAML-vlag in alle gevallen uit.

## E. Aanbevelingen

### Klaar voor review/merge

- Core `CancelledError`/timeout-tracking en de connectorbegrensde
  not-foundclassificatie.
- Bitget `LIMIT_MAKER` capability met config uit.
- Offline FIFO-ledger en niveau-A replay als onderzoeksinfrastructuur.

### Vereist verdere validatie

- Kraken OpenOrders/ClosedOrders-recovery is volledig gemockt getest, maar nog
  niet tegen Kraken sandbox/live read-only responses gevalideerd.
- Bitget post-only is niet op testnet/paper met echte cancelredenen en fillrate
  gemeten.
- Niveau-A candlefills moeten conservatief worden gekalibreerd tegen echte
  fillhistorie; niveau B vereist eerst betrouwbare historische data.

### Vóór een volgende live deployment

1. Review de diff specifiek op orderstate en Kraken API-permissions/rate limits.
2. Draai dezelfde suites in CI en controleer de bestaande deprecationwarnings.
3. Controleer dat startupreconciliatie alle open Bitget/Kraken-orders toont.
4. Deploy eerst met Bitget `use_post_only_orders: false` en monitor nieuwe
   `PENDING_CREATE`-waarschuwingen en recoveryduur.
5. Activeer post-only alleen in een afzonderlijke expliciete wijziging met
   kleine exposure en metrics voor cancelratio, fillrate, maker/takerfees en
   inventoryverschil.

Geen van deze wijzigingen bewijst of claimt dat de strategie winstgevend is.
