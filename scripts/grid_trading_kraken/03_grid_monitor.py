#!/usr/bin/env python3
"""
Grid Trading Monitor for Kraken - Real-time order & profit tracking

Shows:
- Current price & grid levels
- Active orders
- Filled orders & profits
- Overall P&L
"""

import asyncio
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

try:
    import ccxt
except ImportError:
    print("ERROR: ccxt not installed. Run: pip install ccxt")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class GridMonitor:
    def __init__(self, config_file='01_grid_config_eth_usd.yml'):
        self.exchange = ccxt.kraken()
        self.trading_pair = "ETH/USD"

        # Load config
        self.config = {
            'start_price': 3400,
            'end_price': 3700,
            'num_grids': 10,
            'total_amount_usd': 100,
            'maker_fee_pct': 0.16,
        }

        self.grid_levels = self._calculate_grid_levels()
        self.filled_orders = []
        self.total_profit = Decimal('0')

        logger.info("=" * 80)
        logger.info("GRID TRADING MONITOR (Kraken ETH/USD)")
        logger.info("=" * 80)
        logger.info(f"Trading pair: {self.trading_pair}")
        logger.info(f"Grid range: ${self.config['start_price']} - ${self.config['end_price']}")
        logger.info(f"Number of levels: {self.config['num_grids']}")
        logger.info(f"Capital: ${self.config['total_amount_usd']}")
        logger.info("=" * 80)

    def _calculate_grid_levels(self, grid_type='logarithmic'):
        """Calculate price levels for grid (linear or logarithmic)"""
        start = self.config['start_price']
        end = self.config['end_price']
        num = self.config['num_grids']

        levels = []

        if grid_type == 'logarithmic':
            # Logarithmic spacing - denser in middle where more action happens
            import math
            log_start = math.log(start)
            log_end = math.log(end)
            log_step = (log_end - log_start) / (num - 1)

            for i in range(num):
                price = math.exp(log_start + (log_step * i))
                levels.append(Decimal(str(price)))
        else:
            # Linear spacing (original)
            step = (end - start) / (num - 1)
            for i in range(num):
                price = start + (step * i)
                levels.append(Decimal(str(price)))

        return sorted(levels)

    def get_current_price(self):
        """Fetch current ETH/USD price"""
        try:
            ticker = self.exchange.fetch_ticker(self.trading_pair)
            return Decimal(str(ticker['last']))
        except Exception as e:
            logger.warning(f"Failed to fetch price: {e}")
            return None

    def display_grid_status(self, current_price):
        """Display visual grid with current price"""
        print(f"\n📊 GRID STATUS (Current: ${current_price})")
        print("=" * 70)

        for level in reversed(self.grid_levels):
            marker = " ◄── YOU ARE HERE" if abs(level - current_price) < 10 else ""
            order_type = "SELL" if level > current_price else "BUY "
            distance = abs(level - current_price)

            print(f"  ${level:8.0f} │ {order_type} │ Distance: ${distance:7.0f} {marker}")

        print("=" * 70)

    def simulate_orders(self, current_price):
        """Show what orders would be placed"""
        print(f"\n📋 PENDING ORDERS (if grid active):")
        print("=" * 70)

        order_amount_per_level = Decimal(str(self.config['total_amount_usd'])) / Decimal(str(self.config['num_grids']))

        buy_orders = 0
        sell_orders = 0

        for level in self.grid_levels:
            if level < current_price:
                print(f"  BUY  @ ${level:8.0f} - ${order_amount_per_level:.2f}")
                buy_orders += 1
            else:
                print(f"  SELL @ ${level:8.0f} - ${order_amount_per_level:.2f}")
                sell_orders += 1

        print(f"\nTotal: {buy_orders} BUY orders, {sell_orders} SELL orders")
        print(f"Capital per level: ${order_amount_per_level:.2f}")
        print("=" * 70)

    def calculate_expected_profit(self, current_price):
        """Calculate expected profit if all orders filled"""
        print(f"\n💰 PROFIT SIMULATION (Best case):")
        print("=" * 70)

        amount_per_level = Decimal(str(self.config['total_amount_usd'])) / Decimal(str(self.config['num_grids']))
        fee_pct = Decimal(str(self.config['maker_fee_pct']))

        total_profit = Decimal('0')
        completed_cycles = 0

        # Simulate completed buy->sell cycles
        for i in range(len(self.grid_levels) - 1):
            buy_price = self.grid_levels[i]
            sell_price = self.grid_levels[i + 1]

            if sell_price <= current_price:
                # This cycle is complete
                profit = amount_per_level * (sell_price - buy_price) / buy_price
                profit -= profit * (fee_pct * Decimal('2') / Decimal('100'))  # Buy + Sell fees

                total_profit += profit
                completed_cycles += 1
                print(f"✓ BUY @${buy_price:.0f} → SELL @${sell_price:.0f}: ${profit:.2f}")

        print(f"\nCompleted cycles: {completed_cycles}")
        print(f"Total potential profit: ${total_profit:.2f}")
        print(f"ROI: {(total_profit / Decimal(str(self.config['total_amount_usd'])) * 100):.2f}%")
        print("=" * 70)

    def run_monitor(self):
        """Run continuous monitoring"""
        iteration = 0

        try:
            while True:
                iteration += 1
                current_price = self.get_current_price()

                if current_price:
                    print(f"\n\n{'=' * 70}")
                    print(f"Iteration {iteration} - {datetime.now().strftime('%H:%M:%S')}")
                    print(f"{'=' * 70}")

                    self.display_grid_status(current_price)
                    self.simulate_orders(current_price)
                    self.calculate_expected_profit(current_price)

                # Wait before next update
                logger.info("Next update in 30 seconds...")
                asyncio.run(asyncio.sleep(30))

        except KeyboardInterrupt:
            print("\n\nMonitor stopped (Ctrl+C)")


if __name__ == '__main__':
    monitor = GridMonitor()
    monitor.run_monitor()
