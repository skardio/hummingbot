"""
Pydantic config schema for the Bitget Spot Micro-Arbitrage bot.
Defaults follow the provided conservative preset.
"""
from decimal import Decimal
from typing import List

from pydantic import BaseModel, Field


class MicroArbBitgetConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable micro-arb mode")
    symbols: List[str] = Field(
        default_factory=lambda: [
            # Start with top 5 most liquid - dynamic discovery will find more
            "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT"
        ],
        description="Initial symbols (dynamic discovery will populate more)")

    # Edge - LOWERED for tighter markets
    min_spread_pct: Decimal = Field(default=Decimal("0.10"), description="Minimum spread in % (gross) - LOWERED from 0.35%")
    maker_fee_pct: Decimal = Field(default=Decimal("0.10"), description="Maker fee percent")
    buffer_pct: Decimal = Field(default=Decimal("0.02"), description="Extra buffer percent - LOWERED from 0.05%")

    # Orders
    order_size_usdt: Decimal = Field(default=Decimal("50"), description="Order notional in quote (test: $50)")
    price_offset_ticks: int = Field(default=1, description="Tick offset to prioritize maker queue")
    maker_only: bool = Field(default=True, description="Place maker-only orders")

    # Lifecycle (seconds)
    buy_timeout_sec: int = Field(default=3, description="Cancel buy if not filled within seconds")
    max_hold_sec: int = Field(default=6, description="Force exit after this hold time")
    cooldown_after_trade_sec: int = Field(default=5, description="Cooldown after each round-trip")
    cooldown_after_cancel_sec: int = Field(default=2, description="Cooldown after cancel/no fill")
    cooldown_after_force_exit_sec: int = Field(default=10, description="Cooldown after forced exit")

    # Guards - LOWERED for more opportunities
    min_depth_usdt: Decimal = Field(default=Decimal("10000"), description="Combined top-of-book depth - LOWERED from 25000")
    volatility_block_pct_30s: Decimal = Field(default=Decimal("0.30"), description="Max 30s swing %")
    max_inventory_usdt: Decimal = Field(default=Decimal("200"), description="Inventory cap in quote - INCREASED from 150")
    inventory_breach_cooldown_sec: int = Field(default=30, description="Cooldown after inventory breach")
    dust_threshold_base: Decimal = Field(default=Decimal("1e-8"), description="Treat smaller base as dust/flat")

    # Rate limits
    order_refresh_time: int = Field(default=2, description="Refresh interval for orders (s)")
    rate_limit_buffer: Decimal = Field(default=Decimal("0.8"), description="Rate limit buffer (0-1)")
    min_cancel_interval_sec: int = Field(default=1, description="Minimum interval between cancels")

    # Logging
    log_level: str = Field(default="INFO", description="Logger level")
    log_decisions: bool = Field(default=True, description="Verbose decision logging")
    log_block_reasons: bool = Field(default=True, description="Log block reasons")
    log_trade_summary: bool = Field(default=True, description="Log trade summary")
    log_metrics_interval_sec: int = Field(default=30, description="Periodic metrics log interval")

    # Dynamic Symbol Discovery
    auto_discover_symbols: bool = Field(default=True, description="Auto-discover best trading pairs from exchange")
    min_volume_24h_usdt: Decimal = Field(default=Decimal("1000000"), description="Minimum 24h volume in USDT")
    max_symbols: int = Field(default=50, description="Maximum number of symbols to monitor")
    symbol_refresh_interval_sec: int = Field(default=300, description="Refresh symbol list every N seconds (5 min)")
