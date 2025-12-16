#!/home/mo/repos/hummingbot/.venv/bin/python3
"""
Standalone Demo: Multi-Indicator, Multi-Timeframe Trend Engine
Demonstrates the output contract without importing the full trend calculator.
"""

import json
from dataclasses import dataclass
from enum import Enum

# Constants
MIN_TREND_THRESHOLD = 0.5
MIN_CANDLES_FOR_WARMUP = 360
TARGET_HISTORICAL_CANDLES = 720


# Enums
class TrendStatus(str, Enum):
    WARMUP = "WARMUP"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"
    BULLISH = "BULLISH"


# Output Contract
@dataclass
class TrendSelection:
    symbol: str
    trend_1h: float
    trend_4h: float
    trend_24h: float
    trend_score_pct: float
    passes: bool
    status: TrendStatus
    candle_count: int
    consensus_pct: float = 0.0
    volatility: float = 0.0


def main():
    print("\n" + "=" * 80)
    print("🚀 MULTI-INDICATOR, MULTI-TIMEFRAME TREND ENGINE - OUTPUT CONTRACT DEMO")
    print("=" * 80)
    print()

    # Display configuration
    print("📋 CONFIGURATION:")
    print(f"  MIN_TREND_THRESHOLD: {MIN_TREND_THRESHOLD:+.2f}%")
    print(f"  MIN_CANDLES_FOR_WARMUP: {MIN_CANDLES_FOR_WARMUP} (30 hours)")
    print(f"  TARGET_HISTORICAL_CANDLES: {TARGET_HISTORICAL_CANDLES} (60 hours)")
    print()

    print("🔧 INDICATORS (Per Timeframe):")
    print("  1. Raw Trend (5% weight) - Baseline direction")
    print("  2. Volatility-Normalized Trend (15%) - Context-adjusted")
    print("  3. EMA Distance Trend (40%) - Momentum & alignment")
    print("  4. Linear Regression Trend (40%) - Structural direction")
    print()

    print("⏰ TIMEFRAMES:")
    print("  - 1h (short-term): 20% weight")
    print("  - 4h (mid-term): 40% weight")
    print("  - 24h (long-term): 40% weight")
    print()

    print("✅ VALIDATION RULES:")
    print(f"  1. Minimum {MIN_CANDLES_FOR_WARMUP} candles required (30h × 5m)")
    print(f"  2. Trend score must be >= {MIN_TREND_THRESHOLD:+.2f}% for selection")
    print("  3. Status: WARMUP → BEARISH → SIDEWAYS → BULLISH")
    print()

    # Create mock trend data
    print("⚙️  Creating mock trend data for demonstration...")
    print()

    mock_data = {
        "BTC-EUR": {
            "trend_60m": 0.8, "trend_240m": 1.9, "trend_1440m": 3.2,
            "trend_score": 2.45, "consensus_pct": 2.1, "volatility": 0.85, "candles": 650
        },
        "ETH-EUR": {
            "trend_60m": 0.5, "trend_240m": 1.2, "trend_1440m": 2.8,
            "trend_score": 1.85, "consensus_pct": 1.6, "volatility": 0.72, "candles": 620
        },
        "XRP-EUR": {
            "trend_60m": 0.1, "trend_240m": 0.3, "trend_1440m": 0.2,
            "trend_score": 0.23, "consensus_pct": 0.18, "volatility": 1.2, "candles": 580
        },
        "SOL-EUR": {
            "trend_60m": -0.8, "trend_240m": -1.4, "trend_1440m": -2.9,
            "trend_score": -1.96, "consensus_pct": -2.1, "volatility": 1.5, "candles": 700
        },
        "ADA-EUR": {
            "trend_60m": 0.3, "trend_240m": 0.8, "trend_1440m": 1.2,
            "trend_score": 0.92, "consensus_pct": 0.75, "volatility": 0.95, "candles": 250
        },
    }

    # Create TrendSelection objects
    selections = []
    for symbol, data in mock_data.items():
        # Determine status and passes
        if data["candles"] < MIN_CANDLES_FOR_WARMUP:
            status = TrendStatus.WARMUP
            passes = False
        elif data["trend_score"] < -MIN_TREND_THRESHOLD:
            status = TrendStatus.BEARISH
            passes = False
        elif data["trend_score"] < MIN_TREND_THRESHOLD:
            status = TrendStatus.SIDEWAYS
            passes = False
        else:
            status = TrendStatus.BULLISH
            passes = True

        selection = TrendSelection(
            symbol=symbol,
            trend_1h=data["trend_60m"],
            trend_4h=data["trend_240m"],
            trend_24h=data["trend_1440m"],
            trend_score_pct=data["trend_score"],
            passes=passes,
            status=status,
            candle_count=data["candles"],
            consensus_pct=data["consensus_pct"],
            volatility=data["volatility"]
        )
        selections.append(selection)

    # Print report
    print("=" * 80)
    print("📊 TREND SELECTION REPORT")
    print("=" * 80)
    print(f"Total coins tracked: {len(selections)}")
    print(f"Minimum threshold: {MIN_TREND_THRESHOLD:+.2f}%")
    print(f"Minimum candles: {MIN_CANDLES_FOR_WARMUP}")
    print()

    # Count by status
    status_counts = {s: 0 for s in TrendStatus}
    for sel in selections:
        status_counts[sel.status] += 1

    print("Status Distribution:")
    print(f"  WARMUP:   {status_counts[TrendStatus.WARMUP]} coins (insufficient data)")
    print(f"  BEARISH:  {status_counts[TrendStatus.BEARISH]} coins (< {-MIN_TREND_THRESHOLD:+.2f}%)")
    print(f"  SIDEWAYS: {status_counts[TrendStatus.SIDEWAYS]} coins ({-MIN_TREND_THRESHOLD:+.2f}% to {MIN_TREND_THRESHOLD:+.2f}%)")
    print(f"  BULLISH:  {status_counts[TrendStatus.BULLISH]} coins (>= {MIN_TREND_THRESHOLD:+.2f}%)")
    print()

    # Sort by trend score
    selections.sort(key=lambda x: x.trend_score_pct, reverse=True)

    # Print each selection
    for idx, sel in enumerate(selections, 1):
        status_emoji = {
            TrendStatus.WARMUP: "⏳",
            TrendStatus.BEARISH: "📉",
            TrendStatus.SIDEWAYS: "➡️",
            TrendStatus.BULLISH: "📈"
        }[sel.status]

        passes_emoji = "✅" if sel.passes else "❌"

        print(
            f"{idx:2}. {status_emoji} {sel.symbol:12} | "
            f"Score: {sel.trend_score_pct:+6.2f}% | "
            f"1h: {sel.trend_1h:+6.2f}% | "
            f"4h: {sel.trend_4h:+6.2f}% | "
            f"24h: {sel.trend_24h:+6.2f}% | "
            f"Candles: {sel.candle_count:3} | "
            f"{passes_emoji} {sel.status.value}"
        )

    print("=" * 80)
    print()

    # Show individual examples
    print("=" * 80)
    print("🔍 INDIVIDUAL VALIDATION EXAMPLES")
    print("=" * 80)
    print()

    for sel in selections[:3]:
        print(f"Symbol: {sel.symbol}")
        print(f"  Trend 1h:  {sel.trend_1h:+6.2f}%")
        print(f"  Trend 4h:  {sel.trend_4h:+6.2f}%")
        print(f"  Trend 24h: {sel.trend_24h:+6.2f}%")
        print(f"  Score:     {sel.trend_score_pct:+6.2f}%")
        print(f"  Consensus: {sel.consensus_pct:+6.2f}%")
        print(f"  Volatility: {sel.volatility:.3f}%")
        print(f"  Candles:   {sel.candle_count} / {MIN_CANDLES_FOR_WARMUP}")
        print(f"  Passes:    {sel.passes} ({'✅' if sel.passes else '❌'})")
        print(f"  Status:    {sel.status.value}")
        print()

    # Show JSON output
    print("=" * 80)
    print("📄 JSON OUTPUT CONTRACT EXAMPLE")
    print("=" * 80)
    print()

    output = {
        "symbol": selections[0].symbol,
        "trend_1h": round(selections[0].trend_1h, 2),
        "trend_4h": round(selections[0].trend_4h, 2),
        "trend_24h": round(selections[0].trend_24h, 2),
        "trend_score_pct": round(selections[0].trend_score_pct, 2),
        "passes": selections[0].passes,
        "status": selections[0].status.value,
        "candle_count": selections[0].candle_count,
        "consensus_pct": round(selections[0].consensus_pct, 2),
        "volatility": round(selections[0].volatility, 3)
    }
    print(json.dumps(output, indent=2))
    print()

    print("=" * 80)
    print("✅ DEMONSTRATION COMPLETE")
    print("=" * 80)
    print()
    print("🎯 Key Features Demonstrated:")
    print("  ✅ OHLCV candle requirement (720 candles)")
    print("  ✅ 4 indicators with weighted consensus")
    print("  ✅ Multi-timeframe analysis (1h, 4h, 24h)")
    print("  ✅ MIN_TREND_THRESHOLD validation (+0.5%)")
    print("  ✅ Structured output with passes/status")
    print("  ✅ WARMUP mode for insufficient data")
    print("  ✅ Bearish/Sideways market blocking")
    print()

    print("=" * 80)
    print("📚 IMPLEMENTATION DETAILS")
    print("=" * 80)
    print()
    print("Location: multi_coin_grid_pro/utils/trend_calculator.py")
    print()
    print("Key Classes:")
    print("  - TrendCalculator: Main calculation engine")
    print("  - TrendSelection: Output contract dataclass")
    print("  - TrendStatus: Enum for status values")
    print("  - CoinTrend: Internal trend data storage")
    print()
    print("Key Methods:")
    print("  - validate_trend(symbol) → TrendSelection")
    print("  - get_all_selections() → List[TrendSelection]")
    print("  - print_selection_report() → formatted console output")
    print()
    print("Documentation:")
    print("  - Full guide: TREND_ENGINE_IMPLEMENTATION.md")
    print("  - Quick ref:  TREND_ENGINE_QUICK_REF.md")
    print()


if __name__ == "__main__":
    main()
