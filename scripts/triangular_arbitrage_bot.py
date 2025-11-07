"""Triangular arbitrage detection + paper-trade execution script

Lightweight script inspired by Hummingbot internals. It detects triangular arbitrage
opportunities for triples of trading pairs on a single exchange and can optionally
execute them in paper-trade mode using Hummingbot's paper trade market connectors.

Usage:
 - Edit the CONFIG dict below or place similar values in a YAML file and modify the script.
 - Run from repository root: python scripts/triangular_arbitrage_bot.py

This script is intentionally conservative: by default it only detects and logs
opportunities. Set `execute_trades=True` to simulate execution in paper-trade markets.
"""
import asyncio
import logging
from decimal import Decimal
from typing import List, Tuple

from hummingbot.connector.exchange.paper_trade import create_paper_trade_market
from hummingbot.core.data_type.common import PriceType

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Simple config - update as needed
CONFIG = {
    "exchange": "kraken",
    # Each triple: three trading pairs (A-B, B-C, A-C) where pairs are in Hummingbot format BASE-QUOTE
    # Example: ETH-BTC, BTC-USD, ETH-USD
    "triples": [
        ["ETH-BTC", "BTC-USD", "ETH-USD"],
    ],
    "order_amount": Decimal("0.01"),  # amount in base currency A for each check
    "min_profitability_pct": Decimal("0.5"),  # percent threshold to report (0.5 = 0.5%)
    "poll_interval": 5.0,  # seconds
    "execute_trades": False,  # set to True to run paper-trade execution
}


def compute_implied_price(price_ab: Decimal, price_bc: Decimal) -> Decimal:
    """Compute implied A->C price via A->B->C path (price expressed as quote per base).
    If price_ab is (B per A) and price_bc is (C per B) then implied price AC = price_ab * price_bc.
    """
    return price_ab * price_bc


async def monitor_loop(config):
    exchange = config["exchange"]
    triples: List[List[str]] = config["triples"]
    order_amount: Decimal = config["order_amount"]
    min_profit = config["min_profitability_pct"] / Decimal("100")
    poll_interval = config["poll_interval"]
    execute_trades = config["execute_trades"]

    # Create a paper-trade market (uses internal paper-trade connector implementation)
    unique_pairs = set(p for triple in triples for p in triple)
    market = create_paper_trade_market(exchange, list(unique_pairs))

    logger.info("Starting triangular arbitrage monitor for exchange=%s", exchange)

    while True:
        try:
            for triple in triples:
                a_b, b_c, a_c = triple
                try:
                    price_ab = Decimal(str(market.get_price_by_type(a_b, PriceType.MidPrice)))
                    price_bc = Decimal(str(market.get_price_by_type(b_c, PriceType.MidPrice)))
                    price_ac = Decimal(str(market.get_price_by_type(a_c, PriceType.MidPrice)))
                except Exception as e:
                    logger.debug("Error obtaining prices for triple %s: %s", triple, e)
                    continue

                implied_ac = compute_implied_price(price_ab, price_bc)

                # relative edge: (implied - actual) / actual
                if price_ac == 0:
                    continue
                edge = (implied_ac - price_ac) / price_ac

                if edge > min_profit:
                    logger.info("Arbitrage detected for triple %s: implied_ac=%.8f actual_ac=%.8f edge=%.4f%%",
                                triple, implied_ac, price_ac, float(edge * 100))

                    if execute_trades:
                        logger.info("Simulating execution of cycle %s amount=%s", triple, order_amount)
                        # Very conservative simulated execution: we compute expected end amount after sequential trades
                        # This does NOT execute real orders on exchanges. Replace with live connector calls only after tests.
                        amount_a = order_amount
                        # A -> B: sell A at price_ab => receive B = amount_a * price_ab
                        amount_b = amount_a * price_ab
                        # B -> C: sell B at price_bc => receive C = amount_b * price_bc
                        amount_c = amount_b * price_bc
                        # C -> A: buy A with C at direct A-C price => receive A_final = amount_c / price_ac
                        amount_a_final = amount_c / price_ac if price_ac > 0 else Decimal("0")
                        profit = amount_a_final - amount_a
                        logger.info("Simulated cycle result: start A=%.8f end A=%.8f profit=%.8f (%.4f%%)",
                                    amount_a, amount_a_final, profit, float((profit / amount_a) * 100))
                # else: no arbitrage

            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected error in monitor loop, continuing")


def main():
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(monitor_loop(CONFIG))
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting")


if __name__ == "__main__":
    main()
