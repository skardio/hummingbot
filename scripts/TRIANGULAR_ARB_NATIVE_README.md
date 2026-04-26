# Triangular Arb Native (Bitget first, Kraken-ready)

Strategy file: `scripts/triangular_arb_native.py`
Class: `TriangularArbNative`
Config model: `TriangularArbNativeConfig`

## What this is

Native Hummingbot script strategy for triangular arbitrage.

- Runs inside Hummingbot script lifecycle (`on_tick`, order events, balance checks).
- Bitget-first defaults (`connector_name=bitget`, `holding_asset=USDT`).
- Designed for later Kraken by changing connector/routes/holding asset.
- Safe by default: `execute_trades=False`.

## Bitget quick start

Use triples that form a valid cycle from USDT and back:

- `ETH-USDT,ETH-BTC,BTC-USDT`
- `SOL-USDT,SOL-BTC,BTC-USDT`

Recommended initial config:

- `connector_name: bitget`
- `holding_asset: USDT`
- `execute_trades: false`
- `order_amount_in_holding_asset: 20`
- `min_profitability_pct: 0.20`
- `taker_fee_pct: 0.10`

When dry-run behavior looks correct, set:

- `execute_trades: true`

Ready-made profile:

- `conf/scripts/triangular_arb_native_bitget.yml`

## Kraken later

Switch only configuration:

- `connector_name: kraken`
- `holding_asset: USDT`
- `triples_csv`: Kraken-valid routes, e.g. `ETH-USDT,USDT-USD,ETH-USD`
- Tune `taker_fee_pct` to your Kraken fee tier.

Ready-made profile:

- `conf/scripts/triangular_arb_native_kraken.yml`

## Launch examples

Bitget profile:

```bash
python3 bin/hummingbot_quickstart.py --script triangular_arb_native --conf conf/scripts/triangular_arb_native_bitget.yml
```

Kraken profile:

```bash
python3 bin/hummingbot_quickstart.py --script triangular_arb_native --conf conf/scripts/triangular_arb_native_kraken.yml
```

## Notes

- The strategy executes one cycle at a time, leg-by-leg via order completion events.
- Profitability estimate includes fee haircut per leg.
- If `execute_trades=false`, it only logs opportunities above threshold.
- Always validate routes and balances before enabling live execution.
