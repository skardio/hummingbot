"""
Demo: Dynamic Slot Manager (Task 3.1)

Shows how slot allocation scales with account size and regime.
"""

from decimal import Decimal

from multi_coin_grid_pro.execution.dynamic_slot_manager import DynamicSlotManager


def demo_dynamic_slots():
    """Demonstrate dynamic slot allocation"""
    print("=" * 80)
    print("TASK 3.1: DYNAMIC SLOT MANAGER DEMO")
    print("=" * 80)
    print()

    # Create manager with default config
    manager = DynamicSlotManager(config={
        "enabled": True,
        "min_slots": 1,
        "max_slots": 12,
        "regime_multipliers": {
            "BULL": Decimal("1.5"),
            "CHOP": Decimal("0.75"),
            "BEAR": Decimal("0.25")
        }
    })

    # Demo different account sizes
    account_sizes = [
        (Decimal("350"), "Small Account"),
        (Decimal("700"), "Medium-Small"),
        (Decimal("1000"), "Medium"),
        (Decimal("1500"), "Medium-Large"),
        (Decimal("2000"), "Large"),
        (Decimal("3000"), "Very Large")
    ]

    regimes = ["baseline", "BULL", "CHOP", "BEAR"]

    print("📊 SLOT ALLOCATION TABLE")
    print("-" * 80)
    print(f"{'Account':<20} {'Balance':>10} {'baseline':>10} {'BULL':>10} {'CHOP':>10} {'BEAR':>10}")
    print("-" * 80)

    for balance, name in account_sizes:
        slots = {}
        for regime in regimes:
            slots[regime] = manager.get_dynamic_slots(
                account_balance_eur=balance,
                current_regime=regime,
                static_fallback=4
            )

        print(f"{name:<20} €{float(balance):>9,.0f} {slots['baseline']:>10} "
              f"{slots['BULL']:>10} {slots['CHOP']:>10} {slots['BEAR']:>10}")

    print("-" * 80)
    print()

    # Show detailed report for €1000 account
    print("📈 DETAILED REPORT: €1000 Account in BULL Regime")
    print("-" * 80)
    report = manager.get_slot_report(
        account_balance_eur=Decimal("1000"),
        current_regime="BULL"
    )
    print(report)
    print()

    # Demo regime transitions
    print("🔄 REGIME TRANSITION SIMULATION: €1000 Account")
    print("-" * 80)

    balance = Decimal("1000")
    transitions = [
        ("baseline", "Starting in baseline market"),
        ("BULL", "Market turns bullish → increase slots"),
        ("CHOP", "Market becomes choppy → reduce slots"),
        ("BEAR", "Market turns bearish → defensive mode"),
        ("baseline", "Market normalizes → back to baseline")
    ]

    for regime, description in transitions:
        slots = manager.get_dynamic_slots(
            account_balance_eur=balance,
            current_regime=regime,
            static_fallback=4
        )
        multiplier = manager._get_regime_multiplier(regime)
        print(f"{regime:>10} ({multiplier:>4}x): {slots:>2} slots - {description}")

    print()
    print("=" * 80)
    print("KEY BENEFITS:")
    print("=" * 80)
    print("✅ Risk-adjusted: Smaller accounts = fewer slots (capital preservation)")
    print("✅ Regime-aware: BULL = more slots, BEAR = defensive")
    print("✅ Smooth scaling: Linear interpolation between tiers")
    print("✅ Bounded: Respects min/max slots for safety")
    print("✅ Professional: Adapts to market conditions automatically")
    print()


if __name__ == "__main__":
    demo_dynamic_slots()
