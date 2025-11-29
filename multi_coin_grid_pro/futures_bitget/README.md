# Bitget Futures Grid (USDT)

Dedicated entrypoint for running the multi-coin grid strategy on `bitget_perpetual`.

## Files

- `scripts/futures_grid_bitget.py` – Hummingbot script entrypoint.
- `multi_coin_grid_pro/futures_bitget/config/futures_grid_bitget.yaml` – isolated futures config.
- `multi_coin_grid_pro/futures_bitget/README.md` – this guide.

## Usage

1. Create/enable Bitget Futures API keys (trade + read + ws) and export them before starting Hummingbot:
   ```bash
   export BITGET_PERPETUAL_API_KEY="..."
   export BITGET_PERPETUAL_SECRET_KEY="..."
   export BITGET_PERPETUAL_PASSPHRASE="..."
   ```

2. Review `multi_coin_grid_pro/futures_bitget/config/futures_grid_bitget.yaml`:
   - `manual_trading_pairs` defaults to a basket of liquid USDT perps.
   - `total_amount_quote` is expressed in USDT.
   - `derivative_leverage` and `position_mode` are futures-specific knobs (default 1x / ONEWAY).

3. Start Hummingbot and run the futures script:
   ```bash
   bin/hummingbot.py
   >>> start --script futures_grid_bitget.py
   ```

The existing spot bot (`multi_coin_grid_v2.py`) remains untouched, so you can run both scripts simultaneously (spot on Kraken, futures on Bitget) in separate Hummingbot instances.
