#!/usr/bin/env python3
"""
Monitor Memory Cleanup Activity from Bot Logs

Tracks the memory cleanup messages to verify the fix is working.
Analyzes both current run and historical cleanup patterns.
"""

import glob
import re
from collections import defaultdict


def parse_log_file(log_path):
    """Parse a single log file for memory cleanup events"""
    cleanups = []

    with open(log_path, 'r', errors='ignore') as f:
        for line in f:
            # Match cleanup log lines
            # Example: "🧹 Memory cleanup: Removed 250 old tracked executors (750 remaining)"
            match = re.search(
                r'🧹 Memory cleanup: Removed (\d+) old (tracked executors|timeout executors) \((\d+) remaining\)',
                line
            )

            if match:
                # Extract timestamp from log line (format: YYYY-MM-DD HH:MM:SS)
                ts_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
                timestamp = ts_match.group(1) if ts_match else "unknown"

                removed = int(match.group(1))
                cleanup_type = match.group(2)
                remaining = int(match.group(3))

                cleanups.append({
                    'timestamp': timestamp,
                    'type': cleanup_type,
                    'removed': removed,
                    'remaining': remaining,
                    'file': log_path
                })

    return cleanups


def analyze_memory_health():
    """Analyze memory cleanup activity from logs"""
    print("=" * 80)
    print("MEMORY CLEANUP MONITORING")
    print("=" * 80)
    print()

    # Find all log files
    log_patterns = [
        'logs/*.log',
        'logs/kraken/*.log',
        'logs/bitget/*.log'
    ]

    all_log_files = []
    for pattern in log_patterns:
        all_log_files.extend(glob.glob(pattern))

    if not all_log_files:
        print("❌ No log files found in logs/ directory")
        print("   Make sure bot is running and has created logs")
        return

    print(f"📁 Scanning {len(all_log_files)} log file(s)...\n")

    # Parse all logs
    all_cleanups = []
    for log_file in sorted(all_log_files):
        cleanups = parse_log_file(log_file)
        all_cleanups.extend(cleanups)

    if not all_cleanups:
        print("✅ No cleanup events found yet")
        print()
        print("This means either:")
        print("  1. Bot hasn't run long enough to hit thresholds")
        print("  2. Memory usage is healthy (< 1000 tracked, < 500 timeouts)")
        print("  3. Bot needs restart to activate the fix")
        print()
        print("💡 Cleanup triggers:")
        print("   - When _realised_executors_tracked > 1000")
        print("   - When _processed_timeout_executors > 500")
        print()
        return

    # Analyze cleanup patterns
    print(f"🧹 Found {len(all_cleanups)} cleanup event(s):\n")

    # Group by type
    by_type = defaultdict(list)
    for cleanup in all_cleanups:
        by_type[cleanup['type']].append(cleanup)

    # Show recent cleanups
    print("📊 RECENT CLEANUP ACTIVITY:")
    print("-" * 80)

    for cleanup in sorted(all_cleanups, key=lambda x: x['timestamp'], reverse=True)[:10]:
        print(f"{cleanup['timestamp']} | {cleanup['type']:20} | "
              f"Removed: {cleanup['removed']:4} | Remaining: {cleanup['remaining']:4}")

    print()

    # Summary statistics
    print("📈 CLEANUP STATISTICS:")
    print("-" * 80)

    for cleanup_type, events in by_type.items():
        total_removed = sum(e['removed'] for e in events)
        avg_removed = total_removed / len(events) if events else 0

        recent_remaining = events[-1]['remaining'] if events else 0

        print(f"\n{cleanup_type}:")
        print(f"  Total cleanup events: {len(events)}")
        print(f"  Total entries removed: {total_removed}")
        print(f"  Average per cleanup: {avg_removed:.1f}")
        print(f"  Current remaining: {recent_remaining}")

        if recent_remaining > 900 and 'tracked' in cleanup_type:
            print("  ⚠️  Near threshold (1000) - cleanup will trigger soon")
        elif recent_remaining > 450 and 'timeout' in cleanup_type:
            print("  ⚠️  Near threshold (500) - cleanup will trigger soon")
        else:
            print("  ✅ Healthy level")

    print()
    print("=" * 80)
    print("MEMORY HEALTH STATUS:")
    print("=" * 80)

    if len(all_cleanups) > 0:
        print("✅ Memory cleanup is ACTIVE and working")
        print("   - Leak prevention mechanism is operational")
        print("   - Memory usage is bounded")
        print()

    # Check for concerning patterns
    recent_tracked = [e for e in by_type.get('tracked executors', []) if e['remaining']]
    if recent_tracked and recent_tracked[-1]['remaining'] > 950:
        print("⚠️  Tracked executors near limit - expect cleanup soon")

    recent_timeout = [e for e in by_type.get('timeout executors', []) if e['remaining']]
    if recent_timeout and recent_timeout[-1]['remaining'] > 480:
        print("⚠️  Timeout executors near limit - expect cleanup soon")

    print()


if __name__ == "__main__":
    try:
        analyze_memory_health()
    except KeyboardInterrupt:
        print("\n\n❌ Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
