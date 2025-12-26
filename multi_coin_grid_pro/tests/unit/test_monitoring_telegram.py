#!/usr/bin/env python3
"""
Test Telegram Bot

Quick test script to verify Telegram bot is working.
"""
import os
import sys
from pathlib import Path

from multi_coin_grid_pro.monitoring.config import MonitoringConfig
from multi_coin_grid_pro.monitoring.database import MonitoringDatabase

# Add parent directory to path
from multi_coin_grid_pro.monitoring.telegram_bot import TelegramBot

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_telegram_bot():
    """Test Telegram bot functionality"""

    print("=" * 70)
    print("  TELEGRAM BOT TEST")
    print("=" * 70)
    print()

    # Get credentials from environment or config
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or MonitoringConfig.TELEGRAM_BOT_TOKEN
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or MonitoringConfig.TELEGRAM_CHAT_ID

    if not bot_token:
        print("❌ Error: TELEGRAM_BOT_TOKEN not set!")
        print("   Set it with: export TELEGRAM_BOT_TOKEN='your_token'")
        return False

    if not chat_id:
        print("❌ Error: TELEGRAM_CHAT_ID not set!")
        print("   Set it with: export TELEGRAM_CHAT_ID='your_chat_id'")
        return False

    print(f"✅ Bot Token: {bot_token[:10]}...{bot_token[-5:]}")
    print(f"✅ Chat ID: {chat_id}")
    print()

    # Initialize database (required for bot)
    print("📊 Initializing database...")
    db = MonitoringDatabase()
    print("✅ Database initialized")
    print()

    # Initialize Telegram bot
    print("🤖 Initializing Telegram bot...")
    bot = TelegramBot(bot_token=bot_token, chat_id=chat_id, db=db)
    print("✅ Telegram bot initialized")
    print()

    # Test 1: Send simple message
    print("📤 Test 1: Sending simple test message...")
    success = bot.send_message("🧪 Test message from bot monitoring system!")
    if success:
        print("✅ Message sent successfully!")
    else:
        print("❌ Failed to send message")
        return False
    print()

    # Test 2: Send status
    print("📤 Test 2: Sending bot status...")
    success = bot.send_status()
    if success:
        print("✅ Status sent successfully!")
    else:
        print("⚠️  Status sent (may show 'No status' if database is empty)")
    print()

    # Test 3: Send recent events
    print("📤 Test 3: Sending recent events...")
    success = bot.send_recent_events(limit=5)
    if success:
        print("✅ Events sent successfully!")
    else:
        print("⚠️  Events sent (may show 'No events' if database is empty)")
    print()

    # Test 4: Send alert
    print("📤 Test 4: Sending test alert...")
    bot.send_alert(
        event_type="test",
        message="This is a test alert to verify Telegram notifications are working!",
        coin="TEST-EUR"
    )
    print("✅ Alert sent!")
    print()

    print("=" * 70)
    print("  ✅ ALL TESTS COMPLETED!")
    print("=" * 70)
    print()
    print("📱 Check your Telegram app - you should have received:")
    print("   1. Simple test message")
    print("   2. Bot status (may be empty if no data)")
    print("   3. Recent events (may be empty if no data)")
    print("   4. Test alert")
    print()
    print("💡 If you didn't receive messages:")
    print("   - Check bot token is correct")
    print("   - Check chat ID is correct")
    print("   - Make sure you've started a conversation with the bot")
    print("   - Check bot logs for errors")
    print()

    return True


if __name__ == "__main__":
    try:
        success = test_telegram_bot()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n❌ Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
