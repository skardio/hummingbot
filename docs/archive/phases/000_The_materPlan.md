
Backlog voor Copilot — van retail bot naar institutionelere Hummingbot
PRIORITEIT 1 — Direct geld besparen
1. Re-entry Control Engine

Wat is het:
Een slimme herinstaplaag die voorkomt dat de bot direct opnieuw dezelfde slechte markt koopt na een exit.

Waarom:
Veel verlies komt niet door de eerste trade, maar door de tweede of derde trade in dezelfde verslechterende context.

User story:
Als risk engine wil ik dat de bot per coin en per exit-type een andere cooldown gebruikt, zodat slechte herentries worden voorkomen.

Voorbeeldregels:

Take Profit → 15 min cooldown
Small Loss → 60 min cooldown
Stop Loss → 4 uur cooldown
Trend Exit / Falling Knife Exit → block voor rest van sessie

Acceptance criteria:

Bot bewaart per coin de laatste exit-state
Nieuwe entries op dezelfde coin worden geblokkeerd zolang cooldown actief is
Cooldown hangt af van exit-type, niet van één vaste regel
Logs tonen duidelijk: ENTRY_BLOCKED_REENTRY_COOLDOWN
2. State-Aware Re-entry Machine

Wat is het:
Niet alleen tijd-gebaseerde cooldowns, maar ook marktsituatie meenemen in de beslissing om opnieuw in te stappen.

Waarom:
Een simpele timer is te dom. Een echte desk kijkt naar context: daalt de markt versneld? Is dit al de tweede mislukte cyclus?

User story:
Als strategy controller wil ik dat re-entry afhangt van vorige trade-uitkomst plus huidige marktconditie, zodat de bot niet blind opnieuw instapt.

Voorbeelden van states:

WIN_EXIT
LOSS_EXIT
STOP_EXIT
TREND_EXIT
LOSS_EXIT + ACCELERATING_DROP
2_FAILED_CYCLES_SAME_COIN

Acceptance criteria:

Re-entry gebruikt zowel vorige exit als actuele trend/momentum
Bij 2 mislukte cycli op dezelfde coin → coin lock
Falling momentum kan cooldown verlengen of hard blokkeren
State transitions zijn zichtbaar in logs
3. Daily Coin Kill Switch

Wat is het:
Een veiligheidslaag die een coin uitschakelt zodra die te veel schade aanricht op één dag.

Waarom:
Professionele systemen beschermen kapitaal tegen één coin die in een onhandelbaar regime zit.

User story:
Als portfolio risk manager wil ik per coin een dagelijkse verlieslimiet, zodat één slechte markt geen reeks nieuwe verliezen veroorzaakt.

Voorbeeldregels:

-1R gerealiseerd op coin → halve size
-2R → coin disabled voor rest van de dag

Acceptance criteria:

Dagelijkse PnL wordt per coin bijgehouden
Size vermindert automatisch na eerste verliesdrempel
Coin wordt geblokkeerd na tweede verliesdrempel
Reset op nieuwe dag / sessie
4. Hard Pre-Trade Risk Gateway

Wat is het:
Een centrale poort vóór elke order. Geen trade gaat live zonder risk-goedkeuring.

Waarom:
Dit is het grootste verschil tussen “strategie” en “trading system”.

User story:
Als execution engine wil ik dat elke order eerst door een centrale risk gateway gaat, zodat verboden trades nooit geplaatst worden.

Checks in gateway:

max exposure per coin
max open inventory
max daily drawdown
max spread
max slippage estimate
active cooldown
BTC crash / regime block
liquidity status

Acceptance criteria:

Geen enkele order omzeilt de gateway
Elke rejection heeft een expliciete reden
Risk checks zijn centraal configureerbaar
Logs tonen ORDER_REJECTED_BY_RISK_GATEWAY
5. Trade Quality Filter vóór entry

Wat is het:
Een scoremodel dat bepaalt of een setup überhaupt tradable is.

Waarom:
Niet elke setup met een entry-signaal is een goede trade.

User story:
Als strategy engine wil ik dat elke potentiële trade een quality score krijgt, zodat alleen setups boven een minimumdrempel worden uitgevoerd.

Scorecomponenten:

spread
orderboekdiepte
volatility quality
trend state
fakeout frequency
slippage risk
recent coin performance

Acceptance criteria:

Elke setup krijgt score 0–100
Alleen traden boven bijvoorbeeld 70/100
Subscores worden opgeslagen in logs
Backtests kunnen score-impact tonen
PRIORITEIT 2 — Meer winst per trade
6. Adaptive Grid Width

Wat is het:
Grid-afstanden niet vast zetten, maar aanpassen aan actuele volatiliteit.

Waarom:
Een vaste grid is te smal in wilde markten en te breed in rustige markten.

User story:
Als grid strategy wil ik de grid width aanpassen aan actuele volatiliteit, zodat entries en exits beter passen bij het regime.

Implementatie-idee:
Gebruik ATR of rolling volatility:

hoge volatility → bredere grid
lage volatility → smallere grid

Acceptance criteria:

Grid width verandert dynamisch per coin
Volatility-meting wordt elke X minuten ververst
Logs tonen gebruikte grid width en volatility state
7. Dynamic Profit Taking

Wat is het:
Niet altijd één vaste take profit, maar exits aanpassen aan de kwaliteit van de bounce.

Waarom:
Sterke rebounds vragen ander gedrag dan zwakke dead-cat bounces.

User story:
Als exit engine wil ik winstneming aanpassen aan bounce strength, zodat sterke moves meer opleveren en zwakke moves sneller worden veiliggesteld.

Voorbeeldgedrag:

zwakke bounce → snelle volledige exit
sterke bounce → scale out + runner laten lopen

Acceptance criteria:

Exit engine kent minimaal 2 modi: fast exit / scale out
Bounce strength wordt objectief berekend
Runner-logica is optioneel en configureerbaar
8. Position Sizing op kwaliteit

Wat is het:
Niet elke trade dezelfde grootte geven, maar size koppelen aan setup-kwaliteit.

Waarom:
Kapitaal hoort harder te werken op de beste setups.

User story:
Als sizing engine wil ik trade size laten afhangen van setup quality, zodat A-kwaliteit setups meer kapitaal krijgen en twijfelgevallen minder.

Voorbeeld:

A+ setup → 1.25x
normaal → 1.0x
twijfel → 0.5x

Acceptance criteria:

Size multiplier hangt af van score bucket
Risk caps blijven altijd gelden
Sizing-beslissing wordt gelogd per trade
9. Inventory-Aware Sizing

Wat is het:
Position sizing aanpassen aan bestaande inventory en recente fills.

Waarom:
Professionele bots denken niet alleen in signals, maar ook in inventory risk.

User story:
Als market making engine wil ik size verminderen wanneer inventory scheefloopt, zodat de bot niet steeds verder gemiddeld in dezelfde richting.

Acceptance criteria:

Size daalt naarmate inventory toeneemt
Tweede/derde entry op dezelfde coin is kleiner
Extra buys worden strenger begrensd in downtrend
PRIORITEIT 3 — Institutionele risk-laag
10. Portfolio Exposure Engine

Wat is het:
Een centrale laag die kapitaal verdeelt over coins en risicobuckets.

Waarom:
Vijf altcoins tegelijk kopen is vaak geen diversificatie maar één bet in vermomming.

User story:
Als portfolio allocator wil ik blootstelling per coin, sector en risicocluster begrenzen, zodat correlated losers niet tegelijk het account raken.

Voorbeelden van buckets:

meme beta
alt L1/L2 beta
illiquid small caps
majors

Acceptance criteria:

Elke coin krijgt een risk bucket
Max exposure per bucket is instelbaar
Nieuwe trades worden geweigerd als bucket vol zit
11. Correlation Guard

Wat is het:
Voorkomen dat de bot altcoins blijft kopen terwijl de marktleider hard wegzakt.

Waarom:
Veel alts volgen BTC of de bredere risicosentiment-shift.

User story:
Als risk controller wil ik nieuwe alt entries blokkeren bij sterke BTC-daling of marktbred stress, zodat de bot niet tegen macro momentum in blijft kopen.

Acceptance criteria:

BTC regime wordt apart gemeten
Bij sterke negatieve BTC move → alt-entry block
Block geldt alleen voor nieuwe risk-on entries, niet per se voor exits
12. Liquidity Blacklist Auto Mode

Wat is het:
Coins automatisch uitschakelen wanneer marktkwaliteit te slecht wordt.

Waarom:
Veel bots verliezen geld in coins die technisch tradable lijken maar praktisch onhandelbaar zijn.

User story:
Als execution risk engine wil ik coins automatisch disablen wanneer spread, diepte of slippage te slecht wordt, zodat de bot niet in slechte liquiditeit handelt.

Triggers:

spread > X
orderboek te dun
slippage estimate > Y
volume collapse
teveel fakeouts / failed fills

Acceptance criteria:

Coin krijgt status NORMAL, WARN, BLACKLISTED
Blacklist kan tijdelijk of sessiebreed zijn
Statuswijziging wordt gelogd
13. Per-Coin Daily Exposure Cap

Wat is het:
Niet alleen verlieslimiet, maar ook limiet op hoeveel kapitaal dezelfde coin op één dag mag gebruiken.

Waarom:
Zelfs winstgevende churn kan concentratierisico geven.

User story:
Als allocator wil ik een dagelijkse exposure cap per coin, zodat één asset niet disproportioneel veel account-capitaal opslokt.

Acceptance criteria:

Dagelijkse gross notional per coin wordt bijgehouden
Na bereiken cap geen nieuwe entries meer
Exits mogen altijd doorgaan
PRIORITEIT 4 — Alpha / slimmer worden
14. Learn From Logs Engine

Wat is het:
Elke trade labelen en later analyseren om patronen te ontdekken.

Waarom:
Zonder feedback loop blijft optimalisatie grotendeels giswerk.

User story:
Als analytics engine wil ik alle trades labelen met context en uitkomst, zodat het systeem patronen kan vinden en slechte setups kan blokkeren.

Te loggen velden:

coin
tijdstip
sessie
regime
volatility
spread
reason entry
reason exit
PnL
MFE / MAE
reentry ja/nee

Acceptance criteria:

Elke trade krijgt een volledige context-record
Data is exporteerbaar naar CSV/DB
Minimaal 500 trades bruikbaar voor patroonanalyse
15. Session Edge Detection

Wat is het:
Ontdekken in welke sessies de bot wel of niet presteert.

Waarom:
Sommige bots zijn sterk in chop, zwak rond US open, of juist andersom.

User story:
Als scheduler wil ik per sessie de historische edge kennen, zodat de bot alleen actief is in uren waarin hij aantoonbaar beter presteert.

Acceptance criteria:

Trades worden gelabeld op Asia / EU / US / weekend
Rapport toont PnL, winrate, expectancy per sessie
Slechte sessies kunnen automatisch worden geblokkeerd
16. Meta Ranking Engine

Wat is het:
Coins dagelijks scoren en alleen de beste candidates toelaten.

Waarom:
Niet elke coin verdient vandaag kapitaal.

User story:
Als allocator wil ik coins dagelijks ranken op tradability en edge, zodat alleen de top X coins actief worden verhandeld.

Mogelijke inputs:

liquidity
spread quality
recent performance
volatility stability
fakeout rate
session performance
slippage profile

Acceptance criteria:

Elke coin krijgt een dagscore
Alleen top X of score > threshold mag handelen
Ranking wordt periodiek ververst
17. Session + Coin Auto Block

Wat is het:
Combinatie van sessie- en coininzichten gebruiken om slechte combinaties te blokkeren.

Waarom:
Soms is niet de coin slecht, maar die coin in die sessie.

User story:
Als adaptive system wil ik coins automatisch blokkeren in zwakke sessies, zodat bekende verliespatronen niet blijven terugkomen.

Voorbeeld:
RAVE in EU ochtend → auto block

Acceptance criteria:

Engine ondersteunt coin × sessie combinaties
Pattern wordt pas actief boven minimale steekproefgrootte
Block kan automatisch verlopen na reviewperiode
PRIORITEIT 5 — Quant-grade upgrades
18. Fill Quality Monitor

Wat is het:
Een laag die expected fill vergelijkt met actual fill.

Waarom:
Slechte uitvoering kan een goede strategie kapotmaken.

User story:
Als execution monitor wil ik fill quality meten, zodat ik weet of verliezen uit strategie of uit uitvoering komen.

Te meten:

expected fill
actual fill
slippage
maker/taker ratio
partial fills
adverse move after fill

Acceptance criteria:

Per fill wordt execution quality opgeslagen
Alerts bij verslechterende fillkwaliteit
Rapport per exchange en coin beschikbaar
19. Capital Efficiency Layer

Wat is het:
Kapitaal niet random uitrollen, maar bewust reserveren voor beste kansen.

Waarom:
Institutioneel denken is niet “altijd volledig deployed zijn”.

User story:
Als allocator wil ik kapitaal gericht toewijzen aan beste setups en een reserve aanhouden, zodat ik niet op middelmatige setups vastzit als betere kansen verschijnen.

Acceptance criteria:

Reserve cash percentage instelbaar
Slechte setups krijgen geen allocatie ondanks beschikbaar saldo
Best-scoring setups krijgen voorrang
20. Monte Carlo Risk Test

Wat is het:
Scenario’s simuleren om te zien of de bot overleeft.

Waarom:
Een systeem dat alleen in normale omstandigheden werkt, is niet robuust.

User story:
Als risk engineer wil ik stressscenario’s simuleren, zodat ik weet hoe de bot zich gedraagt bij verliesreeksen en marktverstoring.

Scenario’s:

10 losers op rij
flash crash
spread explosion
latency spike
API lag
fill failures

Acceptance criteria:

Simulaties geven max drawdown en survival metrics
Resultaten tonen welke parameterlagen te agressief zijn
Rapport is reproduceerbaar
21. Execution Quality Dashboard

Wat is het:
Een dashboard voor risk, fills en expectancy.

Waarom:
Zonder zichtbaarheid blijft verbetering traag en reactief.

User story:
Als operator wil ik in één dashboard risk, coin performance, slippage en expectancy zien, zodat ik snel kan ingrijpen en patronen kan herkennen.

Acceptance criteria:

Per coin PnL
per sessie performance
fill quality
blacklist status
cooldown status
risk bucket usage
Wat een echte engineer waarschijnlijk direct zou schrappen
22. Stop Random Smallcap Trading

Wat is het:
Geen kleine illiquide coins meer traden zonder liquidity ranking en hard risk budget.

Waarom:
Small caps hebben vaak slechte execution, hoge slippage en regime-instabiliteit.

User story:
Als portfolio manager wil ik small caps alleen toelaten als ze aan minimale liquiditeits- en kwaliteitseisen voldoen, zodat slechte markten geen verborgen tax worden.

23. Stop Fixed Cooldown for Everything

Wat is het:
Geen universele cooldown meer.

Waarom:
Niet elke exit vertelt hetzelfde verhaal.

User story:
Als risk engine wil ik cooldowns differentiëren per situatie, zodat goede herentries mogelijk blijven en slechte worden geblokkeerd.

24. Stop Fixed Size Every Trade

Wat is het:
Geen identieke stake op elke trade.

Waarom:
Niet elke trade verdient dezelfde allocatie.

User story:
Als sizing engine wil ik size koppelen aan kwaliteit, liquidity en risk, zodat kapitaal efficiënter wordt ingezet.

25. Stop Trading Without Liquidity Ranking

Wat is het:
Geen coin traden zonder minimale liquidity / spread ranking.

Waarom:
Veel edge verdwijnt nog vóór de strategie kans krijgt.

User story:
Als execution controller wil ik dat elke coin een liquidity score heeft voordat hij tradable is.

26. Stop Trading Risky Alts During BTC Dump

Wat is het:
Geen nieuwe alt-long entries in duidelijke marktstress.

Waarom:
Macro drukt vaak alle lagere-beta en illiquide coins mee omlaag.

User story:
Als correlation guard wil ik alt-risk uitschakelen tijdens sterke BTC-zwakte.

27. Reduce Fee-Churn / Overtrading

Wat is het:
Minder micro trades met weinig edge.

Waarom:
Veel systemen sterven aan fees en churn, niet aan één grote fout.

User story:
Als execution optimizer wil ik trades met te kleine verwachte edge blokkeren, zodat fees en churn mijn expectancy niet opeten.

Acceptance criteria:

Minimum net expectancy na fees vereist
Te kleine TP / te hoge fee impact → block
Churn ratio wordt gemeten
