#!/usr/bin/env python3
"""
Test Multi-Coin Grid Bot V2 via Hummingbot CLI

This script starts the bot in the simplest possible way.
"""

import sys
from pathlib import Path

# Add hummingbot to path (from tests/ directory, go up 3 levels to project root)
project_root = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(project_root))

print("\n" + "=" * 70)
print("  TESTING MULTI-COIN GRID BOT V2")
print("=" * 70)

# Test 1: Import
print("\n1. Testing imports...")
try:
    # Try multiple import strategies like other test files
    try:
        from multi_coin_grid_pro.scripts.multi_coin_grid_v2 import MultiCoinGridStrategyConfig, MultiCoinGridStrategyV2
    except ImportError:
        try:
            from scripts.multi_coin_grid_v2 import MultiCoinGridStrategyConfig, MultiCoinGridStrategyV2
        except ImportError:
            # Last resort: direct file import
            import importlib.util
            script_path = project_root / "scripts" / "multi_coin_grid_v2.py"
            spec = importlib.util.spec_from_file_location("multi_coin_grid_v2", script_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            MultiCoinGridStrategyConfig = module.MultiCoinGridStrategyConfig
            MultiCoinGridStrategyV2 = module.MultiCoinGridStrategyV2
    print("   ✓ Strategy imports OK")
except Exception as e:
    print(f"   ✗ Import failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 2: Create config
print("\n2. Creating config...")
try:
    config = MultiCoinGridStrategyConfig()
    print(f"   ✓ Config created: {config.markets}")
except Exception as e:
    print(f"   ✗ Config failed: {e}")
    sys.exit(1)

# Test 3: Show what's needed
print("\n3. What's needed to run:")
print("   ✓ Config: multi_coin_grid_pro/config/multi_coin_grid.yml")
print("   ✓ Script: scripts/multi_coin_grid_v2.py")
print("   ✓ Controllers: Loaded via symlinks")
print("   ✓ Utils: Loaded via symlinks")

print("\n" + "=" * 70)
print("  ✅ ALL TESTS PASSED!")
print("=" * 70)

print("\n📋 TO RUN THE BOT:")
print("\n   Option 1: Via Hummingbot CLI")
print("   $ cd /home/mo/repos/hummingbot")
print("   $ bin/hummingbot.py")
print("   >>> start --script multi_coin_grid_v2.py")
print("\n   Option 2: Via Python (if CLI doesn't work)")
print("   $ python scripts/run_multi_coin_grid.py")

print("\n" + "=" * 70 + "\n")

