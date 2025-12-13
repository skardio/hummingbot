#!/usr/bin/env python3
"""Analyze last 13 hours of trading"""

from datetime import datetime, timedelta

from multi_coin_grid_pro.monitoring.trade_analyzer import TradeAnalyzer

print("📊 SPORT GRID ANALYSE - LAATSTE 13 UUR")
print("=" * 70)

analyzer = TradeAnalyzer()
report = analyzer.analyze(hours=13)

print(f"\n🤖 BOT STATUS")
status_emoji = "🟢 RUNNING" if report.status.is_running else "🔴 STOPPED"
print(f"   Status: {status_emoji}")
if report.status.last_update:
    print(f"   Laatste update: {report.status.last_update}")
if report.status.active_coin:
    print(f"   Actieve coin: {report.status.active_coin}")
if report.status.best_trend_coin:
    print(f"   Best trend: {report.status.best_trend_coin} ({report.status.best_trend_pct:+.2f}%)")

print(f"\n💰 FINANCIEEL OVERZICHT")
print(f"   Total P&L: €{float(report.total_pnl):.2f}")
print(f"   Realized P&L: €{float(report.realized_pnl):.2f}")

print(f"\n📈 TRADING STATISTIEKEN")
print(f"   Totaal trades: {len(report.trades)}")
print(f"   Winning trades: {report.win_count}")
print(f"   Losing trades: {report.loss_count}")
if len(report.trades) > 0:
    win_rate = (report.win_count / len(report.trades)) * 100
    print(f"   Win rate: {win_rate:.1f}%")

if report.trades:
    print(f"\n🔄 RECENTE TRADES (laatste 10)")
    print("-" * 70)
    for trade in report.trades[:10]:
        profit = trade.profit
        status = "✅ WIN" if profit > 0 else "❌ LOSS" if profit < 0 else "⏳ OPEN"
        buy_time = trade.buy_time.strftime("%H:%M:%S")
        sell_time = trade.sell_time.strftime("%H:%M:%S") if trade.sell_time else "------"
        sell_price_val = float(trade.sell_price) if trade.sell_price else 0
        print(f"   {status} | {trade.coin:10s} | "
              f"BUY: {buy_time} @ €{float(trade.buy_price):8.4f} | "
              f"SELL: {sell_time} @ €{sell_price_val:8.4f} | "
              f"P&L: €{float(profit):6.2f}")

if report.errors:
    print(f"\n❌ ERRORS ({len(report.errors)})")
    print("-" * 70)
    for error in report.errors[:5]:
        print(f"   • {error}")

if report.warnings:
    print(f"\n⚠️  WARNINGS ({len(report.warnings)})")
    print("-" * 70)
    for warning in report.warnings[:5]:
        print(f"   • {warning}")

print("\n" + "=" * 70)
