#!/usr/bin/env python3
"""
Continuous Dry-Run Executor for Triangular Arbitrage.
Monitors tri_candidates.log in real-time and simulates execution with detailed breakdown.
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
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ContinuousDryRun:
    def __init__(self):
        self.candidate_log = os.path.join(ROOT, 'logs', 'tri_candidates.log')
        self.output_log = os.path.join(ROOT, 'logs', 'dry_run_continuous.log')

        self.config = {
            'min_edge_pct_to_execute': Decimal('0.10'),
            'order_size_eur': Decimal('100'),
            'slippage_pct': Decimal('0.30'),  # 0.30% per leg
            'taker_fee_pct': Decimal('0.26'),  # Kraken fee per leg
        }

        self.last_log_pos = 0
        self.processed_count = 0
        self.executed_count = 0
        self.total_profit = Decimal('0')

        logger.info(f"Candidate log: {self.candidate_log}")
        logger.info(f"Output log: {self.output_log}")
        logger.info(f"Config: min_edge={self.config['min_edge_pct_to_execute']}%, slippage={self.config['slippage_pct']}%, fee={self.config['taker_fee_pct']}%")
        logger.info("Starting continuous dry-run executor...\n")

    def detailed_simulate(self, triple, logged_edge_pct, timestamp):
        """
        Detailed simulation: logged_edge_pct represents the profit opportunity.
        We apply conservative adjustments (slippage + fees) to estimate real profit.
        """
        try:
            start_amount = self.config['order_size_eur']
            logged_edge = Decimal(str(logged_edge_pct))

            # The logged edge is the theoretical profit %
            # Apply conservative adjustments:
            # - Slippage cost: 0.30% per leg × 3 legs = 0.90%
            # - Fees: 0.26% per leg × 3 legs = 0.78%
            # - Total expected cost: ~1.68%
            total_cost_pct = (self.config['slippage_pct'] * Decimal('3')) + (self.config['taker_fee_pct'] * Decimal('3'))

            # Real profit = logged edge - costs
            real_edge = logged_edge - total_cost_pct

            if real_edge <= Decimal('0'):
                return None  # Would be unprofitable

            # Calculate amounts at each stage
            final_amount = start_amount * (Decimal('1') + (real_edge / Decimal('100')))
            total_profit = final_amount - start_amount
            total_cost = start_amount * (total_cost_pct / Decimal('100'))

            # Breakdown per leg (for display)
            leg_cost_pct = total_cost_pct / Decimal('3')
            leg_cost = start_amount * (leg_cost_pct / Decimal('100'))

            return {
                'timestamp': timestamp,
                'route': triple,
                'market_data': {
                    'logged_edge_pct': float(logged_edge),
                },
                'cost_breakdown': {
                    'slippage_pct_total': float(self.config['slippage_pct'] * Decimal('3')),
                    'fees_pct_total': float(self.config['taker_fee_pct'] * Decimal('3')),
                    'total_cost_pct': float(total_cost_pct),
                    'cost_per_leg_pct': float(leg_cost_pct),
                    'cost_per_leg_eur': float(leg_cost),
                },
                'profit_calculation': {
                    'theoretical_profit_pct': float(logged_edge),
                    'minus_costs_pct': float(total_cost_pct),
                    'real_edge_pct': float(real_edge),
                },
                'execution': {
                    'start_amount': float(start_amount),
                    'total_costs': float(total_cost),
                    'final_amount': float(final_amount),
                    'profit': float(total_profit),
                    'edge_pct': float(real_edge),
                    'roi': float((total_profit / start_amount) * Decimal('100')),
                    'profitable': total_profit > Decimal('0'),
                }
            }
        except Exception as e:
            logger.debug(f"Simulation error: {e}")
            return None

    def read_new_candidates(self):
        """Read new candidates from the log file since last position."""
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
                            candidate = json.loads(line)
                            candidates.append(candidate)
                        except json.JSONDecodeError:
                            continue

                self.last_log_pos = f.tell()
        except Exception as e:
            logger.error(f"Error reading log: {e}")

        return candidates

    def process_candidates(self, candidates):
        """Process a batch of new candidates."""
        for candidate in candidates:
            triple = candidate.get('triple')
            logged_edge_pct = candidate.get('edge_pct', 0)
            timestamp = candidate.get('timestamp', '')

            self.processed_count += 1

            # Only simulate if edge is high enough
            if Decimal(str(logged_edge_pct)) >= self.config['min_edge_pct_to_execute']:
                result = self.detailed_simulate(triple, logged_edge_pct, timestamp)

                if result:
                    self.executed_count += 1
                    profit = Decimal(str(result['summary']['final_profit']))
                    self.total_profit += profit

                    # Log to file
                    with open(self.output_log, 'a') as out:
                        out.write(json.dumps(result) + '\n')

                    # Log to console (every execution)
                    logger.info(
                        f"[{self.executed_count}] {timestamp} | {triple}\n"
                        f"  Market opportunity: {result['market_data']['logged_edge_pct']:.4f}%\n"
                        f"  Costs breakdown:\n"
                        f"    - Slippage (0.30% × 3 legs): {result['cost_breakdown']['slippage_pct_total']:.2f}%\n"
                        f"    - Fees (0.26% × 3 legs): {result['cost_breakdown']['fees_pct_total']:.2f}%\n"
                        f"    - Total cost: {result['cost_breakdown']['total_cost_pct']:.2f}%\n"
                        f"  Profit calculation:\n"
                        f"    {result['profit_calculation']['theoretical_profit_pct']:.4f}% (opportunity) - {result['profit_calculation']['minus_costs_pct']:.2f}% (costs) = {result['profit_calculation']['real_edge_pct']:.4f}% (real)\n"
                        f"  Execution:\n"
                        f"    Start: €{result['execution']['start_amount']:.2f}\n"
                        f"    Costs: €{result['execution']['total_costs']:.4f}\n"
                        f"    Final: €{result['execution']['final_amount']:.2f}\n"
                        f"    ➜ Profit: €{result['execution']['profit']:.4f} (ROI: {result['execution']['roi']:.4f}%)\n"
                    )

    def run(self, poll_interval=5):
        """Continuous run loop."""
        logger.info(f"Polling interval: {poll_interval}s\n")
        logger.info("=" * 80)

        try:
            while True:
                candidates = self.read_new_candidates()

                if candidates:
                    logger.info(f"\n[{datetime.now().strftime('%H:%M:%S')}] Processing {len(candidates)} new candidates...")
                    self.process_candidates(candidates)

                    logger.info(
                        f"Status: {self.processed_count} candidates read, "
                        f"{self.executed_count} executed, "
                        f"€{float(self.total_profit):.2f} total profit"
                    )
                    logger.info("=" * 80)

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("\n\nDry-run stopped (Ctrl+C)")
            logger.info(f"\nFinal Summary:")
            logger.info(f"  Total candidates: {self.processed_count}")
            logger.info(f"  Simulated trades: {self.executed_count}")
            logger.info(f"  Total profit: €{float(self.total_profit):.2f}")
            logger.info(f"  Output: {self.output_log}")


if __name__ == '__main__':
    executor = ContinuousDryRun()
    executor.run(poll_interval=5)
