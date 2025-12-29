#!/usr/bin/env python3
"""
Test to find the ACTUAL cause of the SQLite INTEGER overflow
"""

conn = sqlite3.connect(':memory:')
cursor = conn.cursor()

cursor.execute('''
    CREATE TABLE TestTable (
        id INTEGER PRIMARY KEY,
        value INTEGER
    )
''')

print("🔍 Finding the INTEGER overflow threshold\n")

# SQLite INTEGER is 64-bit signed: -9,223,372,036,854,775,808 to 9,223,372,036,854,775,807
max_int64 = 9223372036854775807
min_int64 = -9223372036854775808

print("SQLite INTEGER range:")
print(f"  Min: {min_int64:,}")
print(f"  Max: {max_int64:,}\n")

# Test 1: Max safe value
print("Test 1: SQLite max INTEGER")
try:
    cursor.execute("INSERT INTO TestTable (value) VALUES (?)", (max_int64,))
    print(f"  ✅ {max_int64:,} - SUCCESS\n")
except Exception as e:
    print(f"  ❌ FAILED: {e}\n")

# Test 2: One over the max
print("Test 2: One over max INTEGER")
try:
    cursor.execute("INSERT INTO TestTable (value) VALUES (?)", (max_int64 + 1,))
    print(f"  ✅ {max_int64 + 1:,} - Unexpectedly succeeded\n")
except Exception as e:
    print(f"  ❌ FAILED AS EXPECTED: {e}\n")

# Test 3: Python int that's too large
print("Test 3: Very large Python int")
huge_int = 10**20  # 100,000,000,000,000,000,000
print(f"  Value: {huge_int:,} ({len(str(huge_int))} digits)")
try:
    cursor.execute("INSERT INTO TestTable (value) VALUES (?)", (huge_int,))
    print("  ✅ Unexpectedly succeeded\n")
except Exception as e:
    print(f"  ❌ FAILED: {type(e).__name__}: {e}\n")

# Test 4: From the actual log - order_id as INTEGER
print("Test 4: Actual order_id from logs")
order_id_str = "801598577"
order_id_int = int(order_id_str)
print(f"  Order ID: {order_id_int:,}")
try:
    cursor.execute("INSERT INTO TestTable (value) VALUES (?)", (order_id_int,))
    print("  ✅ SUCCESS - order_id fits\n")
except Exception as e:
    print(f"  ❌ FAILED: {e}\n")

# Test 5: Timestamp from logs in nanoseconds
print("Test 5: Timestamp as nanoseconds")
ts = 1766974035000000000
print(f"  Value: {ts:,} ({len(str(ts))} digits)")
print(f"  Max:   {max_int64:,} ({len(str(max_int64))} digits)")
print(f"  Diff:  {max_int64 - ts:,}")
try:
    cursor.execute("INSERT INTO TestTable (value) VALUES (?)", (ts,))
    print("  ✅ SUCCESS - fits in INTEGER\n")
except Exception as e:
    print(f"  ❌ FAILED: {e}\n")

# Test 6: What if it's a float that becomes huge when converted?
print("Test 6: Float precision causing overflow")
# Sometimes float operations can create unexpectedly large numbers
ts_float = 1766974035.0
# If someone does ts_float * 1e12 instead of 1e3...
ts_wrong = int(ts_float * 1e12)
print(f"  If multiplied by 1e12: {ts_wrong:,} ({len(str(ts_wrong))} digits)")
print(f"  SQLite max:            {max_int64:,} ({len(str(max_int64))} digits)")
print(f"  Exceeds by:            {ts_wrong - max_int64:,}")
try:
    cursor.execute("INSERT INTO TestTable (value) VALUES (?)", (ts_wrong,))
    print("  ✅ Unexpectedly succeeded\n")
except Exception as e:
    print(f"  ❌ FAILED: {type(e).__name__}: {e}\n")

# Test 7: The REAL issue - Python timestamp() method returns float
print("Test 7: datetime.timestamp() * 1e12")
dt = datetime.datetime.now()
ts_seconds = dt.timestamp()
# If converted with wrong multiplier
ts_picoseconds = int(ts_seconds * 1e12)  # Picoseconds!
print(f"  Timestamp (seconds):     {ts_seconds}")
print(f"  If converted to pico:    {ts_picoseconds:,} ({len(str(ts_picoseconds))} digits)")
print(f"  SQLite max:              {max_int64:,} ({len(str(max_int64))} digits)")
if ts_picoseconds > max_int64:
    print(f"  ⚠️  OVERFLOW! Exceeds by: {ts_picoseconds - max_int64:,}")
else:
    print(f"  Fits (diff: {max_int64 - ts_picoseconds:,})")

conn.close()

print("\n" + "=" * 70)
print("💡 KEY INSIGHT:")
print("=" * 70)
print("Python integers can be arbitrarily large, but when SQLite tries to")
print("store them in an INTEGER column (64-bit), it triggers OverflowError.")
print("The error happens at cursor.execute() when Python's sqlite3 module")
print("tries to convert the Python int to a C int64.")
print("=" * 70)
