#!/usr/bin/env python3
"""
Quick test for Task 2.1.1 Stale Detection Implementation
Tests the core stale detection logic without full bot startup
"""
import asyncio
import time
from decimal import Decimal


class MockController:
    """Mock controller to test stale detection methods"""

    def __init__(self):
        # Stale detection state (from Task 2.1.1)
        self._last_price_update = {}
        self._last_ob_update = {}
        self._stale_symbols = set()
        self._resubscribe_backoff = {}
        self._max_stale_seconds = 5.0
        self._stale_check_task = None
        self.monitored_coins = ["BTC-EUR", "ETH-EUR", "SOL-EUR"]

    def logger(self):
        """Mock logger"""
        class Logger:
            def info(self, msg): print(f"ℹ️  {msg}")
            def warning(self, msg): print(f"⚠️  {msg}")
            def error(self, msg): print(f"❌ {msg}")
        return Logger()

    def _is_data_ready(self, symbol: str) -> bool:
        """Check if we have recent data for this symbol"""
        now = time.time()
        price_age = now - self._last_price_update.get(symbol, 0)
        ob_age = now - self._last_ob_update.get(symbol, 0)

        is_ready = (price_age < self._max_stale_seconds and
                    ob_age < self._max_stale_seconds)

        if not is_ready:
            self.logger().warning(
                f"{symbol} data stale: price {price_age:.1f}s, "
                f"orderbook {ob_age:.1f}s (max {self._max_stale_seconds}s)"
            )

        return is_ready

    def _mark_data_update(self, symbol: str, data_type: str):
        """Mark that we received fresh data"""
        now = time.time()
        if data_type == "price":
            self._last_price_update[symbol] = now
        elif data_type == "orderbook":
            self._last_ob_update[symbol] = now

        # If was stale, remove from stale set
        if symbol in self._stale_symbols:
            self._stale_symbols.discard(symbol)
            self.logger().info(f"✅ {symbol} recovered from stale state")

    def _mark_stale(self, symbol: str):
        """Mark symbol as stale and trigger recovery"""
        if symbol not in self._stale_symbols:
            self._stale_symbols.add(symbol)
            self.logger().warning(f"⚠️  {symbol} marked STALE - recovery needed")
            # In real implementation: asyncio.create_task(self._recover_symbol(symbol))

    async def _recover_symbol(self, symbol: str):
        """Mock recovery - just simulate resubscribe delay"""
        backoff = self._resubscribe_backoff.get(symbol, 1.0)
        self.logger().info(f"🔄 Attempting recovery for {symbol} (backoff={backoff}s)")
        await asyncio.sleep(backoff)

        # Simulate successful recovery
        self._mark_data_update(symbol, "price")
        self._mark_data_update(symbol, "orderbook")
        self._resubscribe_backoff[symbol] = 1.0  # Reset backoff

    async def _periodic_stale_check(self):
        """Background task to check for stale data"""
        check_count = 0
        while check_count < 3:  # Run 3 times for test
            await asyncio.sleep(2)  # Check every 2s for test
            check_count += 1

            self.logger().info(f"🔍 Periodic stale check #{check_count}")
            for symbol in self.monitored_coins:
                if not self._is_data_ready(symbol):
                    self._mark_stale(symbol)


async def test_stale_detection():
    """Test stale detection workflow"""
    print("\n" + "=" * 60)
    print("TEST: Task 2.1.1 Stale Detection")
    print("=" * 60 + "\n")

    controller = MockController()

    # Scenario 1: Fresh data
    print("📋 Scenario 1: Fresh data")
    controller._mark_data_update("BTC-EUR", "price")
    controller._mark_data_update("BTC-EUR", "orderbook")
    assert controller._is_data_ready("BTC-EUR"), "Should be ready with fresh data"
    print("✅ PASS: Fresh data detected\n")

    # Scenario 2: Stale data (no updates)
    print("📋 Scenario 2: Stale data detection")
    await asyncio.sleep(6)  # Wait longer than _max_stale_seconds
    assert not controller._is_data_ready("BTC-EUR"), "Should be stale after 6s"
    controller._mark_stale("BTC-EUR")
    assert "BTC-EUR" in controller._stale_symbols
    print("✅ PASS: Stale data detected\n")

    # Scenario 3: Recovery
    print("📋 Scenario 3: Recovery from stale")
    await controller._recover_symbol("BTC-EUR")
    assert controller._is_data_ready("BTC-EUR"), "Should be ready after recovery"
    assert "BTC-EUR" not in controller._stale_symbols
    print("✅ PASS: Recovery successful\n")

    # Scenario 4: Periodic check
    print("📋 Scenario 4: Periodic stale check (6s total)")
    # Mark SOL fresh but not ETH
    controller._mark_data_update("SOL-EUR", "price")
    controller._mark_data_update("SOL-EUR", "orderbook")
    # ETH has no data, should be detected as stale

    stale_task = asyncio.create_task(controller._periodic_stale_check())
    await stale_task

    assert "ETH-EUR" in controller._stale_symbols, "ETH should be stale"
    print("✅ PASS: Periodic check detected stale symbol\n")

    print("=" * 60)
    print("✅ ALL TESTS PASSED - Stale Detection Working!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(test_stale_detection())
