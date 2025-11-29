#!/usr/bin/env python3
"""
Bitget Perpetual Positions Checker
Shows all active positions on Bitget Perpetual Futures
Uses Bitget API directly (no Hummingbot dependencies)
"""
import base64
import hashlib
import hmac
import os
import time
from decimal import Decimal
from urllib.parse import urlencode

import requests


def generate_signature(timestamp, method, request_path, body, secret_key):
    """Generate Bitget API signature (base64 encoded, not hex)"""
    # Bitget uses: timestamp + method.upper() + request_path + body
    if body in ["None", "null", None]:
        body = ""

    message = str(timestamp) + method.upper() + request_path + str(body)

    # Generate HMAC-SHA256 and encode as base64 (not hex!)
    digest = hmac.new(
        bytes(secret_key, encoding='utf8'),
        bytes(message, encoding='utf8'),
        digestmod=hashlib.sha256
    ).digest()

    signature = base64.b64encode(digest).decode().strip()
    return signature


def check_bitget_positions():
    """Check Bitget Perpetual active positions"""

    # Get API keys from environment first
    api_key = os.getenv("BITGET_API_KEY", "")
    api_secret = os.getenv("BITGET_SECRET_KEY", "")
    passphrase = os.getenv("BITGET_PASSPHRASE", "")

    # Try to load from Hummingbot config if not in environment
    if not api_key or not api_secret or not passphrase:
        try:
            from pathlib import Path

            import yaml

            # Try different possible config locations
            script_dir = Path(__file__).parent.parent
            possible_paths = [
                script_dir / "conf" / "connectors" / "bitget_perpetual.yml",
                script_dir / "conf" / "connectors" / "bitget_perpetual.yaml",
                Path.home() / ".hummingbot" / "connectors" / "bitget_perpetual.yml",
                Path.home() / ".hummingbot" / "connectors" / "bitget_perpetual.yaml",
                Path("/home/mo/.hummingbot/connectors/bitget_perpetual.yml"),
                Path("/home/mo/.hummingbot/connectors/bitget_perpetual.yaml"),
            ]

            config_data = None
            config_path = None

            for path in possible_paths:
                if path.exists():
                    config_path = path
                    with open(path, 'r') as f:
                        config_data = yaml.safe_load(f)
                    break

            if config_data:
                # Try different possible key names
                encrypted_api_key = config_data.get('bitget_perpetual_api_key') or config_data.get('bitget_api_key') or ""
                encrypted_api_secret = config_data.get('bitget_perpetual_secret_key') or config_data.get('bitget_secret_key') or ""
                encrypted_passphrase = config_data.get('bitget_perpetual_passphrase') or config_data.get('bitget_passphrase') or ""

                # Check if keys are encrypted (hex string starting with 7b22...)
                if encrypted_api_key and isinstance(encrypted_api_key, str) and len(encrypted_api_key) > 100:
                    try:
                        # Try to decrypt using Hummingbot's decryption
                        import binascii
                        try:
                            from eth_account import Account
                        except ImportError:
                            print("⚠️  Cannot decrypt: eth_account module not found")
                            print("   Install with: pip install eth-account")
                            print("   Or set API keys via environment variables")
                            Account = None

                        # Get password from environment or prompt
                        password = os.getenv("CONFIG_PASSWORD", "")
                        if not password:
                            # Try to read from start_auto.sh
                            try:
                                with open(script_dir / "start_auto.sh", 'r') as f:
                                    for line in f:
                                        if 'CONFIG_PASSWORD=' in line:
                                            password = line.split('=')[1].strip().strip('"').strip("'")
                                            break
                            except Exception:
                                pass

                        if password and Account:
                            # Decrypt the encrypted values
                            try:
                                api_key_val = binascii.unhexlify(encrypted_api_key)
                                api_key = Account.decrypt(api_key_val.decode(), password).decode()

                                api_secret_val = binascii.unhexlify(encrypted_api_secret)
                                api_secret = Account.decrypt(api_secret_val.decode(), password).decode()

                                passphrase_val = binascii.unhexlify(encrypted_passphrase)
                                passphrase = Account.decrypt(passphrase_val.decode(), password).decode()

                                if api_key and api_secret and passphrase:
                                    print(f"✅ Decrypted API keys from: {config_path}")
                                    print()
                            except Exception as decrypt_error:
                                print(f"⚠️  Decryption failed: {decrypt_error}")
                                print("   Please set API keys via environment variables:")
                                print("   export BITGET_API_KEY='...'")
                                print("   export BITGET_SECRET_KEY='...'")
                                print("   export BITGET_PASSPHRASE='...'")
                                # Don't use encrypted values - they won't work
                                api_key = ""
                                api_secret = ""
                                passphrase = ""
                        elif not Account:
                            # eth_account not available, can't decrypt
                            print("⚠️  Cannot decrypt encrypted keys (eth_account not installed)")
                            print("   Please set API keys via environment variables:")
                            print("   export BITGET_API_KEY='...'")
                            print("   export BITGET_SECRET_KEY='...'")
                            print("   export BITGET_PASSPHRASE='...'")
                            api_key = ""
                            api_secret = ""
                            passphrase = ""
                        else:
                            # Use encrypted values as-is (will fail API call but shows we found them)
                            api_key = api_key or str(encrypted_api_key)
                            api_secret = api_secret or str(encrypted_api_secret)
                            passphrase = passphrase or str(encrypted_passphrase)
                    except Exception:
                        # If decryption fails, use as plain text
                        api_key = api_key or str(encrypted_api_key)
                        api_secret = api_secret or str(encrypted_api_secret)
                        passphrase = passphrase or str(encrypted_passphrase)
                else:
                    # Plain text values
                    api_key = api_key or str(encrypted_api_key) if encrypted_api_key else ""
                    api_secret = api_secret or str(encrypted_api_secret) if encrypted_api_secret else ""
                    passphrase = passphrase or str(encrypted_passphrase) if encrypted_passphrase else ""
        except Exception:
            # Silently fail and continue with environment variables
            pass

    if not api_key or not api_secret or not passphrase:
        print("❌ BITGET API KEYS NOT FOUND!")
        print()
        print("Please set environment variables:")
        print("  export BITGET_API_KEY='your_api_key'")
        print("  export BITGET_SECRET_KEY='your_secret_key'")
        print("  export BITGET_PASSPHRASE='your_passphrase'")
        print()
        print("💡 TIP: You can find these in your Bitget account:")
        print("   1. Go to: https://www.bitget.com/")
        print("   2. Account → API Management")
        print("   3. Create API key if needed")
        print()
        print("OR check positions directly on Bitget website:")
        print("   https://www.bitget.com/futures/position")
        return

    base_url = "https://api.bitget.com"

    print("=" * 80)
    print("  BITGET PERPETUAL POSITIONS CHECKER")
    print("=" * 80)
    print()

    try:
        print("🔌 Fetching active positions...")
        timestamp = str(int(time.time() * 1000))
        method = "GET"
        base_path = "/api/v2/mix/position/all-position"

        # For GET requests, Bitget includes query params in the path for signature
        params = {"productType": "USDT-FUTURES"}
        string_params = {str(k): v for k, v in params.items()}
        request_path = base_path + "?" + urlencode(string_params)

        body = ""

        signature = generate_signature(timestamp, method, request_path, body, api_secret)

        headers = {
            "ACCESS-KEY": api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
            "locale": "en-US"
        }

        # Check USDT-M futures positions
        response = requests.get(base_url + base_path, headers=headers, params=params, timeout=10)

        # Check response
        if response.status_code != 200:
            print(f"❌ API Error: {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Message: {error_data.get('msg', 'Unknown error')}")
                print(f"   Code: {error_data.get('code', 'N/A')}")
            except Exception:
                print(f"   Response: {response.text[:200]}")
            return

        data = response.json()
        if data.get("code") == "00000":
            positions = data.get("data", [])

            if not positions:
                print("✅ NO ACTIVE POSITIONS")
                print()
                print("All positions are closed. You can start new trades!")
                return

            print(f"📊 Found {len(positions)} active position(s):")
            print()
            print("=" * 80)

            total_unrealized_pnl = Decimal("0")
            total_margin_used = Decimal("0")

            for i, pos in enumerate(positions, 1):
                symbol = pos.get("symbol", "N/A")
                size = Decimal(str(pos.get("total", "0")))
                available = Decimal(str(pos.get("available", "0")))
                margin_coin = pos.get("marginCoin", "USDT")
                leverage = pos.get("leverage", "N/A")
                avg_price = Decimal(str(pos.get("averageOpenPrice", "0")))
                mark_price = Decimal(str(pos.get("markPrice", "0")))
                unrealized_pnl = Decimal(str(pos.get("unrealizedPL", "0")))
                margin_used = Decimal(str(pos.get("marginSize", "0")))
                margin_mode = pos.get("holdMode", "N/A")  # isolated or crossed
                side = pos.get("holdSide", "N/A")  # long or short

                # Calculate P&L percentage
                if avg_price > 0:
                    if side == "long":
                        pnl_pct = ((mark_price - avg_price) / avg_price) * 100
                    else:
                        pnl_pct = ((avg_price - mark_price) / avg_price) * 100
                else:
                    pnl_pct = Decimal("0")

                total_unrealized_pnl += unrealized_pnl
                total_margin_used += margin_used

                print(f"\n📍 Position #{i}: {symbol}")
                print("-" * 80)
                print(f"   Side:           {side.upper()}")
                print(f"   Size:           {size:,.6f} {symbol.split('-')[0]}")
                print(f"   Available:      {available:,.6f} {symbol.split('-')[0]}")
                print(f"   Avg Entry:      ${avg_price:,.4f}")
                print(f"   Mark Price:     ${mark_price:,.4f}")
                print(f"   Leverage:       {leverage}x")
                print(f"   Margin Mode:    {margin_mode.upper()}")
                print(f"   Margin Used:    {margin_used:,.4f} {margin_coin}")
                print(f"   Unrealized P&L: {unrealized_pnl:+,.4f} {margin_coin} ({pnl_pct:+.2f}%)")

                # Status indicator
                if unrealized_pnl > 0:
                    print("   Status:         ✅ PROFIT")
                elif unrealized_pnl < 0:
                    print("   Status:         ❌ LOSS")
                else:
                    print("   Status:         ⚪ BREAK EVEN")

            print()
            print("=" * 80)
            print("  SUMMARY")
            print("=" * 80)
            print()
            print(f"📊 Total Positions:     {len(positions)}")
            print(f"💰 Total Margin Used:   {total_margin_used:,.4f} USDT")
            print(f"💵 Total Unrealized P&L: {total_unrealized_pnl:+,.4f} USDT")
            print()

            if total_unrealized_pnl > 0:
                print("✅ Overall: PROFIT")
            elif total_unrealized_pnl < 0:
                print("❌ Overall: LOSS")
            else:
                print("⚪ Overall: BREAK EVEN")

            print()
            print("=" * 80)
            print("  ⚠️  IMPORTANT NOTES")
            print("=" * 80)
            print()
            print("1. These are ACTIVE positions that need to be closed manually")
            print("2. The bot cannot create new executors while positions exist")
            print("3. To close positions:")
            print("   - Use Bitget website: https://www.bitget.com/futures/position")
            print("   - Or use Hummingbot CLI: close --position <symbol>")
            print("   - Or wait for stop-loss/take-profit to trigger")
            print()

            # Check if positions are blocking new trades
            if len(positions) > 0:
                print("⚠️  WARNING: Active positions detected!")
                print("   The bot may not be able to create new executors")
                print("   because leverage cannot be changed with open positions.")
                print()
                print("   Solution: Close positions manually or wait for exit conditions.")
                print()

        else:
            print(f"❌ Error fetching positions: {data.get('msg', 'Unknown error')}")
            print(f"   Code: {data.get('code', 'N/A')}")
            if data.get('code') == '40001':
                print("   → Invalid API credentials. Check your API keys.")
            elif data.get('code') == '40003':
                print("   → API key does not have permission to access positions.")

    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
        print("   Check your internet connection and Bitget API status.")
    except Exception as e:
        print(f"❌ Error checking positions: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    print()
    check_bitget_positions()
    print()
