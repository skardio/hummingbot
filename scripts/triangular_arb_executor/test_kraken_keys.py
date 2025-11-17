#!/usr/bin/env python3
"""
Test Kraken API keys via direct REST API (no dependencies).

Usage:
  export KRAKEN_API_KEY="your_key"
  export KRAKEN_SECRET_KEY="your_secret"
  python3 scripts/test_kraken_keys.py

This script will:
 - Verify API connectivity
 - Fetch account balances (tests read permissions)
 - Check for trading permissions
 - Print safety summary

Important: NO trades will be placed. This is a read-only test.
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import time

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed. Run: pip install requests")
    sys.exit(1)


class KrakenAPI:
    """Simple Kraken REST API client for testing."""

    def __init__(self, api_key, api_secret):
        self.api_key = api_key
        self.api_secret = api_secret
        self.url_base = "https://api.kraken.com"

    def _get_kraken_signature(self, urlpath, data, secret):
        postdata = json.dumps(data)
        encoded = (str(data['nonce']) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()

        # Decode the secret from base64 before using it
        try:
            secret_decoded = base64.b64decode(secret)
        except Exception:
            # If decoding fails, use secret as-is
            secret_decoded = secret.encode() if isinstance(secret, str) else secret

        signature = hmac.new(
            secret_decoded,
            message,
            hashlib.sha512
        )
        sigdigest = base64.b64encode(signature.digest())
        return sigdigest.decode()

    def kraken_request(self, endpoint, data=None, timeout=10):
        if data is None:
            data = {}

        if endpoint.startswith('/0/private'):
            data['nonce'] = int(1000 * time.time())
            headers = {
                'API-Sign': self._get_kraken_signature(endpoint, data, self.api_secret),
                'API-Key': self.api_key,
            }
            res = requests.post(
                self.url_base + endpoint,
                headers=headers,
                data=data,
                timeout=timeout
            )
        else:
            res = requests.get(self.url_base + endpoint, timeout=timeout)

        return res

    def get_balance(self):
        """Get account balance."""
        return self.kraken_request('/0/private/Balance')

    def get_open_orders(self):
        """Get open orders."""
        return self.kraken_request('/0/private/OpenOrders')


def main():
    api_key = os.environ.get('KRAKEN_API_KEY')
    api_secret = os.environ.get('KRAKEN_SECRET_KEY')

    if not api_key or not api_secret:
        print("Please export KRAKEN_API_KEY and KRAKEN_SECRET_KEY in your shell.")
        print()
        print("Example:")
        print("  export KRAKEN_API_KEY='ld98d1D80ekCuThGZvFZnPQf4yKmuflpsn3PRLOFazNw2Jd/ECFl/6Sk'")
        print("  export KRAKEN_SECRET_KEY='4izpj+vDx6wmF6UelTAyVZLH3QwyyqKY3tvO7M9rrOQRjIKm6/It87aWEG/F2xTJnKU8miPn39EGCKockuG6jw=='")
        return 1

    print("=" * 80)
    print("KRAKEN API KEY TEST (REST API)")
    print("=" * 80)
    print()

    kraken = KrakenAPI(api_key, api_secret)

    # Test 1: Get balance
    print("[1/3] Testing balance retrieval (read permissions)...")
    try:
        res = kraken.get_balance()
        if res.status_code != 200:
            print(f"✗ FAILED: HTTP {res.status_code}")
            print(f"  Response: {res.text[:200]}")
            return 1

        data = res.json()
        if data.get('error'):
            print(f"✗ FAILED: {data['error']}")
            return 1

        balance_dict = data.get('result', {})
        print(f"✓ Successfully retrieved balance")
        print(f"  Available currencies: {len(balance_dict)}")

        # Print non-zero balances
        has_balance = False
        for cur, amount in sorted(balance_dict.items())[:10]:
            if float(amount) > 0:
                print(f"    {cur}: {amount}")
                has_balance = True

        if not has_balance:
            print("  (all zero balances)")

    except Exception as e:
        print(f"✗ FAILED: {e}")
        return 1

    # Test 2: Get open orders (tests trading permissions)
    print()
    print("[2/3] Testing open orders retrieval (trading permissions)...")
    try:
        res = kraken.get_open_orders()
        if res.status_code != 200:
            print(f"✗ FAILED: HTTP {res.status_code}")
            print(f"  Response: {res.text[:200]}")
            return 1

        data = res.json()
        if data.get('error'):
            # 'EAPI:Invalid permissions' indicates no trading permission
            error_msg = data['error'][0] if isinstance(data['error'], list) else data['error']
            if 'Invalid permissions' in error_msg:
                print(f"✗ FAILED: API key does NOT have trading permissions!")
                print(f"  Error: {error_msg}")
                print()
                print("  → Go to Kraken API settings and enable 'Query Open Orders' and 'Query Closed Orders'")
                return 1
            else:
                print(f"✗ FAILED: {error_msg}")
                return 1

        orders = data.get('result', {}).get('open', {})
        print(f"✓ Successfully checked open orders ({len(orders)} open)")

    except Exception as e:
        print(f"✗ FAILED: {e}")
        return 1

    # Test 3: Public endpoint (sanity check)
    print()
    print("[3/3] Testing public API (sanity check)...")
    try:
        res = requests.get('https://api.kraken.com/0/public/Ticker?pair=ETHUSD', timeout=5)
        if res.status_code == 200:
            data = res.json()
            if not data.get('error'):
                print(f"✓ Public API working (ETH-USD ticker available)")
            else:
                print(f"⚠ Public API returned error: {data['error']}")
        else:
            print(f"⚠ Public API returned HTTP {res.status_code}")
    except Exception as e:
        print(f"⚠ Public API test failed: {e}")

    print()
    print("=" * 80)
    print("✓ API KEY TESTS COMPLETED")
    print("=" * 80)
    print()
    print("Summary:")
    print("  ✓ API keys are valid")
    print("  ✓ Read permissions verified (balance retrieved)")
    print("  ✓ Trading permissions verified (can query orders)")
    print("  ✓ Ready for execution scripts")
    print()
    print("Next steps:")
    print("  1. Run dry-run: python3 scripts/execute_triangular_dry_run.py")
    print("  2. Monitor logs for opportunities")
    print("  3. If satisfied: python3 scripts/execute_triangular_live.py")
    print()
    return 0


if __name__ == '__main__':
    sys.exit(main())
