"""
Utility modules for multi-coin grid trading
"""

__all__ = [
    "CoinDiscovery",
    "TrendCalculator",
    "CoinTrend",
    "TrendSelection",
    "TrendStatus",
    "CandleData",
    "MIN_TREND_THRESHOLD",
    "MIN_CANDLES_FOR_WARMUP",
    "TARGET_HISTORICAL_CANDLES",
]


def __getattr__(name):
    """Lazy-load heavy connector-dependent utilities only when requested."""
    if name == "CoinDiscovery":
        from .coin_discovery import CoinDiscovery
        return CoinDiscovery
    if name in {
        "TrendCalculator",
        "CoinTrend",
        "TrendSelection",
        "TrendStatus",
        "CandleData",
        "MIN_TREND_THRESHOLD",
        "MIN_CANDLES_FOR_WARMUP",
        "TARGET_HISTORICAL_CANDLES",
    }:
        from . import trend_calculator as _trend_calculator
        return getattr(_trend_calculator, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
