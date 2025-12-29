#!/usr/bin/env python3
"""
Simple test to verify the timestamp normalization fix
"""

# Add the repo to path
sys.path.insert(0, '/home/mo/repos/hummingbot')

# Test the normalize_timestamp logic directly


def normalize_timestamp(ts):
    """Fixed version from in_flight_order.py"""
    if ts >= 1e18:  # Nanoseconds or larger (19+ digits)
        # For very large values (picoseconds), divide more aggressively
        return int(ts / 1e6) if ts < 1e21 else int(ts / 1e9)
    elif ts >= 1e15:  # Microseconds (16-18 digits)
        return int(ts / 1e3)  # microseconds -> milliseconds
    elif ts >= 1e12:  # Already milliseconds (13-15 digits)
        return int(ts)
    else:  # Seconds (< 13 digits) - convert to milliseconds
        return int(ts * 1e3)


print("=" * 70)
print("TIMESTAMP NORMALIZATION TEST")
print("=" * 70)

# Test cases
test_cases = [
    ("Seconds (from log)", 1766974035.0, 1766974035000),
    ("Already milliseconds", 1766974035000, 1766974035000),
    ("Microseconds", 1766974035000000, 1766974035000),  # Should convert to ms
    ("Nanoseconds (would overflow)", 1766974035000000000, 1766974035000),  # Should convert to ms
    ("Picoseconds (OVERFLOW!)", 1766974035000000000000, 1766974035000),  # Should convert to ms
]

max_int64 = 9223372036854775807
all_pass = True

for name, input_ts, expected in test_cases:
    result = normalize_timestamp(input_ts)
    status = "✅" if result == expected else "❌"
    overflow = result > max_int64

    print(f"\n{status} {name}")
    print(f"   Input:    {input_ts:>25,} ({len(str(int(input_ts)))} digits)")
    print(f"   Output:   {result:>25,} ({len(str(result))} digits)")
    print(f"   Expected: {expected:>25,}")

    if overflow:
        print(f"   ⚠️  OVERFLOW: Exceeds SQLite INTEGER max by {result - max_int64:,}")
        all_pass = False
    elif result > 9e15:
        print("   ⚠️  WARNING: Very large value, close to overflow")
    else:
        print("   ✓ Safe for SQLite INTEGER")

    if result != expected:
        print("   ❌ MISMATCH!")
        all_pass = False

print("\n" + "=" * 70)
if all_pass:
    print("✅ ALL TESTS PASSED - Fix prevents overflow!")
else:
    print("❌ SOME TESTS FAILED - Fix needs adjustment")
print("=" * 70)
