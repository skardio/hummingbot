#!/usr/bin/env python3
"""
Paper Trading Grid Bot - Simulated Trading
Logs all trades without executing real orders
"""

import json
import logging
import math
import time
from datetime import datetime
from decimal import Decimal

import ccxt

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/grid_paper_trade.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PaperGridTrader:
    def __init__(self):
        self.exchange = ccxt.kraken({'enableRateLimit': True})
        self.trading_pair = "ETH/EUR"

        # Config (from optimized YAML)
        self.config = {
            'start_price': 2950,
            'end_price': 3200,
            'num_grids': 10,
            'total_capital': 100,
            'maker_fee': 0.0016,  # 0.16%
            'stop_loss': 2850,
            'take_profit': 3300,
        }

        # Paper trading state
        self.paper_balance_eur = Decimal(str(self.config['total_capital']))
        self.paper_balance_eth = Decimal('0')
        self.grid_levels = self._calculate_grid_levels()
        self.open_orders = []  # Simulated orders
        self.filled_orders = []
        self.total_profit = Decimal('0')
        self.trade_count = 0

        logger.info("=" * 80)
        logger.info("PAPER TRADING GRID BOT STARTED")
        logger.info("=" * 80)
        logger.info(f"Pair: {self.trading_pair}")
        logger.info(f"Range: €{self.config['start_price']} - €{self.config['end_price']}")
        logger.info(f"Grids: {self.config['num_grids']}")
        logger.info(f"Capital: €{self.config['total_capital']}")
        logger.info(f"Paper EUR: €{float(self.paper_balance_eur):.2f}")
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
            logger.warning(f"Failed to fetch price: {e}")
            return None

    def place_grid_orders(self, current_price):
        """Place simulated grid orders"""
        # Clear old orders
        self.open_orders = []

        capital_per_level = self.paper_balance_eur / Decimal(str(self.config['num_grids']))

        for level in self.grid_levels:
            if level < current_price:
                # BUY order below current price
                amount_eur = capital_per_level
                amount_eth = amount_eur / level

                order = {
                    'id': f"paper_{int(time.time())}_{len(self.open_orders)}",
                    'type': 'BUY',
                    'price': float(level),
                    'amount_eur': float(amount_eur),
                    'amount_eth': float(amount_eth),
                    'status': 'open',
                    'timestamp': datetime.now().isoformat()
                }
                self.open_orders.append(order)

            elif level > current_price:
                # SELL order above current price
                amount_eur = capital_per_level
                amount_eth = amount_eur / current_price  # Use current holdings estimate

                order = {
                    'id': f"paper_{int(time.time())}_{len(self.open_orders)}",
                    'type': 'SELL',
                    'price': float(level),
                    'amount_eur': float(amount_eur),
                    'amount_eth': float(amount_eth),
                    'status': 'open',
                    'timestamp': datetime.now().isoformat()
                }
                self.open_orders.append(order)

        logger.info(f"✓ Placed {len(self.open_orders)} grid orders (paper)")

    def check_fills(self, current_price):
        """Check if any orders would be filled"""
        filled = []

        for order in self.open_orders:
            order_price = Decimal(str(order['price']))

            # Simple fill logic: if price crosses order level
            if order['type'] == 'BUY' and current_price <= order_price:
                # BUY order filled
                self.paper_balance_eur -= Decimal(str(order['amount_eur']))
                self.paper_balance_eth += Decimal(str(order['amount_eth']))

                # Apply fee
                fee = Decimal(str(order['amount_eth'])) * Decimal(str(self.config['maker_fee']))
                self.paper_balance_eth -= fee

                order['status'] = 'filled'
                order['fill_time'] = datetime.now().isoformat()
                order['fill_price'] = float(current_price)
                order['fee_eth'] = float(fee)

                self.filled_orders.append(order)
                self.trade_count += 1
                filled.append(order)

                logger.info(f"✓ BUY FILLED @ €{order['fill_price']:.2f} | {order['amount_eth']:.6f} ETH | Fee: {float(fee):.6f} ETH")

            elif order['type'] == 'SELL' and current_price >= order_price:
                # SELL order filled
                self.paper_balance_eth -= Decimal(str(order['amount_eth']))
                self.paper_balance_eur += Decimal(str(order['amount_eur']))

                # Apply fee
                fee = Decimal(str(order['amount_eur'])) * Decimal(str(self.config['maker_fee']))
                self.paper_balance_eur -= fee

                # Calculate profit for this trade
                profit = Decimal(str(order['amount_eur'])) - (Decimal(str(order['amount_eth'])) * order_price)
                profit -= fee
                self.total_profit += profit

                order['status'] = 'filled'
                order['fill_time'] = datetime.now().isoformat()
                order['fill_price'] = float(current_price)
                order['fee_eur'] = float(fee)
                order['profit'] = float(profit)

                self.filled_orders.append(order)
                self.trade_count += 1
                filled.append(order)

                logger.info(f"✓ SELL FILLED @ €{order['fill_price']:.2f} | {order['amount_eth']:.6f} ETH | Profit: €{float(profit):.3f}")

        # Remove filled orders
        self.open_orders = [o for o in self.open_orders if o['status'] == 'open']

        return filled

    def display_status(self, current_price):
        """Display current status"""
        total_value = self.paper_balance_eur + (self.paper_balance_eth * current_price)
        pnl = total_value - Decimal(str(self.config['total_capital']))
        pnl_pct = (pnl / Decimal(str(self.config['total_capital']))) * 100

        print("\n" + "=" * 70)
        print(f"  PAPER TRADING STATUS - {datetime.now().strftime('%H:%M:%S')}")
        print("=" * 70)
        print(f"Current Price: €{float(current_price):.2f}")
        print(f"\nPaper Balances:")
        print(f"  EUR: €{float(self.paper_balance_eur):.2f}")
        print(f"  ETH: {float(self.paper_balance_eth):.6f}")
        print(f"  Total Value: €{float(total_value):.2f}")
        print(f"\nPerformance:")
        print(f"  PnL: €{float(pnl):.2f} ({float(pnl_pct):+.2f}%)")
        print(f"  Trades: {self.trade_count}")
        print(f"  Total Profit: €{float(self.total_profit):.3f}")
        print(f"\nOrders:")
        print(f"  Open: {len(self.open_orders)}")
        print(f"  Filled: {len(self.filled_orders)}")
        print("=" * 70)

    def run(self, duration_minutes=60):
        """Run paper trading bot"""
        logger.info(f"Starting paper trading for {duration_minutes} minutes...")

        start_time = time.time()
        end_time = start_time + (duration_minutes * 60)

        # Initial setup
        current_price = self.get_current_price()
        if current_price:
            self.place_grid_orders(current_price)
            self.display_status(current_price)

        iteration = 0
        try:
            while time.time() < end_time:
                iteration += 1

                # Fetch current price
                current_price = self.get_current_price()
                if not current_price:
                    time.sleep(10)
                    continue

                # Check for fills
                filled = self.check_fills(current_price)

                # If any fills, replace orders
                if filled:
                    self.place_grid_orders(current_price)

                # Display status every 5 iterations (~50s)
                if iteration % 5 == 0:
                    self.display_status(current_price)

                # Check stop loss / take profit
                if current_price <= Decimal(str(self.config['stop_loss'])):
                    logger.warning(f"⚠️  STOP LOSS HIT @ €{float(current_price):.2f}")
                    break

                if current_price >= Decimal(str(self.config['take_profit'])):
                    logger.info(f"✓ TAKE PROFIT HIT @ €{float(current_price):.2f}")
                    break

                # Wait 10s
                time.sleep(10)

        except KeyboardInterrupt:
            logger.info("\n⚠️  Paper trading stopped by user (Ctrl+C)")

        # Final report
        self.display_final_report(current_price)

    def display_final_report(self, final_price):
        """Display final trading report"""
        total_value = self.paper_balance_eur + (self.paper_balance_eth * final_price)
        pnl = total_value - Decimal(str(self.config['total_capital']))
        pnl_pct = (pnl / Decimal(str(self.config['total_capital']))) * 100

        print("\n" + "=" * 80)
        print("  FINAL PAPER TRADING REPORT")
        print("=" * 80)
        print(f"\nStarting Capital: €{self.config['total_capital']:.2f}")
        print(f"Final Value: €{float(total_value):.2f}")
        print(f"PnL: €{float(pnl):.2f} ({float(pnl_pct):+.2f}%)")
        print(f"\nTrade Statistics:")
        print(f"  Total Trades: {self.trade_count}")
        print(f"  Total Profit: €{float(self.total_profit):.3f}")
        print(f"  Avg Profit/Trade: €{float(self.total_profit) / max(1, self.trade_count):.3f}")
        print(f"\nFinal Balances:")
        print(f"  EUR: €{float(self.paper_balance_eur):.2f}")
        print(f"  ETH: {float(self.paper_balance_eth):.6f}")
        print("=" * 80)

        # Save report
        report = {
            'timestamp': datetime.now().isoformat(),
            'starting_capital': self.config['total_capital'],
            'final_value': float(total_value),
            'pnl': float(pnl),
            'pnl_pct': float(pnl_pct),
            'trades': self.trade_count,
            'total_profit': float(self.total_profit),
            'filled_orders': self.filled_orders
        }

        with open('logs/grid_paper_report.json', 'w') as f:
            json.dump(report, f, indent=2)

        logger.info("✓ Report saved to logs/grid_paper_report.json")


if __name__ == "__main__":
    import sys

    # Default 1 hour, or specify minutes as argument
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 60

    trader = PaperGridTrader()
    trader.run(duration_minutes=duration)
