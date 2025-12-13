#!/usr/bin/env python3
"""Check P&L calculation details"""

from multi_coin_grid_pro.monitoring.trade_analyzer import TradeAnalyzer

analyzer = TradeAnalyzer()
report = analyzer.analyze(hours=13)

print("📊 DETAILED TRADE ANALYSIS")
print("=" * 70)

total_realized = 0
total_unrealized = 0

for i, trade in enumerate(report.trades, 1):
    print(f"\nTrade {i}: {trade.coin}")
    buy_time = trade.buy_time.strftime("%H:%M:%S")
    print(f"  Buy:  {buy_time} @ €{float(trade.buy_price):.4f} x {float(trade.buy_amount):.4f}")
    print(f"  Buy Value: €{float(trade.buy_value):.2f}")
    print(f"  Buy Fee: €{float(trade.buy_fee):.2f}")

    if trade.is_closed:
        sell_time = trade.sell_time.strftime("%H:%M:%S")
        print(f"  Sell: {sell_time} @ €{float(trade.sell_price):.4f} x {float(trade.sell_amount):.4f}")
        print(f"  Sell Value: €{float(trade.sell_value):.2f}")
        print(f"  Sell Fee: €{float(trade.sell_fee):.2f}")
        print(f"  ✅ REALIZED P&L: €{float(trade.profit):.2f} ({trade.profit_pct:.2f}%)")
        total_realized += float(trade.profit)
    else:
        print(f"  ⏳ OPEN POSITION (no unrealized P&L calculation yet)")
        print(f"  Current exposure: €{float(trade.buy_value):.2f}")

print("\n" + "=" * 70)
print(f"TOTAL REALIZED P&L: €{total_realized:.2f}")
print(f"Report says: €{float(report.realized_pnl):.2f}")
print(f"Report total: €{float(report.total_pnl):.2f}")
print(f"\nWin count: {report.win_count}")
print(f"Loss count: {report.loss_count}")
