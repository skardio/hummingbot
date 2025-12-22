# Quick Start – Bitget Spot Micro-Arb

1) Config check
```
cat multi_coin_grid_pro/spot_microarb_bitget/config/spot_microarb_bitget.yaml
```

2) Start Hummingbot en run script
```
./start
start --script spot_micro_arb_bitget.py
```

3) Optionele env overrides
- `MICRO_ARB_EXCHANGE=bitget` of `bitget_paper_trade`
- `MICRO_ARB_PAPER=true` (voegt `_paper_trade` suffix toe)
- `MICRO_ARB_SYMBOLS=BTC-USDT,ETH-USDT`
- `MICRO_ARB_ORDER_USDT=10`

4) Wat de bot doet
- States: IDLE → WAIT_BUY → WAIT_SELL → IDLE (force-exit bij timeout)
- Maker-only, tick-offset voor queue-priority
- Guards: spread + fees + buffer, depth, 30s-vol, inventory cap
- Timeouts in seconden: buy_timeout=3, max_hold=6, cooldown=5

5) Veilig samen met andere bots
- Eigen script/PID/config-map (`spot_microarb_bitget`)
- Max één actief symbol tegelijk in de state machine
- Kleine order size en korte lifecycle om competitie te vermijden
