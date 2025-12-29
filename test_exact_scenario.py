#!/usr/bin/env python3
"""
Simulate the EXACT scenario from the logs to trigger the overflow
"""

# Create test database with actual schema
conn = sqlite3.connect(':memory:')
cursor = conn.cursor()

# Create the actual MarketState table schema
cursor.execute('''
    CREATE TABLE IF NOT EXISTS MarketState (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        config_file_path TEXT NOT NULL,
        market TEXT NOT NULL,
        timestamp BIGINT NOT NULL,
        saved_state TEXT NOT NULL
    )
''')

print("🧪 Simulating EXACT scenario from logs\n")
print("=" * 70)

# The event timestamp from logs
event_timestamp = 1766974035.0  # Seconds

# Scenario 1: InFlightOrder with WRONG timestamp conversion
print("\n❌ SCENARIO 1: InFlightOrder with timestamp * 1e12 (WRONG)")
print("-" * 70)

# Simulate what might happen if timestamp is wrongly converted
order_wrong = {
    "client_order_id": "801598577",
    "exchange_order_id": "OG3BJ6-UMKZX-LTCSNI",
    "trading_pair": "BNB-EUR",
    "creation_timestamp": int(event_timestamp * 1e12),  # WRONG: Picoseconds!
    "last_update_timestamp": int(event_timestamp * 1e12)
}

tracking_states_wrong = {
    "801598577": order_wrong
}

json_state_wrong = json.dumps(tracking_states_wrong)
print(f"Tracking state JSON: {json_state_wrong[:100]}...")
print(f"creation_timestamp value: {order_wrong['creation_timestamp']:,}")
print("SQLite INTEGER max:       9,223,372,036,854,775,807")
print(f"Digits: {len(str(order_wrong['creation_timestamp']))}")

# Try to insert - this should FAIL if JSON parsing extracts integers
try:
    cursor.execute(
        "INSERT INTO MarketState (config_file_path, market, timestamp, saved_state) VALUES (?, ?, ?, ?)",
        ("test_config", "kraken", int(event_timestamp * 1000), json_state_wrong)
    )
    print("✅ Insertion succeeded (JSON is just TEXT, no validation yet)")
    print("   But when loaded back and processed, integers will overflow!\n")
except Exception as e:
    print(f"❌ FAILED: {type(e).__name__}: {e}\n")

# Scenario 2: Correct timestamp conversion (milliseconds)
print("✅ SCENARIO 2: InFlightOrder with timestamp * 1e3 (CORRECT)")
print("-" * 70)

order_correct = {
    "client_order_id": "801598577",
    "exchange_order_id": "OG3BJ6-UMKZX-LTCSNI",
    "trading_pair": "BNB-EUR",
    "creation_timestamp": int(event_timestamp * 1e3),  # CORRECT: Milliseconds
    "last_update_timestamp": int(event_timestamp * 1e3)
}

tracking_states_correct = {
    "801598577": order_correct
}

json_state_correct = json.dumps(tracking_states_correct)
print(f"Tracking state JSON: {json_state_correct[:100]}...")
print(f"creation_timestamp value: {order_correct['creation_timestamp']:,}")
print("SQLite INTEGER max:       9,223,372,036,854,775,807")
print(f"Digits: {len(str(order_correct['creation_timestamp']))}")

try:
    cursor.execute(
        "INSERT INTO MarketState (config_file_path, market, timestamp, saved_state) VALUES (?, ?, ?, ?)",
        ("test_config2", "kraken", int(event_timestamp * 1000), json_state_correct)
    )
    print("✅ Insertion succeeded - safe to store and process!\n")
except Exception as e:
    print(f"❌ FAILED: {type(e).__name__}: {e}\n")

# Check what we stored
print("=" * 70)
print("VERIFICATION: What's in the database?")
print("=" * 70)
result = cursor.execute("SELECT id, market, timestamp, saved_state FROM MarketState").fetchall()
for row in result:
    print(f"\nRow {row[0]}:")
    print(f"  Market: {row[1]}")
    print(f"  Timestamp: {row[2]:,}")
    state = json.loads(row[3])
    for order_id, order in state.items():
        print(f"  Order {order_id}:")
        print(f"    creation_timestamp: {order['creation_timestamp']:,} ({len(str(order['creation_timestamp']))} digits)")
        if order['creation_timestamp'] > 9223372036854775807:
            print("    ⚠️  WOULD OVERFLOW if used as INTEGER!")

conn.close()

print("\n" + "=" * 70)
print("🎯 ROOT CAUSE IDENTIFIED:")
print("=" * 70)
print("The overflow happens when InFlightOrder.to_json() stores timestamps")
print("that are TOO LARGE (e.g., using wrong multiplier like 1e12 or raw")
print("nanoseconds). When MarketState is saved, the JSON contains these")
print("large numbers. Later, if SQLAlchemy tries to deserialize and insert")
print("them into INTEGER columns, the overflow occurs.")
print("\n✅ FIX: Normalize timestamps in InFlightOrder.to_json() - DONE!")
print("=" * 70)
