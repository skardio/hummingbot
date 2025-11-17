#!/usr/bin/env python3
"""
LIVE Grid Trading Bot - Real Orders on Kraken
⚠️  WARNING: This uses REAL money!
"""

import json
import logging
import math
import os
import time
from datetime import datetime
from decimal import Decimal

import ccxt

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/grid_live_trade.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class LiveGridTrader:
    def __init__(self, dry_run=False):
        """
        Initialize live grid trader
        dry_run=True will log orders but NOT execute them
        """
        self.dry_run = dry_run

        # Get API keys
        api_key = os.getenv('KRAKEN_API_KEY')
        api_secret = os.getenv('KRAKEN_SECRET_KEY')

        if not api_key or not api_secret:
            raise ValueError("❌ API keys not found! Set KRAKEN_API_KEY and KRAKEN_SECRET_KEY")

        self.exchange = ccxt.kraken({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot'
            }
        })

        self.trading_pair = "ETH/EUR"

        # Config (from optimized YAML)
        self.config = {
            'start_price': 2950,
            'end_price': 3200,
            'num_grids': 10,
            'total_capital': 100,
            'maker_fee': 0.0016,  # 0.16% (with volume discount)
            'stop_loss': 2850,
            'take_profit': 3300,
            'check_interval': 10,  # seconds
            'rebalance_interval': 300,  # 5 minutes
        }

        # State
        self.grid_levels = self._calculate_grid_levels()
        self.open_orders = {}  # {order_id: order_info}
        self.filled_orders = []
        self.total_profit = Decimal('0')
        self.last_rebalance = 0

        logger.info("=" * 80)
        logger.info(f"{'DRY RUN - ' if dry_run else ''}LIVE GRID TRADING BOT")
        logger.info("=" * 80)
        logger.info(f"Pair: {self.trading_pair}")
        logger.info(f"Range: €{self.config['start_price']} - €{self.config['end_price']}")
        logger.info(f"Grids: {self.config['num_grids']}")
        logger.info(f"Capital: €{self.config['total_capital']}")
        logger.info(f"Stop Loss: €{self.config['stop_loss']}")
        logger.info(f"Take Profit: €{self.config['take_profit']}")
        logger.info(f"Dry Run: {dry_run}")
        logger.info("=" * 80)

    def _calculate_grid_levels(self):
        """Calculate logarithmic grid levels"""
        start = self.config['start_price']
        end = self.config['end_price']
        num = self.config['num_grids']

        levels = []
        log_start = math.log(start)
        log_end = math.log(end)
        log_step = (log_end - log_start) / (num - 1)

        for i in range(num):
            price = math.exp(log_start + (log_step * i))
            levels.append(Decimal(str(price)))

        return sorted(levels)

    def get_current_price(self):
        """Fetch current market price"""
        try:
            ticker = self.exchange.fetch_ticker(self.trading_pair)
            return Decimal(str(ticker['last']))
        except Exception as e:
            logger.error(f"Failed to fetch price: {e}")
            return None

    def get_balances(self):
        """Fetch account balances"""
        try:
            balance = self.exchange.fetch_balance()
            eur = Decimal(str(balance.get('EUR', {}).get('free', 0)))
            eth = Decimal(str(balance.get('ETH', {}).get('free', 0)))
            return eur, eth
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return None, None

    def place_limit_order(self, side, price, amount):
        """Place a limit order on Kraken"""
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would place {side} order: {amount:.6f} ETH @ €{price:.2f}")
                return f"dry_run_{int(time.time())}_{side}"

            order = self.exchange.create_limit_order(
                symbol=self.trading_pair,
                side=side.lower(),
                amount=amount,
                price=float(price),
                params={'post_only': True}  # Maker-only
            )

            logger.info(f"✓ {side} order placed: {amount:.6f} ETH @ €{price:.2f} | ID: {order['id']}")
            return order['id']

        except Exception as e:
            logger.error(f"Failed to place {side} order @ €{price:.2f}: {e}")
            return None

    def cancel_order(self, order_id):
        """Cancel an open order"""
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would cancel order {order_id}")
                return True

            self.exchange.cancel_order(order_id, self.trading_pair)
            logger.info(f"✓ Cancelled order {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    def cancel_all_orders(self):
        """Cancel all open orders"""
        logger.info("Cancelling all open orders...")

        if self.dry_run:
            logger.info(f"[DRY RUN] Would cancel {len(self.open_orders)} orders")
            self.open_orders.clear()
            return

        for order_id in list(self.open_orders.keys()):
            self.cancel_order(order_id)

        self.open_orders.clear()

    def place_grid_orders(self, current_price):
        """Place all grid orders"""
        logger.info(f"Placing grid orders (current price: €{float(current_price):.2f})...")

        # Cancel existing orders first
        if self.open_orders:
            self.cancel_all_orders()

        # Calculate capital per level
        eur_balance, eth_balance = self.get_balances()
        if eur_balance is None:
            logger.error("Cannot place orders - failed to get balance")
            return

        # AUTO-REBALANCE: If starting fresh with only EUR, buy half as ETH
        total_value_eur = eur_balance + (eth_balance * current_price)
        target_eth_value = total_value_eur / Decimal('2')  # 50/50 split

        if eth_balance == 0 and eur_balance >= target_eth_value:
            logger.info(f"🔄 Auto-rebalancing: Converting €{float(target_eth_value):.2f} to ETH...")
            eth_to_buy = target_eth_value / current_price

            if not self.dry_run:
                try:
                    # Place market order to buy ETH
                    order = self.exchange.create_market_order(
                        symbol=self.trading_pair,
                        side='buy',
                        amount=float(eth_to_buy)
                    )
                    logger.info(f"✓ Bought {float(eth_to_buy):.6f} ETH @ market price")
                    time.sleep(2)  # Wait for balance update
                    eur_balance, eth_balance = self.get_balances()
                except Exception as e:
                    logger.error(f"Failed to rebalance: {e}")
            else:
                logger.info(f"[DRY RUN] Would buy {float(eth_to_buy):.6f} ETH")
                # Simulate balance
                eur_balance -= target_eth_value
                eth_balance = eth_to_buy

        capital_per_level = Decimal(str(self.config['total_capital'])) / Decimal(str(self.config['num_grids']))

        buy_orders = 0
        sell_orders = 0

        for level in self.grid_levels:
            if level < current_price:
                # Place BUY order below current price
                amount_eur = capital_per_level
                amount_eth = amount_eur / level

                # Check minimum order size (Kraken ETH/EUR min ~0.0001 ETH)
                if amount_eth < Decimal('0.001'):
                    logger.warning(f"BUY order too small @ €{float(level):.2f}: {float(amount_eth):.6f} ETH")
                    continue

                # Check EUR balance
                if eur_balance < amount_eur:
                    logger.warning(f"Insufficient EUR for BUY @ €{float(level):.2f}: need €{float(amount_eur):.2f}, have €{float(eur_balance):.2f}")
                    continue

                order_id = self.place_limit_order('buy', level, float(amount_eth))
                if order_id:
                    self.open_orders[order_id] = {
                        'type': 'BUY',
                        'price': float(level),
                        'amount': float(amount_eth),
                        'timestamp': datetime.now().isoformat()
                    }
                    buy_orders += 1

            elif level > current_price:
                # Place SELL order above current price
                amount_eur = capital_per_level
                amount_eth = amount_eur / current_price

                if amount_eth < Decimal('0.001'):
                    logger.warning(f"SELL order too small @ €{float(level):.2f}: {float(amount_eth):.6f} ETH")
                    continue

                # Check if we have enough ETH
                if eth_balance < amount_eth:
                    logger.warning(f"Insufficient ETH for SELL @ €{float(level):.2f}: need {float(amount_eth):.6f}, have {float(eth_balance):.6f}")
                    continue

                order_id = self.place_limit_order('sell', level, float(amount_eth))
                if order_id:
                    self.open_orders[order_id] = {
                        'type': 'SELL',
                        'price': float(level),
                        'amount': float(amount_eth),
                        'timestamp': datetime.now().isoformat()
                    }
                    sell_orders += 1

        logger.info(f"✓ Placed {buy_orders} BUY + {sell_orders} SELL orders = {buy_orders + sell_orders} total")

    def check_filled_orders(self):
        """Check for filled orders and update state"""
        if self.dry_run:
            return []

        filled = []

        try:
            # Fetch open orders
            open_orders = self.exchange.fetch_open_orders(self.trading_pair)
            open_order_ids = {o['id'] for o in open_orders}

            # Check which tracked orders are no longer open (=filled)
            for order_id in list(self.open_orders.keys()):
                if order_id not in open_order_ids:
                    # Order was filled
                    order_info = self.open_orders.pop(order_id)

                    # Fetch order details
                    try:
                        order = self.exchange.fetch_order(order_id, self.trading_pair)

                        if order['status'] == 'closed':
                            order_info['filled_time'] = datetime.now().isoformat()
                            order_info['filled_price'] = order.get('average', order_info['price'])
                            order_info['fee'] = order.get('fee', {})

                            self.filled_orders.append(order_info)
                            filled.append(order_info)

                            logger.info(f"✓ {order_info['type']} FILLED @ €{order_info['filled_price']:.2f} | {order_info['amount']:.6f} ETH")

                    except Exception as e:
                        logger.error(f"Failed to fetch order {order_id}: {e}")

        except Exception as e:
            logger.error(f"Failed to check filled orders: {e}")

        return filled

    def display_status(self, current_price):
        """Display current trading status"""
        eur_balance, eth_balance = self.get_balances()

        if eur_balance is None:
            logger.warning("Cannot display status - failed to get balance")
            return

        total_value = eur_balance + (eth_balance * current_price)
        pnl = total_value - Decimal(str(self.config['total_capital']))
        pnl_pct = (pnl / Decimal(str(self.config['total_capital']))) * 100

        print("\n" + "=" * 70)
        print(f"  LIVE GRID TRADING STATUS - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 70)
        print(f"Current Price: €{float(current_price):.2f}")
        print(f"\nBalances:")
        print(f"  EUR: €{float(eur_balance):.2f}")
        print(f"  ETH: {float(eth_balance):.6f}")
        print(f"  Total Value: €{float(total_value):.2f}")
        print(f"\nPerformance:")
        print(f"  PnL: €{float(pnl):.2f} ({float(pnl_pct):+.2f}%)")
        print(f"  Filled Orders: {len(self.filled_orders)}")
        print(f"\nOpen Orders:")
        print(f"  Total: {len(self.open_orders)}")

        buy_count = sum(1 for o in self.open_orders.values() if o['type'] == 'BUY')
        sell_count = sum(1 for o in self.open_orders.values() if o['type'] == 'SELL')
        print(f"  BUY: {buy_count} | SELL: {sell_count}")
        print("=" * 70)

    def run(self):
        """Run live grid trading bot"""
        logger.info("Starting live grid trading bot...")

        # Initial setup
        current_price = self.get_current_price()
        if not current_price:
            logger.error("Failed to get initial price. Exiting.")
            return

        # Safety check
        if not self.dry_run:
            print("\n" + "⚠️ " * 20)
            print("  WARNING: LIVE TRADING WITH REAL MONEY!")
            print("  Press Ctrl+C within 5 seconds to abort...")
            print("⚠️ " * 20)
            try:
                time.sleep(5)
            except KeyboardInterrupt:
                logger.info("\n✓ Aborted by user")
                return

        # Place initial grid
        self.place_grid_orders(current_price)
        self.display_status(current_price)

        iteration = 0
        try:
            while True:
                iteration += 1
                time.sleep(self.config['check_interval'])

                # Fetch current price
                current_price = self.get_current_price()
                if not current_price:
                    continue

                # Check for filled orders
                filled = self.check_filled_orders()

                # If orders filled, rebalance grid
                if filled:
                    logger.info(f"✓ {len(filled)} orders filled - rebalancing grid...")
                    self.place_grid_orders(current_price)

                # Periodic rebalance
                if time.time() - self.last_rebalance > self.config['rebalance_interval']:
                    logger.info("⟳ Periodic rebalance...")
                    self.place_grid_orders(current_price)
                    self.last_rebalance = time.time()

                # Display status every 30 iterations (~5 minutes)
                if iteration % 30 == 0:
                    self.display_status(current_price)

                # Safety checks
                if current_price <= Decimal(str(self.config['stop_loss'])):
                    logger.warning(f"⚠️  STOP LOSS HIT @ €{float(current_price):.2f}")
                    self.cancel_all_orders()
                    break

                if current_price >= Decimal(str(self.config['take_profit'])):
                    logger.info(f"✓ TAKE PROFIT HIT @ €{float(current_price):.2f}")
                    self.cancel_all_orders()
                    break

        except KeyboardInterrupt:
            logger.info("\n⚠️  Bot stopped by user (Ctrl+C)")

        finally:
            # Cleanup
            logger.info("Cleaning up...")
            self.cancel_all_orders()
            self.display_status(current_price if current_price else Decimal('0'))
            logger.info("✓ Bot stopped")


if __name__ == "__main__":
    import sys

    # Check for dry-run flag
    dry_run = '--dry-run' in sys.argv or '-d' in sys.argv

    if dry_run:
        print("\n🧪 DRY RUN MODE - Orders will be logged but NOT executed\n")
    else:
        print("\n💰 LIVE MODE - Orders will be EXECUTED on Kraken\n")

    trader = LiveGridTrader(dry_run=dry_run)
    trader.run()
