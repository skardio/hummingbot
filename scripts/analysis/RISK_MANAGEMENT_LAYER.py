"""
Global Risk Management Layer for Trading Bot

This module implements enterprise-grade risk management across all strategies:
- Daily max loss protection
- Per-trade risk limits
- Position size limits
- Correlation checks
- Volatility regime detection
- Circuit breaker

Usage:
    from RISK_MANAGEMENT_LAYER import RiskManager

    risk_mgr = RiskManager(
        starting_balance=1000.0,
        daily_max_loss_pct=2.0,
        max_risk_per_trade_pct=0.5
    )

    # Before each trade
    if not risk_mgr.can_trade(symbol, proposed_size):
        logger.warning("Trade rejected by risk manager")
        return

    # After each trade
    risk_mgr.record_trade(symbol, pnl, size)
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class VolatilityRegime(str, Enum):
    """Market volatility regime classification"""
    CALM = "CALM"          # ATR < 1.0% (normal market)
    MODERATE = "MODERATE"  # ATR 1.0-2.5% (elevated volatility)
    HIGH = "HIGH"          # ATR 2.5-5.0% (high volatility)
    EXTREME = "EXTREME"    # ATR > 5.0% (crisis mode)


class TradingStatus(str, Enum):
    """Current trading status"""
    ACTIVE = "ACTIVE"                    # Normal trading
    PAUSED_DAILY_LOSS = "PAUSED_DAILY_LOSS"  # Daily loss limit hit
    PAUSED_CIRCUIT_BREAKER = "PAUSED_CIRCUIT_BREAKER"  # Circuit breaker triggered
    PAUSED_VOLATILITY = "PAUSED_VOLATILITY"  # Volatility too high
    PAUSED_MANUAL = "PAUSED_MANUAL"      # Manual override


@dataclass
class TradeRecord:
    """Record of a single trade"""
    timestamp: float
    symbol: str
    pnl: Decimal  # Realized PnL
    size: Decimal  # Position size
    is_winning: bool


@dataclass
class RiskLimits:
    """Risk limit configuration"""
    daily_max_loss_pct: float = 2.0  # Max 2% daily loss
    max_risk_per_trade_pct: float = 0.5  # Max 0.5% risk per trade
    max_total_open_risk_pct: float = 3.0  # Max 3% total open risk
    max_correlation_exposure_pct: float = 50.0  # Max 50% in correlated assets
    circuit_breaker_loss_pct: float = 1.0  # Circuit breaker at 1% loss in 5 min
    circuit_breaker_window_seconds: int = 300  # 5 minute window


class RiskManager:
    """
    Global Risk Management Layer

    Implements all critical risk controls across spot, futures, grid, and arbitrage strategies.
    """

    def __init__(
        self,
        starting_balance: float,
        daily_max_loss_pct: float = 2.0,
        max_risk_per_trade_pct: float = 0.5,
        max_total_open_risk_pct: float = 3.0,
        enable_circuit_breaker: bool = True,
        enable_correlation_check: bool = True
    ):
        """
        Initialize Risk Manager

        Args:
            starting_balance: Starting capital (EUR)
            daily_max_loss_pct: Maximum daily loss percentage
            max_risk_per_trade_pct: Maximum risk per trade
            max_total_open_risk_pct: Maximum total open risk
            enable_circuit_breaker: Enable circuit breaker
            enable_correlation_check: Enable correlation checking
        """
        self.starting_balance = Decimal(str(starting_balance))
        self.current_balance = self.starting_balance

        # Risk limits
        self.limits = RiskLimits(
            daily_max_loss_pct=daily_max_loss_pct,
            max_risk_per_trade_pct=max_risk_per_trade_pct,
            max_total_open_risk_pct=max_total_open_risk_pct
        )

        # Feature flags
        self.enable_circuit_breaker = enable_circuit_breaker
        self.enable_correlation_check = enable_correlation_check

        # State tracking
        self.trading_status = TradingStatus.ACTIVE
        self.daily_start_time = time.time()
        self.daily_pnl = Decimal("0")
        self.trades_today: List[TradeRecord] = []

        # Circuit breaker
        self.recent_pnl = deque(maxlen=100)  # Last 100 PnL updates
        self.circuit_breaker_triggered_at: Optional[float] = None
        self.circuit_breaker_reset_seconds = 3600  # 1 hour cooldown

        # Position tracking
        self.open_positions: Dict[str, Decimal] = {}  # {symbol: position_size}
        self.position_entry_prices: Dict[str, Decimal] = {}  # {symbol: entry_price}

        # Correlation tracking (simplified)
        self.crypto_eur_exposure = Decimal("0")  # Total exposure to crypto/EUR pairs

        # Volatility tracking
        self.volatility_regime = VolatilityRegime.CALM
        self.symbol_volatility: Dict[str, float] = {}  # {symbol: ATR_pct}

        logger.info("=" * 80)
        logger.info("🛡️  RISK MANAGER INITIALIZED")
        logger.info("=" * 80)
        logger.info(f"Starting Balance: €{self.starting_balance:.2f}")
        logger.info(f"Daily Max Loss: {self.limits.daily_max_loss_pct}%")
        logger.info(f"Max Risk Per Trade: {self.limits.max_risk_per_trade_pct}%")
        logger.info(f"Circuit Breaker: {'ENABLED' if enable_circuit_breaker else 'DISABLED'}")
        logger.info("=" * 80)

    def reset_daily_counters(self) -> None:
        """Reset daily counters at start of new trading day"""
        current_time = time.time()
        time_since_day_start = current_time - self.daily_start_time

        # Reset every 24 hours
        if time_since_day_start > 86400:  # 24 hours
            logger.info(f"📅 New trading day - resetting counters")
            logger.info(f"   Previous day PnL: €{self.daily_pnl:.2f} ({float(self.daily_pnl / self.starting_balance * 100):.2f}%)")
            logger.info(f"   Trades: {len(self.trades_today)}")

            # Archive yesterday's trades
            winning_trades = sum(1 for t in self.trades_today if t.is_winning)
            win_rate = winning_trades / len(self.trades_today) * 100 if self.trades_today else 0
            logger.info(f"   Win Rate: {win_rate:.1f}%")

            # Reset
            self.daily_start_time = current_time
            self.daily_pnl = Decimal("0")
            self.trades_today.clear()

            # Resume trading if paused due to daily loss
            if self.trading_status == TradingStatus.PAUSED_DAILY_LOSS:
                logger.info("✅ Daily loss limit reset - resuming trading")
                self.trading_status = TradingStatus.ACTIVE

    def can_trade(
        self,
        symbol: str,
        proposed_size: Decimal,
        proposed_stop_loss_pct: float = 2.0
    ) -> tuple:
        """
        Check if trade is allowed under risk management rules

        Args:
            symbol: Trading pair symbol
            proposed_size: Proposed position size (EUR)
            proposed_stop_loss_pct: Proposed stop loss percentage

        Returns:
            (allowed: bool, reason: str)
        """
        # Reset daily counters if new day
        self.reset_daily_counters()

        # Check 1: Trading status
        if self.trading_status != TradingStatus.ACTIVE:
            return (False, f"Trading paused: {self.trading_status.value}")

        # Check 2: Daily loss limit
        daily_loss_pct = float(self.daily_pnl / self.starting_balance * 100)
        if daily_loss_pct <= -self.limits.daily_max_loss_pct:
            self.trading_status = TradingStatus.PAUSED_DAILY_LOSS
            logger.critical(
                f"🛑 DAILY LOSS LIMIT HIT: {daily_loss_pct:.2f}% (limit: {self.limits.daily_max_loss_pct}%)\n"
                f"   Trading PAUSED for 24 hours"
            )
            return (False, f"Daily loss limit exceeded: {daily_loss_pct:.2f}%")

        # Check 3: Per-trade risk limit
        max_trade_risk = self.starting_balance * Decimal(str(self.limits.max_risk_per_trade_pct / 100))
        proposed_risk = proposed_size * Decimal(str(proposed_stop_loss_pct / 100))

        if proposed_risk > max_trade_risk:
            return (
                False,
                f"Per-trade risk too high: €{proposed_risk:.2f} > max €{max_trade_risk:.2f}"
            )

        # Check 4: Total open risk limit
        total_open_risk = sum(
            size * Decimal("0.02")  # Assume 2% risk per position
            for size in self.open_positions.values()
        )
        total_open_risk_pct = float(total_open_risk / self.starting_balance * 100)

        if total_open_risk_pct + float(proposed_risk / self.starting_balance * 100) > self.limits.max_total_open_risk_pct:
            return (
                False,
                f"Total open risk limit exceeded: {total_open_risk_pct:.2f}% + "
                f"{float(proposed_risk / self.starting_balance * 100):.2f}% > "
                f"{self.limits.max_total_open_risk_pct}%"
            )

        # Check 5: Correlation limit (simplified: all crypto/EUR pairs are correlated)
        if self.enable_correlation_check and symbol.endswith("/EUR"):
            new_crypto_exposure = self.crypto_eur_exposure + proposed_size
            crypto_exposure_pct = float(new_crypto_exposure / self.starting_balance * 100)

            if crypto_exposure_pct > self.limits.max_correlation_exposure_pct:
                return (
                    False,
                    f"Correlation limit exceeded: {crypto_exposure_pct:.1f}% > "
                    f"{self.limits.max_correlation_exposure_pct}%"
                )

        # Check 6: Circuit breaker
        if self.enable_circuit_breaker and self.circuit_breaker_triggered_at:
            time_since_trigger = time.time() - self.circuit_breaker_triggered_at
            if time_since_trigger < self.circuit_breaker_reset_seconds:
                return (
                    False,
                    f"Circuit breaker active - wait {(self.circuit_breaker_reset_seconds - time_since_trigger) / 60:.0f} min"
                )
            else:
                # Reset circuit breaker
                logger.info("✅ Circuit breaker reset - resuming trading")
                self.circuit_breaker_triggered_at = None
                self.trading_status = TradingStatus.ACTIVE

        # Check 7: Volatility regime (optional - warn only)
        if symbol in self.symbol_volatility:
            volatility = self.symbol_volatility[symbol]
            if volatility > 5.0:  # Extreme volatility
                logger.warning(
                    f"⚠️  WARNING: {symbol} has EXTREME volatility ({volatility:.2f}% ATR)\n"
                    f"   Consider reducing position size"
                )

        # All checks passed
        return (True, "OK")

    def record_trade(
        self,
        symbol: str,
        pnl: Decimal,
        size: Decimal
    ) -> None:
        """
        Record a completed trade

        Args:
            symbol: Trading pair symbol
            pnl: Realized PnL (EUR)
            size: Position size (EUR)
        """
        # Create trade record
        trade = TradeRecord(
            timestamp=time.time(),
            symbol=symbol,
            pnl=pnl,
            size=size,
            is_winning=pnl > 0
        )

        # Update daily PnL
        self.daily_pnl += pnl
        self.trades_today.append(trade)

        # Update balance
        self.current_balance += pnl

        # Log trade
        pnl_pct = float(pnl / size * 100) if size > 0 else 0
        daily_pnl_pct = float(self.daily_pnl / self.starting_balance * 100)

        logger.info(
            f"📊 TRADE RECORDED: {symbol}\n"
            f"   PnL: €{pnl:.2f} ({pnl_pct:+.2f}%)\n"
            f"   Daily PnL: €{self.daily_pnl:.2f} ({daily_pnl_pct:+.2f}%)\n"
            f"   Balance: €{self.current_balance:.2f}\n"
            f"   Trades Today: {len(self.trades_today)}"
        )

        # Update circuit breaker
        if self.enable_circuit_breaker:
            self._check_circuit_breaker(pnl)

        # Remove from open positions
        if symbol in self.open_positions:
            if symbol.endswith("/EUR"):
                self.crypto_eur_exposure -= self.open_positions[symbol]
            del self.open_positions[symbol]
            del self.position_entry_prices[symbol]

    def open_position(
        self,
        symbol: str,
        size: Decimal,
        entry_price: Decimal
    ) -> None:
        """
        Record opening a new position

        Args:
            symbol: Trading pair symbol
            size: Position size (EUR)
            entry_price: Entry price
        """
        self.open_positions[symbol] = size
        self.position_entry_prices[symbol] = entry_price

        # Track correlation exposure
        if symbol.endswith("/EUR"):
            self.crypto_eur_exposure += size

        logger.info(
            f"📈 POSITION OPENED: {symbol}\n"
            f"   Size: €{size:.2f}\n"
            f"   Entry: €{entry_price:.4f}\n"
            f"   Open Positions: {len(self.open_positions)}"
        )

    def _check_circuit_breaker(self, pnl: Decimal) -> None:
        """
        Check if circuit breaker should trigger

        Circuit breaker triggers if loss > threshold in short time window.

        Args:
            pnl: Recent PnL to add to window
        """
        current_time = time.time()

        # Add to recent PnL
        self.recent_pnl.append({'pnl': pnl, 'timestamp': current_time})

        # Calculate PnL in window
        window_seconds = self.limits.circuit_breaker_window_seconds
        cutoff_time = current_time - window_seconds

        recent_pnl_sum = sum(
            item['pnl']
            for item in self.recent_pnl
            if item['timestamp'] > cutoff_time
        )

        recent_pnl_pct = float(recent_pnl_sum / self.starting_balance * 100)

        # Trigger if loss exceeds threshold
        if recent_pnl_pct <= -self.limits.circuit_breaker_loss_pct:
            self.circuit_breaker_triggered_at = current_time
            self.trading_status = TradingStatus.PAUSED_CIRCUIT_BREAKER

            logger.critical(
                f"🚨 CIRCUIT BREAKER TRIGGERED\n"
                f"   Loss in {window_seconds / 60:.0f} min: €{recent_pnl_sum:.2f} ({recent_pnl_pct:.2f}%)\n"
                f"   Threshold: {self.limits.circuit_breaker_loss_pct}%\n"
                f"   Trading PAUSED for {self.circuit_breaker_reset_seconds / 60:.0f} minutes"
            )

    def update_volatility(
        self,
        symbol: str,
        atr_pct: float
    ) -> None:
        """
        Update volatility tracking for a symbol

        Args:
            symbol: Trading pair symbol
            atr_pct: Average True Range as percentage
        """
        self.symbol_volatility[symbol] = atr_pct

        # Classify volatility regime (global - use max across all symbols)
        if self.symbol_volatility:
            max_atr = max(self.symbol_volatility.values())

            if max_atr < 1.0:
                self.volatility_regime = VolatilityRegime.CALM
            elif max_atr < 2.5:
                self.volatility_regime = VolatilityRegime.MODERATE
            elif max_atr < 5.0:
                self.volatility_regime = VolatilityRegime.HIGH
            else:
                self.volatility_regime = VolatilityRegime.EXTREME

    def get_status_report(self) -> str:
        """Get comprehensive status report"""
        daily_pnl_pct = float(self.daily_pnl / self.starting_balance * 100)
        open_risk = sum(self.open_positions.values())
        open_risk_pct = float(open_risk / self.starting_balance * 100)

        winning_trades = sum(1 for t in self.trades_today if t.is_winning)
        win_rate = winning_trades / len(self.trades_today) * 100 if self.trades_today else 0

        report = f"""
╔════════════════════════════════════════════════════════════════╗
║                   RISK MANAGER STATUS REPORT                    ║
╠════════════════════════════════════════════════════════════════╣
║ Status: {self.trading_status.value:50s} ║
║ Volatility Regime: {self.volatility_regime.value:45s} ║
╠════════════════════════════════════════════════════════════════╣
║ BALANCE & PNL                                                  ║
║   Starting Balance:  €{self.starting_balance:>10.2f}                           ║
║   Current Balance:   €{self.current_balance:>10.2f}                           ║
║   Daily PnL:         €{self.daily_pnl:>10.2f} ({daily_pnl_pct:+.2f}%)                    ║
╠════════════════════════════════════════════════════════════════╣
║ TRADING ACTIVITY                                               ║
║   Trades Today:      {len(self.trades_today):>3d}                                     ║
║   Win Rate:          {win_rate:>6.1f}%                                   ║
║   Open Positions:    {len(self.open_positions):>3d}                                     ║
║   Open Risk:         €{open_risk:>10.2f} ({open_risk_pct:.2f}%)                    ║
╠════════════════════════════════════════════════════════════════╣
║ RISK LIMITS                                                    ║
║   Daily Max Loss:    {self.limits.daily_max_loss_pct}% (used: {abs(daily_pnl_pct):.2f}%)                 ║
║   Max Risk/Trade:    {self.limits.max_risk_per_trade_pct}%                                        ║
║   Max Total Risk:    {self.limits.max_total_open_risk_pct}% (used: {open_risk_pct:.2f}%)                 ║
╚════════════════════════════════════════════════════════════════╝
"""
        return report


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Initialize risk manager
    risk_mgr = RiskManager(
        starting_balance=1000.0,
        daily_max_loss_pct=2.0,
        max_risk_per_trade_pct=0.5
    )

    # Check if trade is allowed
    can_trade, reason = risk_mgr.can_trade(
        symbol="XRP/EUR",
        proposed_size=Decimal("50"),
        proposed_stop_loss_pct=2.0
    )

    if can_trade:
        print("✅ Trade allowed")

        # Open position
        risk_mgr.open_position(
            symbol="XRP/EUR",
            size=Decimal("50"),
            entry_price=Decimal("0.5000")
        )

        # Record trade (simulated loss)
        risk_mgr.record_trade(
            symbol="XRP/EUR",
            pnl=Decimal("-1.0"),  # Lost €1
            size=Decimal("50")
        )
    else:
        print(f"❌ Trade rejected: {reason}")

    # Print status
    print(risk_mgr.get_status_report())
