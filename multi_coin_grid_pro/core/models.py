"""
Core data models for Hybrid Grid Bot v2.0
"""
from dataclasses import dataclass
from decimal import Decimal


@dataclass
class Candle:
    """OHLCV candle data"""
    ts: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass
class CandleIndicators:
    """Technical indicators calculated from candle data"""
    price: Decimal
    rsi_14: float
    vwap: Decimal
    atr_pct: float
    wick_ratio: float
    trend_1h_pct: float
    trend_4h_pct: float
    trend_24h_pct: float
    change_5m_pct: float


@dataclass
class Position:
    """Trading position"""
    symbol: str
    size: Decimal
    avg_entry_price: Decimal
    notional_eur: Decimal
    unrealized_pnl: Decimal = Decimal("0")


@dataclass
class TradeFill:
    """Executed trade fill"""
    symbol: str
    side: str  # "buy" / "sell"
    price: Decimal
    size: Decimal
    fee: Decimal
    ts: int
    order_id: str = ""
