"""
Professional Risk Management System

Implements institutional-grade risk management techniques:
1. Dynamic stop-loss (ATR-based trailing stops)
2. Time-based exits (cut losers early)
3. Correlation-aware position sizing
4. Daily drawdown limits
5. Win rate monitoring
6. Risk/Reward ratio validation

Used by professional traders to protect capital and maximize edge.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PositionRisk:
    """Risk metrics for an open position"""
    symbol: str
    entry_price: Decimal
    current_price: Decimal
    unrealized_pnl_pct: float
    time_held_minutes: int
    atr_pct: float  # Current ATR as % of price

    # Dynamic stops
    initial_stop_pct: float
    current_stop_pct: float  # Can tighten as position moves favorable
    trailing_stop_distance_pct: float

    # Time-based risk
    max_hold_time_minutes: int
    is_time_expired: bool

    # Confidence score
    entry_confidence: float  # 0-1, based on setup quality


@dataclass
class PortfolioRisk:
    """Overall portfolio risk metrics"""
    total_equity: Decimal
    daily_pnl: Decimal
    daily_pnl_pct: float
    max_daily_loss_pct: float  # Hard limit (e.g., -3%)

    open_positions: int
    max_positions: int

    # Win rate tracking (last N trades)
    recent_wins: int
    recent_losses: int
    win_rate: float

    # Correlation
    highly_correlated_positions: List[Tuple[str, str]]  # Pairs of correlated symbols
    correlation_risk_score: float  # 0-1, higher = more concentrated risk


class ProfessionalRiskManager:
    """
    Professional-grade risk management system for GRID/MEAN-REVERSION bots.

    Key Principles (Grid-Aware):
    1. ATR-based stops (not fixed %) - respect market volatility
    2. Profit tiers (not trailing stops) - preserve grid structure
    3. Context-aware time exits - only exit stalled positions
    4. Daily drawdown limits - hard capital protection
    5. PnL-driven pauses - not just win rate

    ⚠️  CRITICAL: This is designed for GRID bots, NOT momentum/trend strategies.

    Usage:
        risk_mgr = ProfessionalRiskManager(config)

        # Before entry
        if risk_mgr.can_open_new_position(symbol, confidence=0.8):
            size = risk_mgr.calculate_position_size(symbol, confidence=0.8)

        # During holding
        action, reason = risk_mgr.should_exit_position(position_risk)
        if action == "STOP_LOSS":
            close_position()
        elif action == "PROFIT_LOCK":
            close_position()  # Profit tier hit
        elif action == "TIME_STOP":
            close_position()  # Stalled position
    """

    def __init__(
        self,
        max_daily_loss_pct: float = 0.03,  # -3% daily limit (HARD LIMIT)
        max_positions: int = 6,
        atr_stop_multiplier: float = 2.0,  # Stop at 2x ATR (grid-aware)
        min_stop_pct: float = 0.02,  # Min -2% stop (never too tight)
        max_stop_pct: float = 0.08,  # Max -8% stop (never too wide)
        time_based_stop_minutes: int = 360,  # 6 hours for grids (not 3!)
        time_stop_requires_stall: bool = True,  # Only exit if price stalled
        price_stall_threshold_atr: float = 0.3,  # < 0.3x ATR = stalled
        min_minutes_since_last_fill: int = 45,  # Dead liquidity check
        profit_lock_tiers: List[Tuple[float, float, float]] = None,  # [(peak_pct, required_pullback_pct, lock_pct)]
        min_rolling_pnl_pct: float = -0.02,  # Pause if rolling 20-trade PnL < -2%
        min_win_rate: float = 0.35,  # Grid bots can be 35% win rate and profitable
        pause_cooldown_minutes: int = 120,  # 2-hour pause after trigger
        resume_min_pnl_pct: float = 0.0,  # Resume only if last 10 trades >= 0%
        max_pause_extensions: int = 1,  # Max times pause can extend before forced resume
        post_resume_immunity_minutes: int = 30,  # After force-resume, immune from re-pause
        max_correlation: float = 0.7,  # Max correlation between open positions
    ):
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_positions = max_positions
        self.atr_stop_multiplier = atr_stop_multiplier
        self.min_stop_pct = min_stop_pct
        self.max_stop_pct = max_stop_pct
        self.time_based_stop_minutes = time_based_stop_minutes
        self.time_stop_requires_stall = time_stop_requires_stall
        self.price_stall_threshold_atr = price_stall_threshold_atr
        self.min_minutes_since_last_fill = min_minutes_since_last_fill
        self.profit_lock_tiers = profit_lock_tiers or [
            (0.01, 0.005, 0.0),   # Peak +1% → pullback 0.5% → lock breakeven
            (0.02, 0.013, 0.007),  # Peak +2% → pullback 1.3% → lock +0.7%
            (0.03, 0.015, 0.015),  # Peak +3% → pullback 1.5% → lock +1.5%
        ]
        self.min_rolling_pnl_pct = min_rolling_pnl_pct
        self.min_win_rate = min_win_rate
        self.pause_cooldown_minutes = pause_cooldown_minutes
        self.resume_min_pnl_pct = resume_min_pnl_pct
        self.max_pause_extensions = max_pause_extensions
        self.post_resume_immunity_minutes = post_resume_immunity_minutes
        self.max_correlation = max_correlation

        # Tracking
        self.daily_start_equity: Optional[Decimal] = None
        self.daily_reset_time: Optional[datetime] = None
        self.recent_trades: List[Dict] = []  # Last 20 trades for win rate
        self.position_high_water_marks: Dict[str, Decimal] = {}  # For profit tiers (peak tracking)
        self.position_last_fill_time: Dict[str, datetime] = {}  # For dead liquidity detection
        self.pause_until: Optional[datetime] = None  # Cooldown tracking
        self.pause_reason: Optional[str] = None
        self._pause_extensions: int = 0  # Number of times pause has been extended
        self._post_resume_immune_until: Optional[datetime] = None  # Immunity after force-resume

        logger.info("=" * 80)
        logger.info("🛡️  Professional Risk Manager initialized (GRID-AWARE v2)")
        logger.info(f"   Daily Loss Limit: -{self.max_daily_loss_pct * 100:.1f}% (HARD)")
        logger.info(f"   Stop Loss: {self.atr_stop_multiplier}x ATR (clamped: -{self.min_stop_pct * 100:.1f}% to -{self.max_stop_pct * 100:.1f}%)")
        logger.info(f"   Time Stop: {self.time_based_stop_minutes} min (stall + no fills > {self.min_minutes_since_last_fill} min)")
        logger.info(f"   Profit Tiers: {len(self.profit_lock_tiers)} levels (drawdown-based)")
        logger.info(f"   Pause: Rolling PnL < {self.min_rolling_pnl_pct * 100:.1f}% (cooldown: {self.pause_cooldown_minutes} min)")
        logger.info("=" * 80)

    def can_open_new_position(
        self,
        symbol: str,
        confidence: float,
        portfolio_risk: PortfolioRisk
    ) -> Tuple[bool, str]:
        """
        Check if it's safe to open a new position.

        Returns:
            (can_open, reason)
        """
        # 0. Check pause cooldown
        if self.pause_until and datetime.now() < self.pause_until:
            remaining = (self.pause_until - datetime.now()).total_seconds() / 60
            return False, f"⏸️  Paused (cooldown: {remaining:.0f} min remaining) - Reason: {self.pause_reason}"

        # Check if we can resume from pause
        if self.pause_until and datetime.now() >= self.pause_until:
            # Check if conditions improved
            if len(self.recent_trades) >= 10:
                last_10_pnl = sum(t["pnl_pct"] for t in self.recent_trades[-10:]) / 10
                if last_10_pnl < self.resume_min_pnl_pct:
                    self._pause_extensions += 1
                    if self._pause_extensions >= self.max_pause_extensions:
                        # Force resume: stale data can't improve without new trades
                        # Clear stale trades so step 3 won't immediately re-trigger
                        total_idle_min = (self._pause_extensions + 1) * self.pause_cooldown_minutes
                        logger.warning(
                            f"▶️  Force-resuming after {self._pause_extensions} extensions "
                            f"({total_idle_min} min total) — "
                            f"clearing stale trade history to break deadlock"
                        )
                        self.recent_trades.clear()
                        # Grant post-resume immunity to prevent immediate re-trigger
                        self._post_resume_immune_until = (
                            datetime.now()
                            + timedelta(minutes=self.post_resume_immunity_minutes)
                        )
                    else:
                        # Extend pause
                        self.pause_until = datetime.now() + timedelta(minutes=self.pause_cooldown_minutes)
                        return False, (
                            f"⏸️  Pause extended ({self._pause_extensions}/{self.max_pause_extensions}) "
                            f"(last 10 trades PnL: {last_10_pnl:.2%} < {self.resume_min_pnl_pct:.1%})"
                        )
            # Resume OK
            logger.info("▶️  Resume trading after pause (conditions improved)")
            self.pause_until = None
            self.pause_reason = None
            self._pause_extensions = 0

        # 1. Check daily loss limit (equity-based)
        if portfolio_risk.daily_pnl_pct <= -self.max_daily_loss_pct:
            return False, f"Daily loss limit reached: {portfolio_risk.daily_pnl_pct:.2f}% <= -{self.max_daily_loss_pct * 100:.1f}%"

        # 2. Check max positions
        if portfolio_risk.open_positions >= self.max_positions:
            return False, f"Max positions reached: {portfolio_risk.open_positions}/{self.max_positions}"

        # 3. Check rolling PnL + win rate (if we have enough history)
        # Skip if within post-resume immunity window (prevents immediate re-trigger after deadlock break)
        is_immune = (
            self._post_resume_immune_until is not None
            and datetime.now() < self._post_resume_immune_until
        )
        if is_immune:
            remaining_immunity = (self._post_resume_immune_until - datetime.now()).total_seconds() / 60
            logger.debug(
                f"🛡️ Post-resume immunity active ({remaining_immunity:.0f} min remaining) — "
                f"skipping rolling PnL/win rate check"
            )
        elif self._post_resume_immune_until is not None and datetime.now() >= self._post_resume_immune_until:
            # Immunity expired, clear it
            logger.info("▶️  Post-resume immunity expired — normal pause checks resume")
            self._post_resume_immune_until = None

        if not is_immune and len(self.recent_trades) >= 10:
            rolling_pnl = sum(t["pnl_pct"] for t in self.recent_trades[-20:]) / len(self.recent_trades[-20:])

            # PnL-driven pause (primary) - trigger cooldown
            if rolling_pnl < self.min_rolling_pnl_pct:
                self._trigger_pause(f"Rolling PnL too low: {rolling_pnl:.2%} < {self.min_rolling_pnl_pct:.1%}")
                return False, f"⏸️  Pause triggered: Rolling PnL {rolling_pnl:.2%} < {self.min_rolling_pnl_pct:.1%} (strategy not working)"

            # Win rate check (secondary, only if PnL also bad)
            if rolling_pnl < 0 and portfolio_risk.win_rate < self.min_win_rate:
                self._trigger_pause(f"Win rate + PnL both negative: WR {portfolio_risk.win_rate:.1%}, PnL {rolling_pnl:.2%}")
                return False, f"⏸️  Pause triggered: WR {portfolio_risk.win_rate:.1%} < {self.min_win_rate:.0%} + PnL {rolling_pnl:.2%} < 0"

        # 4. Check correlation risk (if adding to correlated positions)
        if portfolio_risk.correlation_risk_score > 0.8:
            return False, f"Correlation risk too high: {portfolio_risk.correlation_risk_score:.2f} > 0.80 (too concentrated)"

        # 5. Check confidence threshold
        if confidence < 0.5:
            return False, f"Confidence too low: {confidence:.2f} < 0.50 (weak setup)"

        return True, "OK"

    def calculate_position_size(
        self,
        symbol: str,
        confidence: float,
        account_equity: Decimal,
        base_position_size: Decimal
    ) -> Decimal:
        """
        Calculate position size based on confidence and risk.

        Professional approach: Scale size by edge strength.
        High confidence = larger size, low confidence = smaller size.

        Args:
            symbol: Trading pair
            confidence: 0-1 score (0.5 = neutral, 1.0 = very high confidence)
            account_equity: Total account value
            base_position_size: Base size (e.g., €200)

        Returns:
            Adjusted position size
        """
        # Kelly Criterion inspired: size proportional to edge
        # confidence 0.5 → 0.5x size
        # confidence 0.7 → 1.0x size
        # confidence 0.9 → 1.5x size

        confidence_multiplier = 2 * (confidence - 0.5) + 1.0  # Maps [0.5, 1.0] to [1.0, 2.0]
        confidence_multiplier = max(0.5, min(2.0, confidence_multiplier))  # Clamp to [0.5, 2.0]

        adjusted_size = base_position_size * Decimal(str(confidence_multiplier))

        # Cap at 10% of equity per position (concentration limit)
        max_size = account_equity * Decimal("0.10")
        adjusted_size = min(adjusted_size, max_size)

        logger.info(
            f"📏 Position sizing: {symbol} | "
            f"Confidence: {confidence:.2f} → {confidence_multiplier:.2f}x | "
            f"Base: €{base_position_size:.2f} → Adjusted: €{adjusted_size:.2f}"
        )

        return adjusted_size

    def should_exit_position(
        self,
        position: PositionRisk,
        price_movement_last_hour_atr: float = 0.0  # Movement in last hour (in ATR units)
    ) -> Tuple[str, str]:
        """
        Determine if position should be exited (GRID-AWARE logic).

        Args:
            position: Position risk metrics
            price_movement_last_hour_atr: Price movement in last hour as multiple of ATR (e.g., 0.2 = moved 0.2x ATR)

        Returns:
            (action, reason)
            action: "HOLD" | "STOP_LOSS" | "PROFIT_LOCK" | "TIME_STOP"
        """
        pnl_pct = position.unrealized_pnl_pct

        # 1. ATR-based stop loss (grid-aware) - CLAMPED
        # Dynamic: clamp(2×ATR, min_stop, max_stop)
        # Examples:
        #   BTC ATR 1.2% → 2.4% → clamped to 2.4% (within bounds)
        #   RENDER ATR 3.5% → 7.0% → clamped to 7.0%
        #   Super volatile 10% → clamped to 8% (max)
        atr_based_stop = position.atr_pct * self.atr_stop_multiplier
        effective_stop = max(self.min_stop_pct, min(atr_based_stop, self.max_stop_pct))

        if pnl_pct <= -effective_stop:
            return "STOP_LOSS", f"ATR stop hit: {pnl_pct:.2%} <= -{effective_stop * 100:.1f}% (clamp({self.atr_stop_multiplier}×{position.atr_pct * 100:.1f}% = {atr_based_stop * 100:.1f}%))"

        # 2. Context-aware time-based stop
        # Only exit if: time expired AND losing AND (price stalled OR no recent fills)
        if position.is_time_expired and pnl_pct < 0:
            if self.time_stop_requires_stall:
                is_stalled = price_movement_last_hour_atr < self.price_stall_threshold_atr

                # Check for dead liquidity (no fills recently)
                last_fill_time = self.position_last_fill_time.get(position.symbol)
                minutes_since_fill = 999  # Default: assume no fills
                if last_fill_time:
                    minutes_since_fill = (datetime.now() - last_fill_time).total_seconds() / 60

                no_recent_fills = minutes_since_fill > self.min_minutes_since_last_fill

                if is_stalled or no_recent_fills:
                    reason_parts = [f"{position.time_held_minutes}min", f"PnL {pnl_pct:.2%}"]
                    if is_stalled:
                        reason_parts.append(f"movement {price_movement_last_hour_atr:.2f}×ATR < {self.price_stall_threshold_atr}×")
                    if no_recent_fills:
                        reason_parts.append(f"no fills in {minutes_since_fill:.0f}min > {self.min_minutes_since_last_fill}min")
                    return "TIME_STOP", f"Dead position: {', '.join(reason_parts)}"
                else:
                    logger.debug(f"{position.symbol} - Time expired but healthy (moving: {price_movement_last_hour_atr:.2f}×ATR, fills: {minutes_since_fill:.0f}min ago)")
            else:
                return "TIME_STOP", f"Time limit expired with loss: {position.time_held_minutes}min >= {position.max_hold_time_minutes}min, PnL: {pnl_pct:.2%}"

        # 3. Profit tier logic (HIGH WATERMARK DRAWDOWN)
        # Tiers: [(peak_pct, required_pullback_pct, lock_pct)]
        # Lock triggert op: peak PnL bereikt EN drawdown >= required_pullback

        # Update high water mark (peak PnL tracking)
        current_peak_pnl = self.position_high_water_marks.get(position.symbol, 0.0)
        if pnl_pct > current_peak_pnl:
            self.position_high_water_marks[position.symbol] = pnl_pct
            current_peak_pnl = pnl_pct
            logger.debug(f"📈 {position.symbol} - New peak PnL: {current_peak_pnl:.2%}")

        # Check each tier from highest to lowest
        for peak_pct, required_pullback_pct, lock_pct in sorted(self.profit_lock_tiers, reverse=True):
            if current_peak_pnl >= peak_pct:
                # Peak reached this tier - check if drawdown triggers lock
                drawdown_from_peak = current_peak_pnl - pnl_pct

                if drawdown_from_peak >= required_pullback_pct:
                    # Lock triggered
                    return "PROFIT_LOCK", f"Profit tier lock: Peak {current_peak_pnl:.2%} → Current {pnl_pct:.2%} (drawdown {drawdown_from_peak:.2%} >= {required_pullback_pct:.2%}), locking +{lock_pct * 100:.1f}%"

                # In tier but waiting for drawdown
                return "HOLD", f"In profit tier (peak {current_peak_pnl:.2%}, current {pnl_pct:.2%}), waiting for {required_pullback_pct:.2%} drawdown to lock +{lock_pct * 100:.1f}%"

        return "HOLD", "No exit signal"

    def _trigger_pause(self, reason: str) -> None:
        """Trigger pause cooldown"""
        self.pause_until = datetime.now() + timedelta(minutes=self.pause_cooldown_minutes)
        self.pause_reason = reason
        self._pause_extensions = 0
        logger.warning(f"⏸️  PAUSE TRIGGERED: {reason} (cooldown: {self.pause_cooldown_minutes} min)")

    def record_fill(
        self,
        symbol: str,
        fill_time: Optional[datetime] = None
    ) -> None:
        """Record fill time for dead liquidity detection"""
        self.position_last_fill_time[symbol] = fill_time or datetime.now()

    def record_trade_result(
        self,
        symbol: str,
        pnl_pct: float,
        close_reason: str,
        hold_time_minutes: int
    ) -> None:
        """
        Record trade result for win rate tracking.

        Args:
            symbol: Trading pair
            pnl_pct: Realized P&L percentage
            close_reason: Why position was closed
            hold_time_minutes: How long position was held
        """
        is_win = pnl_pct > 0

        trade_record = {
            "symbol": symbol,
            "pnl_pct": pnl_pct,
            "is_win": is_win,
            "close_reason": close_reason,
            "hold_time_minutes": hold_time_minutes,
            "timestamp": datetime.now()
        }

        self.recent_trades.append(trade_record)

        # Keep only last 20 trades
        if len(self.recent_trades) > 20:
            self.recent_trades.pop(0)

        # Calculate current win rate (exclude breakeven — they don't signal strategy failure)
        decisive = [t for t in self.recent_trades if t["pnl_pct"] != 0]
        wins = sum(1 for t in decisive if t["is_win"])
        win_rate = wins / len(decisive) if decisive else 0.5

        logger.info(
            f"📊 Trade closed: {symbol} | "
            f"PnL: {pnl_pct:+.2f}% | "
            f"Reason: {close_reason} | "
            f"Win Rate: {win_rate:.1%} ({wins}/{len(decisive)} decisive, "
            f"{len(self.recent_trades) - len(decisive)} breakeven excluded)"
        )

        # Cleanup tracking data
        if symbol in self.position_high_water_marks:
            del self.position_high_water_marks[symbol]
        if symbol in self.position_last_fill_time:
            del self.position_last_fill_time[symbol]

    def calculate_dynamic_stop_loss(
        self,
        entry_price: Decimal,
        atr_pct: float,
        confidence: float = 0.7  # Not used for grids, kept for API compatibility
    ) -> Decimal:
        """
        Calculate ATR-based stop loss for GRID bot.

        Grid logic: Stop = max(atr_multiplier × ATR, min_capital_stop)
        No confidence adjustment - grids need consistent risk per volatility regime.

        Args:
            entry_price: Entry price
            atr_pct: ATR as % of price (e.g., 0.03 = 3%)
            confidence: Ignored for grid bots (kept for API compat)

        Returns:
            Stop loss price
        """
        # ATR-based stop distance
        atr_stop_distance = self.atr_stop_multiplier * atr_pct

        # Take wider of: ATR stop or minimum capital stop
        final_stop_distance = max(atr_stop_distance, self.min_capital_stop_pct)

        stop_price = entry_price * Decimal(str(1 - final_stop_distance))

        logger.debug(
            f"Stop calculation (ATR-based): Entry €{entry_price:.4f}, "
            f"ATR: {atr_pct:.2%}, Multiplier: {self.atr_stop_multiplier}x → "
            f"Stop distance: {final_stop_distance:.2%} (ATR={atr_stop_distance:.2%}, min={self.min_capital_stop_pct:.2%}) → "
            f"Stop price: €{stop_price:.4f}"
        )

        return stop_price


def calculate_correlation_risk(
    open_positions: List[str],
    price_correlations: Dict[Tuple[str, str], float]
) -> float:
    """
    Calculate portfolio correlation risk score.

    Returns score 0-1:
    - 0 = fully diversified (no correlations)
    - 1 = highly concentrated (all positions correlated)

    Args:
        open_positions: List of open position symbols
        price_correlations: Dict of pairwise correlations

    Returns:
        Correlation risk score (0-1)
    """
    if len(open_positions) <= 1:
        return 0.0

    # Calculate average correlation between all open positions
    total_correlation = 0.0
    pair_count = 0

    for i, sym1 in enumerate(open_positions):
        for sym2 in open_positions[i + 1:]:
            pair = (sym1, sym2) if sym1 < sym2 else (sym2, sym1)
            correlation = price_correlations.get(pair, 0.0)
            total_correlation += abs(correlation)  # Use absolute (negative correlation also concentrates risk)
            pair_count += 1

    avg_correlation = total_correlation / pair_count if pair_count > 0 else 0.0

    return avg_correlation
