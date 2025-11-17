#!/usr/bin/env python3
"""
LIVE Grid Trading Bot - XRP/EUR on Kraken
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
        logging.FileHandler('logs/grid_xrp_live.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class XRPGridTrader:
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

        self.trading_pair = "XRP/EUR"

        # Config optimized for XRP (4 grids = €25/order > €22 min)
        self.config = {
            'range_pct_down': 3.0,   # -3% below current price
            'range_pct_up': 8.0,     # +8% above current price
            'num_grids': 4,          # 4 grids × €25 = €100
            'total_capital': 100,
            'maker_fee': 0.0025,     # 0.25% maker fee via API (website is 0%, API niet!)
            'stop_loss': 1.95,
            'take_profit': 2.50,
            'min_order_size': 10,    # XRP minimum
            'check_interval': 10,
            'rebalance_interval': 300,
            'dynamic_range_interval': 3600,  # Herbereken range elk uur
            'trend_filter_enabled': True,    # Trade alleen bij stijgende trend!
            'trend_lookback_minutes': 30,    # Check trend over laatste 30 min
            'trend_min_change_pct': 0.5,     # Minimaal 0.5% stijging vereist
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
        self.price_history = []  # Voor trend detectie

        logger.info("=" * 80)
        logger.info(f"{'DRY RUN - ' if dry_run else ''}XRP/EUR GRID TRADING BOT WITH TREND FILTER")
        logger.info("=" * 80)
        logger.info(f"Dynamic range: -{self.config['range_pct_down']}% / +{self.config['range_pct_up']}% from current price")
        logger.info(f"Range updates: Every {self.config['dynamic_range_interval'] / 3600:.0f} hour(s)")
        logger.info(f"Grids: {self.config['num_grids']}")
        logger.info(f"Capital: €{self.config['total_capital']}")
        if self.config.get('trend_filter_enabled', False):
            logger.info(f"📈 TREND FILTER: Enabled - Trade only when price rises {self.config['trend_min_change_pct']}%+ over {self.config['trend_lookback_minutes']} min")
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
            price = Decimal(str(ticker['last']))

            # Track price history voor trend filter
            if self.config.get('trend_filter_enabled', False):
                self.price_history.append({
                    'price': price,
                    'timestamp': time.time()
                })
                # Hou alleen laatste X minuten bij
                lookback_seconds = self.config['trend_lookback_minutes'] * 60
                cutoff_time = time.time() - lookback_seconds
                self.price_history = [p for p in self.price_history if p['timestamp'] > cutoff_time]

            return price
        except Exception as e:
            logger.error(f"Failed to fetch price: {e}")
            return None

    def is_uptrend(self):
        """Check of XRP in een uptrend is"""
        if not self.config.get('trend_filter_enabled', False):
            return True  # Trend filter uit = altijd traden

        if len(self.price_history) < 2:
            logger.warning("⚠️  Not enough price history for trend detection")
            return True  # Te weinig data = voorzichtig traden

        # Bereken price change over lookback periode
        oldest_price = self.price_history[0]['price']
        current_price = self.price_history[-1]['price']

        price_change_pct = float((current_price - oldest_price) / oldest_price * 100)
        min_change = self.config['trend_min_change_pct']

        is_up = price_change_pct >= min_change

        if is_up:
            logger.info(f"📈 UPTREND: {price_change_pct:+.2f}% over {self.config['trend_lookback_minutes']}min (threshold: {min_change}%)")
        else:
            logger.warning(f"📉 DOWNTREND: {price_change_pct:+.2f}% over {self.config['trend_lookback_minutes']}min - NIET TRADEN!")

        return is_up

    def get_balances(self):
        try:
            balance = self.exchange.fetch_balance()
            eur = Decimal(str(balance.get('EUR', {}).get('free', 0)))
            xrp = Decimal(str(balance.get('XRP', {}).get('free', 0)))
            return eur, xrp
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return None, None

    def place_limit_order(self, side, price, amount):
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] {side} order: {amount:.2f} XRP @ €{price:.4f}")
                return f"dry_{int(time.time())}_{side}"

            order = self.exchange.create_limit_order(
                symbol=self.trading_pair,
                side=side.lower(),
                amount=float(amount),
                price=float(price),
                params={'post_only': True}
            )

            logger.info(f"✓ {side} order: {amount:.2f} XRP @ €{price:.4f} | ID: {order['id']}")
            return order['id']

        except Exception as e:
            logger.error(f"Failed to place {side} order: {e}")
            return None

    def cancel_order(self, order_id):
        try:
            if self.dry_run:
                return True
            self.exchange.cancel_order(order_id, self.trading_pair)
            return True
        except Exception as e:
            logger.error(f"Failed to cancel {order_id}: {e}")
            return False

    def cancel_all_orders(self):
        if self.dry_run:
            logger.info(f"[DRY RUN] Would cancel {len(self.open_orders)} orders")
            self.open_orders.clear()
            return

        for order_id in list(self.open_orders.keys()):
            self.cancel_order(order_id)
        self.open_orders.clear()

    def place_grid_orders(self, current_price):
        logger.info(f"Placing grid orders (XRP: €{float(current_price):.4f})...")

        # Check trend filter
        if not self.is_uptrend():
            logger.warning("⚠️  DOWNTREND DETECTED - Cancelling all orders and waiting...")
            if self.open_orders:
                self.cancel_all_orders()
            return

        if self.open_orders:
            self.cancel_all_orders()

        eur_balance, xrp_balance = self.get_balances()
        if eur_balance is None:
            return

        capital_per_level = Decimal(str(self.config['total_capital'])) / Decimal(str(self.config['num_grids']))

        buy_orders = 0
        sell_orders = 0

        for level in self.grid_levels:
            if level < current_price:
                # BUY order
                amount_eur = capital_per_level
                amount_xrp = amount_eur / level

                if amount_xrp < Decimal(str(self.config['min_order_size'])):
                    continue

                if eur_balance < amount_eur:
                    logger.warning(f"Insufficient EUR for BUY @ €{float(level):.4f}")
                    continue

                order_id = self.place_limit_order('buy', level, amount_xrp)
                if order_id:
                    self.open_orders[order_id] = {
                        'type': 'BUY',
                        'price': float(level),
                        'amount': float(amount_xrp),
                        'timestamp': datetime.now().isoformat()
                    }
                    buy_orders += 1

            elif level > current_price:
                # SELL order
                amount_eur = capital_per_level
                amount_xrp = amount_eur / current_price

                if amount_xrp < Decimal(str(self.config['min_order_size'])):
                    continue

                if xrp_balance < amount_xrp:
                    logger.warning(f"Insufficient XRP for SELL @ €{float(level):.4f}")
                    continue

                order_id = self.place_limit_order('sell', level, amount_xrp)
                if order_id:
                    self.open_orders[order_id] = {
                        'type': 'SELL',
                        'price': float(level),
                        'amount': float(amount_xrp),
                        'timestamp': datetime.now().isoformat()
                    }
                    sell_orders += 1

        logger.info(f"✓ Placed {buy_orders} BUY + {sell_orders} SELL = {buy_orders + sell_orders} orders")

    def check_filled_orders(self):
        if self.dry_run:
            return []

        filled = []
        try:
            open_orders = self.exchange.fetch_open_orders(self.trading_pair)
            open_order_ids = {o['id'] for o in open_orders}

            for order_id in list(self.open_orders.keys()):
                if order_id not in open_order_ids:
                    order_info = self.open_orders.pop(order_id)
                    self.filled_orders.append(order_info)
                    filled.append(order_info)
                    logger.info(f"✓ {order_info['type']} FILLED @ €{order_info['price']:.4f}")
        except Exception as e:
            logger.error(f"Failed to check orders: {e}")

        return filled

    def display_status(self, current_price):
        eur_balance, xrp_balance = self.get_balances()
        if eur_balance is None:
            return

        xrp_value = xrp_balance * current_price
        total_value = eur_balance + xrp_value

        print("\n" + "=" * 70)
        print(f"  XRP/EUR GRID STATUS - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 70)
        print(f"XRP Price: €{float(current_price):.4f}")
        print(f"\nBalances:")
        print(f"  EUR: €{float(eur_balance):.2f}")
        print(f"  XRP: {float(xrp_balance):.2f} (€{float(xrp_value):.2f})")
        print(f"  Total: €{float(total_value):.2f}")
        print(f"\nOpen Orders: {len(self.open_orders)}")
        print(f"Filled Orders: {len(self.filled_orders)}")
        print("=" * 70)

    def run(self):
        logger.info("Starting XRP/EUR grid bot...")

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
    import sys
    dry_run = '--dry-run' in sys.argv or '-d' in sys.argv

    if dry_run:
        print("\n🧪 DRY RUN - Orders logged, not executed\n")
    else:
        print("\n💰 LIVE MODE - Real orders on Kraken\n")

    trader = XRPGridTrader(dry_run=dry_run)
    trader.run()
