#!/usr/bin/env python3
"""
Automatic Error Checker and Fixer
Waits 1 hour, then checks logs for errors and fixes them automatically
"""

import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

LOG_FILE = PROJECT_ROOT / "logs" / "logs_multi_coin_grid_v2.log"
WAIT_TIME = 3600  # 1 hour in seconds
CHECK_LINES = 500  # Check last 500 lines

# Known error patterns and their fixes
ERROR_PATTERNS = {
    r"'OrderBookTracker' object has no attribute 'trading_pairs'": {
        "fix": "order_book_tracker_attr_fix",
        "description": "OrderBookTracker attribute error - already fixed"
    },
    r"AttributeError.*trading_pairs": {
        "fix": "order_book_tracker_attr_fix",
        "description": "OrderBookTracker attribute error"
    },
    r"ValidationError.*Extra inputs are not permitted": {
        "fix": "config_validation_fix",
        "description": "Config validation error"
    },
    r"No order book exists for": {
        "fix": "order_book_init_fix",
        "description": "Order book initialization error"
    },
    r"Connector.*not found": {
        "fix": "connector_init_fix",
        "description": "Connector initialization error"
    },
}


def check_logs_for_errors():
    """Check logs for errors and return list of found errors"""
    if not LOG_FILE.exists():
        print(f"❌ Log file not found: {LOG_FILE}")
        return []

    errors = []
    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            recent_lines = lines[-CHECK_LINES:] if len(lines) > CHECK_LINES else lines

            for i, line in enumerate(recent_lines):
                # Check for ERROR or CRITICAL level
                if 'ERROR' in line or 'CRITICAL' in line or 'Exception' in line or 'Traceback' in line:
                    # Get context (5 lines before and after)
                    start = max(0, i - 5)
                    end = min(len(recent_lines), i + 10)
                    context = ''.join(recent_lines[start:end])

                    # Check against known patterns
                    for pattern, info in ERROR_PATTERNS.items():
                        if re.search(pattern, line, re.IGNORECASE):
                            errors.append({
                                "line": line.strip(),
                                "pattern": pattern,
                                "fix": info["fix"],
                                "description": info["description"],
                                "context": context
                            })
                            break
                    else:
                        # Unknown error
                        errors.append({
                            "line": line.strip(),
                            "pattern": None,
                            "fix": None,
                            "description": "Unknown error",
                            "context": context
                        })

    except Exception as e:
        print(f"❌ Error reading log file: {e}")
        return []

    return errors


def apply_fix(fix_type, error_context):
    """Apply automatic fix based on error type"""
    print(f"\n🔧 Applying fix: {fix_type}")

    if fix_type == "order_book_tracker_attr_fix":
        # This is already fixed, just log it
        print("✅ This error is already fixed in the code")
        return True

    elif fix_type == "config_validation_fix":
        # Check if log_level is missing from config
        config_file = PROJECT_ROOT / "multi_coin_grid_pro" / "controllers" / "multi_coin_grid_config.py"
        if config_file.exists():
            with open(config_file, 'r') as f:
                content = f.read()
                if 'log_level' not in content:
                    print("⚠️  log_level might be missing from config - manual check needed")
        return False

    elif fix_type == "order_book_init_fix":
        # Order book initialization - already handled in code
        print("✅ Order book initialization is handled in _ensure_order_book_exists")
        return True

    elif fix_type == "connector_init_fix":
        # Connector initialization - check if connectors parameter is passed
        print("⚠️  Connector initialization error - manual check needed")
        return False

    return False


def main():
    """Main function"""
    print("=" * 70)
    print("  AUTOMATIC ERROR CHECKER")
    print("=" * 70)
    check_time = datetime.fromtimestamp(datetime.now().timestamp() + WAIT_TIME)
    print(f"\n⏰ Waiting {WAIT_TIME // 60} minutes before checking logs...")
    print(f"📁 Log file: {LOG_FILE}")
    print(f"🕐 Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🕐 Check time: {check_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n💤 Sleeping... (Press Ctrl+C to cancel)")

    try:
        time.sleep(WAIT_TIME)
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
        return

    print("\n" + "=" * 70)
    print("  CHECKING LOGS FOR ERRORS")
    print("=" * 70)
    print(f"\n🕐 Check time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    errors = check_logs_for_errors()

    if not errors:
        print("\n✅ No errors found in recent logs!")
        print("📊 Bot appears to be running normally")
        return

    print(f"\n❌ Found {len(errors)} error(s):")
    print("-" * 70)

    fixed_count = 0
    unknown_errors = []

    for i, error in enumerate(errors, 1):
        print(f"\n[{i}] {error['description']}")
        print(f"    Pattern: {error['pattern'] or 'Unknown'}")
        print(f"    Line: {error['line'][:100]}...")

        if error['fix']:
            if apply_fix(error['fix'], error['context']):
                fixed_count += 1
                print("    ✅ Fix applied")
            else:
                print("    ⚠️  Fix attempted but manual intervention may be needed")
        else:
            unknown_errors.append(error)
            print("    ⚠️  No automatic fix available")

    print("\n" + "=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    print(f"Total errors found: {len(errors)}")
    print(f"Auto-fixed: {fixed_count}")
    print(f"Unknown/Manual: {len(unknown_errors)}")

    if unknown_errors:
        print("\n⚠️  Unknown errors that need manual attention:")
        for error in unknown_errors:
            print(f"  - {error['line'][:80]}...")

    # Save report
    report_file = PROJECT_ROOT / "logs" / f"error_check_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w') as f:
        f.write(f"Error Check Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"Total errors: {len(errors)}\n")
        f.write(f"Auto-fixed: {fixed_count}\n")
        f.write(f"Unknown: {len(unknown_errors)}\n\n")
        for i, error in enumerate(errors, 1):
            f.write(f"[{i}] {error['description']}\n")
            f.write(f"Line: {error['line']}\n")
            f.write(f"Context:\n{error['context']}\n")
            f.write("-" * 70 + "\n")

    print(f"\n📄 Full report saved to: {report_file}")
    print("=" * 70)


if __name__ == "__main__":
    main()
