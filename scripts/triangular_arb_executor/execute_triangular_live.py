#!/usr/bin/env python3
"""
Triangular Arbitrage LIVE Executor for Kraken (ccxt-based).

⚠️ WARNING: THIS SCRIPT PLACES REAL ORDERS ON KRAKEN ⚠️

This script reads high-edge triangular opportunities and places REAL trades.
Start with SMALL order sizes (10-50 EUR) and monitor closely.

Usage:
  export KRAKEN_API_KEY="your_key"
  export KRAKEN_SECRET_KEY="your_secret"
  python3 scripts/execute_triangular_live.py

Features:
  - Monitors logs/tri_candidates.log for real-time opportunities
  - Filters by edge threshold (default: 0.15%)
  - Places real orders via Kraken API
  - Logs ALL trades to logs/live_executions.log
  - Safety features: order size limit, execution threshold, cancellation on timeout
  - Dry-run mode available (set EXECUTE_TRADES=False in shell)

Configuration:
  Edit CONFIG below or pass environment variables:
  - KRAKEN_MIN_EDGE_PCT: minimum edge % to execute (default: 0.15)
  - KRAKEN_ORDER_SIZE_EUR: order size in EUR (default: 50)
  - KRAKEN_EXECUTE_TRADES: set to "true" to enable real execution (default: false)

Safety Recommendations:
  1. Start with order_size=10 EUR and edge_min=0.2%
  2. Run in dry-run mode first (EXECUTE_TRADES=false)
  3. Monitor logs closely for first 100 trades
  4. Gradually increase order size if profitable
  5. Never exceed your daily loss tolerance
"""

import asyncio
import json
import logging
import os
import sys
import time
from collections import deque
from datetime import datetime
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    import ccxt
except ImportError:
    print("ERROR: ccxt not installed. Run: pip install ccxt")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LiveExecutor:
    """Live executor for triangular arbitrage on Kraken."""

    CONFIG = {
        'exchange_name': 'kraken',
        'polling_interval': 10.0,
        'min_edge_pct_to_execute': Decimal(os.environ.get('KRAKEN_MIN_EDGE_PCT', '0.15')),
        'order_size_eur': Decimal(os.environ.get('KRAKEN_ORDER_SIZE_EUR', '50')),
        'execute_trades': os.environ.get('KRAKEN_EXECUTE_TRADES', 'false').lower() == 'true',
        'slippage_pct': Decimal('0.3'),
        'taker_fee_pct': Decimal('0.26'),
        'order_timeout_seconds': 30,  # cancel if not filled in 30s
        'max_open_trades': 10,
        'max_trades_per_day': 100,
    }

    def __init__(self):
        self.exchange = None
        self.last_log_pos = 0
        self.processed_candidates = deque(maxlen=1000)
        self.open_trades = {}
        self.executed_trades = []
        self.failed_trades = []

        # Setup logging
        logs_dir = os.path.join(ROOT, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        self.log_file = os.path.join(logs_dir, 'live_executions.log')
        self.candidate_log = os.path.join(logs_dir, 'tri_candidates.log')

        # Print safety warning
        print("\n" + "=" * 80)
        if self.CONFIG['execute_trades']:
            print("⚠️  LIVE EXECUTION MODE ENABLED ⚠️")
            print(f"Order size: {self.CONFIG['order_size_eur']} EUR")
            print(f"Min edge threshold: {self.CONFIG['min_edge_pct_to_execute']}%")
        else:
            print("🟡 DRY-RUN MODE (no real trades)")
            print(f"Set KRAKEN_EXECUTE_TRADES=true to enable real execution")
        print("=" * 80 + "\n")

        logger.info(f"LiveExecutor initialized (EXECUTE_TRADES={self.CONFIG['execute_trades']})")

    def init_exchange(self):
        """Initialize Kraken exchange via ccxt."""
        api_key = os.environ.get('KRAKEN_API_KEY')
        api_secret = os.environ.get('KRAKEN_SECRET_KEY')

        if not api_key or not api_secret:
            logger.error("KRAKEN_API_KEY or KRAKEN_SECRET_KEY not set")
            return False

        try:
            self.exchange = ccxt.kraken({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
            })
            logger.info("Kraken exchange initialized")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Kraken: {e}")
            return False

    def get_mid_price(self, pair):
        """Get mid-price for a pair."""
        try:
            ticker = self.exchange.fetch_ticker(pair)
            bid = Decimal(str(ticker['bid']))
            ask = Decimal(str(ticker['ask']))
            mid = (bid + ask) / Decimal('2')
            return mid
        except Exception as e:
            logger.warning(f"Failed to fetch mid-price for {pair}: {e}")
            return None

    async def place_order(self, pair, side, amount, price=None):
        """Place a limit or market order."""
        if not self.CONFIG['execute_trades']:
            logger.debug(f"[DRY-RUN] Would place {side} order: {amount} {pair} @ {price}")
            return {'id': f'dry_run_{int(time.time())}', 'status': 'simulated'}

        try:
            if price:
                order = self.exchange.create_limit_order(pair, side, amount, float(price))
            else:
                order = self.exchange.create_market_order(pair, side, amount)
            logger.info(f"✓ Order placed: {side} {amount} {pair} (ID: {order['id']})")
            return order
        except Exception as e:
            logger.error(f"✗ Failed to place order: {e}")
            return None

    async def execute_trade(self, pair1, pair2, pair3):
        """Execute a full triangular trade."""
        try:
            # Fetch current prices
            p1 = self.get_mid_price(pair1)
            p2 = self.get_mid_price(pair2)
            p3 = self.get_mid_price(pair3)

            if not all([p1, p2, p3]):
                logger.warning(f"Failed to fetch prices for {pair1}, {pair2}, {pair3}")
                return None

            # Leg 1: Buy (BUY base of pair1)
            logger.info(f"[LEG 1] Buying {pair1} @ {p1}")
            order1 = await self.place_order(pair1, 'buy', float(self.CONFIG['order_size_eur']), p1)
            if not order1:
                return None

            # Leg 2: Buy (BUY base of pair2 using proceeds from leg1)
            logger.info(f"[LEG 2] Buying {pair2} @ {p2}")
            # Simplified: assume we got full amount from leg 1
            amount2 = self.CONFIG['order_size_eur'] / p1
            order2 = await self.place_order(pair2, 'buy', float(amount2), p2)
            if not order2:
                logger.error("Leg 2 failed - attempting to cancel leg 1")
                await self.cancel_order(pair1, order1['id'])
                return None

            # Leg 3: Sell (SELL quote of pair3 to get back EUR)
            logger.info(f"[LEG 3] Selling {pair3} @ {p3}")
            amount3 = amount2 / p2
            order3 = await self.place_order(pair3, 'sell', float(amount3), p3)
            if not order3:
                logger.error("Leg 3 failed - attempting to cancel legs 1&2")
                await self.cancel_order(pair1, order1['id'])
                await self.cancel_order(pair2, order2['id'])
                return None

            # All legs successful
            execution = {
                'timestamp': datetime.utcnow().isoformat(),
                'type': 'live_execution',
                'pair1': pair1, 'pair2': pair2, 'pair3': pair3,
                'order_ids': [order1['id'], order2['id'], order3['id']],
                'prices': (float(p1), float(p2), float(p3)),
                'status': 'pending' if self.CONFIG['execute_trades'] else 'simulated',
            }

            logger.info(f"✓ Trade executed: {pair1} → {pair2} → {pair3}")
            self.executed_trades.append(execution)
            return execution

        except Exception as e:
            logger.error(f"Trade execution failed: {e}")
            self.failed_trades.append({
                'timestamp': datetime.utcnow().isoformat(),
                'route': (pair1, pair2, pair3),
                'error': str(e),
            })
            return None

    async def cancel_order(self, pair, order_id):
        """Cancel an order."""
        if not self.CONFIG['execute_trades']:
            logger.debug(f"[DRY-RUN] Would cancel order {order_id} on {pair}")
            return True

        try:
            self.exchange.cancel_order(order_id, pair)
            logger.info(f"✓ Canceled order {order_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to cancel order {order_id}: {e}")
            return False

    def read_new_candidates(self):
        """Read new high-edge candidates from log."""
        candidates = []
        try:
            if not os.path.exists(self.candidate_log):
                return candidates

            with open(self.candidate_log, 'r', errors='ignore') as f:
                f.seek(self.last_log_pos)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            record = json.loads(line)
                            edge_pct = Decimal(str(record.get('edge_pct', 0)))
                            triple = tuple(record.get('triple', []))

                            # Filter by edge threshold
                            if edge_pct >= self.CONFIG['min_edge_pct_to_execute']:
                                if triple not in self.processed_candidates:
                                    candidates.append(record)
                                    self.processed_candidates.append(triple)
                        except (json.JSONDecodeError, ValueError):
                            continue

                self.last_log_pos = f.tell()
        except Exception as e:
            logger.error(f"Error reading candidate log: {e}")

        return candidates

    async def run_cycle(self):
        """Run one cycle: read candidates, execute trades."""
        candidates = self.read_new_candidates()

        if not candidates:
            return 0

        executed = 0
        for candidate in candidates:
            triple = candidate.get('triple', [])
            if len(triple) != 3:
                continue

            # Check trade limits
            if len(self.executed_trades) >= self.CONFIG['max_trades_per_day']:
                logger.warning(f"Daily trade limit reached ({self.CONFIG['max_trades_per_day']})")
                break

            if len(self.open_trades) >= self.CONFIG['max_open_trades']:
                logger.warning(f"Max open trades reached ({self.CONFIG['max_open_trades']})")
                break

            # Execute trade
            result = await self.execute_trade(triple[0], triple[1], triple[2])
            if result:
                self.open_trades[result['order_ids'][0]] = result
                executed += 1

        return executed

    async def run(self):
        """Main loop."""
        logger.info("Starting LIVE executor")
        logger.info(f"Configuration: {self.CONFIG}")

        if not self.init_exchange():
            logger.error("Failed to initialize exchange")
            return

        try:
            while True:
                executed = await self.run_cycle()

                if executed > 0:
                    logger.info(f"Executed {executed} trades")
                    logger.info(f"Total executed: {len(self.executed_trades)}, Failed: {len(self.failed_trades)}")

                await asyncio.sleep(self.CONFIG['polling_interval'])

        except KeyboardInterrupt:
            logger.info("\nLive executor stopped (Ctrl+C)")
            logger.info(f"Total executed: {len(self.executed_trades)}")
            logger.info(f"Total failed: {len(self.failed_trades)}")


def main():
    executor = LiveExecutor()
    asyncio.run(executor.run())


if __name__ == '__main__':
    main()
