#!/usr/bin/env python3
"""
Lightweight Bitvavo API key tester using ccxt.

Usage:

# Export your keys in the shell (do NOT paste them here):
export BITVAVO_API_KEY="your_key"
export BITVAVO_API_SECRET="your_secret"

# Run the tester (in the project venv):
source ~/.venvs/bot/bin/activate
pip install ccxt  # if not already installed
python3 scripts/triangular_arb_bitvavo/05_test_bitvavo_keys.py

This script will:
 - attempt to instantiate the Bitvavo exchange (ccxt) with your keys
 - call a simple balance query to validate authentication
 - print a concise success/failure summary

Important: This script will NOT place orders. It only creates an exchange instance and reads balances.
"""

import json
import os
import sys

try:
    import ccxt
except ImportError:
    print("ERROR: ccxt not installed. Run: pip install ccxt")
    sys.exit(1)


def test_keys():
    """Test Bitvavo API keys via ccxt."""

    api_key = os.environ.get('BITVAVO_API_KEY')
    api_secret = os.environ.get('BITVAVO_API_SECRET')

    if not api_key or not api_secret:
        print("Please export BITVAVO_API_KEY and BITVAVO_API_SECRET in your shell before running this script.")
        print()
        print("Example:")
        print("  export BITVAVO_API_KEY='your_api_key'")
        print("  export BITVAVO_API_SECRET='your_api_secret'")
        print("  python3 scripts/triangular_arb_bitvavo/05_test_bitvavo_keys.py")
        return 1

    print("Attempting to instantiate Bitvavo exchange with provided API keys (no trades will be placed)...")

    try:
        exchange = ccxt.bitvavo({
            'apiKey': api_key,
            'secret': api_secret,
            'enableRateLimit': True,
        })
        print("✓ Exchange instance created successfully")
    except Exception as e:
        print(f"✗ FAILED to create exchange: {e}")
        return 1

    # Try to fetch balances (requires API read permissions)
    print()
    print("Attempting to fetch balances (to validate authentication)...")

    try:
        balance = exchange.fetch_balance()
        print("✓ Successfully fetched balances")
        print()
        print("  Your Bitvavo balances:")

        # Filter to non-zero and print
        non_zero = {k: v for k, v in balance['free'].items() if v > 0}
        if non_zero:
            for currency, amount in sorted(non_zero.items())[:10]:
                print(f"    {currency}: {amount}")
            if len(non_zero) > 10:
                print(f"    ... and {len(non_zero) - 10} more")
        else:
            print("    (no non-zero balances)")

        print()
        print("=" * 60)
        print("✓ API keys are VALID and have read permissions")
        print("=" * 60)
        return 0

    except ccxt.AuthenticationError as e:
        print(f"✗ FAILED: Authentication error (invalid keys?): {e}")
        return 1
    except ccxt.PermissionDenied as e:
        print(f"✗ FAILED: Permission denied (check API key scopes): {e}")
        return 1
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(test_keys())
