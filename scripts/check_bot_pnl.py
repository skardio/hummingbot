#!/usr/bin/env python3
"""
Check bot P&L (Profit & Loss)
Shows total profit/loss from all executors
"""
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

print("=" * 80)
print("  BOT P&L CHECKER")
print("=" * 80)
print()

# Try to get executor info from database
try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from hummingbot.model import get_declarative_base
    from hummingbot.model.executors import Executors

    # Get database path
    db_path = Path(__file__).parent.parent / "data" / "hummingbot_trades.db"
    if not db_path.exists():
        # Try alternative location
        db_path = Path(__file__).parent.parent / "hummingbot" / "data" / "hummingbot_trades.db"

    if db_path.exists():
        print(f"📊 Reading executor data from database: {db_path}")
        print()

        # Create database connection
        engine = create_engine(f'sqlite:///{db_path}')
        Base = get_declarative_base()
        Session = sessionmaker(bind=engine)
        session = Session()

        # Get all executors for multi_coin_grid controller
        executors = session.query(Executors).filter(
            Executors.controller_id.like('%multi_coin_grid%')
        ).order_by(Executors.timestamp.desc()).all()

        if executors:
            print(f"Found {len(executors)} executor(s) in database:")
            print()

            total_pnl_quote = Decimal("0")
            total_fees = Decimal("0")
            total_filled = Decimal("0")
            active_count = 0
            closed_count = 0

            for i, ex in enumerate(executors[:20], 1):  # Show last 20
                pnl_quote = Decimal(str(ex.net_pnl_quote))
                pnl_pct = Decimal(str(ex.net_pnl_pct))
                fees = Decimal(str(ex.cum_fees_quote))
                filled = Decimal(str(ex.filled_amount_quote))

                # Parse config to get trading pair
                config = ex.config if isinstance(ex.config, dict) else {}
                trading_pair = config.get('trading_pair', 'Unknown')

                # Format timestamp
                ts = datetime.fromtimestamp(ex.timestamp)
                status_str = "ACTIVE" if ex.is_active else "CLOSED"
                close_type_str = f" ({ex.close_type})" if ex.close_type else ""

                # Color code P&L
                pnl_sign = "💰" if pnl_quote > 0 else "📉" if pnl_quote < 0 else "➖"

                print(f"{i}. {trading_pair} ({status_str}{close_type_str})")
                print(f"   Time: {ts.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"   {pnl_sign} P&L: €{pnl_quote:.2f} ({pnl_pct:+.2f}%)")
                print(f"   💸 Fees: €{fees:.2f}")
                print(f"   📊 Volume: €{filled:.2f}")
                print()

                total_pnl_quote += pnl_quote
                total_fees += fees
                total_filled += filled
                if ex.is_active:
                    active_count += 1
                else:
                    closed_count += 1

            print("-" * 80)
            print("📈 TOTALS:")
            total_sign = "💰" if total_pnl_quote > 0 else "📉" if total_pnl_quote < 0 else "➖"
            print(f"   {total_sign} Total P&L: €{total_pnl_quote:.2f}")
            print(f"   💸 Total Fees: €{total_fees:.2f}")
            print(f"   📊 Total Volume: €{total_filled:.2f}")
            print(f"   ✅ Active Executors: {active_count}")
            print(f"   🛑 Closed Executors: {closed_count}")

            if total_pnl_quote > 0:
                print()
                print("🎉 BOT IS MAKING PROFIT!")
            elif total_pnl_quote < 0:
                print()
                print("⚠️  BOT IS AT A LOSS")
            else:
                print()
                print("➖ BOT IS BREAK-EVEN")
        else:
            print("❌ No executors found in database")
            print("   The bot may not have created any executors yet, or")
            print("   the database is in a different location")
    else:
        print(f"❌ Database not found at: {db_path}")
        print("   The bot may not have run yet, or database is elsewhere")

    session.close()

except ImportError as e:
    print(f"⚠️  Could not import database modules: {e}")
    print("   This is normal if Hummingbot database is not accessible")
except Exception as e:
    print(f"⚠️  Error reading database: {e}")
    import traceback
    traceback.print_exc()

print()
print("=" * 80)
print("💡 Alternative ways to check P&L:")
print("   1. In Hummingbot CLI: status (shows executor P&L)")
print("   2. Check monitoring dashboard: http://localhost:5000")
print("   3. Check logs for executor status updates")
print("=" * 80)
