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
    "exchange": "kraken",
    # ALL 102 EUR TRIANGULAR ARBITRAGE ROUTES (USDT excluded for NL)
    # Auto-generated from find_all_eur_routes.py
    "triples": [
        ["AAVE-EUR", "AAVE-BTC", "BTC-EUR"],
        ["AAVE-EUR", "AAVE-ETH", "ETH-EUR"],
        ["PEAQ-EUR", "PEAQ-USDC", "USDC-EUR"],
        ["XMR-EUR", "XMR-BTC", "BTC-EUR"],
        ["XMR-EUR", "XMR-USDC", "USDC-EUR"],
        ["ADA-EUR", "ADA-BTC", "BTC-EUR"],
        ["ADA-EUR", "ADA-ETH", "ETH-EUR"],
        ["ADA-EUR", "ADA-USDC", "USDC-EUR"],
        ["EURC-EUR", "BTC-EURC", "BTC-EUR"],
        ["EURC-EUR", "ETH-EURC", "ETH-EUR"],
        ["EURC-EUR", "SOL-EURC", "SOL-EUR"],
        ["EURC-EUR", "EURC-USDC", "USDC-EUR"],
        ["WBTC-EUR", "WBTC-BTC", "BTC-EUR"],
        ["ETHW-EUR", "ETHW-ETH", "ETH-EUR"],
        ["XDC-EUR", "XDC-USDC", "USDC-EUR"],
        ["TON-EUR", "TON-USDC", "USDC-EUR"],
        ["SNX-EUR", "SNX-BTC", "BTC-EUR"],
        ["BTC-EUR", "TBTC-BTC", "TBTC-EUR"],
        ["BTC-EUR", "UNI-BTC", "UNI-EUR"],
        ["BTC-EUR", "ETH-BTC", "ETH-EUR"],
        ["BTC-EUR", "XLM-BTC", "XLM-EUR"],
        ["BTC-EUR", "SC-BTC", "SC-EUR"],
        ["BTC-EUR", "TRX-BTC", "TRX-EUR"],
        ["BTC-EUR", "ETC-BTC", "ETC-EUR"],
        ["BTC-EUR", "ATOM-BTC", "ATOM-EUR"],
        ["BTC-EUR", "ZRX-BTC", "ZRX-EUR"],
        ["BTC-EUR", "BTC-DAI", "DAI-EUR"],
        ["BTC-EUR", "SAND-BTC", "SAND-EUR"],
        ["BTC-EUR", "BTC-PYUSD", "PYUSD-EUR"],
        ["BTC-EUR", "SOL-BTC", "SOL-EUR"],
        ["BTC-EUR", "BCH-BTC", "BCH-EUR"],
        ["BTC-EUR", "LINK-BTC", "LINK-EUR"],
        ["BTC-EUR", "MANA-BTC", "MANA-EUR"],
        ["BTC-EUR", "XRP-BTC", "XRP-EUR"],
        ["BTC-EUR", "BTC-USDR", "USDR-EUR"],
        ["BTC-EUR", "BTC-EUROP", "EUROP-EUR"],
        ["BTC-EUR", "MINA-BTC", "MINA-EUR"],
        ["BTC-EUR", "BTC-USDQ", "USDQ-EUR"],
        ["BTC-EUR", "ALGO-BTC", "ALGO-EUR"],
        ["BTC-EUR", "DOGE-BTC", "DOGE-EUR"],
        ["BTC-EUR", "LTC-BTC", "LTC-EUR"],
        ["BTC-EUR", "COMP-BTC", "COMP-EUR"],
        ["BTC-EUR", "ANKR-BTC", "ANKR-EUR"],
        ["BTC-EUR", "GRT-BTC", "GRT-EUR"],
        ["BTC-EUR", "PAXG-BTC", "PAXG-EUR"],
        ["BTC-EUR", "DOT-BTC", "DOT-EUR"],
        ["BTC-EUR", "FIL-BTC", "FIL-EUR"],
        ["BTC-EUR", "BTC-USDC", "USDC-EUR"],
        ["BTC-EUR", "MLN-BTC", "MLN-EUR"],
        ["CRO-EUR", "CRO-USDC", "USDC-EUR"],
        ["UNI-EUR", "UNI-ETH", "ETH-EUR"],
        ["ETH-EUR", "TRX-ETH", "TRX-EUR"],
        ["ETH-EUR", "ETC-ETH", "ETC-EUR"],
        ["ETH-EUR", "ATOM-ETH", "ATOM-EUR"],
        ["ETH-EUR", "LSETH-ETH", "LSETH-EUR"],
        ["ETH-EUR", "ETH-DAI", "DAI-EUR"],
        ["ETH-EUR", "ETH-PYUSD", "PYUSD-EUR"],
        ["ETH-EUR", "SOL-ETH", "SOL-EUR"],
        ["ETH-EUR", "BCH-ETH", "BCH-EUR"],
        ["ETH-EUR", "LINK-ETH", "LINK-EUR"],
        ["ETH-EUR", "XRP-ETH", "XRP-EUR"],
        ["ETH-EUR", "ETH-EUROP", "EUROP-EUR"],
        ["ETH-EUR", "ALGO-ETH", "ALGO-EUR"],
        ["ETH-EUR", "LTC-ETH", "LTC-EUR"],
        ["ETH-EUR", "PAXG-ETH", "PAXG-EUR"],
        ["ETH-EUR", "DOT-ETH", "DOT-EUR"],
        ["ETH-EUR", "FIL-ETH", "FIL-EUR"],
        ["ETH-EUR", "ETH-USDC", "USDC-EUR"],
        ["EURR-EUR", "EURR-USDC", "USDC-EUR"],
        ["BERA-EUR", "BERA-USDC", "USDC-EUR"],
        ["TRX-EUR", "TRX-USDD", "USDD-EUR"],
        ["TRUMP-EUR", "TRUMP-USDC", "USDC-EUR"],
        ["ATOM-EUR", "ATOM-USDC", "USDC-EUR"],
        ["SHIB-EUR", "SHIB-USDC", "USDC-EUR"],
        ["FARTCOIN-EUR", "FARTCOIN-USDC", "USDC-EUR"],
        ["SOL-EUR", "LSSOL-SOL", "LSSOL-EUR"],
        ["SOL-EUR", "PUMP-SOL", "PUMP-EUR"],
        ["SOL-EUR", "JITOSOL-SOL", "JITOSOL-EUR"],
        ["SOL-EUR", "SOL-USDC", "USDC-EUR"],
        ["PENGU-EUR", "PENGU-USDC", "USDC-EUR"],
        ["USDE-EUR", "USDE-USDC", "USDC-EUR"],
        ["BNB-EUR", "BNB-USDC", "USDC-EUR"],
        ["BCH-EUR", "BCH-USDC", "USDC-EUR"],
        ["AI16Z-EUR", "AI16Z-USDC", "USDC-EUR"],
        ["XTZ-EUR", "XTZ-USDC", "USDC-EUR"],
        ["LINK-EUR", "LINK-USDC", "USDC-EUR"],
        ["MANA-EUR", "MANA-USDC", "USDC-EUR"],
        ["XRP-EUR", "XRP-USDC", "USDC-EUR"],
        ["USDR-EUR", "USDR-USDC", "USDC-EUR"],
        ["APE-EUR", "APE-USDC", "USDC-EUR"],
        ["EUROP-EUR", "EUROP-USDC", "USDC-EUR"],
        ["USTC-EUR", "USTC-USDC", "USDC-EUR"],
        ["VIRTUAL-EUR", "VIRTUAL-USDC", "USDC-EUR"],
        ["USDQ-EUR", "USDQ-USDC", "USDC-EUR"],
        ["ALGO-EUR", "ALGO-USDC", "USDC-EUR"],
        ["MELANIA-EUR", "MELANIA-USDC", "USDC-EUR"],
        ["DOGE-EUR", "DOGE-USDC", "USDC-EUR"],
        ["LTC-EUR", "LTC-USDC", "USDC-EUR"],
        ["AVAX-EUR", "AVAX-USDC", "USDC-EUR"],
        ["DOT-EUR", "DOT-USDC", "USDC-EUR"],
        ["S-EUR", "S-USDC", "USDC-EUR"],
        ["CC-EUR", "CC-USDC", "USDC-EUR"],
    ],
    "order_amount": Decimal("1.0"),  # UNUSED: Set to 1.0 (ignored). Dynamic allocation from available balance is used instead.
    "order_amount_pct": Decimal("1.0"),  # Use 100% of available base currency A balance for each arbitrage cycle
    "min_profitability_pct": Decimal("0.0"),  # Set to 0.0 to catch any positive opportunity (even tiny ones)
    "poll_interval": 5.0,  # seconds between each polling cycle
    "execute_trades": True,  # True = enables candidate logging with fee simulation
    "use_paper_trade": True,  # Use paper-trade market for live-feed monitoring
    # Fee and slippage estimation used for pre-execution checks (percent)
    # 0% FEES under €10k volume! 🎉
    "taker_fee_pct": Decimal("0.00"),  # ZERO FEES!
    "slippage_pct_per_leg": Decimal("0.03"),  # Conservative 0.03% per leg
    # If True, the bot will log a warning and skip simulated execution when expected net profit
    # after fees+slippage is below `min_profitability_pct`.
    "warn_before_execute": False,  # Don't warn, just log all candidates
}


def _fetch_kraken_hb_pairs() -> dict:
    """Return a mapping of Hummingbot-style trading pairs (BASE-QUOTE) -> Kraken pair code supported by Kraken.

    Prefer using the AssetPairs 'wsname' when available (it contains 'BASE/QUOTE').
    Returns a dict where keys are 'BASE-QUOTE' strings and values are the Kraken pair code.
    """
    # simple in-memory cache to avoid repeated HTTP calls in a single run
    if getattr(_fetch_kraken_hb_pairs, "_cache", None) is not None:
        return _fetch_kraken_hb_pairs._cache

    try:
        logger.info("Ophalen Kraken AssetPairs van https://api.kraken.com/0/public/AssetPairs ...")
        url = 'https://api.kraken.com/0/public/AssetPairs'
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.load(r)

        # Debug: list a few AssetPairs to help development (kan veel zijn)
        pairs = data.get('result', {})
        try:
            sample = list(pairs.items())[:10]
            for pair_code, info in sample:
                logger.debug("Kraken AssetPair sample - %s: %s", pair_code, info.get('wsname'))
        except Exception:
            pass
        hb_map = {}
        for pair_code, info in pairs.items():
            # prefer wsname like 'FIL/XBT'
            ws = info.get('wsname') or info.get('wsname')
            if ws and '/' in ws:
                parts = ws.split('/')
                if len(parts) == 2:
                    base_hb = parts[0].upper()
                    quote_hb = parts[1].upper()
                    hb = f"{base_hb}-{quote_hb}"
                    hb_map[hb] = pair_code
                    continue

            # fallback: try to use 'base' and 'quote' fields and map via Assets altname
            try:
                assets_resp = json.load(urllib.request.urlopen('https://api.kraken.com/0/public/Assets', timeout=10))
                assets = {k: v.get('altname', k).upper() for k, v in assets_resp.get('result', {}).items()}
                base = info.get('base')
                quote = info.get('quote')
                if base in assets and quote in assets:
                    base_hb = assets[base].upper()
                    quote_hb = assets[quote].upper()
                    hb = f"{base_hb}-{quote_hb}"
                    hb_map[hb] = pair_code
            except Exception:
                # ignore per-pair asset mapping failures
                continue

        # store in function attribute cache
        _fetch_kraken_hb_pairs._cache = hb_map
        return hb_map
    except Exception:
        logger.exception('Failed to fetch Kraken AssetPairs; assuming no external filtering')
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


def _get_bid_ask_prices(curr_market, pair: str, exchange: str) -> tuple:
    """Get bid and ask prices for a pair.

    Returns (bid, ask) tuple as Decimals.
    For triangular arbitrage, you MUST use:
    - ASK when BUYING (you pay the ask price)
    - BID when SELLING (you receive the bid price)
    """
    try:
        # Try to get bid/ask from connector
        bid_price = curr_market.get_price_by_type(pair, PriceType.BestBid)
        ask_price = curr_market.get_price_by_type(pair, PriceType.BestAsk)
        return Decimal(str(bid_price)), Decimal(str(ask_price))
    except Exception as e:
        logger.debug("Connector bid/ask read failed for %s: %s", pair, e)

    # fallback: use Kraken REST Ticker if applicable
    if exchange.lower() == 'kraken':
        try:
            hb2kr = _fetch_kraken_hb_pairs()
            kr_pair = hb2kr.get(pair)
            if not kr_pair:
                raise Exception(f"No Kraken mapping for HB pair '{pair}'")

            logger.debug("REST-fallback: ophalen ticker voor %s (Kraken code %s)", pair, kr_pair)
            url = f"https://api.kraken.com/0/public/Ticker?pair={urllib.parse.quote(kr_pair)}"
            with urllib.request.urlopen(url, timeout=10) as r:
                data = json.load(r)

            res = data.get('result') or {}
            if not res:
                raise Exception("Empty ticker result from Kraken")
            first = next(iter(res.values()))
            # bids and asks are lists of [price, wholeLotVolume, lotVolume]
            bid = Decimal(str(first.get('b', [None])[0])) if first.get('b') else None
            ask = Decimal(str(first.get('a', [None])[0])) if first.get('a') else None
            if bid is None or ask is None:
                # try 'c' (last trade) as fallback
                last = first.get('c', [None])[0] if first.get('c') else None
                if last is None:
                    raise Exception("No bid/ask/last available in Kraken ticker")
                last_dec = Decimal(str(last))
                return last_dec, last_dec  # Use last price for both if no bid/ask

            logger.debug("REST-fallback ticker for %s: bid=%s ask=%s", pair, bid, ask)
            return bid, ask
        except Exception as e:
            logger.warning("REST-fallback failed for %s: %s", pair, e)
            raise

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
        # For some exchanges (Kraken) certain HB pairs in our triples may not actually exist on the exchange
        # and passing unsupported pairs into the connector can cause mapping KeyErrors during startup.
        supported_pairs = set()
        if exchange.lower() == 'kraken':
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
        if exchange.lower() == 'kraken':
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
                if exchange.lower() == 'kraken':
                    # map generic api_key/api_secret -> kraken_api_key/kraken_secret_key
                    if 'api_key' in kwargs or 'api_secret' in kwargs:
                        k = kwargs.pop('api_key', None)
                        s = kwargs.pop('api_secret', None)
                        if k:
                            kwargs['kraken_api_key'] = k
                        if s:
                            kwargs['kraken_secret_key'] = s
                        remapped = True
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

                # 🔧 FIX: Determine BUY/SELL direction per leg based on asset flow
                # Route ["ETH-EUR", "ETH-USDT", "USDT-EUR"] means:
                # - Start with EUR (quote of first pair)
                # - Leg 1: BUY ETH with EUR (ETH-EUR pair, we buy base)
                # - Leg 2: SELL ETH for USDT (ETH-USDT pair, we sell base)
                # - Leg 3: SELL USDT for EUR (USDT-EUR pair, we sell base)

                try:
                    bid_ab, ask_ab = _get_bid_ask_prices(market, a_b, exchange)
                    bid_bc, ask_bc = _get_bid_ask_prices(market, b_c, exchange)
                    bid_ac, ask_ac = _get_bid_ask_prices(market, a_c, exchange)
                except Exception as e:
                    logger.info("Ophalen prijzen voor triple %s mislukt (connector+REST fallback): %s", triple, e)
                    continue
                checked_count += 1

                # Parse assets from pairs (format: BASE-QUOTE)
                base_ab, quote_ab = a_b.split('-')
                base_bc, quote_bc = b_c.split('-')
                base_ac, quote_ac = a_c.split('-')

                # Triangular arbitrage: simulate trading 1 unit of start currency through the route
                start_currency = quote_ab
                start_amount = Decimal('1')

                # Leg 1: We have start_currency, trade on a_b pair
                if start_currency == quote_ab:
                    # BUY base with quote (e.g., buy ETH with EUR)
                    amount_after_leg1 = start_amount / ask_ab
                    asset_after_leg1 = base_ab
                    leg1_side = "BUY"
                else:
                    # SELL base for quote
                    amount_after_leg1 = start_amount * bid_ab
                    asset_after_leg1 = quote_ab
                    leg1_side = "SELL"

                # Leg 2: We have asset_after_leg1, trade on b_c pair
                if asset_after_leg1 == base_bc:
                    # We have base, SELL it for quote
                    amount_after_leg2 = amount_after_leg1 * bid_bc
                    asset_after_leg2 = quote_bc
                    leg2_side = "SELL"
                elif asset_after_leg1 == quote_bc:
                    # We have quote, BUY base
                    amount_after_leg2 = amount_after_leg1 / ask_bc
                    asset_after_leg2 = base_bc
                    leg2_side = "BUY"
                else:
                    logger.warning("Invalid route %s: asset %s not in pair %s", triple, asset_after_leg1, b_c)
                    continue

                # Leg 3: We have asset_after_leg2, trade on a_c pair to get back start_currency
                if asset_after_leg2 == base_ac:
                    # We have base, SELL it for quote
                    amount_after_leg3 = amount_after_leg2 * bid_ac
                    asset_after_leg3 = quote_ac
                    leg3_side = "SELL"
                elif asset_after_leg2 == quote_ac:
                    # We have quote, BUY base
                    amount_after_leg3 = amount_after_leg2 / ask_ac
                    asset_after_leg3 = base_ac
                    leg3_side = "BUY"
                else:
                    logger.warning("Invalid route %s: asset %s not in pair %s", triple, asset_after_leg2, a_c)
                    continue

                # Check if we ended up with start currency
                if asset_after_leg3 != start_currency:
                    logger.warning("Route %s doesn't return to start currency %s (ended with %s)",
                                   triple, start_currency, asset_after_leg3)
                    continue

                # Calculate edge: (final_amount - start_amount) / start_amount
                edge = (amount_after_leg3 - start_amount) / start_amount

                logger.debug("Triple %s: %s→%s→%s→%s | %.6f→%.6f→%.6f→%.6f | edge=%.4f%%",
                             triple, start_currency, asset_after_leg1, asset_after_leg2, asset_after_leg3,
                             start_amount, amount_after_leg1, amount_after_leg2, amount_after_leg3,
                             float(edge * 100))

                if edge > min_profit:
                    logger.info("Arbitrage detected for triple %s: edge=%.4f%% (route: %s→%s→%s→%s)",
                                triple, float(edge * 100), start_currency, asset_after_leg1, asset_after_leg2, asset_after_leg3)
                    found_count += 1
                    # collect human-friendly detail for summary and persistence
                    detail = {
                        "timestamp": datetime.utcnow().isoformat(),
                        "triple": triple,
                        "edge_pct": float(edge * 100),
                        "route": f"{start_currency}→{asset_after_leg1}→{asset_after_leg2}→{asset_after_leg3}",
                    }

                    if execute_trades:
                        # The edge calculation above already includes proper bid/ask logic
                        # Now apply slippage and fees to estimate final profit
                        logger.info("Candidate found for cycle %s with edge=%.4f%% (before slippage/fees)", triple, float(edge * 100))
                        logger.debug("Applying fees=%.4f%% slippage_per_leg=%.4f%%", float(taker_fee * 100), float(slippage * 100))

                        # Total slippage impact (3 legs)
                        total_slippage = slippage * Decimal("3")
                        # Total fee impact (3 legs)
                        total_fees = taker_fee * Decimal("3")

                        # Estimated profit after slippage and fees
                        profit_pct_after_costs = edge - total_slippage - total_fees

                        logger.info("Simulated cycle result: edge=%.4f%% - slippage=%.4f%% - fees=%.4f%% = profit_after_costs=%.4f%%",
                                    float(edge * 100), float(total_slippage * 100), float(total_fees * 100), float(profit_pct_after_costs * 100))

                        # Pre-execution check: warn and skip if net profit after fees+slippage is below configured min_profit
                        if warn_before_execute and profit_pct_after_costs <= min_profit:
                            logger.warning("Simulatie resultaat: cycle %s niet rendabel na fees+slippage: profit=%.4f%% <= min_profit=%.4f%% -- simulatie overgeslagen.",
                                           triple, float(profit_pct_after_costs * 100), float(min_profit * 100))
                        else:
                            logger.info("Simulatie resultaat: cycle %s lijkt rendabel: verwacht profit after fees+slippage = %.4f%%", triple, float(profit_pct_after_costs * 100))
                        # attach simulated profit to detail
                        try:
                            detail['profit_pct_after_fees'] = float(profit_pct_after_costs * 100)
                        except Exception:
                            detail['profit_pct_after_fees'] = None
                # else: no arbitrage

                # if we found detail (edge>min_profit), persist to candidates log and append to list
                if 'detail' in locals() and detail.get('triple') == triple:
                    found_details.append(detail)
                    # persist to logs/tri_candidates.log
                    try:
                        os.makedirs(os.path.join(os.getcwd(), 'logs'), exist_ok=True)
                        with open(os.path.join('logs', 'tri_candidates.log'), 'a') as cf:
                            cf.write(json.dumps(detail) + '\n')
                    except Exception:
                        logger.debug('Failed to write tri_candidates.log', exc_info=True)
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
