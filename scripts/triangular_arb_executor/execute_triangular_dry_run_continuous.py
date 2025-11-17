#!/usr/bin/env python3
"""
Continuous Dry-Run Executor for Triangular Arbitrage.

This script:
1. Continuously monitors tri_candidates.log for new opportunities
2. For each candidate, simulates the trade with detailed breakdown
3. Logs: timestamp, route, edge%, fees, profit, step-by-step calculation
4. NO real orders placed - safe testing
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ContinuousDryRunExecutor:
    def __init__(self):
        self.candidate_log = os.path.join(ROOT, 'logs', 'tri_candidates.log')
        self.output_log = os.path.join(ROOT, 'logs', 'dry_run_continuous.log')

        self.config = {
            'min_edge_pct_to_execute': Decimal('0.05'),  # Log trades > 0.05%
            'order_size_eur': Decimal('79'),  # €79 ALL IN! 🚀
            'taker_fee_pct': Decimal('0.00'),  # 0% fees under €10k volume! 🎉
            'maker_fee_pct': Decimal('0.00'),  # 0% maker fee too
            'slippage_pct_per_leg': Decimal('0.01'),  # 0.01% slippage per leg
        }

        self.last_position = 0
        self.simulated_count = 0

        logger.info("=" * 80)
        logger.info("CONTINUOUS DRY-RUN EXECUTOR STARTED")
        logger.info("=" * 80)
        logger.info(f"Candidate log: {self.candidate_log}")
        logger.info(f"Output log: {self.output_log}")
        logger.info(f"Min edge to log: {self.config['min_edge_pct_to_execute']}%")
        logger.info(f"Order size: {self.config['order_size_eur']} EUR")
        logger.info(f"Taker fee: {self.config['taker_fee_pct']}%")
        logger.info(f"Slippage per leg: {self.config['slippage_pct_per_leg']}%")
        logger.info("=" * 80)

    def calculate_trade_simulation(self, candidate_edge_pct, triple):
        """
        Simulate a triangular trade with detailed breakdown.

        candidate_edge_pct: The edge % from the monitor (already includes market prices)
        We apply realistic slippage & fees to see if it would still be profitable.
        """
        start_eur = self.config['order_size_eur']
        logged_edge = Decimal(str(candidate_edge_pct))

        # Total fees for 3 legs (buy, buy, sell)
        # Each leg has taker fee
        total_fee_pct = self.config['taker_fee_pct'] * Decimal('3')

        # Total slippage (0.2% per leg × 3 legs)
        total_slippage_pct = self.config['slippage_pct_per_leg'] * Decimal('3')

        # Actual profit after deductions
        net_edge_pct = logged_edge - total_fee_pct - total_slippage_pct

        profit_eur = start_eur * (net_edge_pct / Decimal('100'))
        final_eur = start_eur + profit_eur

        return {
            'timestamp': datetime.now().isoformat(),
            'route': triple,
            'logged_edge_pct': float(logged_edge),
            'fee_breakdown': {
                'leg1_fee_pct': float(self.config['taker_fee_pct']),
                'leg2_fee_pct': float(self.config['taker_fee_pct']),
                'leg3_fee_pct': float(self.config['taker_fee_pct']),
                'total_fee_pct': float(total_fee_pct),
            },
            'slippage_breakdown': {
                'leg1_slippage_pct': float(self.config['slippage_pct_per_leg']),
                'leg2_slippage_pct': float(self.config['slippage_pct_per_leg']),
                'leg3_slippage_pct': float(self.config['slippage_pct_per_leg']),
                'total_slippage_pct': float(total_slippage_pct),
            },
            'start_amount_eur': float(start_eur),
            'total_costs_pct': float(total_fee_pct + total_slippage_pct),
            'net_edge_pct': float(net_edge_pct),
            'profit_eur': float(profit_eur),
            'final_amount_eur': float(final_eur),
            'is_profitable': net_edge_pct > Decimal('0'),
        }

    def run_continuous(self):
        """Monitor the log file and process new candidates continuously."""
        logger.info("Entering continuous monitor loop...")
        cycle = 0

        try:
            while True:
                cycle += 1
                new_candidates = 0
                profitable = 0

                try:
                    if not os.path.exists(self.candidate_log):
                        logger.warning(f"Log file not found: {self.candidate_log}")
                        time.sleep(5)
                        continue

                    with open(self.candidate_log, 'r', errors='ignore') as f:
                        f.seek(self.last_position)

                        for line in f:
                            line = line.strip()
                            if not line:
                                continue

                            try:
                                candidate = json.loads(line)
                                triple = candidate.get('triple')
                                edge_pct = candidate.get('edge_pct', 0)

                                if edge_pct >= float(self.config['min_edge_pct_to_execute']):
                                    new_candidates += 1

                                    # Simulate the trade
                                    result = self.calculate_trade_simulation(edge_pct, triple)

                                    # Log to file
                                    with open(self.output_log, 'a') as out:
                                        out.write(json.dumps(result) + '\n')

                                    # Console output
                                    if result['is_profitable']:
                                        profitable += 1
                                        logger.info(
                                            f"✓ PROFIT | {result['route']} | "
                                            f"Logged edge: {result['logged_edge_pct']:.4f}% | "
                                            f"Fees: {result['fee_breakdown']['total_fee_pct']:.4f}% | "
                                            f"Slippage: {result['slippage_breakdown']['total_slippage_pct']:.4f}% | "
                                            f"Net edge: {result['net_edge_pct']:.4f}% | "
                                            f"Profit: €{result['profit_eur']:.4f}"
                                        )
                                    else:
                                        logger.debug(
                                            f"✗ LOSS | {result['route']} | "
                                            f"Logged edge: {result['logged_edge_pct']:.4f}% | "
                                            f"Total costs: {result['total_costs_pct']:.4f}%"
                                        )

                                    self.simulated_count += 1

                            except json.JSONDecodeError:
                                pass  # Skip malformed JSON lines

                        self.last_position = f.tell()

                    # Status log every 10 cycles
                    if cycle % 10 == 0:
                        logger.info(
                            f"[Cycle {cycle}] Processed {self.simulated_count} total candidates "
                            f"({profitable} profitable in this batch)"
                        )

                except Exception as e:
                    logger.error(f"Error in cycle {cycle}: {e}")

                # Poll interval
                time.sleep(5)

        except KeyboardInterrupt:
            logger.info("\n" + "=" * 80)
            logger.info("CONTINUOUS DRY-RUN STOPPED (Ctrl+C)")
            logger.info(f"Total candidates simulated: {self.simulated_count}")
            logger.info(f"Output log: {self.output_log}")
            logger.info("=" * 80)


if __name__ == '__main__':
    executor = ContinuousDryRunExecutor()
    executor.run_continuous()
