#!/usr/bin/env python3
"""
Quick script to view bot reports from event logs
"""
from pathlib import Path

from multi_coin_grid_pro.observability.console_reporter import ConsoleReporter

# Setup
events_dir = Path('logs/events')
bot_name = "report_viewer"  # Can be anything for standalone viewing

# Create reporter
reporter = ConsoleReporter(log_dir=events_dir, bot_name=bot_name)

print("=" * 80)
print("📊 BOT REPORTS - Last 24 hours")
print("=" * 80)
print()

# Full summary report
print("\n" + "=" * 80)
print("1️⃣  SUMMARY REPORT (Last 24h)")
print("=" * 80)
reporter.report_summary(hours=24)

# By symbol (top candidates)
print("\n" + "=" * 80)
print("2️⃣  TOP 10 SYMBOLS (Last 6h)")
print("=" * 80)
reporter.report_by_symbol(hours=6, top_n=10)

# By stage (where rejections happen)
print("\n" + "=" * 80)
print("3️⃣  REJECTION BY STAGE (Last 6h)")
print("=" * 80)
reporter.report_by_stage(hours=6)

# Full dashboard
print("\n" + "=" * 80)
print("4️⃣  FULL DASHBOARD")
print("=" * 80)
reporter.report_full_dashboard()

print("\n" + "=" * 80)
print("✅ Reports complete!")
print("=" * 80)
