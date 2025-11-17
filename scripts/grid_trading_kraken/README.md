# Grid Trading on Kraken

Grid trading strategy: plaats orders in een raster tussen twee prijsniveaus en verdien op elke bounce.

## Concept

```
Prijs: €100
┌─────────────────────┐
│ SELL @ €105 (grid 5)│  ← Wil verkopen op bounce omhoog
├─────────────────────┤
│ BUY @ €95 (grid 4) │  ← Wil kopen op dip
├─────────────────────┤
│ BUY @ €85 (grid 3) │  ← Ondersteuning
├─────────────────────┤
│ BUY @ €75 (grid 2) │  ← Sterke ondersteuning
├─────────────────────┤
│ BUY @ €65 (grid 1) │  ← Maximaal risico
└─────────────────────┘
```

Winst: verkoop hoog, koop laag, herhaal!

## Voordelen vs Triangulaire Arbitrage

| Feature | Grid Trading | Triangulaire Arbitrage |
|---------|--------------|----------------------|
| Market beweging nodig | JA (sideways ok) | NEEN (inefficientie nodig) |
| Fees | Laag (maker orders) | Hoog (taker fees 3x) |
| Liquiditeit | Via market movements | Via prisverschillen |
| Risk | Managed (stop loss) | Theoretisch risicoloos |
| Capital efficiency | Hoog (leverage mogelijk) | Laag (3 legs zelf) |

## Setup

### Vereisten

```bash
source ~/.venvs/bot/bin/activate
export KRAKEN_API_KEY="your_key"
export KRAKEN_SECRET_KEY="your_secret"
```

### Config aanpassen

Edit `01_grid_config_eth_usd.yml`:
- `start_price`: Laagste buy order
- `end_price`: Hoogste sell order
- `total_amount_quote`: €100-€1000
- `max_open_orders`: 5-20 orders tegelijk

## Strategie

### EUR/USD Grid (SAFE)
```yaml
start_price: 1.05
end_price: 1.12
total_amount: €100
grid_levels: 8
```
✅ Stabil paar, lage volatiliteit, consistent winsten

### ETH/USD Grid (AGGRESSIVE)
```yaml
start_price: €3400
end_price: €3700
total_amount: €500
grid_levels: 15
```
⚠️ Meer volatiliteit, meer bounces, meer winsten (maar meer risico)

## Files

- `01_grid_config_eth_usd.yml` - ETH/USD grid config
- `02_grid_config_eur_usd.yml` - EUR/USD grid config (safe)
- `03_grid_monitor.py` - Real-time grid monitoring
- `04_grid_executor.py` - Execute grid strategy via HB

## Starten

```bash
# Monitor (zie order status real-time)
python3 03_grid_monitor.py

# Executor (plaats orders)
python3 04_grid_executor.py --pair ETH-USD --config 01_grid_config_eth_usd.yml

# Beide tegelijk
nohup python3 03_grid_monitor.py > logs/grid_monitor.log 2>&1 &
python3 04_grid_executor.py --pair ETH-USD --config 01_grid_config_eth_usd.yml
```

## Logs

- `logs/grid_orders.log` - Order placements
- `logs/grid_fills.log` - Fills en winsten
- `logs/grid_status.log` - Real-time status

## Verwachte Resultaten

```
Capital: €100
Daily winnen: €1-2 (1-2% per dag)
Monthly: €20-40 (20-40%)

Capital: €500
Daily winnen: €5-10 (1-2% per dag)
Monthly: €100-200 (20-40%)
```

## Voorzichtigheid

⚠️ Grid trading kan verlies geven als:
- Grote crash (ineens onder laagste order)
- Trend in 1 richting (geen bounces)
- Fees hoger dan ingesteld

Start KLEIN (€100) en test eerst!
