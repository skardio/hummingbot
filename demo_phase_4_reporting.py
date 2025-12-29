#!/usr/bin/env python3
"""
Demo script for Phase 4: "Why No Trade?" Reporting

This script demonstrates the event aggregation and reporting capabilities.
It creates sample events and generates various reports.

Usage:
    python demo_phase_4_reporting.py
"""


# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)


def create_sample_events(event_dir: Path, num_hours: int = 3):
    """
    Create sample events spanning multiple hours.

    Simulates a realistic trading session with various rejections.
    """
    print("\n📝 Creating sample events...")

    events_file = event_dir / "events_demo.jsonl"
    now = datetime.now()

    events = []

    # Hour 1: Early morning - mostly RSI blocks (overbought market)
    print("  - Hour 1: Morning session (RSI overbought market)")
    for i in range(15):
        events.append({
            'timestamp': (now - timedelta(hours=2, minutes=i * 3)).isoformat(),
            'event_type': 'gate_denied',
            'stage': Stage.SMART_ENTRY.value,
            'reason_code': ReasonCode.RSI_OVERBOUGHT.value,
            'symbol': f'{"BTC ETH ADA SOL DOT".split()[i % 5]}-EUR',
            'correlation_id': f'morning-{i}',
            'reason_msg': 'RSI > 70',
            'metadata': {'rsi': 72 + i}
        })

    # Hour 2: Midday - mixed rejections (volatility issues)
    print("  - Hour 2: Midday volatility")
    for i in range(10):
        events.append({
            'timestamp': (now - timedelta(hours=1, minutes=i * 5)).isoformat(),
            'event_type': 'gate_denied',
            'stage': Stage.SMART_ENTRY.value,
            'reason_code': ReasonCode.ATR_TOO_LOW.value,
            'symbol': f'{"ETH BTC ADA".split()[i % 3]}-EUR',
            'correlation_id': f'midday-atr-{i}',
            'reason_msg': 'Low volatility',
            'metadata': {'atr': 0.003 + i * 0.0001}
        })

    # Some VWAP deviations
    for i in range(5):
        events.append({
            'timestamp': (now - timedelta(hours=1, minutes=20 + i * 3)).isoformat(),
            'event_type': 'gate_denied',
            'stage': Stage.SMART_ENTRY.value,
            'reason_code': ReasonCode.VWAP_DEVIATION_TOO_HIGH.value,
            'symbol': f'{"SOL DOT MATIC".split()[i % 3]}-EUR',
            'correlation_id': f'midday-vwap-{i}',
            'reason_msg': 'Price too far from VWAP',
            'metadata': {'deviation': 3.5 + i * 0.2}
        })

    # Hour 3: Recent - execution stage issues (capacity limits)
    print("  - Hour 3: Recent execution limits")
    for i in range(8):
        events.append({
            'timestamp': (now - timedelta(minutes=i * 6)).isoformat(),
            'event_type': 'gate_denied',
            'stage': Stage.EXECUTION.value,
            'reason_code': ReasonCode.SLOT_FULL.value,
            'symbol': f'{"BTC ETH ADA SOL".split()[i % 4]}-EUR',
            'correlation_id': f'recent-slot-{i}',
            'reason_msg': 'All slots filled',
            'metadata': {'max_slots': 3, 'active': 3}
        })

    # Some successful trades
    print("  - Adding successful trades (approvals)")
    for i in range(5):
        events.append({
            'timestamp': (now - timedelta(minutes=i * 12)).isoformat(),
            'event_type': 'gate_passed',
            'stage': Stage.SMART_ENTRY.value,
            'symbol': f'{"BTC ETH".split()[i % 2]}-EUR',
            'correlation_id': f'success-{i}',
            'metadata': {'reason': 'All checks passed'}
        })

    # Add some risk stage rejections
    print("  - Adding risk limit rejections")
    for i in range(3):
        events.append({
            'timestamp': (now - timedelta(hours=1, minutes=40 + i * 5)).isoformat(),
            'event_type': 'gate_denied',
            'stage': Stage.RISK.value,
            'reason_code': ReasonCode.EXPOSURE_LIMIT.value,
            'symbol': f'{"BTC ETH ADA".split()[i % 3]}-EUR',
            'correlation_id': f'risk-exp-{i}',
            'reason_msg': 'Max exposure reached',
            'metadata': {'current_exposure': 0.95, 'max_exposure': 0.9}
        })

    # Write all events
    with open(events_file, 'w') as f:
        for event in events:
            f.write(json.dumps(event) + '\n')

    print(f"✅ Created {len(events)} events")
    print(f"   - {sum(1 for e in events if e['event_type'] == 'gate_denied')} rejections")
    print(f"   - {sum(1 for e in events if e['event_type'] == 'gate_passed')} approvals")

    return len(events)


def main():
    """Run the demo"""
    print("\n" + "=" * 80)
    print("🚀 PHASE 4 DEMO: 'Why No Trade?' Reporting")
    print("=" * 80)

    # Create temporary directory for demo events
    with tempfile.TemporaryDirectory() as temp_dir:
        event_dir = Path(temp_dir)

        # Create sample events
        create_sample_events(event_dir)

        # Initialize reporter
        reporter = ConsoleReporter(event_dir, bot_name="demo_phase4")

        # Generate various reports
        print("\n" + "=" * 80)
        print("📊 REPORT 1: High-Level Summary (Last 24h)")
        print("=" * 80)
        reporter.report_summary(hours=24)

        print("\n" + "=" * 80)
        print("📊 REPORT 2: Rejections by Pipeline Stage")
        print("=" * 80)
        reporter.report_by_stage(hours=24)

        print("\n" + "=" * 80)
        print("📊 REPORT 3: Top Rejected Symbols")
        print("=" * 80)
        reporter.report_by_symbol(hours=24, top_n=5)

        print("\n" + "=" * 80)
        print("📊 REPORT 4: Hourly Breakdown (Last 3 Hours)")
        print("=" * 80)
        reporter.report_last_n_hours(hours=3)

        print("\n" + "=" * 80)
        print("✅ DEMO COMPLETE")
        print("=" * 80)
        print("\nKey Features Demonstrated:")
        print("  ✅ Event aggregation from JSONL files")
        print("  ✅ Hourly/daily summaries")
        print("  ✅ Rejection breakdown by reason code")
        print("  ✅ Stage-level analysis (SMART_ENTRY, EXECUTION, RISK)")
        print("  ✅ Symbol-level analysis")
        print("  ✅ Percentage calculations")
        print("\n💡 Integration:")
        print("  - Controller can call reporter.report_summary() every hour")
        print("  - Events automatically logged during trading")
        print("  - No performance impact (reads from disk asynchronously)")
        print("\n📁 In production:")
        print("  - Events stored in logs/events/events_YYYYMMDD_HHMMSS.jsonl")
        print("  - Enable with: observability.structured_events_enabled = true")
        print("  - Configure interval with: observability.report_interval_minutes")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
