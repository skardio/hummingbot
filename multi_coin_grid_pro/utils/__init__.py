"""
Utility modules for multi-coin grid trading
"""

from .coin_discovery import CoinDiscovery
from .trend_calculator import (
    MIN_CANDLES_FOR_WARMUP,
    MIN_TREND_THRESHOLD,
    TARGET_HISTORICAL_CANDLES,
    CandleData,
    CoinTrend,
    TrendCalculator,
    TrendSelection,
    TrendStatus,
)

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
