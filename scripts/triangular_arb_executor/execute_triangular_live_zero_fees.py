#!/usr/bin/env python3
"""
LIVE Triangular Arbitrage Executor - ZERO FEES VERSION

With 0% Kraken fees (under €10k), triangular arbitrage is NOW PROFITABLE!

This bot:
1. Monitors tri_candidates.log for opportunities
2. Calculates profit after slippage (NO fees!)
3. Executes REAL trades on Kraken when profitable
4. Tracks volume to stay under €10k limit

⚠️  LIVE TRADING MODE - Real money!
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from decimal import Decimal

import ccxt

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LiveTriangularExecutor:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.candidate_log = os.path.join(ROOT, 'logs', 'tri_candidates.log')

        # Initialize Kraken
        self.exchange = ccxt.kraken({
            'apiKey': os.getenv('KRAKEN_API_KEY'),
            'secret': os.getenv('KRAKEN_API_SECRET') or os.getenv('KRAKEN_SECRET_KEY'),
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            }
        })

        self.config = {
            # 🚀 €70 CAPITAL MODE - GEFIXTE MONITOR!
            'capital_eur': Decimal('70'),  # €70 capital (you have €76.59)
            'min_profit_eur': Decimal('0.01'),  # €0.01 min profit (very aggressive!)
            'max_position_size_pct': Decimal('90'),  # Use 90% of capital per trade
            'maker_fee_pct': Decimal('0.00'),  # 0% fees! 🎉
            'taker_fee_pct': Decimal('0.00'),  # 0% fees! 🎉
            'slippage_pct_per_leg': Decimal('0.01'),  # Ultra-low 0.01% per leg = 0.03% total
            'volume_limit_eur': Decimal('9500'),  # Stay under €10k
            'check_interval': 2,  # Check every 2 seconds
        }

        self.stats = {
            'total_volume': Decimal('0'),
            'trades_executed': 0,
            'total_profit': Decimal('0'),
            'opportunities_seen': 0,
            'profitable_found': 0,
        }

        self.last_position = 0

        logger.info("=" * 80)
        logger.info(f"{'DRY RUN - ' if self.dry_run else '⚠️  LIVE - '}TRIANGULAR ARBITRAGE (ZERO FEES)")
        logger.info("=" * 80)
        logger.info(f"Capital: €{self.config['capital_eur']}")
        logger.info(f"Fees: {self.config['taker_fee_pct']}% (0% under €10k!)")
        logger.info(f"Slippage: {self.config['slippage_pct_per_leg']}% per leg")
        logger.info(f"Min profit: €{self.config['min_profit_eur']}")
        logger.info(f"Volume limit: €{self.config['volume_limit_eur']}")
        logger.info("=" * 80)

        if not self.dry_run:
            logger.warning("⚠️  LIVE TRADING MODE - Real orders will be placed!")
            logger.warning("⚠️  You have 5 seconds to cancel (Ctrl+C)...")
            time.sleep(5)
            logger.info("✓ Starting live trading...")

    def get_current_balance(self):
        """Get EUR and crypto balances"""
        try:
            # Debug: check if API keys are loaded
            if not self.exchange.apiKey:
                logger.error("KRAKEN_API_KEY not loaded!")
                return None
            if not self.exchange.secret:
                logger.error("KRAKEN_SECRET_KEY not loaded!")
                return None

            balance = self.exchange.fetch_balance()
            return balance
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return None

    def calculate_profit(self, candidate_edge_pct):
        """
        Calculate expected profit with 0% fees!

        With zero fees, only slippage matters:
        Net profit = Edge - Slippage
        """
        edge = Decimal(str(candidate_edge_pct))

        # Only slippage costs (3 legs × 0.03% = 0.09%)
        total_slippage = self.config['slippage_pct_per_leg'] * Decimal('3')

        # Net edge after slippage
        net_edge_pct = edge - total_slippage

        # Calculate profit
        position_size = self.config['capital_eur'] * (self.config['max_position_size_pct'] / Decimal('100'))
        profit_eur = position_size * (net_edge_pct / Decimal('100'))

        return {
            'edge_pct': edge,
            'slippage_pct': total_slippage,
            'net_edge_pct': net_edge_pct,
            'position_size': position_size,
            'profit_eur': profit_eur,
            'profitable': profit_eur >= self.config['min_profit_eur']
        }

    def execute_triangular_trade(self, route, edge_pct):
        """
        Execute triangular arbitrage trade

        Route example: ['ETH', 'BTC', 'EUR']
        Execution: EUR → ETH → BTC → EUR
        """
        calc = self.calculate_profit(edge_pct)

        if not calc['profitable']:
            return False

        logger.info(f"🎯 Executing: {' → '.join(route)}")
        logger.info(f"   Edge: {calc['edge_pct']:.3f}%")
        logger.info(f"   Slippage: {calc['slippage_pct']:.3f}%")
        logger.info(f"   Net: {calc['net_edge_pct']:.3f}%")
        logger.info(f"   Expected profit: €{calc['profit_eur']:.4f}")

        if self.dry_run:
            logger.info("   [DRY RUN] Would execute 3 trades")
            self.stats['trades_executed'] += 1
            self.stats['total_profit'] += calc['profit_eur']
            return True

        try:
            # Execute 3-leg trade
            position_size = calc['position_size']

            # Leg 1: EUR → route[0] (buy first asset)
            pair1 = f"{route[0]}/EUR"
            amount1 = position_size  # EUR amount
            logger.info(f"   Leg 1: Buy {pair1} with €{amount1:.2f}")

            # REAL ORDER EXECUTION - Leg 1
            order1 = self.exchange.create_market_buy_order(pair1, amount1)
            amount_from_leg1 = Decimal(str(order1['filled']))  # How much route[0] we got
            logger.info(f"   ✓ Leg 1 filled: {amount_from_leg1:.8f} {route[0]} (order {order1['id']})")

            # Leg 2: route[0] → route[1]
            pair2 = f"{route[1]}/{route[0]}"
            logger.info(f"   Leg 2: Trade {pair2} with {amount_from_leg1:.8f} {route[0]}")

            # REAL ORDER EXECUTION - Leg 2
            order2 = self.exchange.create_market_sell_order(pair2, float(amount_from_leg1))
            amount_from_leg2 = Decimal(str(order2['filled']))  # How much route[1] we got
            logger.info(f"   ✓ Leg 2 filled: {amount_from_leg2:.8f} {route[1]} (order {order2['id']})")

            # Leg 3: route[1] → EUR (back to EUR)
            pair3 = f"{route[1]}/EUR"
            logger.info(f"   Leg 3: Sell {pair3} with {amount_from_leg2:.8f} {route[1]} back to EUR")

            # REAL ORDER EXECUTION - Leg 3
            order3 = self.exchange.create_market_sell_order(pair3, float(amount_from_leg2))
            final_eur = Decimal(str(order3['cost']))  # How much EUR we got back
            logger.info(f"   ✓ Leg 3 filled: €{final_eur:.4f} (order {order3['id']})")

            actual_profit = final_eur - position_size

            self.stats['trades_executed'] += 1
            self.stats['total_volume'] += position_size
            self.stats['total_profit'] += actual_profit

            logger.info(f"✅ Trade completed! Expected: €{calc['profit_eur']:.4f}, Actual: €{actual_profit:.4f}")
            logger.info(f"   Order IDs: {order1['id']}, {order2['id']}, {order3['id']}")
            return True

        except Exception as e:
            logger.error(f"❌ Trade failed: {e}")
            return False

    def parse_candidate(self, line):
        """Parse candidate from log line (JSON format)"""
        try:
            line = line.strip()
            if not line or line.startswith('#'):
                return None

            # Parse JSON format from monitor
            # Format: {"timestamp": "...", "triple": ["ETH-EUR", "EUR-USD", "ETH-USD"], "edge_pct": 0.05}
            data = json.loads(line)

            if 'triple' not in data or 'edge_pct' not in data:
                return None

            # Convert triple format: ["ETH-EUR", "EUR-USD", "ETH-USD"] -> ["ETH", "EUR", "USD"]
            # Extract unique assets from pairs
            triple = data['triple']
            assets = []
            for pair in triple:
                parts = pair.split('-')
                if len(assets) == 0:
                    assets.append(parts[0])
                    assets.append(parts[1])
                elif parts[0] not in assets:
                    assets.append(parts[0])
                elif parts[1] not in assets:
                    assets.append(parts[1])

            return {
                'route': assets,
                'edge_pct': data['edge_pct'],
                'profit_pct_after_fees': data.get('profit_pct_after_fees', None),
                'triple': data.get('triple', [])
            }
        except Exception as e:
            return None

    def display_status(self):
        """Display current stats"""
        logger.info("=" * 80)
        logger.info(f"  TRIANGULAR ARBITRAGE STATUS")
        logger.info("=" * 80)
        logger.info(f"Opportunities seen: {self.stats['opportunities_seen']}")
        logger.info(f"Profitable found: {self.stats['profitable_found']}")
        logger.info(f"Trades executed: {self.stats['trades_executed']}")
        logger.info(f"Total volume: €{self.stats['total_volume']:.2f} / €{self.config['volume_limit_eur']}")
        logger.info(f"Total profit: €{self.stats['total_profit']:.4f}")
        logger.info("=" * 80)

    def run(self):
        """Main loop: monitor log and execute profitable opportunities"""
        logger.info("Starting triangular arbitrage monitor...")

        # Check balance
        balance = self.get_current_balance()
        if balance:
            eur = balance.get('EUR', {}).get('free', 0)
            logger.info(f"Current EUR balance: €{eur:.2f}")

        status_interval = 60  # Display status every minute
        last_status = time.time()

        try:
            while True:
                # Check if volume limit reached
                if self.stats['total_volume'] >= self.config['volume_limit_eur']:
                    logger.warning(f"⚠️  Volume limit reached: €{self.stats['total_volume']:.2f}")
                    logger.warning("Stopping to stay under €10k limit")
                    break

                # Read new candidates
                if not os.path.exists(self.candidate_log):
                    time.sleep(self.config['check_interval'])
                    continue

                with open(self.candidate_log, 'r') as f:
                    f.seek(self.last_position)
                    lines = f.readlines()
                    self.last_position = f.tell()

                # Process new candidates
                for line in lines:
                    candidate = self.parse_candidate(line)
                    if not candidate:
                        continue

                    self.stats['opportunities_seen'] += 1

                    # ⚠️  CRITICAL: Skip USDT routes (restricted for NL)
                    triple = candidate.get('triple', [])
                    if any('USDT' in pair for pair in triple):
                        logger.debug(f"⚠️  Skipping USDT route (restricted for NL): {triple}")
                        continue

                    # SANITY CHECK: Skip obviously bad data (edge > 100% is data error)
                    if candidate['edge_pct'] > 100:
                        logger.debug(f"⚠️  Skipping invalid edge: {candidate['edge_pct']:.2f}% (data error)")
                        continue

                    # ✅ USE MONITOR'S CALCULATION: profit_pct_after_fees already includes slippage & fees
                    profit_after_fees = candidate.get('profit_pct_after_fees')
                    if profit_after_fees is None:
                        # Fallback to old calculation if monitor didn't provide it
                        calc = self.calculate_profit(candidate['edge_pct'])
                        profit_after_fees = float(calc['net_edge_pct'])

                    # Check if profitable (need positive profit after fees)
                    min_profit_pct = float(self.config['min_profit_eur'] / self.config['capital_eur'] * 100)

                    if profit_after_fees > min_profit_pct:
                        self.stats['profitable_found'] += 1
                        logger.info(f"💰 PROFITABLE: {' → '.join(candidate['route'])}")
                        logger.info(f"   Edge: {candidate['edge_pct']:.3f}% | After fees/slippage: {profit_after_fees:.3f}%")

                        # Execute trade
                        self.execute_triangular_trade(candidate['route'], candidate['edge_pct'])
                    else:
                        logger.debug(f"⏭️  Skipping unprofitable: {' → '.join(candidate['route'])} - profit_after_fees={profit_after_fees:.3f}%")

                # Display status periodically
                if time.time() - last_status >= status_interval:
                    self.display_status()
                    last_status = time.time()

                time.sleep(self.config['check_interval'])

        except KeyboardInterrupt:
            logger.info("\n⚠️  Stopped by user")
        finally:
            self.display_status()
            logger.info("✓ Bot stopped")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Triangular Arbitrage Executor (0% Fees)')
    parser.add_argument('--live', action='store_true', help='Live trading mode (default: dry-run)')
    args = parser.parse_args()

    executor = LiveTriangularExecutor(dry_run=not args.live)
    executor.run()
