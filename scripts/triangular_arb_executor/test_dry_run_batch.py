#!/usr/bin/env python3
"""
Quick test: Process all candidates from tri_candidates.log with dry-run simulation.
"""

import json
import logging
import os
import sys
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    import ccxt
except ImportError:
    print("ERROR: ccxt not installed. Run: pip install ccxt")
    sys.exit(1)


class QuickDryRun:
    def __init__(self):
        self.exchange = ccxt.kraken()
        self.candidate_log = os.path.join(ROOT, 'logs', 'tri_candidates.log')
        self.output_log = os.path.join(ROOT, 'logs', 'dry_run_executions.log')

        self.config = {
            'min_edge_pct_to_execute': Decimal('0.10'),
            'order_size_eur': Decimal('100'),
            'slippage_pct': Decimal('0.3'),
            'taker_fee_pct': Decimal('0.26'),
        }

        self.simulated_trades = []
        logger.info(f"Candidate log: {self.candidate_log}")
        logger.info(f"Output log: {self.output_log}")

    def get_mid_price(self, pair):
        """Fetch current mid-price for a pair."""
        try:
            ticker = self.exchange.fetch_ticker(pair)
            bid = Decimal(str(ticker['bid']))
            ask = Decimal(str(ticker['ask']))
            mid = (bid + ask) / Decimal('2')
            return mid
        except Exception as e:
            logger.debug(f"Failed to fetch {pair}: {e}")
            return None

    def simulate_trade(self, pair1, pair2, pair3, start_amount_eur):
        """Simulate triangular trade."""
        try:
            p1 = self.get_mid_price(pair1)
            p2 = self.get_mid_price(pair2)
            p3 = self.get_mid_price(pair3)

            if not all([p1, p2, p3]):
                return None

            amount = start_amount_eur
            slippage_factor = Decimal('1') + (self.config['slippage_pct'] / Decimal('100'))

            # Leg 1: Buy
            amount = amount / (p1 * slippage_factor)
            fee = amount * (self.config['taker_fee_pct'] / Decimal('100'))
            amount -= fee

            # Leg 2: Buy
            amount = amount / (p2 * slippage_factor)
            fee = amount * (self.config['taker_fee_pct'] / Decimal('100'))
            amount -= fee

            # Leg 3: Sell
            amount = amount * p3 / slippage_factor
            fee = amount * (self.config['taker_fee_pct'] / Decimal('100'))
            amount -= fee

            edge = amount - start_amount_eur
            edge_pct = (edge / start_amount_eur) * Decimal('100') if start_amount_eur != 0 else Decimal('0')

            return {
                'route': (pair1, pair2, pair3),
                'start_amount': float(start_amount_eur),
                'final_amount': float(amount),
                'edge': float(edge),
                'edge_pct': float(edge_pct),
            }
        except Exception as e:
            logger.debug(f"Simulation error: {e}")
            return None

    def process_batch(self, limit=100):
        """Process first N candidates from the log."""
        count = 0
        count_executed = 0

        logger.info(f"Reading up to {limit} candidates from log...")

        try:
            with open(self.candidate_log, 'r', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        candidate = json.loads(line)
                        triple = candidate.get('triple')
                        edge_pct = Decimal(str(candidate.get('edge_pct', 0)))

                        if edge_pct >= self.config['min_edge_pct_to_execute']:
                            logger.info(f"[{count + 1}] Testing: {triple} (edge: {edge_pct:.4f}%)")

                            result = self.simulate_trade(
                                triple[0], triple[1], triple[2],
                                self.config['order_size_eur']
                            )

                            if result:
                                count_executed += 1
                                self.simulated_trades.append(result)
                                logger.info(f"  ✓ Sim result: {result['edge_pct']:.4f}% edge")

                                # Log to file
                                with open(self.output_log, 'a') as out:
                                    out.write(json.dumps(result) + '\n')

                        count += 1
                        if count >= limit:
                            break
                    except Exception as e:
                        logger.debug(f"Line parse error: {e}")
                        continue
        except FileNotFoundError:
            logger.error(f"Candidate log not found: {self.candidate_log}")
            return

        logger.info(f"\n========== BATCH SUMMARY ==========")
        logger.info(f"Candidates read: {count}")
        logger.info(f"Simulated trades: {count_executed}")

        if count_executed > 0:
            avg_edge = sum(t['edge_pct'] for t in self.simulated_trades) / count_executed
            max_edge = max(t['edge_pct'] for t in self.simulated_trades)
            logger.info(f"Avg edge: {avg_edge:.4f}%")
            logger.info(f"Max edge: {max_edge:.4f}%")
            logger.info(f"Output: {self.output_log}")


if __name__ == '__main__':
    executor = QuickDryRun()
    executor.process_batch(limit=200)
