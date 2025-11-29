#!/usr/bin/env python3
"""
Check if the running bot is using paper trading mode
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Check if bot process is running
import subprocess

print("=" * 70)
print("  PAPER TRADING RUNTIME CHECK")
print("=" * 70)
print()

# Check for running bot process
result = subprocess.run(
    ["ps", "aux"],
    capture_output=True,
    text=True
)

bot_running = False
if "multi_coin_grid_v2" in result.stdout or "hummingbot.py" in result.stdout:
    bot_running = True
    print("✅ Bot process is running")
else:
    print("❌ Bot process is NOT running")
    print()
    print("To start the bot with paper trading:")
    print("  1. Make sure config.dev.yaml has: paper_trading: true")
    print("  2. Start the bot: python bin/hummingbot.py")
    print("  3. Run: start --script multi_coin_grid_v2.py")
    sys.exit(0)

print()

# Check config
from multi_coin_grid_pro.config.config_manager import ConfigManager

config_manager = ConfigManager()
environment = config_manager.get_environment()
print(f"Environment: {environment}")

try:
    config_data = config_manager.load_config("multi_coin_grid", environment)
    paper_trading_setting = config_data.get('paper_trading', False)
    connector_name = config_data.get('connector_name', 'kraken')

    expected_connector_name = connector_name
    if paper_trading_setting and not expected_connector_name.endswith('_paper_trade'):
        expected_connector_name = f"{connector_name}_paper_trade"

    print(f"Config File: {config_manager.get_config_path('multi_coin_grid')}")
    print(f"Paper Trading Setting: {paper_trading_setting}")
    print(f"Connector Name in Config: {connector_name}")
    print(f"Expected Connector (if paper trading): {expected_connector_name}")
    print()

    if paper_trading_setting:
        if connector_name == expected_connector_name:
            print("✅ Paper trading is ENABLED and connector name is correct!")
            print("   The bot should be using paper trading mode.")
        else:
            print("⚠️  Paper trading is ENABLED but connector name not adjusted!")
            print(f"   Current: {connector_name}")
            print(f"   Should be: {expected_connector_name}")
            print()
            print("   This means the bot is using LIVE trading, not paper trading!")
            print("   SOLUTION: Restart the bot to apply paper trading mode.")
    else:
        print("❌ Paper trading is DISABLED in config.")
        print("   The bot is using LIVE trading (real money).")
        print()
        print("   To enable paper trading:")
        print(f"   1. Edit: {config_manager.get_config_path('multi_coin_grid')}")
        print("   2. Set: paper_trading: true")
        print("   3. Restart the bot")

except Exception as e:
    print(f"❌ Error checking config: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 70)
print("To see paper trading status in the bot:")
print("  In Hummingbot CLI, type: status")
print("  Look for: '📝 MODE: PAPER TRADING' or '💰 MODE: LIVE TRADING'")
print("=" * 70)
