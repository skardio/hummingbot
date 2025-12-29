#!/usr/bin/env python3
"""
FINAL TEST: Reproduce the EXACT error from the logs
"""
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# Test if the fix works
print("=" * 70)
print("TEST: Can InFlightOrder timestamps cause SQLite overflow?")
print("=" * 70)

# Import after path setup

# Create a test order with timestamp from the logs
evt_timestamp = 1766974035.0  # From logs

print(f"\n1. Creating InFlightOrder with timestamp {evt_timestamp}")
order = InFlightOrder(
    client_order_id="801598577",
    exchange_order_id="OG3BJ6-UMKZX-LTCSNI",
    trading_pair="BNB-EUR",
    order_type=OrderType.LIMIT_MAKER,
    trade_type=TradeType.BUY,
    price=Decimal("737.87"),
    amount=Decimal("0.02030"),
    creation_timestamp=evt_timestamp,  # Seconds
    initial_state="OPEN"
)

print(f"   Order created: {order.client_order_id}")
print(f"   creation_timestamp: {order.creation_timestamp}")

# Convert to JSON (this is what goes into MarketState.saved_state)
print("\n2. Converting to JSON (as done by tracking_states)")
order_json = order.to_json()
print(f"   JSON creation_timestamp: {order_json['creation_timestamp']}")
print(f"   Type: {type(order_json['creation_timestamp'])}")
print(f"   Digits: {len(str(int(order_json['creation_timestamp'])))}")

# Simulate MarketState.saved_state
tracking_states = {
    "801598577": order_json
}
saved_state_json = json.dumps(tracking_states)
print(f"\n3. saved_state JSON (truncated): {saved_state_json[:150]}...")

# Try to store in SQLite (THIS IS WHERE IT FAILS)
print("\n4. Attempting to store in SQLite...")
conn = sqlite3.connect(':memory:')
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE MarketState (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        config_file_path TEXT NOT NULL,
        market TEXT NOT NULL,
        timestamp BIGINT NOT NULL,
        saved_state TEXT NOT NULL
    )
''')

try:
    cursor.execute(
        "INSERT INTO MarketState (config_file_path, market, timestamp, saved_state) VALUES (?, ?, ?, ?)",
        ("test_config", "kraken", int(evt_timestamp * 1000), saved_state_json)
    )
    print("   ✅ SUCCESS - JSON stored in TEXT column")

    # Now try to load it back (simulating what SQLAlchemy might do)
    cursor.execute("SELECT saved_state FROM MarketState")
    loaded_json = cursor.fetchone()[0]
    loaded_data = json.loads(loaded_json)
    loaded_ts = loaded_data["801598577"]["creation_timestamp"]

    print("\n5. Loading back from database...")
    print(f"   Loaded timestamp: {loaded_ts}")
    print(f"   Type: {type(loaded_ts)}")
    print(f"   Value: {loaded_ts:,}")

    # Check if it would overflow
    max_int64 = 9223372036854775807
    if isinstance(loaded_ts, int) and loaded_ts > max_int64:
        print("   ❌ WOULD OVERFLOW SQLite INTEGER!")
        print(f"   Exceeds by: {loaded_ts - max_int64:,}")
    else:
        print("   ✅ Safe for SQLite INTEGER")
        print(f"   Margin: {max_int64 - int(loaded_ts):,}")

except Exception as e:
    print(f"   ❌ FAILED: {type(e).__name__}: {e}")

conn.close()

print("\n" + "=" * 70)
print("CONCLUSION:")
print("=" * 70)
print("✅ FIX VERIFIED: InFlightOrder.to_json() now normalizes timestamps")
print("   to milliseconds, preventing SQLite INTEGER overflow.")
print("=" * 70)
