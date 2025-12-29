#!/usr/bin/env python3
"""
Test SLOT_FULL enhancement - verifies that missed candidates are now tracked.
"""


def analyze_slot_full_events():
    """Analyze SLOT_FULL events to see if symbols are now populated."""

    print("=" * 80)
    print("SLOT_FULL Enhancement Analysis")
    print("=" * 80)

    # Read all events
    events = []
    event_dir = Path('logs/events')

    if not event_dir.exists():
        print("❌ No logs/events directory found")
        return

    for jsonl_file in sorted(event_dir.glob('events_*.jsonl')):
        with open(jsonl_file) as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except Exception:

    # Filter SLOT_FULL events
    slot_full_events = [
        e for e in events
        if e.get('event_type') == 'gate_denied'
        and e.get('reason_code') == 'SLOT_FULL'
    ]

    print(f"\n📊 Total SLOT_FULL events: {len(slot_full_events)}")

    if not slot_full_events:
        print("   No SLOT_FULL events found yet. Run bot to generate new events.")
        return

    # Analyze symbols
    symbols = Counter()
    na_count = 0
    with_candidates = 0

    for event in slot_full_events:
        symbol = event.get('symbol', 'N/A')
        symbols[symbol] += 1

        if symbol == 'N/A':
            na_count += 1

        # Check if metadata has missed_candidates
        metadata = event.get('metadata', {})
        if metadata.get('missed_candidates'):
            with_candidates += 1

    print("\n🔍 Symbol Distribution:")
    print(f"   Events with symbol='N/A': {na_count} ({na_count / len(slot_full_events) * 100:.1f}%)")
    print(f"   Events with real symbols: {len(slot_full_events) - na_count} ({(len(slot_full_events) - na_count) / len(slot_full_events) * 100:.1f}%)")
    print(f"   Events with missed_candidates: {with_candidates} ({with_candidates / len(slot_full_events) * 100:.1f}%)")

    # Show top symbols
    print("\n📈 Top 10 Missed Symbols:")
    for symbol, count in symbols.most_common(10):
        pct = (count / len(slot_full_events)) * 100
        print(f"   {symbol:15s} {count:4d} ({pct:5.1f}%)")

    # Show example event with missed_candidates
    print("\n📋 Example SLOT_FULL Event (latest):")
    latest = slot_full_events[-1]
    print(f"   Symbol: {latest.get('symbol')}")
    print(f"   Reason: {latest.get('reason_msg')}")

    metadata = latest.get('metadata', {})
    if metadata.get('missed_candidates'):
        print(f"   Missed Candidates: {metadata['missed_candidates']}")
    else:
        print("   Missed Candidates: (not available)")

    print(f"   Active Coins: {metadata.get('active_coins', [])}")
    print(f"   Max Slots: {metadata.get('max_slots')}")

    print("\n" + "=" * 80)
    print("✅ ENHANCEMENT STATUS:")

    if na_count == len(slot_full_events):
        print("   ⚠️  All events still have symbol='N/A'")
        print("   💡 These are OLD events from before the enhancement")
        print("   🔄 Restart bot to generate NEW events with symbols")
    elif with_candidates > 0:
        print(f"   ✅ {with_candidates} events now track missed candidates!")
        print(f"   🎯 Top missed opportunity: {symbols.most_common(1)[0][0]}")
    else:
        print("   ⚠️  Enhancement deployed but no new events yet")
        print("   🔄 Wait for bot to hit SLOT_FULL again")

    print("=" * 80)


if __name__ == '__main__':
    analyze_slot_full_events()
