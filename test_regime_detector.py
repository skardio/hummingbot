#!/usr/bin/env python3
"""
Diagnostic script to test Adaptive Regime Detection initialization.
Run this to see if RegimeDetector and AdaptiveFilterResolver can be loaded.
"""

import sys
import traceback
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("=" * 80)
print("🔍 ADAPTIVE REGIME DETECTION DIAGNOSTIC TEST")
print("=" * 80)

# Test 1: Import modules
print("\n📦 Test 1: Importing modules...")
try:
    from multi_coin_grid_pro.utils.regime_detector import RegimeDetector
    print("   ✅ RegimeDetector imported successfully")
except Exception as e:
    print(f"   ❌ Failed to import RegimeDetector: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    from multi_coin_grid_pro.utils.adaptive_filter_resolver import AdaptiveFilterResolver
    print("   ✅ AdaptiveFilterResolver imported successfully")
except Exception as e:
    print(f"   ❌ Failed to import AdaptiveFilterResolver: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 2: Load config
print("\n📋 Test 2: Loading config...")
try:
    import yaml
    config_path = project_root / "multi_coin_grid_pro" / "config" / "config.prod.yaml"

    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)

    print(f"   ✅ Config loaded from {config_path}")

    regime_cfg = config.get('adaptive_regime_detection', {})
    filters_cfg = config.get('adaptive_filters', {})

    print(f"   Regime detection enabled: {regime_cfg.get('enabled', False)}")
    print(f"   Logging only: {regime_cfg.get('logging_only', True)}")
    print(f"   Bull threshold: {regime_cfg.get('bull_score_min', 5.0)}")
    print(f"   Chop threshold: {regime_cfg.get('chop_score_min', -3.0)}")
    print(f"   Bear threshold: {regime_cfg.get('bear_score_max', -3.0)}")

except Exception as e:
    print(f"   ❌ Failed to load config: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 3: Initialize RegimeDetector
print("\n🌡️  Test 3: Initializing RegimeDetector...")
try:
    class DummyLogger:
        def info(self, msg):
            print(f"   [INFO] {msg}")

        def warning(self, msg):
            print(f"   [WARN] {msg}")

        def error(self, msg):
            print(f"   [ERROR] {msg}")

    logger = DummyLogger()
    detector = RegimeDetector(regime_cfg, logger)
    print("   ✅ RegimeDetector initialized")
    print(f"   Current regime: {detector.current_regime}")

except Exception as e:
    print(f"   ❌ Failed to initialize RegimeDetector: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 4: Initialize AdaptiveFilterResolver
print("\n🎚️  Test 4: Initializing AdaptiveFilterResolver...")
try:
    resolver = AdaptiveFilterResolver(filters_cfg, logger)
    print("   ✅ AdaptiveFilterResolver initialized")
    print(f"   Baseline filters: {len(resolver.baseline_filters)} parameters")
    print(f"   BULL filters: {len(resolver.regime_filters.get('BULL', {}))} overrides")
    print(f"   CHOP filters: {len(resolver.regime_filters.get('CHOP', {}))} overrides")
    print(f"   BEAR filters: {len(resolver.regime_filters.get('BEAR', {}))} overrides")

except Exception as e:
    print(f"   ❌ Failed to initialize AdaptiveFilterResolver: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 5: Test regime detection logic
print("\n🧪 Test 5: Testing regime detection logic...")
try:
    from datetime import datetime

    from multi_coin_grid_pro.utils.regime_detector import RegimeMetrics

    # Simulate BULL market metrics
    test_metrics = RegimeMetrics(
        trend_1h=2.5,
        trend_4h=5.0,
        trend_24h=8.0,
        consensus=5.0,
        atr_pct=2.0,
        atr_expansion=15.0,
        range_efficiency=0.75,
        pullback_depth_pct=2.0,
        timestamp=datetime.now()
    )

    regime_state = detector.detect_regime(test_metrics)
    print(f"   ✅ Regime detected: {regime_state.regime}")
    print(f"   Score: {regime_state.score:.1f}")
    print(f"   Confidence: {regime_state.confidence:.2f}")
    print(f"   Reason: {regime_state.reason}")

except Exception as e:
    print(f"   ❌ Regime detection failed: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 6: Test filter resolution
print("\n🎯 Test 6: Testing filter resolution...")
try:
    active_filters = resolver.resolve_filters(regime_state)
    print(f"   ✅ Filters resolved for {regime_state.regime} regime")
    print(f"   RSI buy max: {active_filters.get('rsi_buy_max', 'N/A')}")
    print(f"   VWAP max dev: {active_filters.get('vwap_max_deviation_pct', 'N/A')}%")
    print(f"   Max active grids: {active_filters.get('max_active_grids', 'N/A')}")

    explanation = resolver.explain_active_filters()
    print("\n" + explanation)

except Exception as e:
    print(f"   ❌ Filter resolution failed: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("✅ ALL TESTS PASSED - Adaptive Regime Detection is functional!")
print("=" * 80)
print("\n💡 Next steps:")
print("   1. Restart your bot to apply the improved error logging")
print("   2. Check logs for '🌡️  Loading Adaptive Regime Detection modules...'")
print("   3. If still not working, the issue is in the bot configuration loading")
print()
