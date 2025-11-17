#!/usr/bin/env python3
"""
LIVE Grid Trading Bot - ADA/EUR on Kraken
Dynamic range adjustment every hour
"""

import logging
import math
import os
import time
from datetime import datetime
from decimal import Decimal

import ccxt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/grid_ada_live.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class ADAGridTrader:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run

        api_key = os.getenv('KRAKEN_API_KEY')
        api_secret = os.getenv('KRAKEN_SECRET_KEY')

        if not api_key or not api_secret:
            raise ValueError("❌ API keys not found!")

        self.exchange = ccxt.kraken({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True
        })

        self.trading_pair = "ADA/EUR"

        # Config optimized for ADA (lower price = more coins per order)
        self.config = {
            'range_pct_down': 3.0,   # -3% below current price
            'range_pct_up': 8.0,     # +8% above current price
            'num_grids': 4,          # 4 grids
            'total_capital': 70,     # €70 capital
            'maker_fee': 0.0025,     # 0.25% maker fee via API (website is 0%, API niet!)
            'stop_loss': 0.40,       # Stop @ €0.40
            'take_profit': 0.60,     # Take profit @ €0.60
            'min_order_size': 10,    # ADA minimum (actually lower, but safe)
            'check_interval': 10,
            'rebalance_interval': 300,
            'dynamic_range_interval': 3600,  # Herbereken range elk uur
        }

        # Dynamic range - wordt elk uur herberekend
        self.current_price = None
        self.config['start_price'] = None
        self.config['end_price'] = None

        self.grid_levels = []
        self.open_orders = {}
        self.filled_orders = []
        self.last_rebalance = 0
        self.last_range_update = 0

        logger.info("=" * 80)
        logger.info(f"{'DRY RUN - ' if dry_run else ''}ADA/EUR GRID TRADING BOT")
        logger.info("=" * 80)
        logger.info(f"Dynamic range: -{self.config['range_pct_down']}% / +{self.config['range_pct_up']}% from current price")
        logger.info(f"Range updates: Every {self.config['dynamic_range_interval'] / 3600:.0f} hour(s)")
        logger.info(f"Grids: {self.config['num_grids']}")
        logger.info(f"Capital: €{self.config['total_capital']}")
        logger.info("=" * 80)

    def update_dynamic_range(self, current_price):
        """Update grid range based on current price"""
        range_down = self.config['range_pct_down'] / 100
        range_up = self.config['range_pct_up'] / 100

        self.config['start_price'] = float(current_price * (1 - Decimal(str(range_down))))
        self.config['end_price'] = float(current_price * (1 + Decimal(str(range_up))))

        logger.info(f"📊 Dynamic range update: €{self.config['start_price']:.4f} - €{self.config['end_price']:.4f}")
        logger.info(f"   Current price: €{current_price:.4f} | Range: -{self.config['range_pct_down']}% / +{self.config['range_pct_up']}%")

    def _calculate_grid_levels(self):
        """Logarithmic grid levels"""
        start = self.config['start_price']
        end = self.config['end_price']
        num = self.config['num_grids']

        if start is None or end is None:
            return []

        levels = []
        log_start = math.log(start)
        log_end = math.log(end)
        log_step = (log_end - log_start) / (num - 1)

        for i in range(num):
            price = math.exp(log_start + (log_step * i))
            levels.append(Decimal(str(price)))

        return sorted(levels)

    def get_current_price(self):
        try:
            ticker = self.exchange.fetch_ticker(self.trading_pair)
            return Decimal(str(ticker['last']))
        except Exception as e:
            logger.error(f"Failed to fetch price: {e}")
            return None

    def get_balances(self):
        try:
            balance = self.exchange.fetch_balance()
            eur = Decimal(str(balance.get('EUR', {}).get('free', 0)))
            ada = Decimal(str(balance.get('ADA', {}).get('free', 0)))
            return eur, ada
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return None, None

    def place_limit_order(self, side, price, amount):
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] {side} order: {amount:.2f} ADA @ €{price:.4f}")
                return f"dry_{int(time.time())}_{side}"

            order = self.exchange.create_limit_order(
                symbol=self.trading_pair,
                side=side.lower(),
                amount=float(amount),
                price=float(price),
                params={'post_only': True}
            )

            logger.info(f"✓ {side.lower()} order: {amount:.2f} ADA @ €{price:.4f} | ID: {order['id']}")
            return order['id']
        except Exception as e:
            logger.error(f"Failed to place {side.lower()} order: {e}")
            return None

    def cancel_all_orders(self):
        try:
            if self.dry_run:
                logger.info("[DRY RUN] Cancelling all orders")
                self.open_orders = {}
                return

            open_orders = self.exchange.fetch_open_orders(self.trading_pair)
            for order in open_orders:
                self.exchange.cancel_order(order['id'], self.trading_pair)

            self.open_orders = {}
            logger.info(f"✓ Cancelled {len(open_orders)} orders")
        except Exception as e:
            logger.error(f"Failed to cancel orders: {e}")

    def place_grid_orders(self, current_price):
        self.cancel_all_orders()
        time.sleep(1)

        eur_balance, ada_balance = self.get_balances()
        if eur_balance is None:
            return

        logger.info(f"Placing grid orders (ADA: €{float(current_price):.4f})...")

        buy_count = 0
        sell_count = 0

        for level in self.grid_levels:
            if level < current_price:
                # BUY order - calculate ADA amount from EUR
                order_value = eur_balance / (len([l for l in self.grid_levels if l < current_price]) or 1)
                ada_amount = order_value / level

                if ada_amount >= Decimal(str(self.config['min_order_size'])):
                    order_id = self.place_limit_order('buy', level, ada_amount)
                    if order_id:
                        self.open_orders[order_id] = {'side': 'buy', 'price': level, 'amount': ada_amount}
                        buy_count += 1

            elif level > current_price:
                # SELL order - split available ADA
                sell_levels = [l for l in self.grid_levels if l > current_price]
                ada_amount = ada_balance / (len(sell_levels) or 1)

                if ada_amount >= Decimal(str(self.config['min_order_size'])):
                    order_id = self.place_limit_order('sell', level, ada_amount)
                    if order_id:
                        self.open_orders[order_id] = {'side': 'sell', 'price': level, 'amount': ada_amount}
                        sell_count += 1

        logger.info(f"✓ Placed {buy_count} BUY + {sell_count} SELL = {buy_count + sell_count} orders")

    def check_filled_orders(self):
        if self.dry_run:
            return []

        try:
            closed_orders = self.exchange.fetch_closed_orders(self.trading_pair, limit=20)

            filled = []
            for order in closed_orders:
                order_id = order['id']
                if order_id in self.open_orders and order['status'] == 'closed':
                    filled.append(order_id)
                    self.filled_orders.append(order)
                    del self.open_orders[order_id]
                    logger.info(f"✓ Filled: {order['side']} {order['amount']:.2f} ADA @ €{order['price']:.4f}")

            return filled
        except Exception as e:
            logger.error(f"Failed to check orders: {e}")
            return []

    def display_status(self, current_price):
        eur_balance, ada_balance = self.get_balances()
        if eur_balance is None:
            return

        ada_value = ada_balance * current_price
        total_value = eur_balance + ada_value

        print("\n" + "=" * 70)
        print(f"  ADA/EUR GRID STATUS - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 70)
        print(f"ADA Price: €{float(current_price):.4f}")
        print(f"\nBalances:")
        print(f"  EUR: €{float(eur_balance):.2f}")
        print(f"  ADA: {float(ada_balance):.2f} (€{float(ada_value):.2f})")
        print(f"  Total: €{float(total_value):.2f}")
        print(f"\nOpen Orders: {len(self.open_orders)}")
        print(f"Filled Orders: {len(self.filled_orders)}")
        print("=" * 70)

    def run(self):
        logger.info("Starting ADA/EUR grid bot...")

        current_price = self.get_current_price()
        if not current_price:
            return

        # Initialize dynamic range
        self.update_dynamic_range(current_price)
        self.grid_levels = self._calculate_grid_levels()
        self.last_range_update = time.time()

        if not self.dry_run:
            print("\n" + "⚠️ " * 20)
            print("  LIVE TRADING - REAL MONEY!")
            print("  Ctrl+C within 5 sec to abort...")
            print("⚠️ " * 20)
            try:
                time.sleep(5)
            except KeyboardInterrupt:
                logger.info("\n✓ Aborted")
                return

        self.place_grid_orders(current_price)
        self.display_status(current_price)

        iteration = 0
        try:
            while True:
                iteration += 1
                time.sleep(self.config['check_interval'])

                current_price = self.get_current_price()
                if not current_price:
                    continue

                # Check if we need to update dynamic range (elk uur)
                if time.time() - self.last_range_update > self.config['dynamic_range_interval']:
                    logger.info("🔄 Hourly dynamic range update...")
                    old_start = self.config['start_price']
                    old_end = self.config['end_price']

                    self.update_dynamic_range(current_price)
                    self.grid_levels = self._calculate_grid_levels()
                    self.last_range_update = time.time()

                    # Rebalance with new range
                    logger.info(f"   Old range: €{old_start:.4f} - €{old_end:.4f}")
                    logger.info(f"   New range: €{self.config['start_price']:.4f} - €{self.config['end_price']:.4f}")
                    logger.info("   Rebalancing orders with new grid levels...")
                    self.place_grid_orders(current_price)

                filled = self.check_filled_orders()
                if filled:
                    logger.info(f"Rebalancing after {len(filled)} fills...")
                    self.place_grid_orders(current_price)

                if time.time() - self.last_rebalance > self.config['rebalance_interval']:
                    logger.info("⟳ Periodic rebalance...")
                    self.place_grid_orders(current_price)
                    self.last_rebalance = time.time()

                if iteration % 30 == 0:
                    self.display_status(current_price)

                if current_price <= Decimal(str(self.config['stop_loss'])):
                    logger.warning(f"⚠️  STOP LOSS @ €{float(current_price):.4f}")
                    break

                if current_price >= Decimal(str(self.config['take_profit'])):
                    logger.info(f"✓ TAKE PROFIT @ €{float(current_price):.4f}")
                    break

        except KeyboardInterrupt:
            logger.info("\n⚠️  Stopped by user")
        finally:
            self.cancel_all_orders()
            self.display_status(current_price)
            logger.info("✓ Bot stopped")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='ADA/EUR Grid Trading Bot')
    parser.add_argument('--dry-run', action='store_true', help='Run in dry-run mode (no real orders)')
    parser.add_argument('--live', action='store_true', help='Run in LIVE mode (real orders!)')

    args = parser.parse_args()

    if args.live:
        dry_run = False
        print("\n💰 LIVE MODE - Real orders on Kraken\n")
    elif args.dry_run:
        dry_run = True
        print("\n📝 DRY RUN MODE - No real orders\n")
    else:
        print("\n⚠️  Please specify --live or --dry-run")
        exit(1)

    trader = ADAGridTrader(dry_run=dry_run)
    trader.run()
