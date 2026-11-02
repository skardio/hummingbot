# Hummingbot upstream-audit — 2026-11-02

## Managementsamenvatting

Deze audit vergelijkt de lokale branch `branch_20251109` met de officiële
Hummingbot-upstream, met `upstream/master` als primaire baseline. De conclusie
is nadrukkelijk **niet** dat een algemene upstream-merge wenselijk is. De lokale
code en upstream zijn sinds 3 november 2025 sterk uiteengelopen: 60 lokale en
1.725 upstream-commits na de merge-base. Bovendien bevat de lokale strategie
substantiële uitbreidingen op executors, orderbeheer, telemetry en
connectorgedrag. Een brede merge of vervanging van kernbestanden heeft daarom
een onaanvaardbaar regressierisico voor een live handelsomgeving.

Er zijn wel vier technisch relevante upstream-ontwikkelingen en één lokale
veiligheidsafwijking die concrete vervolgacties verdienen:

1. **Hoogste veiligheidsprioriteit:** de lokale behandeling van
   `asyncio.CancelledError` tijdens orderplaatsing markeert een order direct als
   mislukt. Dat is niet hetzelfde als bewijs dat de exchange het order heeft
   geweigerd. Een geaccepteerd order kan daardoor uit tracking verdwijnen. De
   huidige upstream behoudt in dit geval tracking. Dit moet gericht worden
   herzien met expliciete exchange-reconciliatie.
2. **Bitget `LIMIT_MAKER`:** upstream-commit
   [`950303ceaa`](https://github.com/hummingbot/hummingbot/commit/950303ceaa2fb830f5d334fe1524a705522ee635)
   is klein en relevant. Hij verstuurt Bitget-spot `post_only`, zodat een
   marketable order door Bitget hoort te worden geannuleerd in plaats van als
   taker te vullen. Dit kan takerfees verminderen, maar ook de fill rate
   verlagen. Gericht overnemen en pas na tests activeren is passend.
3. **Backtesting en P&L:** de nieuwe upstream-engine is veel beter dan de lokale
   vereenvoudigde backtest, vooral voor grid-simulatie, open inventory,
   gedeeltelijke sells en de laatste simulatie-tick. Een volledige vervanging
   van de lokale executor is echter niet compatibel. Selectieve overname van
   accounting- en simulatielogica is kansrijk.
4. **Executorconfiguratie-validatie:** upstream valideert onder meer gridrange,
   stop-lossrichting en positieve orderbedragen. De veiligheidswaarde is reëel,
   maar de validators moeten handmatig rond de lokale modellen worden gebouwd.
5. **AI/MCP:** de officiële Hummingbot MCP is een krachtige control plane en is
   niet read-only. Voor analyse van lokale SQLite-data is een afzonderlijke,
   minimale read-only MCP veiliger en functioneel beter passend.

Voor Kraken is geen upstream-bugfix gevonden die de waargenomen fee-druk of
orderafhandeling verklaart. De twee relevante upstream-commits voegen alleen
dynamische publieke WebSocket-subscripties toe en overlappen met lokale code.
De actuele Kraken-fees en de strategie-edge moeten apart tegen echte fills
worden gevalideerd. Nieuwe connectors zijn interessant voor een latere venue-
evaluatie, maar rechtvaardigen nu geen productie-integratie.

Er zijn tijdens deze audit geen codewijzigingen, tests, handelsacties,
configuratiewijzigingen of commits uitgevoerd. Alleen dit rapport is gemaakt.

## 1. Scope, methode en veiligheidsgrenzen

### 1.1 Onderzochte repositories en referenties

| Onderdeel | Waarde |
|---|---|
| Lokale branch | `branch_20251109` |
| Lokale HEAD bij audit | `d111a16f180f5ba57895e06485a6c9fe5006c735` |
| Lokale HEAD-datum | 2026-11-02 21:17:30 +01:00 |
| `origin` | `https://github.com/skardio/hummingbot` |
| `upstream` | `https://github.com/hummingbot/hummingbot` |
| Officiële default branch | `master`, geverifieerd via remote `HEAD` |
| `upstream/master` | `9af100d6822da7d2d0291a906c730ef172284ee2` |
| `upstream/master`-datum | 2026-09-22 |
| `upstream/development` | `59a0b347f630bb05e393d99a0bc8a5cd3f10f09b` |
| Merge-base lokaal/upstream | `ce97fffcd414dddbc215c68ac02bddb82485a109` |
| Merge-base-datum | 2025-11-03 |
| Divergentie na merge-base | 60 lokale / 1.725 upstream-commits |

De officiële remote-referenties `master` en `development` zijn zonder tags
opgehaald om commits en eindtoestand te kunnen inspecteren. Dat wijzigt alleen
Git-referenties, niet de checkout. `upstream/master` correspondeert met de
v2.17.0-release. `development` is uitsluitend aanvullend gecontroleerd, onder
meer op de gevraagde XT-connector; `master` blijft de vergelijkingsbaseline.

### 1.2 Werkboom en gelijktijdige wijzigingen

Aan het begin van de audit was `data/spot_grid_bitget.sqlite` al gewijzigd. Later
verschenen ook wijzigingen in:

- `.gitignore`;
- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`;
- `multi_coin_grid_pro/utils/trend_calculator.py`.

Deze wijzigingen zijn niet door deze audit gemaakt en zijn volledig buiten de
scope gehouden. Ze kunnen van een gelijktijdig proces of IDE-sessie afkomstig
zijn. Bevindingen over die bestanden zijn gebaseerd op de zichtbare toestand
tijdens de audit en moeten bij implementatie opnieuw tegen de dan geldende
versie worden gecontroleerd.

### 1.3 Niet uitgevoerd

- geen tests, linters of backtests;
- geen Docker-, API- of botstart;
- geen live of paper orders;
- geen SQLite-mutaties;
- geen dependency-installaties of upgrades;
- geen cherry-picks, merges of commits;
- geen wijziging buiten dit rapport.

## 2. Prioriteitsindeling

De bevindingen zijn als volgt geclassificeerd:

| Klasse | Betekenis |
|---|---|
| 1 — bewezen relevant | Concreet aangetroffen veiligheidsprobleem of direct toepasselijke fix met verifieerbare lokale impact. |
| 2 — waarschijnlijk nuttig | Goede technische verbetering, maar effect op deze strategie vereist meting of adapterwerk. |
| 3 — optioneel | Alleen nuttig bij een toekomstige use-case; geen huidige productiebehoefte aangetoond. |
| 4 — irrelevant/risicovol | Geen aantoonbaar voordeel voor de huidige strategie, of migratierisico is groter dan de verwachte waarde. |

## 3. Bitget `LIMIT_MAKER` / post-only

### 3.1 Wat commit `950303ceaa` exact doet

De mergecommit
[`950303ceaa`](https://github.com/hummingbot/hummingbot/commit/950303ceaa2fb830f5d334fe1524a705522ee635)
van 9 juli 2026 raakt zes bestanden voor Bitget spot en perpetual, plus tests.
Voor Bitget spot zijn de functionele wijzigingen klein:

- `OrderType.LIMIT_MAKER` wordt als ondersteund ordertype gepubliceerd;
- het ordertype wordt naar Bitgets API-waarde `limit` gemapt;
- een `LIMIT_MAKER`-order krijgt `force="post_only"`;
- een gewoon limitorder behoudt `force="gtc"`;
- een unit test controleert de exacte post-only payload.

De lokale Bitget-connector ondersteunt nu alleen `LIMIT` en `MARKET` en stuurt
voor limitorders altijd `force="gtc"`. De lokale strategie is daarvan bewust:
de Bitget-configuratie heeft `use_post_only_orders: false`, terwijl de controller
afhankelijk van die vlag `LIMIT_MAKER` of `LIMIT` kiest. Kraken en OKX gebruiken
in de lokale configuratie wel post-only. De commit lost dus een werkelijk
aanwezige connectorbeperking op en is **klasse 1 — bewezen relevant**.

### 3.2 Verwacht exchangegedrag

Volgens de primaire Bitget-documentatie accepteert `force` onder meer `gtc` en
`post_only`. Post-only wordt uitsluitend als maker aan het orderboek toegevoegd.
Als het order bij aankomst onmiddellijk zou matchen, hoort Bitget het te
annuleren met een post-only-cancelreden. Een succesvolle plaatsingsresponse
betekent alleen dat het verzoek is ontvangen; de definitieve status moet via
WebSocket of REST worden bevestigd:

- [Bitget Classic Spot Trade API](https://www.bitget.com/docs/catalog/classic-spot-trade/classic-spot-trade)
- [Bitget enum-documentatie](https://www.bitget.com/docs/uta/enum)
- [Bitget best-practices guide](https://www.bitget.com/docs/uta/best-practices-guide)

Daaruit volgen drie operationele gevallen:

1. **Order kruist bij aankomst:** annulering/reject door de matching engine; geen
   takerfill als Bitget de vlag correct handhaaft.
2. **Order rust eerst in het boek:** latere fills horen makerfills te zijn; het
   order kan gedeeltelijk vullen en daarna actief, geannuleerd of volledig
   gevuld eindigen.
3. **Markt beweegt tijdens requote:** meer post-only-annuleringen en gemiste
   fills zijn waarschijnlijk. De controller moet deze toestand als normale
   orderuitkomst behandelen, niet als connectorfout.

Post-only garandeert dus geen betere P&L. Het verlaagt het risico op takerfees,
maar kan fill rate en inventory turnover verlagen. Voor een grid kan het
economische resultaat alleen met echte fillratio, cancelratio, spread en
maker-/takerfee worden beoordeeld.

### 3.3 Fees, partial fills en statusverwerking

De upstream-commit verandert de algemene fill- en feeverwerking niet. De
Bitget-connector verwerkt:

- `live`, `partially_filled`, `filled` en `cancelled` als orderstatussen;
- order- en fill-WebSocketberichten;
- REST-fallback voor orderstatus en fills;
- `feeDetail.totalFee` en `feeCoin` als werkelijk gerapporteerde flat fee;
- maker- en takerpercentages uit de Bitget-fee-endpoint voor schattingen.

De core ordertracker dedupliceert trades op trade-ID, zodat dezelfde fill via
orderstream, fillstream of REST niet nogmaals hoort te worden geboekt. Een
gedeeltelijke makerfill gevolgd door cancel past in het bestaande model.

Een beperking is dat de connector niet blijvend een expliciete maker/taker-vlag
per fill opslaat. De werkelijk gerapporteerde feehoeveelheid en feevaluta worden
wel bewaard. Daarmee kan de financiële impact worden gereconcilieerd, maar een
maker/taker-audit moet mogelijk uit fee, ordertype of exchange-export worden
afgeleid.

### 3.4 Testdekking en ontbrekende scenario's

De gedeelde connector-tests dekken onder meer ordercreatie, create failure,
cancel, REST-fillfallback, volledig en gedeeltelijk vullen, WebSocket-updates en
lost-orderpaden. De Bitget-commit voegt specifiek een payloadtest toe voor
`post_only`.

Niet overtuigend gedekt zijn:

- een door Bitget geannuleerd marketable post-only order;
- post-only-cancel gevolgd door controller-requote;
- maker/taker-classificatie tegen een echte Bitget-fill;
- meerdere gedeeltelijke fills met verschillende feevaluta;
- races tussen order-, fill- en REST-updates in dit specifieke post-onlypad.

### 3.5 Advies

Neem de spotwijziging handmatig en beperkt over; cherry-pick niet automatisch de
hele mergecommit met perpetual-wijzigingen. Voeg eerst de payload-, status-,
partial-fill-, deduplicatie- en requotetests toe. Laat
`use_post_only_orders: false` staan totdat die tests en een niet-live replay of
paperproef slagen. Meet na latere gecontroleerde activering minimaal:

- post-only-cancelratio;
- maker/takerverdeling en werkelijke fee per fill;
- tijd tot fill en fillratio;
- gemiste gridcycli en netto P&L na fees.

## 4. Kritieke lokale core-afwijking: geannuleerde ordertaak

Dit is geen nieuwe upstream-feature, maar een relevante veiligheidsbevinding uit
de vergelijking. De lokale commit
`d2d4d1d46d50471a9b9b144c53dd8d82068c9da8` voegde aan
`ExchangePyBase` gedrag toe waarbij `asyncio.CancelledError` tijdens
orderplaatsing direct `_on_order_failure` aanroept en daarna de cancel opnieuw
opwerpt. De lokale test noemt dit een ghost-orderfix.

Een geannuleerde coroutine zegt echter alleen dat de lokale taak is afgebroken.
Zij bewijst niet dat het HTTP-verzoek de exchange niet bereikte. Het volgende
scenario blijft mogelijk:

1. de exchange accepteert het order;
2. de lokale taak wordt tijdens netwerkrespons, shutdown of timeout geannuleerd;
3. lokaal wordt het order als failed uit tracking verwijderd;
4. het exchangeorder blijft live of vult zonder normale lokale opvolging.

De huidige upstream laat `CancelledError` doorlopen zonder het order op dat
moment als failed af te boeken. Dat is veiliger zolang onzeker geplaatste orders
later via client-order-ID, open orders en fills worden gereconcilieerd. De lokale
wijziging kan ironisch genoeg juist een niet-getrackt exchangeorder creëren.

Dit is **klasse 1 — bewezen relevante veiligheidsafwijking**. Het advies is niet
om blind één regel terug te draaien, maar om het plaatsingspad als een expliciete
toestandsmachine te behandelen:

- `submission_pending` blijft getrackt bij een ambigue cancel/timeout;
- reconcileer eerst op client-order-ID via orderstatus, open orders en fills;
- markeer pas failed wanneer de exchange afwezigheid overtuigend bevestigt;
- blokkeer dubbele vervangingsorders totdat reconciliatie klaar is;
- test shutdown, timeout vóór verzending, timeout na acceptatie en late fill.

Een upstream-commit uit september 2026 die alleen echte "not found"-fouten als
lost order wilde tellen, is de volgende dag teruggedraaid. De uiteindelijke
`upstream/master` bevat die generieke fix niet. Release-notes en eindboom lopen
hier dus niet volledig gelijk; de gereverte code moet niet alsnog zonder
connector-specifieke foutclassificatie worden overgenomen.

## 5. Backtesting, executor-ledger en P&L

### 5.1 Relevante upstream-ontwikkeling

Sinds de merge-base heeft upstream de Strategy V2-backtesting aanzienlijk
uitgebreid. Belangrijke commits zijn:

| Commit | Datum | Kern |
|---|---:|---|
| [`06fdf380`](https://github.com/hummingbot/hummingbot/commit/06fdf380) | 2026-04-14 | Positie- en fee-accounting behouden. |
| [`6d20f89`](https://github.com/hummingbot/hummingbot/commit/6d20f89) | 2026-04-14 | `BacktestPositionHold` voor open/restposities. |
| [`560f289`](https://github.com/hummingbot/hummingbot/commit/560f289) | 2026-04-14 | Fee-accounting voor Position/DCA gecorrigeerd. |
| [`561b4e47`](https://github.com/hummingbot/hummingbot/commit/561b4e47) | 2026-05-25 | Position-holdberekening verbeterd. |
| [`9485b23`](https://github.com/hummingbot/hummingbot/commit/9485b23) | 2026-06-05 | Verdere P&L-correcties voor position holds. |
| [`5c58dce7ff`](https://github.com/hummingbot/hummingbot/commit/5c58dce7ffc7ac3b2deda66cc560c789d2daded6) | 2026-09-01 | Ook executors die op de laatste tick ontstaan in het eindledger opnemen. |
| [`036f3e17`](https://github.com/hummingbot/hummingbot/commit/036f3e17f34412a83a3ec449101b86746a45bafe) | 2026-09-03 | Final-tick `POSITION_HOLD` via hold-accounting verwerken. |
| [`1067844ce5`](https://github.com/hummingbot/hummingbot/commit/1067844ce5be0f01ff14710a7e1112ccca40f2d0) | 2026-09-06 | Merge van het complete executor-ledger/final-tickwerk en tests. |

Upstream ondersteunt nu onder meer Grid-, Position-, DCA- en OrderExecutor-
simulatie, een apart position-holdledger, P&L-timeseries en een gestructureerd
`BacktestingResult`. Commit `1067844ce5` omvat bovendien tests voor een begrensd
controllerbeeld en final-tick-ledgergedrag.

### 5.2 Waarom de lokale vereenvoudigde backtest niet betrouwbaar is

`multi_coin_grid_pro/tests/backtest/backtest_engine.py` is geen volledige
Strategy V2-simulator. De code noemt zichzelf vereenvoudigd en modelleert niet:

- gridlevels en orderlevenscyclus;
- post-only-annuleringen;
- bid/askspread, queuepositie of latentie;
- partial fills en beschikbare marktvolume;
- realistische coinselectie op trend;
- connectorstatussen en exchange-reconciliatie.

Er zijn daarnaast twee concrete boekhoudproblemen:

1. Bij een buy wordt `amount = capital / price` berekend en vervolgens
   `fee = amount * fee_pct`. Die fee staat daarmee in base units, maar wordt bij
   `amount * price` in quote opgeteld. Dit mengt eenheden. Omdat vrijwel al het
   kapitaal wordt ingezet, kan de berekende kostprijs boven het beschikbare
   kapitaal uitkomen, waardoor buys vaak niet plaatsvinden.
2. Trade-P&L wordt niet ingevuld. De winrate blijft daardoor nul, terwijl een
   test alleen eist dat `num_trades >= 0`. Een backtest zonder trades slaagt dus.

De slotwaarde waardeert lokale posities wel tegen de laatste prijs, maar dat
maakt de overige order- en feeveronderstellingen niet betrouwbaar. Deze engine
mag niet als bewijs voor live winstgevendheid dienen.

### 5.3 Open inventory, gedeeltelijke sells en unrealized P&L upstream

`BacktestPositionHold` nettoert buys en sells incrementeel. Bij een sell wordt
het minimum van verkoophoeveelheid en netto longpositie gematcht. De gerealiseerde
P&L wordt alleen over het gematchte deel berekend; de restpositie blijft open en
wordt bij de eindprijs als unrealized P&L gewaardeerd. Dit is wezenlijk beter dan
alle buys en sells ongeconditioneerd samenvoegen.

De rapportagesemantiek vraagt wel voorzichtigheid:

- headline `net_pnl_quote` bevat executor-P&L plus gerealiseerde
  position-hold-P&L, maar niet automatisch de afzonderlijk gerapporteerde
  unrealized P&L;
- `total_fees_quote` staat apart;
- voor gewone executors is `net_pnl_quote` al fee-netto, zodat nogmaals alle fees
  aftrekken tot dubbeltelling kan leiden;
- position-hold realized/unrealized bedragen zijn in de onderzochte code bruto,
  terwijl position fees apart worden geaccumuleerd;
- de grid-simulator rekent voor actieve inventory al een geschatte entry- én
  exitfee, ook als de exit nog niet werkelijk heeft plaatsgevonden;
- één `trade_cost` modelleert geen afzonderlijke maker- en takerfee per fill.

Daarom moet vóór gebruik één eigen, gedocumenteerd P&L-contract worden gekozen,
bijvoorbeeld:

```text
equity_end = cash_end + inventory_end * mark_price
realized_net = matched_sell_proceeds - matched_buy_cost - realized_fees
unrealized_net = inventory_mark_value - remaining_cost_basis - estimated_exit_cost
total_net = realized_net + unrealized_net
```

De velden uit upstream moeten daarna expliciet naar dit contract worden gemapt;
ze mogen niet alleen op naam worden opgeteld.

### 5.4 De final-tick-fix

Vóór de fix kon de eindrapportage een verouderde controllersnapshot gebruiken.
Een executor die tijdens de laatste simulatie-tick ontstond of stopte, kon
daardoor buiten het eindledger vallen. `5c58dce7ff` verzamelt het volledige
ledger uit actieve simulaties en gestopte executorinformatie. `036f3e17` zorgt
dat een laatste-tick position hold via de juiste accounting loopt. De merge
`1067844ce5` bundelt dit met een begrensd beeld van recent beëindigde executors.

Dit is relevant voor gridstrategieën, omdat een laatste candle nieuwe levels kan
raken en open inventory kan achterlaten. De fix is **klasse 1 voor correcte
backtestrapportage**, maar niet zelfstandig cherry-pickbaar op de oude lokale
engine: hij steunt op eerdere simulator- en datamodelwijzigingen.

### 5.5 Compatibiliteit met de lokale custom executor

Een volledige vervanging is niet verantwoord:

- lokale `GridExecutor` is circa 5.260 regels; upstream circa 958 regels;
- lokaal bestaan extra watchdogs, fill-risicologica, adaptieve timeouts,
  serialisatie en auditinformatie;
- lokaal wordt `custom_info` in executorconfiguratie gebruikt; het huidige
  upstreammodel heeft dat veld niet;
- controller- en databaseverwachtingen zijn daardoor niet uitwisselbaar;
- de huidige upstream dependencyset voegt onder meer venue-specifieke SDK's toe
  die voor dit doel niet nodig zijn.

De veilige route is een afzonderlijke backtestadapter of selectieve handmatige
port van de accounting- en simulatielogica. De live lokale executor blijft dan
onaangeroerd.

### 5.6 Historische data en realisme

OHLCV is voldoende voor een eenvoudige touch-simulatie, maar niet om makerfills
betrouwbaar te reproduceren. Voor een realistische counterfactual zijn minimaal
nodig:

- trades of orderboek/BBO-data met tijdstempel;
- tick size, lot size en minimum notional per historisch moment;
- maker- en takerfee per venue, pair en accounttier;
- latency en cancel/replacevertraging;
- post-only-cancelmodel;
- partial-fillvolume en bij voorkeur een conservatief queuepositiemodel;
- spread en slippage voor taker/nooduitgangen;
- funding waar perpetuals worden getest;
- exchange-outs en ontbrekende dataintervallen.

De upstream grid-simulator gebruikt candle-high/low om levels als geraakt te
beschouwen. Dat is bruikbaar voor snelle scenarioanalyse, maar optimistisch als
fillmodel en onvoldoende voor de term "betrouwbare live-achtige backtest".

BacktestingDataProvider ondersteunt in de onderzochte upstreamtoestand bovendien
geen Kraken als historische bron. Kraken-data moeten dus extern worden
ingelezen of naar het interne formaat worden geconverteerd.

### 5.7 Handmatige/externe sells

Geen upstream-ledger kan een sell reconstrueren die buiten de bot plaatsvond en
niet in de executor- of orderdatabase staat. Voor een correcte lokale audit moet
een exchange trade-export of API-fillhistorie worden gematcht met SQLite op:

- exchange trade-ID en order-ID;
- client-order-ID waar beschikbaar;
- connector, pair, side, prijs, hoeveelheid en timestamp;
- feehoeveelheid en feevaluta.

Onverklaarde buys blijven tot die reconciliatie open of "unknown"; ze mogen niet
automatisch als verlies, winst of gesloten positie worden geboekt. Dit is een
vereiste voor betrouwbare P&L, niet alleen een rapportageverbetering.

## 6. Executorconfiguratie-validatie

Merge
[`e925aefc`](https://github.com/hummingbot/hummingbot/commit/e925aefcfa2039ed4cb1ff6fc964b6f91a339270)
van 13 augustus 2026 introduceert gedeelde validators voor executorconfiguraties.
Voor grids voorkomt dit onder meer:

- `start_price >= end_price`;
- een stop-loss aan de winstgevende in plaats van verliezende zijde;
- nul of negatieve orderbedragen;
- ongeldige aantallen levels/orders;
- inconsistente price- en amountvelden.

Dit is **klasse 2 — waarschijnlijk nuttig**, met hoge veiligheidswaarde voor
configuratiefouten. De merge raakt 22 bestanden en de lokale modellen wijken af,
onder meer door `custom_info` en optionele dynamische waarden. Daarom: port de
invarianten als lokale validators en golden tests; neem niet de hele merge over.

## 7. Kraken-connector

### 7.1 Upstreamverschillen sinds de merge-base

Er zijn slechts twee Kraken-specifieke upstream-commits gevonden:

| Commit | Datum | Inhoud |
|---|---:|---|
| [`0899f0c4`](https://github.com/hummingbot/hummingbot/commit/0899f0c4fe21db0e1b01b38faa7997014499cb9f) | authored 2026-01-09, committed 2026-01-19 | Publieke spot orderbook/tradeparen dynamisch subscriben en unsubscriben op een bestaande WebSocket. |
| [`733e4fb8`](https://github.com/hummingbot/hummingbot/commit/733e4fb8db5032cdf2241d615695d3b1529dae06) | 2026-01-12 | Uitgebreide tests voor die dynamische subscripties. |

Er zijn sinds de merge-base geen upstreamwijzigingen aan Kraken-orderstatus,
fills, feeparsing, cancel, balance locking, trading rules, private WebSocket of
REST-retry gevonden. De lokale publieke datasource bevat al eigen dynamische
resubscribe- en unsupported-pairlogica plus QueueFull-afhandeling. De upstream-
wijziging overlapt daarmee en kan conflicteren. Voor een statisch geconfigureerde
spotgrid is geen concrete noodzaak aangetoond. Classificatie: **klasse 3 —
optioneel**.

### 7.2 Wat lokaal al goed wordt afgehandeld

- Kraken post-only wordt via `oflags="post"` verstuurd voor `LIMIT_MAKER`.
- Werkelijke fillfees komen uit Kraken `order_fill["fee"]` en worden als flat
  quote-fee opgeslagen.
- Partial fills worden per trade-ID verwerkt.
- REST-fallback gebruikt QueryTrades; orderstatus gebruikt QueryOrders.
- Private WebSocket verwerkt ownTrades en openOrders.
- Locked balances worden uit open orders bepaald.
- Pairmetadata levert precisie en minimum ordergrootte.
- Lokale nonce- en requestserialisatie per API-key beschermen tegen
  nonceconflicten; upstream heeft deze lokale uitbreiding niet en die moet bij
  elke toekomstige port behouden blijven.

Wel ontbreekt een Kraken-specifieke unit test die exact `oflags="post"` voor
`LIMIT_MAKER` controleert. De gedeelde tests dekken veel status- en fillpaden,
maar zo'n payloadcontract is zinvol bij toekomstig werk.

### 7.3 Feeanalyse

De connector implementeert `_update_trading_fees` niet en gebruikt voor
voorafgaande schattingen statische defaults van ongeveer 0,25% maker en 0,40%
taker. Werkelijke fillfees worden achteraf wel correct uit Krakenberichten
genomen.

De actuele officiële Kraken spot-cryptofees zijn pair- en 30-dagenvolume-
afhankelijk en kunnen op de laagste volumetier hoger zijn dan deze defaults. Op
de tijdens de audit geraadpleegde schedule stonden voor diverse spot-cryptoparen
0,40% maker en 0,80% taker op de eerste tier; stablecoin/FX-pairs kunnen een
ander, symmetrisch schema hebben:

- [Kraken fee schedule](https://www.kraken.com/features/fee-schedule)
- [Kraken: how trading fees work](https://support.kraken.com/articles/201893638-how-trading-fees-work-on-kraken)

Daarom kan de pre-trade winstgevendheidsinschatting te gunstig zijn. Dit is geen
upstreamfix: upstream heeft hetzelfde statische patroon. Valideer het relevante
pair en accounttier tegen de officiële schedule en, belangrijker, tegen echte
fillfees. Kraken-fee-druk kan volledig worden verklaard door normale exchangefees
in combinatie met exits met te weinig bruto edge. Er is geen bewijs gevonden
dat een connectorbug systematisch takerfills of dubbele fees veroorzaakt.

## 8. Officiële Hummingbot MCP versus een lokale read-only MCP

### 8.1 Aard en capabilities van de officiële MCP

De officiële [Hummingbot MCP-documentatie](https://hummingbot.org/mcp/) beschrijft
een MCP-interface bovenop Hummingbot API. De
[tooldocumentatie](https://hummingbot.org/mcp/tools/) omvat portfolio-, order-,
trade-, bot-, executor-, backtest-, gateway-, log- en databasefunctionaliteit.
Het is daarmee een beheer- en handelsinterface, niet alleen een analyticslaag.

Daarnaast is de openbare `hummingbot/mcp`-repository onderzocht op commit
`836f9351d48e5c293eaad3ffa16b55fa7bad1a98` (2026-03-23, versie 1.0.4). Die
snapshot exposeert geconsolideerde tools zoals:

- `setup_connector`;
- `configure_server`;
- `get_portfolio_overview`;
- `set_account_position_mode_and_leverage`;
- `search_history`;
- `get_market_data`;
- `manage_controllers`, `manage_bots` en `manage_executors`;
- DEX-pool- en GeckoTerminalverkenning.

`manage_executors` kan executors creëren en stoppen; `manage_bots` kan bots
deployen, starten, stoppen en configureren; connector-setup verwerkt
credentials. De toolnamen en dekking in de repositorysnapshot wijken deels af
van de actuele documentatie. Die versie-drift moet vóór elk hergebruik opnieuw
worden gecontroleerd.

### 8.2 Securitymodel

De officiële MCP gebruikt Basic Auth richting Hummingbot API en de documentatie
adviseert een privénetwerk/Tailscale. In de onderzochte MCP-repository is geen
read-only rol, fijnmazige RBAC of tool-scopeallowlist aangetroffen. Alleen tools
uit de UI verbergen is geen sterke grens: de achterliggende API-credentials
blijven krachtig.

Voor een lokale productiebot zijn de gevolgen van prompt injection,
modelmisinterpretatie of credentiallek groot: orders, bots, leverage en
connectorcredentials vallen binnen hetzelfde control plane. De officiële MCP is
daarom **klasse 4 voor rechtstreekse read-only productieanalyse**. Hij kan later
wel in een streng geïsoleerde beheeromgeving worden geëvalueerd.

### 8.3 Functionele mismatch met de gewenste SQLite-analyse

De repositorysnapshot kan historische orders en bepaalde posities zoeken, maar
biedt niet de gewenste domeinspecifieke dossiers voor:

- volledige fill/orderlevenscyclus per executor;
- gerealiseerde versus resterende inventory;
- handmatige-sellreconciliatie;
- post-fill snapshots;
- regime- en trendtelemetry;
- datakwaliteits- en orphan-ordercontroles.

Daarvoor is een kleine lokale MCP met vaste queries zowel veiliger als beter
passend.

### 8.4 Aanbevolen read-only ontwerp

Een minimale MCP zou uitsluitend lokale analyse aanbieden:

- database openen met SQLite URI `mode=ro`; gebruik `immutable=1` alleen voor
  een stabiele snapshot/kopie waarbij geen WAL-wijzigingen meer hoeven te worden
  gezien;
- OS-mount en service-account eveneens read-only;
- expliciete allowlist van databasepaden, tabellen en kolommen;
- uitsluitend vaste, geparameteriseerde queries; geen arbitrary SQL-tool;
- row-, tijd- en response-limieten;
- secrets, API-keys en gevoelige configkolommen redigeren;
- elke toolaanroep lokaal auditen;
- geen netwerktoegang en geen exchangecredentials;
- geen order-, bot-, executor-, configuratie- of write-tools.

Zinnige tools zijn bijvoorbeeld:

- lijst runs/executors binnen een periode;
- executor-dossier met orders, fills, fees en statusovergangen;
- realized/unrealized P&L volgens één vast contract;
- unmatched buys en mogelijke externe sells;
- post-fill snapshot en regimecontext;
- datakwaliteitsrapport met ontbrekende of dubbele IDs.

Dit is **klasse 2 — waarschijnlijk nuttig**, mits eerst het P&L-contract en de
reconciliatielogica zonder AI deterministisch zijn getest. AI hoort de uitkomst
te verklaren en onderzoeken, niet de financiële waarheid zelf te definiëren.

### 8.5 Overige AI/observability-upstream

De [v2.17.0 release notes](https://hummingbot.org/release-notes/2.17.0/) noemen
onder meer Condor-agents, performance-historyendpoints en backtestarchivering.
Dat levert ideeën voor observability en offline analyse, maar Condor, Hummingbot
API en MCP zijn afzonderlijke services met live handelsmogelijkheden en extra
operationele afhankelijkheden. Er is nu geen reden om die in de productiebot te
introduceren. Houd AI-analyse offline en read-only.

## 9. Nieuwe en verwijderde connectors

### 9.1 Sinds de merge-base toegevoegd aan `upstream/master`

Spot:

| Connector | Eerste toevoeging | Bronbestanden / testbestanden | Beoordeling |
|---|---:|---:|---|
| Backpack | 2026-01-05 | 9 / 8 | Potentieel relevante CEX voor latere venue-evaluatie; geen huidige noodzaak. |
| Gemini | 2026-02-14 | 9 / 8 | Gevestigde CEX, maar pair/liquiditeit, regio en fees eerst onderzoeken. |
| Lambdaplex | 2025-12-20 | 8 / 5 | Andere custody/netwerkrisico's; geen drop-in vervanger. |
| Lighter | 2026-05-12 | 10 / 7 | DEX/CLOB-specifieke SDK en risico's; niet passend voor een snelle productieport. |

Perpetual:

- Aevo, Architect, Backpack, Decibel, EVEDEX, GRVT, Kalshi, Lighter en Pacifica.

De aanwezigheid van testbestanden toont dat unitdekking bestaat, maar bewijst
geen productievolwassenheid, liquiditeit of operationele geschiktheid voor deze
strategie. De huidige strategie is spotgericht; perpetualconnectors vergroten
scope, leverage-, funding- en liquidatierisico.

### 9.2 XT en connectorverwijderingen

Er is geen officiële XT-connector aangetroffen in `upstream/master` of
`upstream/development`. Er is dus geen upstreammerge om nu te beoordelen.

AscendEX, Cube en Vertex spot zijn in juli 2026 uit upstream verwijderd. Dat is
een waarschuwing tegen venue-afhankelijkheid: connectorbeschikbaarheid en
onderhoud zijn niet permanent.

### 9.3 Advies

Nieuwe connectors zijn **klasse 3 — optioneel**. Backpack en Gemini zijn de
meest logische kandidaten voor een afzonderlijke toekomstige paper-evaluatie,
maar alleen na analyse van pairliquiditeit, spreads, fee tier, accounttoegang,
withdrawal/custody en connector-testnetgedrag. Neem geen connector of brede
dependencyupgrade over voor de huidige Bitget/Kraken-problemen.

Ook de omvangrijke Gateway-refactors zijn voor de huidige CEX-spotgrid niet
relevant en vallen in **klasse 4 — risicovol/irrelevant**.

## 10. Risico- en compatibiliteitsmatrix

| Wijziging | Klasse | Lokale relevantie | Breuk-/migratierisico | Dependencies/data | Testbewijs upstream | Advies |
|---|---:|---|---|---|---|---|
| Bitget `LIMIT_MAKER` `950303ceaa` | 1 | Connector mist post-only; strategie heeft feature uitgeschakeld. | Laag voor connectorcode, middel voor live fill/requotegedrag. | Geen schema of nieuwe dependency. | Payloadunit-test plus gedeelde connector-suite; geen live crossing-test. | Handmatig alleen spotport; standaard uit laten tot gerichte tests slagen. |
| Lokale `CancelledError`-failure versus upstream | 1 | Kan een door exchange geaccepteerd order uit tracking verwijderen. | Middel: raakt kritieke ordertoestanden en shutdowns. | Geen schema/dependency; wel reconciliatielogica. | Lokale test bevestigt huidig gedrag, maar niet ambigue exchangeacceptatie. | Herontwerp als pending + reconcile; hoogste prioriteit. |
| Backtest position/grid/accounting commits apr–jun | 1/2 | Lokale toy-engine heeft eenhedenfout en modelleert gridfills niet. | Hoog bij volledige port; middel in losse adapter. | Historische data en expliciet P&L-contract nodig. | Gerichte upstreamtests voor partial sells, holds en valuation. | Selectief overnemen in afzonderlijke backtestlaag. |
| Final-tick ledger `5c58`, `036f`, `106784` | 1 | Laatste-tick executors/open inventory kunnen rapportage wijzigen. | Hoog als losse cherry-pick op oude engine wegens afhankelijkheden. | Geen productie-DB-migratie; backtestdatamodel wijzigt. | Specifieke final-tick- en ledger-tests. | Logica handmatig porten na basisaccounting, niet mergecommit cherry-picken. |
| Executorvalidators `e925aefc` | 2 | Voorkomt ongeldige grid- en stopconfiguratie. | Middel: lokale config heeft extra/optionele velden. | Geen noodzakelijke dependency; mogelijk configgedrag strenger. | Validator-tests upstream. | Invarianten lokaal implementeren met bestaande modellen. |
| Kraken dynamische subscriptions `0899`, `733e` | 3 | Alleen nuttig bij dynamisch pairuniversum; lokale variant bestaat al. | Middel door overlap met blacklist/queue/resubscribe. | Geen schemawijziging. | Uitgebreide unit-tests. | Niet porten zonder concrete dynamische use-case. |
| Kraken fee-estimator | 2, maar geen upstreamfix | Statische schatting kan actuele tier onderschatten; echte fillfee is wel beschikbaar. | Laag voor analyse, middel voor pre-trade gating. | Actuele pair/accounttierdata nodig. | Geen nieuwe upstreamoplossing. | Los valideren tegen echte fills en officiële fee schedule. |
| Officiële Hummingbot MCP | 4 voor prod-readonly | Te brede live bevoegdheden; mist specifieke SQLite-dossiers. | Hoog security- en operationeel risico. | Hummingbot API, credentials en extra services. | Functionele repo/docs; geen read-only RBAC gevonden. | Niet koppelen aan productiecredentials voor deze use-case. |
| Dedicated read-only SQLite MCP | 2 | Sluit aan op dossiers, P&L en telemetry. | Laag/middel mits harde OS- en querygrenzen. | Alleen lokale read-only data; eerst canoniek ledger. | Nog lokaal te bouwen/testen. | Bouwen na P&L/reconciliatiecontract. |
| Nieuwe connectors / volledige upstreammerge | 3/4 | Geen oplossing voor huidige Bitget/Kraken/backtestproblemen. | Hoog: 1.725 commits, SDK's en lokale custom code. | Brede dependencies en operationele setup. | Connectorunit-tests variëren; geen lokale integratie. | Geen brede merge; alleen toekomstige venue-evaluatie. |

## 11. Maximaal vijf concrete vervolgacties

### Actie 1 — Herstel onzeker orderplaatsingsgedrag

**Prioriteit: P0 / veiligheid.** Vervang het lokale "CancelledError betekent
failed"-contract door pending + exchange-reconciliatie. Maak eerst deterministische
tests voor cancel vóór verzending, cancel na exchangeacceptatie, late response,
late fill, shutdown en vervangingsorder. Portvorm: handmatige lokale wijziging,
geen cherry-pick. Geen live validatie voordat de volledige suite en een
gesimuleerde exchange slagen.

### Actie 2 — Port Bitget spot `LIMIT_MAKER` gericht

**Prioriteit: P1 / fee- en executionkwaliteit.** Neem de relevante constant,
supported-order-type mapping en `force="post_only"` uit `950303ceaa` over, plus
payload- en lifecycle-tests. Voeg expliciete marketable-post-only-cancel,
partial-fill, feevaluta, deduplicatie en controller-requotetests toe. Activeer de
configvlag nog niet tijdens de implementatie. Portvorm: handmatig of een
zorgvuldig uitgesplitste patch, niet de volledige mergecommit.

### Actie 3 — Bouw een betrouwbare afzonderlijke backtest/ledgerlaag

**Prioriteit: P1 / besliskwaliteit.** Definieer eerst één P&L-contract en golden
datasets. Hergebruik daarna selectief de upstreamideeën voor GridSimulator,
PositionHold, partial sells, open-inventory valuation en final-tick ledger. Laat
de custom live `GridExecutor` intact en schrijf adapters. Voeg historische
fees, post-only-cancels, spread, partial fills en conservatieve fillaannames toe.
Reconcileer exchange-export en SQLite zodat handmatige sells zichtbaar worden.
Portvorm: handmatig; de genoemde commits zijn referentie, geen zelfstandige
cherry-picks op deze oude engine.

### Actie 4 — Voeg lokale executorconfiguratie-invarianten toe

**Prioriteit: P2 / preventie.** Vertaal de relevante checks uit `e925aefc` naar
de lokale Pydantic/configmodellen zonder `custom_info` of dynamische velden te
verwijderen. Gebruik tests met geldige bestaande productieconfiguraties en
gerichte ongeldige varianten. Portvorm: handmatig en klein.

### Actie 5 — Bouw daarna een minimale read-only SQLite MCP

**Prioriteit: P2 / observability.** Expose uitsluitend vaste, geparameteriseerde
analyticsqueries boven het geteste canonical ledger. Geen credentials, netwerk,
arbitrary SQL of control-plane-tools. Gebruik filesystem- én SQLite-read-only,
redactie, limieten en auditlogging. Hergebruik eventueel alleen datamodellen of
presentatie-ideeën uit Hummingbot MCP; draai de officiële MCP niet met
productiebevoegdheden voor deze analyse.

## 12. Voorgestelde implementatie- en verificatievolgorde

Deze volgorde is voor een latere, afzonderlijk goedgekeurde implementatiefase:

1. Maak een vaste fixture van geanonimiseerde orders/fills en leg het P&L-contract
   vast voordat code wordt aangepast.
2. Test en herstel eerst de ambigue orderplaatsingsreconciliatie; dit heeft de
   grootste directe veiligheidsimpact.
3. Port Bitget post-only met feature flag standaard uit. Valideer volledig met
   mocks/replay en vervolgens paper/shadow waar mogelijk.
4. Bouw de backtest/ledgeradapter en vergelijk elke scenario-uitkomst handmatig:
   volledige cyclus, partial buy/sell, cancel, open restpositie, fee in base,
   fee in quote, externe sell en laatste tick.
5. Voeg configvalidators toe en draai alle bestaande configfixtures ertegen.
6. Expose pas daarna het canonieke ledger via een read-only MCP.

Een eventuele live proef valt buiten deze audit en vereist een nieuwe expliciete
go/no-go, een zeer beperkte exposure, een vooraf bepaalde kill switch en
monitoring op open orders, maker/takerfees, cancelratio en inventoryverschillen.

## 13. Eindconclusie

De upstream bevat waardevolle, gericht overneembare verbeteringen, maar geen
argument voor een algemene upgrade van deze lokale branch. De Bitget-post-only-
patch is klein en passend; de backtestingverbeteringen zijn inhoudelijk sterk
maar architecturaal verweven; de Krakenwijzigingen lossen het huidige
feeprobleem niet op; en de officiële MCP is te machtig voor een read-only
productieanalyse.

De meest urgente bevinding komt juist uit de lokale afwijking van upstream:
een geannuleerde plaatsingstaak mag niet zonder exchangebewijs tot een failed en
niet langer getrackt order leiden. Los die orderveiligheid eerst op. Daarna zijn
Bitget post-only, een betrouwbaar canonical ledger/backtest, lokale validators
en een streng read-only analytics-MCP een beheerste route naar betere execution,
rapportage en observability zonder de custom strategie door een brede merge in
gevaar te brengen.
