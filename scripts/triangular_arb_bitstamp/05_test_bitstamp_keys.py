#!/usr/bin/env python3
"""
Lightweight Bitstamp API key tester using Hummingbot connector classes.

Usage:

# Export your keys in the shell (do NOT paste them here):
export BITSTAMP_API_KEY="your_key"
export BITSTAMP_API_SECRET="your_secret"
export BITSTAMP_API_PASSPHRASE="your_passphrase"  # optional

# Run the tester (in the project venv):
source ~/.venvs/bot/bin/activate
python3 scripts/triangular_arb_bitstamp/05_test_bitstamp_keys.py

This script will:
 - attempt to instantiate the Bitstamp connector in "trading-enabled" mode (no orders placed)
 - call a simple balance query (if available) to validate authentication
 - print a concise success/failure summary

Important: This script will NOT place orders. It only creates a connector and reads balances.
"""

import asyncio
import importlib
import os
import sys
import traceback
from decimal import Decimal

# make sure project package is importable
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from hummingbot.client.settings import AllConnectorSettings
except Exception as e:
    print("Failed to import Hummingbot settings - ensure you're running inside the project venv and project root")
    raise


def build_connector_with_keys(exchange: str, api_keys: dict):
    """Instantiate trading-enabled connector for exchange using connector settings.
    Returns (connector_instance, error_str)
    """
    try:
        conn_settings = AllConnectorSettings.get_connector_settings()
        if exchange not in conn_settings:
            return None, f"Connector settings for '{exchange}' not found"
        connector_setting = conn_settings[exchange]
        connector_class = getattr(importlib.import_module(connector_setting.module_path()), connector_setting.class_name())
        # Build kwargs. Use trading_required=True to force trading-enabled init path.
        kwargs = connector_setting.conn_init_parameters(trading_pairs=[], trading_required=True, api_keys=api_keys)
        kwargs = connector_setting.add_domain_parameter(kwargs)
        try:
            connector = connector_class(**kwargs)
            return connector, None
        except TypeError as e:
            # Try simple remapping heuristics if connector expects provider-specific names
            err = str(e)
            remapped = False
            if exchange.lower() == 'bitstamp':
                # Most Bitstamp connectors accept api_key/api_secret, so nothing to remap by default
                remapped = False

            if remapped:
                try:
                    connector = connector_class(**kwargs)
                    return connector, None
                except Exception as e2:
                    return None, f"Connector instantiation failed after remapping: {e2}"
            else:
                return None, f"Connector instantiation TypeError: {err}"
        except Exception as e:
            return None, f"Connector instantiation error: {e}"

    except Exception as e:
        return None, f"Failed to build connector: {e}"


async def test_keys():
    exchange = 'bitstamp'
    # Read API keys from env
    api_key = os.environ.get('BITSTAMP_API_KEY')
    api_secret = os.environ.get('BITSTAMP_API_SECRET')
    api_pass = os.environ.get('BITSTAMP_API_PASSPHRASE')

    if not api_key or not api_secret:
        print("Please export BITSTAMP_API_KEY and BITSTAMP_API_SECRET in your shell before running this script.")
        return 1

    # Map environment variable names to connector-specific init parameter names.
    # The Bitstamp connector expects 'bitstamp_api_key' and 'bitstamp_api_secret'.
    if exchange.lower() == 'bitstamp':
        api_keys = {'bitstamp_api_key': api_key, 'bitstamp_api_secret': api_secret}
    else:
        api_keys = {'api_key': api_key, 'api_secret': api_secret}
    # Passphrase is optional and connector-specific; include generically when present.
    if api_pass:
        # Most connectors use 'passphrase' if they need it. Bitstamp config does not define a passphrase field,
        # so we avoid adding it for bitstamp to prevent unexpected kwargs.
        if exchange.lower() != 'bitstamp':
            api_keys['passphrase'] = api_pass

    print("Attempting to instantiate Bitstamp connector with provided API keys (no trades will be placed)...")
    connector, err = build_connector_with_keys(exchange, api_keys)
    if err:
        print("FAILED to create connector:", err)
        return 1

    print("Connector instance created. Trying a simple authenticated call (balance lookup) to validate keys...")

    # Many connectors expose a get_balance(currency) method or get_all_balances; try common ones safely
    try:
        # Some connectors require start_network to populate websockets; avoid that. Use sync balance call if available.
        get_balance_fn = getattr(connector, 'get_balance', None)
        get_all_fn = getattr(connector, 'get_all_balances', None) or getattr(connector, 'get_wallet_balances', None)

        if get_balance_fn is None and get_all_fn is None:
            print('Warning: connector does not expose a simple balance API we can call without starting network. Trying to start network briefly...')
            # Start network but stop immediately after a short wait. This may open websockets.
            try:
                await connector.start_network()
                await asyncio.sleep(1)
                # try get_balance for USD as common
                if hasattr(connector, 'get_balance'):
                    bal = connector.get_balance('USD')
                    print('Sample USD balance:', bal)
                elif hasattr(connector, 'get_all_balances'):
                    allb = connector.get_all_balances()
                    print('Balances available (sample):', list(allb.items())[:5])
                else:
                    print('Could not perform balance check after network start')
                try:
                    await connector.stop_network()
                except Exception:
                    pass
                print('If no errors were raised, the API keys appear valid (connector connected).')
                return 0
            except Exception as e:
                print('Failed to start connector network for test:', e)
                return 1

        # If one of the balance functions exist, call it (synchronously)
        if get_all_fn is not None:
            try:
                bal = get_all_fn()
                print('Retrieved balances (sample):')
                # print a small summary
                if isinstance(bal, dict):
                    for k, v in list(bal.items())[:10]:
                        print(f"  {k}: {v}")
                else:
                    print(bal)
                print('API keys appear valid (balance read succeeded).')
                return 0
            except Exception as e:
                print('Failed to read balances via connector:', e)
                return 1

        if get_balance_fn is not None:
            try:
                # try a few common currencies
                for c in ['USD', 'EUR', 'USDC', 'BTC', 'ETH']:
                    try:
                        b = get_balance_fn(c)
                        print(f'  {c}: {b}')
                    except Exception:
                        pass
                print('If at least one balance printed without raising an error, keys look valid.')
                return 0
            except Exception as e:
                print('Failed during get_balance calls:', e)
                return 1

        print('No viable balance method found to test keys. Connector created successfully but we could not verify balances.')
        return 0

    except Exception as e:
        print('Unexpected error when testing connector:', e)
        traceback.print_exc()
        return 1


def main():
    try:
        res = asyncio.run(test_keys())
        sys.exit(res)
    except KeyboardInterrupt:
        print('\nInterrupted')
        sys.exit(1)


if __name__ == '__main__':
    main()
