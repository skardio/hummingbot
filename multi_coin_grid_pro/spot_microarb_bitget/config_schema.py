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
            "BTC-USDT",
            "ETH-USDT",
            "SOL-USDT"],
        description="Tradable symbols")

    # Edge
    min_spread_pct: Decimal = Field(default=Decimal("0.35"), description="Minimum spread in % (gross)")
    maker_fee_pct: Decimal = Field(default=Decimal("0.10"), description="Maker fee percent")
    buffer_pct: Decimal = Field(default=Decimal("0.05"), description="Extra buffer percent")

    # Orders
    order_size_usdt: Decimal = Field(default=Decimal("10"), description="Order notional in quote")
    price_offset_ticks: int = Field(default=1, description="Tick offset to prioritize maker queue")
    maker_only: bool = Field(default=True, description="Place maker-only orders")

    # Lifecycle (seconds)
    buy_timeout_sec: int = Field(default=3, description="Cancel buy if not filled within seconds")
    max_hold_sec: int = Field(default=6, description="Force exit after this hold time")
    cooldown_after_trade_sec: int = Field(default=5, description="Cooldown after each round-trip")
    cooldown_after_cancel_sec: int = Field(default=2, description="Cooldown after cancel/no fill")
    cooldown_after_force_exit_sec: int = Field(default=10, description="Cooldown after forced exit")

    # Guards
    min_depth_usdt: Decimal = Field(default=Decimal("50000"), description="Combined top-of-book depth")
    volatility_block_pct_30s: Decimal = Field(default=Decimal("0.30"), description="Max 30s swing %")
    max_inventory_usdt: Decimal = Field(default=Decimal("15"), description="Inventory cap in quote")
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
