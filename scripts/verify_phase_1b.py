#!/usr/bin/env python3
"""
Phase 1B Verification Script

Demonstrates that SmartEntry now sets reason_code and stage in traces.
Run: python scripts/verify_phase_1b.py
"""

import sys
from decimal import Decimal
from pathlib import Path

from multi_coin_grid_pro.core.models import CandleIndicators
from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage
from multi_coin_grid_pro.logic.smart_entry import SmartEntryBaseConfig, SmartEntryFilter

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    print("=" * 80)
    print("Phase 1B Verification: SmartEntry Instrumentation")
    print("=" * 80)
    print()

    # Setup SmartEntry filter
    base_cfg = SmartEntryBaseConfig(
        rsi_buy_max=60.0,
        rsi_extreme_low=25.0,
        rsi_block_min=70.0,
        vwap_max_deviation_pct=3.0,
        min_wick_ratio=0.25,
        max_atr_pct_for_grid=6.0,
        min_atr_pct_for_grid=0.5,
        max_5m_spike_pct=2.5,
        max_down_accel_pct=-1.0,
        max_up_accel_pct=1.5,
        max_trend_24h_pct=8.0,
        min_trend_24h_pct=-12.0,
        slippage_check_enabled=False,
        depth_check_enabled=False,
    )

    filter_obj = SmartEntryFilter(
        base_cfg=base_cfg,
        coin_profiles={},
        logger=None,
        exchange_connector=None
    )

    # Test scenarios
    scenarios = [
        {
            "name": "RSI Overbought (>70)",
            "indicators": CandleIndicators(
                price=Decimal("1.5"),
                rsi_14=75.0,
                vwap=Decimal("1.5"),
                atr_pct=1.5,
                wick_ratio=0.5,
                trend_1h_pct=1.0,
                trend_4h_pct=2.0,
                trend_24h_pct=3.0,
                change_5m_pct=0.2,
            ),
            "expected_code": ReasonCode.RSI_OVERBOUGHT,
        },
        {
            "name": "RSI Oversold (<25)",
            "indicators": CandleIndicators(
                price=Decimal("1.5"),
                rsi_14=20.0,
                vwap=Decimal("1.5"),
                atr_pct=1.5,
                wick_ratio=0.5,
                trend_1h_pct=1.0,
                trend_4h_pct=2.0,
                trend_24h_pct=3.0,
                change_5m_pct=0.2,
            ),
            "expected_code": ReasonCode.RSI_OVERSOLD,
        },
        {
            "name": "VWAP Deviation Too High",
            "indicators": CandleIndicators(
                price=Decimal("1.6"),  # 6.67% above VWAP
                rsi_14=45.0,
                vwap=Decimal("1.5"),
                atr_pct=1.5,
                wick_ratio=0.5,
                trend_1h_pct=1.0,
                trend_4h_pct=2.0,
                trend_24h_pct=3.0,
                change_5m_pct=0.2,
            ),
            "expected_code": ReasonCode.VWAP_DEVIATION_TOO_HIGH,
        },
        {
            "name": "ATR Too Low",
            "indicators": CandleIndicators(
                price=Decimal("1.5"),
                rsi_14=45.0,
                vwap=Decimal("1.5"),
                atr_pct=0.3,
                wick_ratio=0.5,
                trend_1h_pct=1.0,
                trend_4h_pct=2.0,
                trend_24h_pct=3.0,
                change_5m_pct=0.2,
            ),
            "expected_code": ReasonCode.ATR_TOO_LOW,
        },
        {
            "name": "ATR Too High",
            "indicators": CandleIndicators(
                price=Decimal("1.5"),
                rsi_14=45.0,
                vwap=Decimal("1.5"),
                atr_pct=8.0,
                wick_ratio=0.5,
                trend_1h_pct=1.0,
                trend_4h_pct=2.0,
                trend_24h_pct=3.0,
                change_5m_pct=0.2,
            ),
            "expected_code": ReasonCode.ATR_TOO_HIGH,
        },
    ]

    passed = 0
    failed = 0

    for scenario in scenarios:
        print(f"Test: {scenario['name']}")
        print(f"  Indicators: RSI={scenario['indicators'].rsi_14:.1f}, "
              f"ATR={scenario['indicators'].atr_pct:.1f}%, "
              f"VWAP deviation={(float(scenario['indicators'].price - scenario['indicators'].vwap) / float(scenario['indicators'].vwap) * 100):+.1f}%")

        allowed, reason, trace = filter_obj.allows_entry(
            "TEST-EUR",
            scenario['indicators'],
            trace_enabled=True
        )

        print(f"  Result: allowed={allowed}")
        print(f"  Reason: {reason}")

        if trace:
            print("  Trace:")
            print(f"    - reason_code: {trace.reason_code}")
            print(f"    - stage: {trace.stage}")
            print(f"    - rejected_by: {trace.rejected_by}")

            # Verify
            expected = scenario['expected_code'].value
            if trace.reason_code == expected:
                print(f"  ✅ PASS: reason_code matches {expected}")
                passed += 1
            else:
                print(f"  ❌ FAIL: expected {expected}, got {trace.reason_code}")
                failed += 1

            if trace.stage == Stage.SMART_ENTRY.value:
                print("  ✅ PASS: stage is SMART_ENTRY")
            else:
                print(f"  ❌ FAIL: stage is {trace.stage}, expected SMART_ENTRY")
                failed += 1
        else:
            print("  ❌ FAIL: No trace returned")
            failed += 1

        print()

    print("=" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 80)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
