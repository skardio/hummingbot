#!/usr/bin/env python3
"""
Simple dry-run: Process candidates from log with STATIC simulation (no live prices).
This shows what the expected profit would be based on the logged edge %,
with conservative slippage/fee adjustments.
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


class SimpleStaticDryRun:
    def __init__(self):
        self.candidate_log = os.path.join(ROOT, 'logs', 'tri_candidates.log')
        self.output_log = os.path.join(ROOT, 'logs', 'dry_run_executions.log')

        self.config = {
            'min_edge_pct_to_execute': Decimal('0.10'),
            'order_size_eur': Decimal('100'),
            'slippage_adjustment': Decimal('0.15'),  # Reduce logged edge by 0.15% for safety
        }

        self.simulated_trades = []
        logger.info(f"Candidate log: {self.candidate_log}")
        logger.info(f"Output log: {self.output_log}")
        logger.info(f"Min edge: {self.config['min_edge_pct_to_execute']}%")
        logger.info(f"Slippage adjustment: {self.config['slippage_adjustment']}%")

    def static_simulate(self, triple, logged_edge_pct):
        """
        Use the logged edge as basis for profit simulation.
        Apply slippage adjustment to be conservative.
        """
        logged_edge = Decimal(str(logged_edge_pct))
        adjusted_edge = logged_edge - self.config['slippage_adjustment']

        if adjusted_edge <= Decimal('0'):
            # Would lose money after slippage
            return None

        start_amount = self.config['order_size_eur']
        profit = start_amount * (adjusted_edge / Decimal('100'))
        final_amount = start_amount + profit

        return {
            'route': triple,
            'start_amount': float(start_amount),
            'final_amount': float(final_amount),
            'edge': float(profit),
            'edge_pct': float(adjusted_edge),
            'simulation_type': 'static_conservative',
        }

    def process_batch(self, limit=500):
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
                        logged_edge_pct = Decimal(str(candidate.get('edge_pct', 0)))

                        if logged_edge_pct >= self.config['min_edge_pct_to_execute']:
                            result = self.static_simulate(triple, logged_edge_pct)

                            if result:
                                count_executed += 1
                                self.simulated_trades.append(result)

                                if count_executed <= 20:  # Log first 20
                                    logger.info(f"[{count_executed}] {triple}: {result['edge_pct']:.4f}% edge → {result['edge']:.2f} EUR profit")

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

        logger.info(f"\n========== DRY-RUN BATCH SUMMARY ==========")
        logger.info(f"Candidates read: {count}")
        logger.info(f"Simulated trades: {count_executed}")

        if count_executed > 0:
            total_profit = sum(t['edge'] for t in self.simulated_trades)
            avg_edge = sum(t['edge_pct'] for t in self.simulated_trades) / count_executed
            max_edge = max(t['edge_pct'] for t in self.simulated_trades)
            logger.info(f"Total potential profit: {total_profit:.2f} EUR")
            logger.info(f"Avg edge: {avg_edge:.4f}%")
            logger.info(f"Max edge: {max_edge:.4f}%")
            logger.info(f"Output saved to: {self.output_log}")


if __name__ == '__main__':
    executor = SimpleStaticDryRun()
    executor.process_batch(limit=1000)
