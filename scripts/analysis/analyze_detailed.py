#!/usr/bin/env python3
"""Uitgebreide analyse van bot performance met error analysis"""

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from multi_coin_grid_pro.monitoring.trade_analyzer import TradeAnalyzer

print("=" * 80)
print("🔍 UITGEBREIDE BOT ANALYSE - LAATSTE 13 UUR")
print("=" * 80)

analyzer = TradeAnalyzer()
report = analyzer.analyze(hours=13)

# ============================================================================
# DEEL 1: TRADING PERFORMANCE
# ============================================================================
print("\n" + "=" * 80)
print("📊 DEEL 1: TRADING PERFORMANCE")
print("=" * 80)

print(f"\n💰 FINANCIEEL RESULTAAT")
print(f"   Total P&L: €{float(report.total_pnl):.2f}")
print(f"   Realized P&L: €{float(report.realized_pnl):.2f}")

closed_trades = [t for t in report.trades if t.is_closed]
open_trades = [t for t in report.trades if not t.is_closed]

print(f"\n📈 TRADE OVERZICHT")
print(f"   Totaal trades: {len(report.trades)}")
print(f"   Gesloten: {len(closed_trades)}")
print(f"   Open: {len(open_trades)}")
print(f"   Wins: {report.win_count}")
print(f"   Losses: {report.loss_count}")

if len(closed_trades) > 0:
    win_rate = (report.win_count / len(closed_trades)) * 100
    print(f"   Win rate: {win_rate:.1f}%")

# Per coin analyse
print(f"\n🪙 PER COIN ANALYSE")
coin_stats = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "total_pnl": 0})

for trade in closed_trades:
    coin = trade.coin.replace("-EUR", "")
    coin_stats[coin]["trades"] += 1
    profit = float(trade.profit)
    coin_stats[coin]["total_pnl"] += profit
    if profit > 0:
        coin_stats[coin]["wins"] += 1
    elif profit < 0:
        coin_stats[coin]["losses"] += 1

for coin, stats in sorted(coin_stats.items()):
    wr = (stats["wins"] / stats["trades"] * 100) if stats["trades"] > 0 else 0
    print(f"\n   {coin}:")
    print(f"      Trades: {stats['trades']} (W: {stats['wins']}, L: {stats['losses']})")
    print(f"      Win rate: {wr:.1f}%")
    print(f"      Total P&L: €{stats['total_pnl']:.2f}")

# Gedetailleerde trades
print(f"\n📋 ALLE TRADES (chronologisch)")
print("-" * 80)

for i, trade in enumerate(sorted(report.trades, key=lambda t: t.buy_time), 1):
    if trade.is_closed:
        profit = float(trade.profit)
        status = "✅ WIN " if profit > 0 else "❌ LOSS"
        buy_time = trade.buy_time.strftime("%H:%M:%S")
        sell_time = trade.sell_time.strftime("%H:%M:%S")
        duration = (trade.sell_time - trade.buy_time).total_seconds() / 60
        print(f"{i:2d}. {status} | {trade.coin:10s} | "
              f"BUY: {buy_time} @ €{float(trade.buy_price):8.4f} | "
              f"SELL: {sell_time} @ €{float(trade.sell_price):8.4f} | "
              f"Amount: {float(trade.buy_amount):8.4f} | "
              f"Duration: {duration:5.0f}m | "
              f"P&L: €{profit:6.2f}")
    else:
        buy_time = trade.buy_time.strftime("%H:%M:%S")
        print(f"{i:2d}. ⏳ OPEN | {trade.coin:10s} | "
              f"BUY: {buy_time} @ €{float(trade.buy_price):8.4f} | "
              f"Amount: {float(trade.buy_amount):8.4f} | "
              f"Value: €{float(trade.buy_value):.2f}")

# ============================================================================
# DEEL 2: ERROR ANALYSIS
# ============================================================================
print("\n" + "=" * 80)
print("❌ DEEL 2: ERROR ANALYSIS")
print("=" * 80)

log_path = Path("/home/mo/repos/hummingbot/logs/logs_multi_coin_grid_v2_2025-12-07-01-22-54.log")
cutoff_time = datetime.now() - timedelta(hours=13)

errors = []
warnings = []
api_errors = []
critical_events = []

error_pattern = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?(ERROR|CRITICAL|Exception|Traceback|Failed)', re.IGNORECASE)
warning_pattern = re.compile(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}).*?WARNING', re.IGNORECASE)
api_error_pattern = re.compile(r'API.*?(error|failed|timeout)', re.IGNORECASE)
stop_loss_pattern = re.compile(r'STOP.?LOSS|Circuit.?breaker', re.IGNORECASE)

print("\n🔍 Scanning log file voor errors...")

try:
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        current_error = []
        in_traceback = False

        for line in f:
            # Check timestamp
            if len(line) > 19:
                try:
                    timestamp_str = line[:19]
                    timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                    if timestamp < cutoff_time:
                        continue
                except ValueError:
                    pass

            # Error detection
            if error_pattern.search(line):
                if 'Traceback' in line:
                    in_traceback = True
                    current_error = [line.strip()]
                elif in_traceback:
                    current_error.append(line.strip())
                    if not line.startswith(' ') and len(current_error) > 1:
                        errors.append('\n'.join(current_error))
                        current_error = []
                        in_traceback = False
                else:
                    errors.append(line.strip())

            # Warning detection
            if warning_pattern.search(line):
                warnings.append(line.strip())

            # API error detection
            if api_error_pattern.search(line):
                api_errors.append(line.strip())

            # Critical events
            if stop_loss_pattern.search(line):
                critical_events.append(line.strip())

except Exception as e:
    print(f"   ⚠️  Error reading log: {e}")

print(f"\n📊 ERROR SUMMARY")
print(f"   Errors: {len(errors)}")
print(f"   Warnings: {len(warnings)}")
print(f"   API Errors: {len(api_errors)}")
print(f"   Critical Events: {len(critical_events)}")

# Error categorization
error_types = Counter()
for error in errors:
    if 'Invalid permissions' in error or 'USDT trading restricted' in error:
        error_types['USDT Trading Restricted (NL)'] += 1
    elif 'order update' in error.lower():
        error_types['Order Update Issues'] += 1
    elif 'api' in error.lower():
        error_types['API Errors'] += 1
    elif 'timeout' in error.lower():
        error_types['Timeout Errors'] += 1
    elif 'exchange' in error.lower():
        error_types['Exchange Errors'] += 1
    else:
        error_types['Other Errors'] += 1

if error_types:
    print(f"\n🏷️  ERROR TYPES")
    for error_type, count in error_types.most_common():
        print(f"   {error_type}: {count}")

# Show critical errors
if critical_events:
    print(f"\n🚨 CRITICAL EVENTS ({len(critical_events)})")
    for event in critical_events[:5]:
        print(f"   • {event[:120]}")

# Show recent errors
if errors:
    print(f"\n⚠️  RECENT ERRORS (laatste 10)")
    for error in errors[-10:]:
        error_line = error.split('\n')[0][:120]
        print(f"   • {error_line}")

# ============================================================================
# DEEL 3: WAAROM VERLIES?
# ============================================================================
print("\n" + "=" * 80)
print("🤔 DEEL 3: WAAROM VERLIES? - ROOT CAUSE ANALYSE")
print("=" * 80)

print("\n💡 ANALYSE:")

# 1. Win/Loss ratio
if len(closed_trades) > 0:
    win_count = sum(1 for t in closed_trades if t.profit > 0)
    loss_count = sum(1 for t in closed_trades if t.profit < 0)
    print(f"\n1. WIN/LOSS RATIO")
    print(f"   Wins: {win_count} trades")
    print(f"   Losses: {loss_count} trades")
    if loss_count > win_count:
        print(f"   ⚠️  Probleem: Meer verliezen dan winsten!")
        print(f"   Mogelijke oorzaken:")
        print(f"      - Trend detection niet accuraat")
        print(f"      - Stop loss te laat getriggerd")
        print(f"      - Exit strategy te zwak")

# 2. Profit per trade analyse
if closed_trades:
    profits = [float(t.profit) for t in closed_trades]
    avg_win = sum(p for p in profits if p > 0) / max(sum(1 for p in profits if p > 0), 1)
    avg_loss = sum(p for p in profits if p < 0) / max(sum(1 for p in profits if p < 0), 1)

    print(f"\n2. PROFIT/LOSS MAGNITUDE")
    print(f"   Gemiddelde win: €{avg_win:.2f}")
    print(f"   Gemiddelde loss: €{avg_loss:.2f}")
    print(f"   Risk/Reward ratio: {abs(avg_win / avg_loss):.2f} (target: >1.5)")

    if abs(avg_loss) > avg_win:
        print(f"   ⚠️  Probleem: Verliezen groter dan winsten!")
        print(f"   Mogelijke oorzaken:")
        print(f"      - Stop loss te breed")
        print(f"      - Take profit te krap")
        print(f"      - Grid range verkeerd ingesteld")

# 3. Coin selection analysis
print(f"\n3. COIN SELECTIE")
for coin, stats in coin_stats.items():
    if stats["total_pnl"] < 0:
        print(f"   ⚠️  {coin}: Verlies van €{stats['total_pnl']:.2f}")
        print(f"      - {stats['losses']} losing trades vs {stats['wins']} winning trades")
        print(f"      - Mogelijk: Verkeerde trend detectie of volatiliteit te hoog")

# 4. Timing analysis
print(f"\n4. TIMING ANALYSE")
if closed_trades:
    durations = [(t.sell_time - t.buy_time).total_seconds() / 60 for t in closed_trades]
    avg_duration = sum(durations) / len(durations)
    print(f"   Gemiddelde trade duration: {avg_duration:.0f} minuten")

    quick_losses = [t for t in closed_trades if t.profit < 0 and (t.sell_time - t.buy_time).total_seconds() < 600]
    if quick_losses:
        print(f"   ⚠️  {len(quick_losses)} snelle verliezen (<10 min)")
        print(f"      Mogelijke oorzaak: Slecht entry timing of te volatile markt")

print("\n" + "=" * 80)
print("🎯 CONCLUSIE & AANBEVELINGEN")
print("=" * 80)

total_pnl = float(report.total_pnl)
if total_pnl < 0:
    print(f"\n❌ Bot maakt verlies: €{total_pnl:.2f}")
    print(f"\n📋 TOP AANBEVELINGEN:")
    print(f"   1. Check trend detection - mogelijk te agressief")
    print(f"   2. Verhoog min_trend_entry_strength (nu: 0.05%)")
    print(f"   3. Overweeg strengere coin filtering")
    print(f"   4. Review grid range settings")
    print(f"   5. Test met paper trading eerst")
else:
    print(f"\n✅ Bot maakt winst: €{total_pnl:.2f}")

print("\n" + "=" * 80)
