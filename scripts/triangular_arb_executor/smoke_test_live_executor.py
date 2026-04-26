#!/usr/bin/env python3
"""Quick smoke test for LiveExecutor without real exchange orders.

This script runs one end-to-end executor cycle by:
- writing one synthetic candidate to a temporary log file
- monkeypatching bid/ask lookups with deterministic prices
- executing run_cycle() in dry-run mode

Usage:
  source ~/.venvs/bot/bin/activate
  python scripts/triangular_arb_executor/smoke_test_live_executor.py
"""

import asyncio
import json
import os
import sys
import tempfile
from decimal import Decimal

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if THIS_DIR not in sys.path:
    sys.path.insert(0, THIS_DIR)

from execute_triangular_live import LiveExecutor  # noqa: E402


def _price_map():
    return {
        "ETH-EUR": (Decimal("3498.0"), Decimal("3500.0")),
        "ETH-USD": (Decimal("3798.0"), Decimal("3800.0")),
        "EUR-USD": (Decimal("1.0850"), Decimal("1.0860")),
    }


async def _run_smoke_test() -> int:
    executor = LiveExecutor()

    # Force dry-run and deterministic thresholds for smoke execution.
    executor.CONFIG["execute_trades"] = False
    executor.CONFIG["min_edge_pct_to_execute"] = Decimal("0.01")
    executor.CONFIG["min_profit_after_costs_pct"] = Decimal("0.01")
    executor.CONFIG["order_size_eur"] = Decimal("50")

    # Monkeypatch bid/ask lookup to avoid live API dependency.
    prices = _price_map()

    def fake_get_bid_ask(pair: str):
        return prices.get(pair, (None, None))

    executor.get_bid_ask = fake_get_bid_ask

    candidate = {
        "timestamp": "2026-04-22T12:00:00Z",
        "triple": ["ETH-EUR", "ETH-USD", "EUR-USD"],
        "edge_pct": 0.20,
        "profit_pct_after_fees": 0.12,
    }

    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as tmp:
        tmp.write(json.dumps(candidate) + "\n")
        tmp_path = tmp.name

    try:
        executor.candidate_log = tmp_path
        executed_count = await executor.run_cycle()

        print("SMOKE TEST RESULT")
        print(f"executed_count={executed_count}")
        print(f"executed_trades={len(executor.executed_trades)}")
        print(f"failed_trades={len(executor.failed_trades)}")

        if executed_count != 1 or len(executor.executed_trades) != 1 or len(executor.failed_trades) != 0:
            print("FAIL: smoke test expected exactly 1 successful simulated execution")
            return 1

        trade = executor.executed_trades[0]
        print(
            "PASS: route executed in dry-run "
            f"with realized_profit_pct={trade.get('realized_profit_pct')}"
        )
        return 0
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def main():
    raise SystemExit(asyncio.run(_run_smoke_test()))


if __name__ == "__main__":
    main()
