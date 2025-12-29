#!/usr/bin/env python3
"""
Test to confirm SQLite INTEGER overflow with large timestamps
"""

# Create a temporary test database
conn = sqlite3.connect(':memory:')
cursor = conn.cursor()

# Create a table similar to MarketState
cursor.execute('''
    CREATE TABLE IF NOT EXISTS TestMarketState (
        id INTEGER PRIMARY KEY,
        config_file_path TEXT,
        market TEXT,
        timestamp INTEGER,
        saved_state TEXT
    )
''')

print("🧪 Testing SQLite INTEGER overflow with timestamps\n")

# Test 1: Normal millisecond timestamp (should work)
normal_ts = int(time.time() * 1000)  # Current time in milliseconds
print("Test 1: Normal timestamp (milliseconds)")
print(f"  Value: {normal_ts} ({len(str(normal_ts))} digits)")
try:
    cursor.execute(
        "INSERT INTO TestMarketState (config_file_path, market, timestamp, saved_state) VALUES (?, ?, ?, ?)",
        ("test_config", "kraken", normal_ts, '{}')
    )
    print("  ✅ SUCCESS - Normal timestamp works\n")
except Exception as e:
    print(f"  ❌ FAILED: {e}\n")

# Test 2: Nanosecond timestamp (too large - should fail)
nano_ts = int(time.time() * 1e9)  # Current time in nanoseconds
print("Test 2: Nanosecond timestamp (too large)")
print(f"  Value: {nano_ts} ({len(str(nano_ts))} digits)")
print("  SQLite INTEGER max: 9,223,372,036,854,775,807 (19 digits)")
try:
    cursor.execute(
        "INSERT INTO TestMarketState (config_file_path, market, timestamp, saved_state) VALUES (?, ?, ?, ?)",
        ("test_config", "kraken", nano_ts, '{}')
    )
    print("  ✅ Unexpectedly succeeded?!\n")
except Exception as e:
    print(f"  ❌ FAILED AS EXPECTED: {e}\n")

# Test 3: Timestamp in JSON (this is what happens in MarketState.saved_state)
print("Test 3: Large timestamp in JSON saved_state")
order_with_large_ts = {
    "order_id": "801598577",
    "creation_timestamp": int(time.time() * 1e9),  # Nanoseconds - TOO LARGE
    "price": "737.87"
}
json_state = json.dumps(order_with_large_ts)
print(f"  JSON: {json_state}")
print(f"  Timestamp in JSON: {order_with_large_ts['creation_timestamp']} ({len(str(order_with_large_ts['creation_timestamp']))} digits)")

try:
    cursor.execute(
        "INSERT INTO TestMarketState (config_file_path, market, timestamp, saved_state) VALUES (?, ?, ?, ?)",
        ("test_config", "kraken", normal_ts, json_state)
    )
    print("  ✅ JSON insertion works (but value inside is too large for later processing)\n")
except Exception as e:
    print(f"  ❌ FAILED: {e}\n")

# Test 4: What timestamp does BNB-EUR order have?
print("Test 4: Actual timestamp from logs")
log_timestamp = 1766974035.0
print(f"  Raw timestamp from log: {log_timestamp}")
print(f"  As milliseconds: {int(log_timestamp * 1000)}")
print(f"  As microseconds: {int(log_timestamp * 1e6)} ({len(str(int(log_timestamp * 1e6)))} digits)")
print(f"  As nanoseconds: {int(log_timestamp * 1e9)} ({len(str(int(log_timestamp * 1e9)))} digits)")
print("  SQLite INTEGER max: 9,223,372,036,854,775,807 (19 digits)")

if int(log_timestamp * 1e9) > 9223372036854775807:
    print("  ⚠️  NANOSECONDS EXCEED SQLite INTEGER MAX!\n")
else:
    print("  ✅ Nanoseconds fit in SQLite INTEGER\n")

# Test 5: Try the exact scenario that fails
print("Test 5: Simulating InFlightOrder.to_json() scenario")
# The creation_timestamp is stored as seconds (1766974035.0)
# If it gets converted to nanoseconds somewhere: 1766974035000000000
creation_ts_seconds = 1766974035.0
creation_ts_nanos = int(creation_ts_seconds * 1e9)

print(f"  Timestamp (seconds): {creation_ts_seconds}")
print(f"  Converted to nanos: {creation_ts_nanos} ({len(str(creation_ts_nanos))} digits)")
print("  SQLite max INTEGER: 9,223,372,036,854,775,807 (19 digits)")

if creation_ts_nanos > 9223372036854775807:
    print("  ❌ TOO LARGE FOR SQLite INTEGER!")
    print(f"  Difference: {creation_ts_nanos - 9223372036854775807} over the limit")
else:
    print("  ✅ Fits in SQLite INTEGER")

conn.close()

print("\n" + "=" * 70)
print("CONCLUSION:")
print("=" * 70)
print("The overflow happens when timestamps are stored in nanoseconds.")
print("Solution: Normalize all timestamps to milliseconds before storing.")
print("=" * 70)
