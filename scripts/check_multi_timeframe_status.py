#!/usr/bin/env python3
"""
Check if Multi-Timeframe Trend Engine is enabled
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from multi_coin_grid_pro.config.config_manager import ConfigManager

    cm = ConfigManager()
    env = cm.get_environment()
    config = cm.load_config('multi_coin_grid', env)

    use_multi_timeframe = config.get('use_multi_timeframe', True)  # Default True
    trend_short = config.get('trend_lookback_short_minutes', 60)
    trend_mid = config.get('trend_lookback_mid_minutes', 240)
    trend_long = config.get('trend_lookback_long_minutes', 1440)

    print("=" * 70)
    print("  MULTI-TIMEFRAME TREND ENGINE STATUS")
    print("=" * 70)
    print(f"Environment: {env}")
    print(f"Config File: {cm.get_config_path('multi_coin_grid')}")
    print()
    print(f"Multi-Timeframe Enabled: {use_multi_timeframe}")
    print()

    if use_multi_timeframe:
        print("✅ Multi-Timeframe Trend Engine: ACTIVE")
        print()
        print("Timeframes:")
        print(f"  - Short-term (60m):  {trend_short} minutes ({trend_short / 60:.1f} hours)")
        print(f"  - Mid-term (240m):   {trend_mid} minutes ({trend_mid / 60:.1f} hours)")
        print(f"  - Long-term (1440m): {trend_long} minutes ({trend_long / 60:.1f} hours)")
        print()
        print("Buy Conditions:")
        print("  - 24h trend > +1%")
        print("  - 4h trend > +1%")
        print("  - 1h trend >= 0% (prevents buying during crashes!)")
        print()
        print("Exit Conditions:")
        print("  - 1h trend < -1% AND 4h trend < +0.5%")
        print("  → Detects crashes quickly and exits before losses get worse")
        print()
        print("📊 Look for these log messages:")
        print("  [TREND] 24h: X.XX% | 4h: X.XX% | 1h: X.XX%")
        print("  [DECISION] ✅ COIN BUY APPROVED")
        print("  [DECISION] ❌ COIN BUY REJECTED: 1h trend < 0% (crash detected!)")
        print("  [DECISION] 🚨 COIN EXIT TRIGGERED")
    else:
        print("❌ Multi-Timeframe Trend Engine: DISABLED")
        print()
        print("⚠️  Warning: Bot will use single 24h lookback only")
        print("   This may miss crashes that happen within 24h period!")
        print()
        print("To enable:")
        print("  1. Edit config file:")
        print(f"     {cm.get_config_path('multi_coin_grid')}")
        print("  2. Add: use_multi_timeframe: true")
        print("  3. Restart bot")

    print("=" * 70)

except Exception as e:
    print(f"❌ Error checking status: {e}")
    import traceback
    traceback.print_exc()
