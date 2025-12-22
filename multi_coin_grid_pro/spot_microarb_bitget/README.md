# Bitget Spot Micro-Arb

Kleine, maker-first micro-arbitrage bot voor Bitget SPOT. Ultra-korte lifecycle (seconden), maximaal één positie tegelijk. Config en script zijn gescheiden van de grid bots.

## Files
- config: `multi_coin_grid_pro/spot_microarb_bitget/config/spot_microarb_bitget.yaml`
- schema: `multi_coin_grid_pro/spot_microarb_bitget/config_schema.py`
- manager: `multi_coin_grid_pro/spot_microarb_bitget/config_manager.py`
- script: `scripts/spot_micro_arb_bitget.py`

## Kernlogica (script)
- States: IDLE → WAIT_BUY → WAIT_SELL → IDLE (force-exit bij timeout)
- Maker-only entries met kleine tick-offset
- Guards: spread, depth, 30s-volatiliteit, inventory cap
- Timeouts in seconden (buy timeout, max hold, cooldown)

## Config snippet
Zie `config/spot_microarb_bitget.yaml` (preset uit de requirements).

## Gebruik
```
./start
hummingbot >>> start --script spot_micro_arb_bitget.py
```
Optionele env overrides:
- `MICRO_ARB_EXCHANGE=bitget` (of `bitget_paper_trade`)
- `MICRO_ARB_PAPER=true` (forceer paper suffix)
- `MICRO_ARB_SYMBOLS=BTC-USDT,ETH-USDT`
- `MICRO_ARB_ORDER_USDT=10`

## Notes
- Geen trend/RSI/grid/rotation; puur spread-edge.
- Houd één symbol tegelijk actief om interne competitie te voorkomen.
