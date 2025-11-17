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
import os
import sys

# Add hummingbot repo root to path so we can import hummingbot modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

import asyncio
import importlib
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal
from typing import List, Tuple

from hummingbot.client.settings import AllConnectorSettings
from hummingbot.connector.exchange.paper_trade import create_paper_trade_market
from hummingbot.core.data_type.common import PriceType

logging.basicConfig(level=logging.DEBUG, force=True)
logger = logging.getLogger(__name__)

# Developer mode: ensure all existing loggers run at DEBUG level so you see
# internal library/debug output while developing. This forces verbose output
# across modules (may be very noisy); to limit output later, set root logger
# level or configure module-specific levels.
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)
try:
    for lname in list(logging.root.manager.loggerDict.keys()):
        try:
            logging.getLogger(lname).setLevel(logging.DEBUG)
        except Exception:
            # ignore loggers we can't set
            pass
except Exception:
    # defensive: some logging manager implementations might behave unexpectedly
    pass


# Simple config - update as needed
CONFIG = {
    "exchange": "kraken",  # Use Kraken connector for data (Bitstamp doesn't have good Hummingbot integration yet)
    # Each triple: three trading pairs (A-B, B-C, A-C) where pairs are in Hummingbot format BASE-QUOTE
    # Routes adapted for Bitstamp (which has different pair support than Kraken)
    # Bitstamp supports: BTC, ETH, USDC, EUR, GBP, USD, USDT, XRP, LTC, BCH, XLM, etc.
    # Bot will continuously monitor and report when profit edge > min_profitability_pct
    "triples": [
        # === ETH Routes ===
        ["ETH-EUR", "EUR-USD", "ETH-USD"],
        ["ETH-USDC", "USDC-EUR", "ETH-EUR"],
        ["ETH-USDC", "USDC-USD", "ETH-USD"],
        ["ETH-USDC", "USDC-USDT", "ETH-USDT"],
        ["ETH-USDT", "USDT-EUR", "ETH-EUR"],
        ["ETH-USDT", "USDT-USD", "ETH-USD"],
        ["ETH-EUR", "EUR-GBP", "ETH-GBP"],
        ["ETH-USDC", "USDC-GBP", "ETH-GBP"],
        ["ETH-USDT", "USDT-GBP", "ETH-GBP"],
        ["ETH-GBP", "GBP-USD", "ETH-USD"],
        # === USDC Routes ===
        ["USDC-USDT", "USDT-USD", "USDC-USD"],
        ["USDC-EUR", "EUR-USD", "USDC-USD"],
        ["USDC-USDT", "USDT-EUR", "USDC-EUR"],
        ["USDC-USDT", "USDT-GBP", "USDC-GBP"],
        ["USDC-GBP", "GBP-USD", "USDC-USD"],
        # === EUR Routes ===
        ["EUR-GBP", "GBP-USD", "EUR-USD"],
        # === BTC Routes ===
        ["BTC-EUR", "EUR-USD", "BTC-USD"],
        ["BTC-GBP", "GBP-USD", "BTC-USD"],
        # === Additional stable routes ===
        ["USDT-EUR", "EUR-USD", "USDT-USD"],
        ["USDT-GBP", "GBP-USD", "USDT-USD"],
    ],
    "order_amount": Decimal("1.0"),  # UNUSED: Set to 1.0 (ignored). Dynamic allocation from available balance is used instead.
    "order_amount_pct": Decimal("1.0"),  # Use 100% of available base currency A balance for each arbitrage cycle
    "min_profitability_pct": Decimal("0.0"),  # Set to 0.0 to catch any positive opportunity (even tiny ones)
    "poll_interval": 5.0,  # seconds between each polling cycle
    "execute_trades": False,  # False = monitoring only (log candidates); True = paper-trade execution
    "use_paper_trade": True,  # Use paper-trade market for live-feed monitoring
    # Fee and slippage estimation used for pre-execution checks (percent)
    # taker_fee_pct: percent fee charged by exchange per trade (e.g. 0.5 for 0.5% on Bitstamp)
    # slippage_pct_per_leg: conservative per-leg price impact to apply when simulating execution
    "taker_fee_pct": Decimal("0.5"),
    "slippage_pct_per_leg": Decimal("0.2"),
    # If True, the bot will log a warning and skip simulated execution when expected net profit
    # after fees+slippage is below `min_profitability_pct`.
    "warn_before_execute": False,  # Don't warn, just log all candidates
}


def _fetch_kraken_hb_pairs() -> dict:
    """Return a mapping of Hummingbot-style trading pairs (BASE-QUOTE) -> Bitstamp pair code supported by Bitstamp.

    Bitstamp uses lowercase pair names like 'btcusd', 'ethusd', etc.
    Returns a dict where keys are 'BASE-QUOTE' strings and values are the Bitstamp pair code.
    """
    # simple in-memory cache to avoid repeated HTTP calls in a single run
    if getattr(_fetch_kraken_hb_pairs, "_cache", None) is not None:
        return _fetch_kraken_hb_pairs._cache

    try:
        logger.info("Ophalen Bitstamp trading pairs van https://www.bitstamp.net/api/v2/trading-pairs-info/...")
        url = 'https://www.bitstamp.net/api/v2/trading-pairs-info/'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)

        # Bitstamp returns array of objects with 'url_symbol' field (e.g., 'btcusd')
        hb_map = {}
        for pair_info in data:
            url_symbol = pair_info.get('url_symbol', '').upper()
            if not url_symbol:
                continue

            # url_symbol is like 'BTCUSD' -> convert to 'BTC-USD'
            # Most pairs are 3-letter/6-letter, but handle variable lengths
            # Try to split intelligently - for now assume last 3-4 chars are quote
            if len(url_symbol) >= 6:
                # Assume quote currency is last 3 chars (USD, EUR, GBP, etc.)
                base = url_symbol[:-3]
                quote = url_symbol[-3:]
                hb = f"{base}-{quote}"
                hb_map[hb] = url_symbol
                logger.debug("Bitstamp pair: %s -> %s", url_symbol, hb)

        # store in function attribute cache
        _fetch_kraken_hb_pairs._cache = hb_map
        logger.info("Cached %d Bitstamp trading pairs", len(hb_map))
        return hb_map
    except Exception:
        logger.exception('Failed to fetch Bitstamp trading pairs; assuming no external filtering')
        return {}


def _preflight_report(triples: List[List[str]], valid_pairs_set: set):
    """Log a concise pre-flight report showing for each triple which pairs will be monitored."""
    logger.info("Pre-flight report: evaluating configured triples vs available pairs")
    for i, triple in enumerate(triples, start=1):
        supported = [p for p in triple if p in valid_pairs_set]
        missing = [p for p in triple if p not in valid_pairs_set]
        if missing:
            logger.info("%d) %s -> SUPPORTED: %s  MISSING: %s", i, triple, supported, missing)
        else:
            logger.info("%d) %s -> SUPPORTED: %s", i, triple, supported)


def compute_implied_price(price_ab: Decimal, price_bc: Decimal) -> Decimal:
    """Compute implied A->C price via A->B->C path (price expressed as quote per base).
    If price_ab is (B per A) and price_bc is (C per B) then implied price AC = price_ab * price_bc.
    """
    return price_ab * price_bc


def _get_mid_price(curr_market, pair: str, exchange: str) -> Decimal:
    """Try to obtain a mid-price for `pair` using the market first.

    If the connector/maket does not have an order book for the pair, fall
    back to a REST Ticker query for Kraken (when exchange == 'kraken').
    Returns a Decimal price (quote per base) or raises an exception if both
    methods fail.
    """
    try:
        # primary: use connector-provided price
        p = curr_market.get_price_by_type(pair, PriceType.MidPrice)
        return Decimal(str(p))
    except Exception as e:
        logger.debug("Connector price read failed for %s: %s", pair, e)

    # fallback: use Bitstamp REST Ticker if applicable
    if exchange.lower() == 'bitstamp':
        try:
            hb2bs = _fetch_kraken_hb_pairs()
            bs_pair = hb2bs.get(pair)
            if not bs_pair:
                raise Exception(f"No Bitstamp mapping for HB pair '{pair}'")

            logger.info("REST-fallback: ophalen ticker voor %s (Bitstamp code %s)", pair, bs_pair)
            # Bitstamp ticker: https://www.bitstamp.net/api/v2/ticker/{pair}/
            url = f"https://www.bitstamp.net/api/v2/ticker/{bs_pair.lower()}/"
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.load(r)

            # Bitstamp ticker returns object with 'bid', 'ask' fields
            bid = Decimal(str(data.get('bid'))) if data.get('bid') else None
            ask = Decimal(str(data.get('ask'))) if data.get('ask') else None
            last = Decimal(str(data.get('last'))) if data.get('last') else None

            if bid is None or ask is None:
                # try 'last' (last trade price) as fallback
                if last is None:
                    raise Exception("No bid/ask/last available in Bitstamp ticker")
                return last

            mid = (bid + ask) / Decimal('2')
            logger.debug("REST-fallback ticker mid for %s: bid=%s ask=%s mid=%s", pair, bid, ask, mid)
            return mid
        except Exception as e:
            logger.warning("REST-fallback failed for %s: %s", pair, e)
            raise

    # If not Bitstamp or fallback not available, re-raise original situation
    raise Exception(f"No order book and no REST fallback available for pair {pair}")


async def monitor_loop(config):
    exchange = config["exchange"]
    triples: List[List[str]] = config["triples"]
    order_amount: Decimal = config["order_amount"]  # UNUSED if order_amount_pct is set
    order_amount_pct: Decimal = config.get("order_amount_pct", Decimal("1.0"))  # % of available balance to use
    min_profit = config["min_profitability_pct"] / Decimal("100")
    poll_interval = config["poll_interval"]
    execute_trades = config["execute_trades"]
    taker_fee = (config.get("taker_fee_pct", Decimal("0")) / Decimal("100"))
    slippage = (config.get("slippage_pct_per_leg", Decimal("0")) / Decimal("100"))
    warn_before_execute = config.get("warn_before_execute", True)

    # Create a paper-trade market (uses internal paper-trade connector implementation)
    unique_pairs = set(p for triple in triples for p in triple)
    # Allow switching between paper-trade (simulated) and real exchange connector for live data
    use_paper = config.get("use_paper_trade", True)

    logger.info("Maak verbinding: gebruik paper-trade mode" if use_paper else "Maak verbinding: gebruik live connector mode")
    logger.info("Exchange=%s Unique configured pairs=%d", exchange, len(unique_pairs))

    if use_paper:
        # For some exchanges (Bitstamp) certain HB pairs in our triples may not actually exist on the exchange
        # and passing unsupported pairs into the connector can cause mapping KeyErrors during startup.
        supported_pairs = set()
        if exchange.lower() == 'bitstamp':
            supported_pairs = _fetch_kraken_hb_pairs()
        if supported_pairs:
            valid_pairs = [p for p in unique_pairs if p in supported_pairs]
            removed = [p for p in unique_pairs if p not in supported_pairs]
            if removed:
                logger.warning("The following requested trading pairs are not available on %s and will be skipped: %s", exchange, removed)
        else:
            # Could not fetch exchange pairs; fall back to requested list but be defensive
            valid_pairs = list(unique_pairs)

        if len(valid_pairs) == 0:
            raise Exception(f"No valid trading pairs available for exchange {exchange} from provided triples")

        # Pre-flight report: show which triples/pairs will be monitored
        _preflight_report(triples, set(valid_pairs))

        # record monitored pairs for logging and runtime summaries
        monitored_pairs = list(valid_pairs)
        logger.info("Aanmaken paper-trade markt voor exchange %s met %d pairs (monitoring)", exchange, len(monitored_pairs))
        logger.debug("Monitored pairs (sample): %s", monitored_pairs[:50])
        logger.info("Nu maak ik paper-trade market aan en start ik netwerk om orderboeken te vullen...")
        market = create_paper_trade_market(exchange, monitored_pairs)

        # Initialize paper-trade account with starting balances
        initial_balances = {
            'ETH': Decimal('0.5'),      # ~€50 at current rates
            'USDC': Decimal('50.0'),    # ~€50
            'EUR': Decimal('50.0'),     # €50
            'AUD': Decimal('50.0'),     # ~€30 AUD
            'USD': Decimal('50.0'),     # ~€50
            'GBP': Decimal('40.0'),     # ~€50
            'CAD': Decimal('65.0'),     # ~€50
            'CHF': Decimal('45.0'),     # ~€50
            'JPY': Decimal('5500.0'),   # ~€50
            'USDT': Decimal('50.0'),    # ~€50
        }
        logger.info("Initializing paper-trade balances:")
        for currency, amount in initial_balances.items():
            try:
                market.set_balance(currency, amount)
                logger.info("  %s: %s", currency, amount)
            except Exception as e:
                logger.debug("  %s: failed to set balance (%s)", currency, e)
    else:
        # Create a non-trading connector instance which provides live order book data by default
        conn_settings = AllConnectorSettings.get_connector_settings()
        if exchange not in conn_settings:
            raise Exception(f"Exchange connector '{exchange}' not found in connector settings")
        connector_setting = conn_settings[exchange]

        # Filter trading_pairs for this connector similar to the paper-trade path to avoid passing unsupported pairs
        connector_supported = []
        if exchange.lower() == 'bitstamp':
            ks = _fetch_kraken_hb_pairs()
            if ks:
                connector_supported = [p for p in unique_pairs if p in ks]
            else:
                connector_supported = list(unique_pairs)
        else:
            connector_supported = list(unique_pairs)

        if len(connector_supported) == 0:
            raise Exception(f"No valid trading pairs available for exchange {exchange} from provided triples")
        # Pre-flight report: show which triples/pairs will be monitored
        _preflight_report(triples, set(connector_supported))

        # record monitored pairs for logging and runtime summaries
        monitored_pairs = list(connector_supported)
        logger.info("Aanmaken live connector voor exchange %s met %d pairs (monitoring)", exchange, len(monitored_pairs))
        logger.debug("Monitored pairs (sample): %s", monitored_pairs[:50])
        logger.info("Nu ga ik de connector instantie aanmaken en verbinden met de exchange...")

        if config.get("execute_trades", False):
            # User requested live execution: attempt to instantiate a trading-enabled connector using API keys
            # API keys should be provided via environment variables named <EXCHANGE>_API_KEY, <EXCHANGE>_API_SECRET
            api_keys = {}
            key_env = os.environ.get(f"{exchange.upper()}_API_KEY")
            secret_env = os.environ.get(f"{exchange.upper()}_API_SECRET")
            pass_env = os.environ.get(f"{exchange.upper()}_API_PASSPHRASE")
            if key_env:
                api_keys.update({"api_key": key_env})
            if secret_env:
                api_keys.update({"api_secret": secret_env})
            if pass_env:
                api_keys.update({"passphrase": pass_env})

            if not api_keys:
                raise Exception(
                    f"execute_trades=True requires API keys for '{exchange}'. Set environment variables {exchange.upper()}_API_KEY and {exchange.upper()}_API_SECRET (and optionally {exchange.upper()}_API_PASSPHRASE)."
                )

            # Build kwargs like ConnectorSetting.conn_init_parameters would do, but request trading_required=True
            connector_class = getattr(importlib.import_module(connector_setting.module_path()), connector_setting.class_name())
            kwargs = connector_setting.conn_init_parameters(
                trading_pairs=connector_supported,
                trading_required=True,
                api_keys=api_keys,
            )
            kwargs = connector_setting.add_domain_parameter(kwargs)
            try:
                logger.debug("Instantiating connector class %s with kwargs keys: %s", connector_class, list(kwargs.keys()))
                market = connector_class(**kwargs)
            except TypeError as e:
                # Some connector __init__ signatures expect provider-specific arg names
                # (for example KrakenExchange expects kraken_api_key / kraken_secret_key).
                # Try a small set of connector-specific remappings before failing.
                err = str(e)
                logger.warning("Connector initialisatie gaf TypeError, probeer remapping van API key namen: %s", err)
                remapped = False
                if exchange.lower() == 'bitstamp':
                    # map generic api_key/api_secret -> bitstamp_api_key/bitstamp_secret_key (if needed)
                    # For now, leave as-is since Bitstamp connector might use standard names
                    remapped = False
                # Add other exchange-specific remappings here if needed

                if remapped:
                    try:
                        market = connector_class(**kwargs)
                    except Exception:
                        logger.exception("Aanmaken connector na remapping mislukt voor %s.", exchange)
                        raise
                else:
                    # Not a recognized remapping case — re-raise the original error with context
                    logger.error("Connector init TypeError for %s: %s", exchange, err)
                    raise

            logger.warning("Started trading-enabled connector for exchange %s with provided API keys. Ensure keys are correct and you understand live-trading risks.", exchange)
        else:
            # read-only connector for live market data
            market = connector_setting.non_trading_connector_instance_with_default_configuration(trading_pairs=connector_supported)

    logger.info("Starting triangular arbitrage monitor for exchange=%s", exchange)

    # Start the paper-trade market network so order books are populated by the tracker.
    try:
        logger.info("Start netwerk voor markt (markt.start_network)...")
        await market.start_network()
    except Exception:
        logger.exception("Start netwerk mislukt; ga door maar prijzen kunnen ontbreken")

    # Wait briefly for order books to initialize (paper trade tracker needs a moment).
    wait_timeout = 30.0
    waited = 0.0
    interval = 1.0
    while not market.ready and waited < wait_timeout:
        logger.info("Waiting for market order books to initialize... (%ds/%ds)", int(waited), int(wait_timeout))
        await asyncio.sleep(interval)
        waited += interval

    if not market.ready:
        logger.warning("Market order books not ready after %ds; price queries may return NaN", int(wait_timeout))

    # Pre-flight validation: some connectors (especially exchange-specific ones) may
    # still not have internal symbol mappings for certain HB pairs even if the
    # exchange advertises them. Try to query a mid-price for each requested pair
    # and remove pairs that raise mapping errors. If any pairs are removed we
    # restart the market with the reduced pair set.
    def _validate_and_prune_pairs(curr_market, pairs_list):
        bad = []
        for p in list(pairs_list):
            logger.debug("Valideren paar: %s", p)
            try:
                # try a quick synchronous price read (connector may raise KeyError internally)
                _ = curr_market.get_price_by_type(p, PriceType.MidPrice)
            except Exception as e:
                logger.warning("Pair %s niet bruikbaar met deze connector (wordt overgeslagen): %s", p, e)
                bad.append(p)
        return bad

    # Run one validation pass only if market reports it is ready; otherwise skip pruning
    bad_pairs = []
    if market.ready:
        bad_pairs = _validate_and_prune_pairs(market, list(unique_pairs))
    else:
        logger.warning("Market not ready after startup; skipping pre-flight pair pruning and continuing. If you see mapping errors later, consider restarting after the market initializes fully.")

    if bad_pairs:
        # compute new valid_pairs and recreate market
        valid_pairs_after = [p for p in unique_pairs if p not in bad_pairs]
        logger.warning("Removing %d unsupported pairs and restarting market with %d pairs", len(bad_pairs), len(valid_pairs_after))
        try:
            # stop the existing market if it supports stop_network
            if hasattr(market, 'stop_network'):
                try:
                    await market.stop_network()
                except Exception:
                    logger.debug("Failed to cleanly stop previous market instance")
        except Exception:
            pass

        if len(valid_pairs_after) == 0:
            raise Exception("No valid trading pairs left after validation against connector; aborting")

        # recreate market depending on paper/live mode
        if use_paper:
            market = create_paper_trade_market(exchange, valid_pairs_after)
        else:
            # for live connector we must rebuild kwargs similarly as before
            conn_settings = AllConnectorSettings.get_connector_settings()
            connector_setting = conn_settings[exchange]
            connector_class = getattr(importlib.import_module(connector_setting.module_path()), connector_setting.class_name())
            kwargs = connector_setting.conn_init_parameters(
                trading_pairs=valid_pairs_after,
                trading_required=config.get('execute_trades', False),
            )
            kwargs = connector_setting.add_domain_parameter(kwargs)
            market = connector_class(**kwargs)

        try:
            await market.start_network()
        except Exception:
            logger.exception("Failed to start market network after pruning pairs; prices may be unavailable")

    poll_count = 0
    while True:
        try:
            poll_count += 1
            checked_count = 0
            found_count = 0
            found_details = []
            logger.info("Poll #%d: checking %d triples (interval %.1fs)", poll_count, len(triples), poll_interval)
            for triple in triples:
                logger.debug("Nu ophalen van prijzen voor triple: %s", triple)
                a_b, b_c, a_c = triple

                # Extract base currency from the first pair (e.g., "ETH-USDC" -> "ETH")
                base_currency = a_b.split('-')[0]

                # Fetch available balance for base currency A
                try:
                    available_balance = Decimal(str(market.get_balance(base_currency)))
                    if available_balance <= 0:
                        logger.debug("Geen beschikbaar saldo voor %s, sla triple %s over", base_currency, triple)
                        continue
                    # Calculate order amount as percentage of available balance
                    order_amount_for_cycle = available_balance * order_amount_pct
                except Exception as e:
                    logger.debug("Ophalen saldo voor %s mislukt, gebruik fallback fixed amount: %s", base_currency, e)
                    order_amount_for_cycle = order_amount

                try:
                    price_ab = _get_mid_price(market, a_b, exchange)
                    price_bc = _get_mid_price(market, b_c, exchange)
                    price_ac = _get_mid_price(market, a_c, exchange)
                except Exception as e:
                    logger.info("Ophalen prijzen voor triple %s mislukt (connector+REST fallback): %s", triple, e)
                    continue
                # mark that we successfully read prices for this triple
                checked_count += 1

                implied_ac = compute_implied_price(price_ab, price_bc)

                # relative edge: (implied - actual) / actual
                if price_ac == 0:
                    continue
                edge = (implied_ac - price_ac) / price_ac

                if edge > min_profit:
                    logger.info("Arbitrage detected for triple %s: implied_ac=%.8f actual_ac=%.8f edge=%.4f%%",
                                triple, implied_ac, price_ac, float(edge * 100))
                    found_count += 1
                    # collect human-friendly detail for summary and persistence
                    detail = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "triple": triple,
                        "implied_ac": float(implied_ac),
                        "actual_ac": float(price_ac),
                        "edge_pct": float(edge * 100),
                    }

                    if execute_trades:
                        logger.info("Nu ga ik simulatie uitvoeren voor cycle %s amount=%s", triple, order_amount_for_cycle)
                        logger.debug("Toepassen fees=%.4f%% slippage_per_leg=%.4f%%", float(taker_fee * 100), float(slippage * 100))
                        # Conservative simulated execution applying slippage and taker fees per leg.
                        # Prices and amounts are Decimal.
                        amount_a = order_amount_for_cycle
                        # A -> B: sell A at price_ab => receive B = amount_a * (price_ab * (1 - slippage)) * (1 - fee)
                        effective_price_ab = price_ab * (Decimal("1") - slippage)
                        amount_b = amount_a * effective_price_ab * (Decimal("1") - taker_fee)

                        # B -> C: sell B at price_bc => receive C = amount_b * (price_bc * (1 - slippage)) * (1 - fee)
                        effective_price_bc = price_bc * (Decimal("1") - slippage)
                        amount_c = amount_b * effective_price_bc * (Decimal("1") - taker_fee)

                        # C -> A: buy A with C at A-C price; buying uses a worse price due to slippage
                        effective_price_ac = price_ac * (Decimal("1") + slippage)
                        # amount of A we can buy = (amount_c / effective_price_ac) * (1 - fee)
                        amount_a_final = (amount_c / effective_price_ac) * (Decimal("1") - taker_fee) if price_ac > 0 else Decimal("0")

                        profit = amount_a_final - amount_a
                        profit_pct = (profit / amount_a) if amount_a != 0 else Decimal("0")
                        logger.info("Simulated cycle result (after fees %.4f%% and slippage %.4f%%/leg): start A=%.8f end A=%.8f profit=%.8f (%.4f%%)",
                                    float(taker_fee * 100), float(slippage * 100), amount_a, amount_a_final, profit, float(profit_pct * 100))

                        # Pre-execution check: warn and skip if net profit after fees+slippage is below configured min_profit
                        if warn_before_execute and profit_pct <= min_profit:
                            logger.warning("Simulatie resultaat: cycle %s niet rendabel na fees+slippage: profit=%.4f%% <= min_profit=%.4f%% -- simulatie overgeslagen.",
                                           triple, float(profit_pct * 100), float(min_profit * 100))
                        else:
                            logger.info("Simulatie resultaat: cycle %s lijkt rendabel: verwacht profit after fees+slippage = %.4f%%", triple, float(profit_pct * 100))
                        # attach simulated profit to detail
                        try:
                            detail['profit_pct_after_fees'] = float(profit_pct * 100)
                        except Exception:
                            detail['profit_pct_after_fees'] = None
                # else: no arbitrage

                # if we found detail (edge>min_profit), persist to candidates log and append to list
                if 'detail' in locals() and detail.get('triple') == triple:
                    found_details.append(detail)
                    # persist to logs/tri_candidates_bitstamp.log
                    try:
                        os.makedirs(os.path.join(os.getcwd(), 'logs'), exist_ok=True)
                        with open(os.path.join('logs', 'tri_candidates_bitstamp.log'), 'a') as cf:
                            cf.write(json.dumps(detail) + '\n')
                    except Exception:
                        logger.debug('Failed to write tri_candidates_bitstamp.log', exc_info=True)
                    # remove local detail so next loop iteration doesn't re-use it
                    del detail

            logger.info("Poll #%d complete: checked %d triples, found %d candidate(s)", poll_count, checked_count, found_count)
            await asyncio.sleep(poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected error in monitor loop, continuing")


def main():
    try:
        asyncio.run(monitor_loop(CONFIG))
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting")


if __name__ == "__main__":
    main()
