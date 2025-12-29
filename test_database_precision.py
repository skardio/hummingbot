#!/usr/bin/env python3
"""
Test script to verify database precision improvements
"""


def test_precision():
    """Test different precision levels for PEPE-like tokens"""

    # PEPE price example: €0.0000035583
    pepe_price = Decimal("0.0000035583")
    pepe_amount = Decimal("4196978.18")

    print("=" * 80)
    print("DATABASE PRECISION TEST")
    print("=" * 80)
    print()
    print(f"Original PEPE price:  €{pepe_price}")
    print(f"Original PEPE amount: {pepe_amount}")
    print()

    # Test old precision (6 decimals)
    print("OLD PRECISION (SqliteDecimal(6)):")
    old_decimal = SqliteDecimal(6)

    old_price_stored = old_decimal._convert_decimal(pepe_price)
    old_price_retrieved = Decimal(old_price_stored) / old_decimal.multiplier_int

    old_amount_stored = old_decimal._convert_decimal(pepe_amount)
    old_amount_retrieved = Decimal(old_amount_stored) / old_decimal.multiplier_int

    print(f"  Price stored as integer:  {old_price_stored}")
    print(f"  Price retrieved:          €{old_price_retrieved}")
    print(f"  Price error:              €{abs(pepe_price - old_price_retrieved)}")
    print(f"  Price error %:            {abs((pepe_price - old_price_retrieved) / pepe_price * 100):.2f}%")
    print()
    print(f"  Amount stored as integer: {old_amount_stored}")
    print(f"  Amount retrieved:         {old_amount_retrieved}")
    print(f"  Amount error:             {abs(pepe_amount - old_amount_retrieved)}")
    print()

    # Test new precision (18 decimals)
    print("NEW PRECISION (SqliteDecimal(18)):")
    new_decimal = SqliteDecimal(18)

    new_price_stored = new_decimal._convert_decimal(pepe_price)
    new_price_retrieved = Decimal(new_price_stored) / new_decimal.multiplier_int

    new_amount_stored = new_decimal._convert_decimal(pepe_amount)
    new_amount_retrieved = Decimal(new_amount_stored) / new_decimal.multiplier_int

    print(f"  Price stored as integer:  {new_price_stored}")
    print(f"  Price retrieved:          €{new_price_retrieved}")
    print(f"  Price error:              €{abs(pepe_price - new_price_retrieved)}")
    print(f"  Price error %:            {abs((pepe_price - new_price_retrieved) / pepe_price * 100) if pepe_price != new_price_retrieved else 0:.10f}%")
    print()
    print(f"  Amount stored as integer: {new_amount_stored}")
    print(f"  Amount retrieved:         {new_amount_retrieved}")
    print(f"  Amount error:             {abs(pepe_amount - new_amount_retrieved)}")
    print()

    # Test TAO price
    tao_price = Decimal("190.6985")

    print("TAO PRICE TEST:")
    print(f"  Original TAO price:       €{tao_price}")
    print()

    old_tao_stored = old_decimal._convert_decimal(tao_price)
    old_tao_retrieved = Decimal(old_tao_stored) / old_decimal.multiplier_int
    print(f"  OLD (6 decimals):         €{old_tao_retrieved}")
    print(f"  Error:                    €{abs(tao_price - old_tao_retrieved)}")
    print()

    new_tao_stored = new_decimal._convert_decimal(tao_price)
    new_tao_retrieved = Decimal(new_tao_stored) / new_decimal.multiplier_int
    print(f"  NEW (18 decimals):        €{new_tao_retrieved}")
    print(f"  Error:                    €{abs(tao_price - new_tao_retrieved)}")
    print()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print()

    if old_price_retrieved == pepe_price:
        print("❌ OLD precision: PERFECT (unexpectedly)")
    else:
        print(f"❌ OLD precision: LOSS of €{abs(pepe_price - old_price_retrieved)} per PEPE")

    if new_price_retrieved == pepe_price:
        print("✅ NEW precision: PERFECT - No data loss!")
    else:
        print(f"⚠️  NEW precision: Minor loss of €{abs(pepe_price - new_price_retrieved)} per PEPE")

    print()


if __name__ == "__main__":
    test_precision()
