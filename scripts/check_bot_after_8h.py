#!/usr/bin/env python3
"""
Bot Activity Checker - 8 Hours
Waits 8 hours, then analyzes bot activity and creates a comprehensive report
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
WAIT_TIME = 28800  # 8 hours in seconds
CHECK_LINES = 5000  # Check last 5000 lines for comprehensive analysis


def analyze_bot_activity():
    """Analyze bot activity from logs"""
    if not LOG_FILE.exists():
        return {"error": f"Log file not found: {LOG_FILE}"}

    stats = {
        "start_time": None,
        "end_time": datetime.now(),
        "total_lines": 0,
        "errors": [],
        "warnings": [],
        "coins_monitored": set(),
        "trend_updates": 0,
        "executors_created": 0,
        "executors_stopped": 0,
        "switches": 0,
        "grid_creations": 0,
        "order_book_initializations": 0,
        "api_errors": 0,
        "circuit_breaker_activations": 0,
        "stop_loss_triggers": 0,
        "recent_activity": [],
        "performance": {
            "avg_update_interval": 0,
            "total_cycles": 0
        }
    }

    try:
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            stats["total_lines"] = len(lines)

            # Analyze last CHECK_LINES lines
            recent_lines = lines[-CHECK_LINES:] if len(lines) > CHECK_LINES else lines

            # Find start time (first log entry)
            if lines:
                first_line = lines[0]
                time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', first_line)
                if time_match:
                    try:
                        stats["start_time"] = datetime.strptime(time_match.group(1), '%Y-%m-%d %H:%M:%S')
                    except Exception:
                        pass

            # Analyze activity
            for i, line in enumerate(recent_lines):
                # Errors
                if 'ERROR' in line or 'CRITICAL' in line:
                    stats["errors"].append({
                        "line": i + len(lines) - len(recent_lines),
                        "content": line.strip()[:200]
                    })

                # Warnings
                if 'WARNING' in line:
                    stats["warnings"].append({
                        "line": i + len(lines) - len(recent_lines),
                        "content": line.strip()[:200]
                    })

                # Coins monitored
                coin_match = re.search(r'([A-Z0-9]+-EUR)', line)
                if coin_match:
                    stats["coins_monitored"].add(coin_match.group(1))

                # Trend updates
                if 'Updating trends' in line or 'trend_calculator.update' in line:
                    stats["trend_updates"] += 1

                # Executor actions
                if 'Creating executor' in line or 'Creating grid executor' in line:
                    stats["executors_created"] += 1
                    stats["grid_creations"] += 1

                if 'Stopping executor' in line or 'StopExecutorAction' in line:
                    stats["executors_stopped"] += 1

                # Coin switches
                if 'SWITCH' in line and ('APPROVED' in line or 'to' in line):
                    stats["switches"] += 1

                # Order book initializations
                if 'Order book initialized' in line or 'Adding.*to order book tracker' in line:
                    stats["order_book_initializations"] += 1

                # API errors
                if 'API' in line and ('error' in line.lower() or 'failed' in line.lower()):
                    stats["api_errors"] += 1

                # Circuit breaker
                if 'Circuit breaker' in line or 'volatility detected' in line.lower():
                    stats["circuit_breaker_activations"] += 1

                # Stop loss
                if 'stop loss' in line.lower() or 'stop-loss' in line.lower():
                    stats["stop_loss_triggers"] += 1

                # Recent important activity (last 50 lines)
                if i >= len(recent_lines) - 50:
                    if any(keyword in line for keyword in ['✅', '🔄', '🎯', '📊', '⚠️', '❌', 'Creating', 'Stopping', 'SWITCH']):
                        stats["recent_activity"].append({
                            "line": i + len(lines) - len(recent_lines),
                            "content": line.strip()[:150]
                        })

            # Calculate runtime
            if stats["start_time"]:
                runtime = stats["end_time"] - stats["start_time"]
                stats["runtime_hours"] = runtime.total_seconds() / 3600
            else:
                stats["runtime_hours"] = 0

            # Convert sets to lists for JSON serialization
            stats["coins_monitored"] = sorted(list(stats["coins_monitored"]))

    except Exception as e:
        stats["error"] = f"Error analyzing logs: {e}"
        import traceback
        stats["traceback"] = traceback.format_exc()

    return stats


def generate_report(stats):
    """Generate a comprehensive report"""
    report = []
    report.append("=" * 80)
    report.append("  BOT ACTIVITY REPORT - 8 HOUR ANALYSIS")
    report.append("=" * 80)
    report.append(f"\n📅 Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if "error" in stats:
        report.append(f"\n❌ ERROR: {stats['error']}")
        return "\n".join(report)

    # Runtime
    if stats.get("start_time"):
        report.append(f"🕐 Bot started: {stats['start_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"🕐 Analysis time: {stats['end_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"⏱️  Runtime: {stats.get('runtime_hours', 0):.2f} hours")

    report.append("\n📊 LOG STATISTICS:")
    report.append(f"   Total log lines: {stats['total_lines']:,}")
    report.append(f"   Lines analyzed: {min(CHECK_LINES, stats['total_lines']):,}")

    # Activity summary
    report.append("\n🎯 BOT ACTIVITY SUMMARY:")
    report.append(f"   Coins monitored: {len(stats['coins_monitored'])}")
    if stats['coins_monitored']:
        report.append(f"   Coins: {', '.join(stats['coins_monitored'][:10])}")
        if len(stats['coins_monitored']) > 10:
            report.append(f"   ... and {len(stats['coins_monitored']) - 10} more")

    report.append(f"   Trend updates: {stats['trend_updates']}")
    report.append(f"   Grid executors created: {stats['executors_created']}")
    report.append(f"   Grid executors stopped: {stats['executors_stopped']}")
    report.append(f"   Coin switches: {stats['switches']}")
    report.append(f"   Order book initializations: {stats['order_book_initializations']}")

    # Errors and warnings
    report.append("\n⚠️  ERRORS & WARNINGS:")
    report.append(f"   Errors: {len(stats['errors'])}")
    report.append(f"   Warnings: {len(stats['warnings'])}")
    report.append(f"   API errors: {stats['api_errors']}")

    if stats['errors']:
        report.append("\n   Recent errors:")
        for error in stats['errors'][-5:]:
            report.append(f"     - Line {error['line']}: {error['content']}")

    # Risk management
    report.append("\n🛡️  RISK MANAGEMENT:")
    report.append(f"   Circuit breaker activations: {stats['circuit_breaker_activations']}")
    report.append(f"   Stop-loss triggers: {stats['stop_loss_triggers']}")

    # Recent activity
    report.append("\n📋 RECENT ACTIVITY (last 20 important events):")
    for activity in stats['recent_activity'][-20:]:
        report.append(f"   Line {activity['line']}: {activity['content']}")

    # Health assessment
    report.append("\n💚 BOT HEALTH ASSESSMENT:")
    health_score = 100

    if len(stats['errors']) > 10:
        health_score -= 20
        report.append("   ⚠️  High error count detected")

    if stats['api_errors'] > 5:
        health_score -= 15
        report.append("   ⚠️  Multiple API errors detected")

    if stats['executors_created'] == 0:
        health_score -= 30
        report.append("   ⚠️  No executors created - bot may not be trading")

    if stats['trend_updates'] == 0:
        health_score -= 20
        report.append("   ⚠️  No trend updates - bot may be stuck")

    if health_score >= 80:
        report.append(f"   ✅ Bot appears healthy (Score: {health_score}/100)")
    elif health_score >= 60:
        report.append(f"   ⚠️  Bot has some issues (Score: {health_score}/100)")
    else:
        report.append(f"   ❌ Bot has significant issues (Score: {health_score}/100)")

    report.append("\n" + "=" * 80)

    return "\n".join(report)


def main():
    """Main function"""
    print("=" * 80)
    print("  BOT ACTIVITY CHECKER - 8 HOUR ANALYSIS")
    print("=" * 80)

    wait_hours = WAIT_TIME // 3600
    check_time = datetime.fromtimestamp(datetime.now().timestamp() + WAIT_TIME)

    print(f"\n⏰ Waiting {wait_hours} hours before analyzing bot activity...")
    print(f"📁 Log file: {LOG_FILE}")
    print(f"🕐 Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🕐 Analysis time: {check_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n💤 Sleeping... (Press Ctrl+C to cancel)")

    try:
        time.sleep(WAIT_TIME)
    except KeyboardInterrupt:
        print("\n❌ Cancelled by user")
        return

    print("\n" + "=" * 80)
    print("  ANALYZING BOT ACTIVITY")
    print("=" * 80)
    print(f"\n🕐 Analysis time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("📊 Analyzing logs...")

    stats = analyze_bot_activity()
    report = generate_report(stats)

    # Print report
    print("\n" + report)

    # Save report to file
    report_file = PROJECT_ROOT / "logs" / f"bot_activity_report_8h_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
        # Also save stats as JSON-like format
        f.write("\n\n" + "=" * 80)
        f.write("\n  DETAILED STATISTICS")
        f.write("\n" + "=" * 80 + "\n")
        import json
        f.write(json.dumps(stats, indent=2, default=str))

    print(f"\n📄 Full report saved to: {report_file}")
    print("=" * 80)


if __name__ == "__main__":
    main()
