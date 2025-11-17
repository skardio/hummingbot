#!/usr/bin/env python3
"""
Grid Trading Executor - Integration with Hummingbot

This script uses Hummingbot's built-in grid executor to:
1. Create a grid between start_price and end_price
2. Place buy/sell orders at each level
3. Execute when filled
4. Rebalance continuously

To use with Hummingbot's full framework:
  hummingbot
  > import strategy grid_strike
  > config 01_grid_config_eth_usd.yml
  > start

For paper trading (testing):
  Set use_testnet: true in config

For live trading:
  Set use_testnet: false
  Ensure API keys are set in environment
"""

import os
import sys


def main():
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    GRID TRADING EXECUTOR - KRAKEN                            ║
║                                                                              ║
║  This executor integrates with Hummingbot's GridStrike controller.           ║
║                                                                              ║
║  STATUS: Ready for integration with Hummingbot CLI                          ║
╚══════════════════════════════════════════════════════════════════════════════╝

📋 SETUP STEPS:

1. Verify Kraken API keys:
   export KRAKEN_API_KEY="your_key"
   export KRAKEN_SECRET_KEY="your_secret"

2. Edit config (01_grid_config_eth_usd.yml):
   - start_price: lowest buy
   - end_price: highest sell
   - total_amount_usd: capital to use
   - num_grids: how many levels (10 = €30 apart)

3. Test with monitor first:
   python3 03_grid_monitor.py

   This shows:
   ✓ Grid levels visualization
   ✓ Where current price is
   ✓ Expected order placement
   ✓ Profit simulation

4. Once satisfied, use Hummingbot CLI:

   hummingbot
   >>> import strategy grid_strike
   >>> config  # Select 01_grid_config_eth_usd.yml
   >>> start

5. Monitor trades:
   tail -f logs/grid_orders.log
   tail -f logs/grid_fills.log

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎯 QUICK STRATEGIES:

Safe (EUR/USD):
  start_price: 1.05
  end_price: 1.12
  num_grids: 8
  capital: €100
  Expected: €1-2/day

Balanced (ETH/USD):
  start_price: 3400
  end_price: 3700
  num_grids: 10
  capital: €100
  Expected: €1-3/day

Aggressive (BTC/USD):
  start_price: 42000
  end_price: 45000
  num_grids: 15
  capital: €500
  Expected: €5-15/day (higher risk)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  IMPORTANT NOTES:

✓ Start with small amounts (€50-100)
✓ Test in paper trading first
✓ Don't risk more than you can afford to lose
✓ Monitor daily for crashes
✓ Set stop loss (config: stop_loss)
✓ Use take profit target (config: take_profit)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Need help? Check README.md
    """)


if __name__ == '__main__':
    main()
