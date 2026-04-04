#!/usr/bin/env python3
"""
Simple P&L checker - reads from logs and shows executor status
"""
import glob
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

print("=" * 80)
print("  BOT P&L CHECKER (Simple)")
print("=" * 80)
print()

# Auto-detect newest log file (supports all bot variants)
log_dir = Path(__file__).parent.parent / "logs"
candidates = sorted(glob.glob(str(log_dir / "logs_*.log")), key=lambda f: Path(f).stat().st_mtime, reverse=True)
log_file = Path(candidates[0]) if candidates else log_dir / "logs_multi_coin_grid_v2.log"

if not log_file.exists():
    print(f"❌ Log file not found: {log_file}")
    print()
    print("💡 To check P&L:")
    print("   1. Start the bot and run: status (in Hummingbot CLI)")
    print("   2. Check the executor info in the status output")
    print("   3. Look for 'net_pnl_quote' and 'net_pnl_pct' values")
    sys.exit(1)

print(f"📄 Reading logs from: {log_file}")
print()

# Read last 2000 lines
with open(log_file, 'r') as f:
    lines = f.readlines()
    recent_lines = lines[-2000:] if len(lines) > 2000 else lines

# Look for executor status or P&L information
print("🔍 Searching for executor P&L information...")
print()

# Pattern to find executor info
executor_patterns = [
    r"net_pnl[_\s]*quote[:\s]*([0-9.-]+)",
    r"net_pnl[_\s]*pct[:\s]*([0-9.-]+)",
    r"P&L[:\s]*€?([0-9.-]+)",
    r"profit[:\s]*€?([0-9.-]+)",
    r"loss[:\s]*€?([0-9.-]+)",
]

found_pnl = []
for line in recent_lines:
    for pattern in executor_patterns:
        matches = re.findall(pattern, line, re.IGNORECASE)
        if matches:
            found_pnl.append((line.strip(), matches))

if found_pnl:
    print(f"Found {len(found_pnl)} P&L-related entries:")
    print()
    for line, matches in found_pnl[-10:]:  # Show last 10
        print(f"  {line[:200]}")
    print()
else:
    print("  No explicit P&L information found in logs")
    print()
    print("💡 This is normal - P&L is usually shown in the bot's status output")
    print()

# Check for executor creation/completion
executor_created = [line for line in recent_lines if "CREATING GRID" in line or "executor" in line.lower()]
if executor_created:
    print(f"📊 Found {len(executor_created)} executor-related entries")
    print("   Recent executor activity:")
    for line in executor_created[-5:]:
        print(f"   {line.strip()[:150]}")
    print()

print("=" * 80)
print("💡 TO CHECK ACTUAL P&L:")
print()
print("   Option 1: In Hummingbot CLI (if bot is running):")
print("     >>> status")
print("     Look for executor info with net_pnl_quote and net_pnl_pct")
print()
print("   Option 2: Check monitoring dashboard:")
print("     http://localhost:5000")
print("     (if monitoring is running)")
print()
print("   Option 3: Check executor database directly:")
print("     The bot stores executor P&L in the database")
print("     Location: data/hummingbot_trades.db")
print()
print("   Option 4: Check Kraken account balance:")
print("     Compare current balance with starting balance")
print("=" * 80)
