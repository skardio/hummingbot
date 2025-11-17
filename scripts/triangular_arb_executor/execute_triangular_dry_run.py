#!/usr/bin/env python3
"""
Triangular Arbitrage DRY-RUN Executor for Kraken (ccxt-based).

This script monitors the Kraken candidate log and SIMULATES execution
without placing real orders. Safe for testing and validation.

Usage:
  export KRAKEN_API_KEY="your_key"
  export KRAKEN_SECRET_KEY="your_secret"
  python3 scripts/execute_triangular_dry_run.py

Features:
  - Reads candidate opportunities from logs/tri_candidates.log (real-time)
  - Simulates order execution with current order book prices
  - Logs simulated trades to logs/dry_run_executions.log
  - NO real orders placed
  - Safe to run 24/7 for testing

Configuration:
  Edit CONFIG below to customize behavior
"""

import asyncio
import json
import logging
import os
import sys
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


class DryRunExecutor:
    """Dry-run executor for triangular arbitrage on Kraken."""

    CONFIG = {
        'exchange_name': 'kraken',
        'polling_interval': 10.0,  # seconds
        'min_edge_pct_to_execute': Decimal('0.10'),  # only simulate trades > 0.1% edge
        'order_size_eur': Decimal('100'),  # simulate 100 EUR per trade
        'slippage_pct': Decimal('0.3'),  # add 0.3% slippage to simulation
        'taker_fee_pct': Decimal('0.26'),  # Kraken taker fee
        'max_simulations_per_cycle': 5,  # max simulations per poll cycle
    }

    def __init__(self):
        self.exchange = None
        self.last_log_pos = 0
        self.processed_candidates = deque(maxlen=100)
        self.simulated_trades = []

        # Setup logging
        logs_dir = os.path.join(ROOT, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        self.log_file = os.path.join(logs_dir, 'dry_run_executions.log')
        self.candidate_log = os.path.join(logs_dir, 'tri_candidates.log')

        logger.info(f"DryRunExecutor initialized")
        logger.info(f"Candidate log: {self.candidate_log}")
        logger.info(f"Execution log: {self.log_file}")

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
            logger.info("Kraken exchange initialized via ccxt")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Kraken: {e}")
            return False

    def get_mid_price(self, pair):
        """Get mid-price for a pair (bid+ask)/2."""
        try:
            ticker = self.exchange.fetch_ticker(pair)
            bid = Decimal(str(ticker['bid']))
            ask = Decimal(str(ticker['ask']))
            mid = (bid + ask) / Decimal('2')
            return mid
        except Exception as e:
            logger.warning(f"Failed to fetch mid-price for {pair}: {e}")
            return None

    def simulate_trade(self, pair1, pair2, pair3, start_amount_eur):
        """
        Simulate a triangular trade execution.

        Returns: {
            'route': (pair1, pair2, pair3),
            'start_amount': float,
            'final_amount': float,
            'edge': float,
            'edge_pct': float,
            'simulated_prices': (p1, p2, p3),
        }
        """
        try:
            # Fetch mid prices
            p1 = self.get_mid_price(pair1)
            p2 = self.get_mid_price(pair2)
            p3 = self.get_mid_price(pair3)

            if not all([p1, p2, p3]):
                return None

            # Simulate execution with slippage
            amount = start_amount_eur
            slippage_factor = Decimal('1') + (self.CONFIG['slippage_pct'] / Decimal('100'))

            # Leg 1: Buy with slippage and fee
            amount_after_leg1 = amount / (p1 * slippage_factor)
            fee1 = amount_after_leg1 * (self.CONFIG['taker_fee_pct'] / Decimal('100'))
            amount_after_leg1 -= fee1

            # Leg 2: Buy with slippage and fee
            amount_after_leg2 = amount_after_leg1 / (p2 * slippage_factor)
            fee2 = amount_after_leg2 * (self.CONFIG['taker_fee_pct'] / Decimal('100'))
            amount_after_leg2 -= fee2

            # Leg 3: Sell with slippage and fee
            amount_after_leg3 = amount_after_leg2 * p3 / slippage_factor
            fee3 = amount_after_leg3 * (self.CONFIG['taker_fee_pct'] / Decimal('100'))
            amount_after_leg3 -= fee3

            edge = amount_after_leg3 - amount
            edge_pct = (edge / amount) * Decimal('100') if amount != 0 else Decimal('0')

            return {
                'route': (pair1, pair2, pair3),
                'start_amount': float(amount),
                'final_amount': float(amount_after_leg3),
                'edge': float(edge),
                'edge_pct': float(edge_pct),
                'simulated_prices': (float(p1), float(p2), float(p3)),
            }
        except Exception as e:
            logger.warning(f"Error simulating {pair1}/{pair2}/{pair3}: {e}")
            return None

    def read_new_candidates(self):
        """Read new candidate lines from the log file."""
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
                            candidate_key = tuple(record.get('triple', []))
                            if candidate_key not in self.processed_candidates:
                                candidates.append(record)
                                self.processed_candidates.append(candidate_key)
                        except json.JSONDecodeError:
                            continue

                self.last_log_pos = f.tell()
        except Exception as e:
            logger.error(f"Error reading candidate log: {e}")

        return candidates

    def log_simulation(self, result):
        """Log a simulated trade execution."""
        record = {
            'timestamp': datetime.utcnow().isoformat(),
            'type': 'dry_run_simulation',
            'pair1': result['route'][0],
            'pair2': result['route'][1],
            'pair3': result['route'][2],
            'start_amount_eur': result['start_amount'],
            'final_amount_eur': result['final_amount'],
            'edge_eur': result['edge'],
            'edge_pct': result['edge_pct'],
            'prices': result['simulated_prices'],
            'status': 'would_execute' if result['edge_pct'] > float(self.CONFIG['min_edge_pct_to_execute']) else 'below_threshold',
        }

        try:
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(record) + '\n')
            self.simulated_trades.append(record)
        except Exception as e:
            logger.error(f"Failed to log simulation: {e}")

    async def run_cycle(self):
        """Run one cycle: read candidates, simulate trades."""
        candidates = self.read_new_candidates()

        if not candidates:
            return 0

        simulated = 0
        for candidate in candidates[:self.CONFIG['max_simulations_per_cycle']]:
            triple = candidate.get('triple', [])
            if len(triple) != 3:
                continue

            result = self.simulate_trade(
                triple[0],
                triple[1],
                triple[2],
                self.CONFIG['order_size_eur']
            )

            if result:
                self.log_simulation(result)

                if result['edge_pct'] > float(self.CONFIG['min_edge_pct_to_execute']):
                    logger.info(
                        f"WOULD EXECUTE: {triple[0]} → {triple[1]} → {triple[2]} "
                        f"(edge: {result['edge_pct']:.4f}%, final: {result['final_amount']:.2f} EUR)"
                    )

                simulated += 1

        return simulated

    async def run(self):
        """Main loop."""
        logger.info("Starting DRY-RUN executor (no real trades)")
        logger.info(f"Configuration: {self.CONFIG}")

        if not self.init_exchange():
            logger.error("Failed to initialize exchange. Exiting.")
            return

        cycle = 0
        try:
            while True:
                cycle += 1
                simulated = await self.run_cycle()

                if simulated > 0:
                    logger.info(f"Cycle #{cycle}: simulated {simulated} trades")
                else:
                    logger.debug(f"Cycle #{cycle}: no new candidates")

                await asyncio.sleep(self.CONFIG['polling_interval'])

        except KeyboardInterrupt:
            logger.info("\nDry-run executor stopped (Ctrl+C)")
            logger.info(f"Total simulations: {len(self.simulated_trades)}")

            # Print summary
            would_execute = [t for t in self.simulated_trades if t['status'] == 'would_execute']
            if would_execute:
                logger.info(f"\nWould have executed: {len(would_execute)} trades")
                avg_edge = sum(t['edge_pct'] for t in would_execute) / len(would_execute)
                max_edge = max(t['edge_pct'] for t in would_execute)
                logger.info(f"  Avg edge: {avg_edge:.4f}%, Max edge: {max_edge:.4f}%")


def main():
    executor = DryRunExecutor()
    asyncio.run(executor.run())


if __name__ == '__main__':
    main()
