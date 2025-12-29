#!/usr/bin/env python3
"""
Demo: Enhanced SLOT_FULL reporting with missed opportunities tracking.

Shows the new feature that tracks which symbols were missed due to SLOT_FULL.
"""

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))


def create_sample_events_with_missed_opportunities():
    """Create sample events showing the new SLOT_FULL enhancement."""

    base_time = datetime.now()
    events = []

    # Simulate a bot running at full capacity
    # Over 1 hour, it encounters many SLOT_FULL situations

    for i in range(30):  # 30 SLOT_FULL events
        # Rotate through popular coins as missed opportunities
        missed_candidates = [
            ['BTC-EUR', 'ETH-EUR', 'SOL-EUR'],
            ['ETH-EUR', 'BTC-EUR', 'BNB-EUR'],
            ['BTC-EUR', 'SOL-EUR', 'MATIC-EUR'],
            ['AVAX-EUR', 'BTC-EUR', 'ETH-EUR'],
            ['BTC-EUR', 'ETH-EUR', 'LINK-EUR'],
        ]

        candidates = missed_candidates[i % len(missed_candidates)]

        event = {
            'ts': (base_time - timedelta(minutes=60 - i * 2)).timestamp(),
            'event_type': 'gate_denied',
            'reason_code': 'SLOT_FULL',
            'symbol': candidates[0],  # NEW: First candidate as symbol
            'reason_msg': 'All 1 slots filled',
            'metadata': {
                'max_slots': 1,
                'active_coins': ['SUI-EUR'],  # Current position
                'missed_candidates': candidates,  # NEW: Top 3 missed opportunities
                'timestamp': (base_time - timedelta(minutes=60 - i * 2)).timestamp()
            }
        }
        events.append(event)

    # Add some other rejections for context
    other_reasons = [
        'RSI_OVERBOUGHT',
        'ATR_TOO_LOW',
        'VWAP_DEVIATION_TOO_HIGH',
    ]

    for i, reason in enumerate(other_reasons * 10):  # 30 other rejections
        event = {
            'ts': (base_time - timedelta(minutes=60 - i)).timestamp(),
            'event_type': 'gate_denied',
            'reason_code': reason,
            'symbol': 'DOGE-EUR',
            'reason_msg': f'Rejected by {reason}',
            'metadata': {
                'timestamp': (base_time - timedelta(minutes=60 - i)).timestamp()
            }
        }
        events.append(event)

    # Add some approvals
    for i in range(5):
        event = {
            'ts': (base_time - timedelta(minutes=60 - i * 10)).timestamp(),
            'event_type': 'gate_passed',
            'symbol': 'SUI-EUR',
            'metadata': {
                'timestamp': (base_time - timedelta(minutes=60 - i * 10)).timestamp()
            }
        }
        events.append(event)

    return sorted(events, key=lambda x: x['ts'])


def demo_enhanced_reporting():
    """Demonstrate the enhanced SLOT_FULL reporting."""

    print("=" * 80)
    print("DEMO: Enhanced SLOT_FULL Reporting with Missed Opportunities")
    print("=" * 80)
    print()
    print("This demo shows the NEW feature that tracks which symbols were missed")
    print("due to SLOT_FULL capacity constraints.")
    print()

    # Create temp directory with sample events
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = Path(tmpdir) / 'events'
        events_dir.mkdir()

        # Write sample events
        events = create_sample_events_with_missed_opportunities()
        events_file = events_dir / f'events_{datetime.now().strftime("%Y%m%d_%H%M%S")}.jsonl'

        with open(events_file, 'w') as f:
            for event in events:
                f.write(json.dumps(event) + '\n')

        print(f"✅ Created {len(events)} sample events in temporary directory")
        print("   - 30 SLOT_FULL events (with missed opportunities)")
        print("   - 30 other rejections (RSI, ATR, VWAP)")
        print("   - 5 approvals")
        print()

        # Create aggregator and reporter
        _aggregator = EventAggregator(log_dir=events_dir)

        # Create a simple logger for demo
        import logging
        logger = logging.getLogger('demo')
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        logger.addHandler(handler)

        reporter = ConsoleReporter(log_dir=events_dir, logger=logger, bot_name="demo_slot_full")

        # Generate report
        print("=" * 80)
        print("REPORT OUTPUT:")
        print("=" * 80)
        print()

        reporter.report_summary(hours=2)

        print()
        print("=" * 80)
        print("KEY INSIGHTS:")
        print("=" * 80)
        print()
        print("🎯 NEW SECTION: 'Top Missed Opportunities (SLOT_FULL)'")
        print("   - Shows which symbols were rejected due to lack of capacity")
        print("   - Based on the 'missed_candidates' metadata from SLOT_FULL events")
        print("   - Helps answer: 'If I add more slots, which coins would I trade?'")
        print()
        print("💡 Use this data to:")
        print("   1. Decide if you need more slots (max_simultaneous_coins)")
        print("   2. See which high-potential coins you're missing")
        print("   3. Adjust your ranking algorithm if wrong coins are prioritized")
        print()
        print("📊 In this demo:")
        print("   - BTC-EUR appears most often in missed opportunities")
        print("   - ETH-EUR is second")
        print("   - This suggests increasing slots would capture these opportunities")
        print()
        print("=" * 80)


if __name__ == '__main__':
    demo_enhanced_reporting()
