#!/usr/bin/env python3
"""
Check if bot is running in paper trading mode
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from multi_coin_grid_pro.config.config_manager import ConfigManager

    cm = ConfigManager()
    env = cm.get_environment()
    config = cm.load_config('multi_coin_grid', env)

    paper_trading = config.get('paper_trading', False)
    connector_name = config.get('connector_name', 'kraken')

    print("=" * 70)
    print("  PAPER TRADING STATUS CHECK")
    print("=" * 70)
    print(f"Environment: {env}")
    print(f"Config File: {cm.get_config_path('multi_coin_grid')}")
    print()
    print(f"Paper Trading Setting: {paper_trading}")
    print(f"Connector Name: {connector_name}")

    if paper_trading:
        expected_connector = f"{connector_name}_paper_trade"
        print(f"Expected Connector: {expected_connector}")
        print()
        if connector_name.endswith('_paper_trade'):
            print("✅ Paper trading is ACTIVE (connector name is correct)")
        else:
            print("⚠️  Paper trading is ENABLED but connector name not adjusted!")
            print(f"   Current: {connector_name}")
            print(f"   Should be: {expected_connector}")
            print()
            print("   This will be fixed when the bot starts.")
    else:
        print()
        print("💰 LIVE TRADING MODE (real money)")

    print("=" * 70)

except Exception as e:
    print(f"❌ Error checking status: {e}")
    import traceback
    traceback.print_exc()
