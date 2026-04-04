# Round 3: Risk Management & Safety Review

> **Hoe te gebruiken**: Open een VERSE Claude Opus (of o3) sessie.
> Plak deze volledige inhoud als eerste bericht.
> Alles zit erin — geen extra file uploads nodig.
>
> **Snapshot datum**: 2026-03-08

---

## Prompt

## Round 3: Risk Management & Failure Modes

```
Act as a trading risk engineer who has managed risk systems for
crypto market makers and prop desks. You think in terms of worst-case
scenarios, tail risks, and "what happens when everything goes wrong
at the same time."

## Current risk controls

### Kill Switch (RiskGuardV2)
- Daily loss: 30% (temporarily raised from 10% — PnL tracking bug)
- Weekly loss: 7%, Monthly: 10%
- Absolute daily cap: €100
- Per-coin exposure: 80%, Total exposure: 80%
- Triggers: disable all trading + Telegram critical alert

### Professional Risk Manager
- ATR-based dynamic stops: 2×ATR, clamped [2%, 8%]
- Context-aware time exits (6h, requires stall + no fills > 45min)
- Profit lock tiers (breakeven at +1%, +0.7% at +2%, +1.5% at +3%)
- Rolling 20-trade PnL < −2% → 2h cooldown
- Win rate monitoring (35% acceptable for grid bots)

### Entry Filters
- RSI regime-based (buy/extreme/block per BULL/CHOP/BEAR)
- VWAP deviation + slope guard (dual 5m/15m confirmation)
- ATR volatility band (min/max for grid suitability)
- 5m spike filter (news/chaos detection)
- Parabolic detector (60 min cooldown, SQLite persistent)
- BTC macro filter (dump detection → 60 min cooldown)
- Altcoin breadth (≥30% of [ETH, SOL, BNB, AVAX, LINK] bullish)
- Multi-timeframe buy protection (1h ≥ 0%, 4h ≥ 0%, 24h ≥ −2.5%)

### Position-Level
- Stop-loss: DISABLED (null)
- Emergency exit: −12%, Hard stop: −15%
- Take profit: 5%
- Budget allocator: 0.2% fee buffer + 5% reserve + Decimal("0.01") tolerance

### Futures-Specific (Bitget 3× leverage)
- 6-guard system: hard loss (−8%), max time (1h), grid depth (65%),
  trend break (1h < −1.5%), ATR explosion (>2.2× baseline)
- Liquidation buffer: 20%, stop at 50% distance to liquidation
- Exchange-side TPSL orders (survives bot crashes)

## Known failure history
| Incident | Impact | Root cause |
|----------|--------|------------|
| Stop-loss → immediate re-buy | Lost money twice on same coin | No cooldown after stop-loss |
| 97–99% zero-fill rate | Bot creates grids but they expire unfilled | Grid too tight + filters too restrictive |
| Grid sells below buys | Guaranteed loss per fill | Grid placement logic bug |
| SQLite overflow crash | Bot crash during trading | Timestamp double-multiplication |
| Memory leak (92→625 MB) | Degraded performance over days | Unbounded executor tracking sets |
| NL restriction infinite retry | API rate limit exhaustion | No blacklist on regulatory errors |
| Bitget stuck LIMIT SELL | $71 budget locked, bot cannot trade | No stale order cleanup at startup |
| Kraken WebSocket 112+ errors | Missed fills, stale data, NO_ORDERBOOK_DATA | Kraken-side instability |
| Futures −310% return | −$155 on $50 capital in 9 days | 96% of filled trades hit stop-loss |
| 2/3 bots capital-blocked | Cannot trade at all | Stuck orders + insufficient capital |
| Rotation timeout loops | SONIC-USDT rotates every 3 min without progress | Rotation logic doesn't detect stuck state |
| Risk Manager permanent pause | SUI-USD blocked indefinitely (WR 30%, PnL −0.44%) | No recovery path from pause state |

## What I need you to evaluate

### 1. Catastrophic scenario analysis
What happens under each scenario:
- Flash crash (−30% in 5 minutes)
- Exchange API down for 30 minutes during open positions
- Bot crash and restart with 6 active grids
- Correlated dump (all 6 coins drop simultaneously)
- Partial fills → stuck inventory across multiple coins
- Database corruption during trading

### 2. Risk control gaps
- Stop-loss disabled + emergency exit at −12% = up to 12% loss per coin
  with 6 coins = potential 72% portfolio hit. Is this acceptable?
- Daily loss at 30% is dangerously high — what should it be?
- No correlation risk control on spot (futures has it but disabled)
- No max drawdown from peak (only period-based loss limits)

### 3. Recovery and reconciliation
- On restart: does the bot correctly load open orders, positions,
  and reconcile with exchange state?
- Orphaned position detection exists (Telegram alert only, no auto-recovery)
- Stale order cleanup exists (alert only, no auto-cancel)
- Is this sufficient? What's missing?

### 4. Edge cases in the risk chain
- What if the risk guard errors? Does it fail-open or fail-closed?
- What if PnL tracking is wrong (known bug — daily limit at 30%)?
- What if the trend calculator returns stale data?
- Rate limiting: what if Kraken rate-limits during a risk event?

## Attachments I'll provide
- [ ] RiskGuardV2 source
- [ ] ProfessionalRiskManager source
- [ ] SmartEntryFilter source
- [ ] **Data snapshot** (`.github/data-snapshot-YYYY-MM-DD.md` — error logs + trade history)

## Output format requirements (apply to all findings)

For every major conclusion, provide an evidence table:

| Finding | Evidence (code/config/logs/data) | Impact | Recommendation | Confidence (high/med/low) |
|---------|----------------------------------|--------|----------------|---------------------------|
| ...     | ...                              | ...    | ...            | ...                       |

Separate clearly between:
- **Confirmed findings** — directly proven from code, logs, or data
- **Reasonable inferences** — likely true but not fully proven
- **Unknowns** — requires more data to determine (state what data is needed)

For each recommendation, rate:
- **Impact on PnL** (high / medium / low)
- **Impact on safety** (high / medium / low)
- **Implementation effort** (hours / days / weeks)
- **Urgency** (immediate / next sprint / backlog)

## What to keep
Identify which risk controls are already well-designed and should be
preserved. Not every layer needs replacing — call out what works.

## Capital scaling verdict
Based on the risk review, state the maximum capital you would trust
this bot with given the CURRENT risk controls:
- [ ] Paper trading only
- [ ] Small live capital (< €500)
- [ ] Medium live capital (€500–€5,000)
- [ ] Larger serious capital (€5,000–€50,000)
- [ ] Professional capital (> €50,000)

Explain what risk improvements are needed for each tier upgrade.

## Expected output
1. **Risk score** (1–10) with justification
2. **Catastrophic scenario playbook**: what happens and what should happen
3. **Missing safeguards** ranked by severity (evidence table format)
4. **Recommended risk parameters** (with math, not gut feel)
5. **Recovery gaps** and what to implement
6. **Risk architecture verdict**: is the layered approach sound or fragile?
7. **What to keep**: risk controls that are already well-designed
8. **Capital scaling verdict**: current max safe capital + upgrade path
```


---

## Attachment: risk_guard.py (255 lines)

```python
"""
RiskGuard v2.0 - Kill Switch & Risk Management

Monitors:
- Daily/weekly/monthly loss limits
- Position size limits
- Drawdown protection
- Emergency stop conditions

Automatically disables trading when limits are breached.
"""
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

from risk.pnl_tracker import RealtimePnLTracker

from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage

sys.path.insert(0, str(Path(__file__).parent.parent))


class RiskGuardV2:
    """
    Risk management kill switch with multiple safety layers

    Usage:
        guard = RiskGuardV2(config, pnl_tracker, telegram_alerter, logger)

        if guard.check_limits():
            # Safe to trade
        else:
            # Kill switch activated - stop all trading
    """

    def __init__(
        self,
        cfg: dict,
        pnl_tracker: RealtimePnLTracker,
        alerter,
        logger: Optional[logging.Logger] = None,
        event_logger=None,  # EventLogger instance (optional)
        connector_name: Optional[str] = None  # Exchange name for event filtering
    ):
        """
        Initialize Risk Guard

        Args:
            cfg: Config dict with risk limits
            pnl_tracker: PnL tracker instance
            alerter: Telegram alerter for critical notifications
            logger: Optional logger instance
            event_logger: Optional EventLogger for structured events
            connector_name: Optional exchange name (e.g., 'kraken', 'bitget')
        """
        self.cfg = cfg
        self.pnl = pnl_tracker
        self.alerter = alerter
        self.logger = logger or logging.getLogger(__name__)
        self.event_logger = event_logger  # Can be None if observability disabled
        self.connector_name = connector_name or cfg.get("connector_name")  # Fallback to cfg

        # Risk limits
        self.max_daily_loss_pct = cfg.get("max_daily_loss_pct", 3.0)
        self.max_weekly_loss_pct = cfg.get("max_weekly_loss_pct", 8.0)
        self.max_monthly_loss_pct = cfg.get("max_monthly_loss_pct", 12.0)
        self.max_daily_loss_eur = cfg.get("max_daily_loss_eur", None)

        # State
        self.trading_enabled = True
        self.kill_reason = None

        self.logger.info("=" * 80)
        self.logger.info("🛡️  RiskGuard v2.0 initialized")
        self.logger.info(f"   Max daily loss: {self.max_daily_loss_pct}%")
        self.logger.info(f"   Max weekly loss: {self.max_weekly_loss_pct}%")
        self.logger.info(f"   Max monthly loss: {self.max_monthly_loss_pct}%")
        if self.max_daily_loss_eur:
            self.logger.info(f"   Max daily loss (abs): €{self.max_daily_loss_eur}")
        self.logger.info("=" * 80)

    def check_limits(self) -> bool:
        """
        Check all risk limits

        Returns:
            True if trading is allowed, False if kill switch activated
        """
        if not self.trading_enabled:
            return False

        # 1) Daily loss percentage check
        daily_pct = self.pnl.daily_pnl_pct()
        if daily_pct <= -self.max_daily_loss_pct:
            self._kill(f"Daily loss {daily_pct:.2f}% ≤ -{self.max_daily_loss_pct}%")
            return False

        # 2) Daily loss absolute check
        if self.max_daily_loss_eur:
            daily_loss_eur = self.pnl.daily_pnl()
            if daily_loss_eur <= -Decimal(str(self.max_daily_loss_eur)):
                self._kill(f"Daily loss €{daily_loss_eur:.2f} ≤ -€{self.max_daily_loss_eur}")
                return False

        # 3) Weekly loss check
        weekly_pct = self.pnl.weekly_pnl_pct()
        if weekly_pct <= -self.max_weekly_loss_pct:
            self._kill(f"Weekly loss {weekly_pct:.2f}% ≤ -{self.max_weekly_loss_pct}%")
            return False

        # 4) Monthly loss check
        monthly_pct = self.pnl.monthly_pnl_pct()
        if monthly_pct <= -self.max_monthly_loss_pct:
            self._kill(f"Monthly loss {monthly_pct:.2f}% ≤ -{self.max_monthly_loss_pct}%")
            return False

        return True

    def _kill(self, reason: str):
        """
        Activate kill switch

        Args:
            reason: Reason for activation
        """
        self.trading_enabled = False
        self.kill_reason = reason

        msg = f"🚨 KILL SWITCH ACTIVATED: {reason}"
        self.logger.critical(msg)
        self.alerter.critical(msg)

        # Log P&L summary
        summary = self.pnl.get_summary()
        self.logger.critical(f"   Equity: €{summary['equity']:.2f}")
        self.logger.critical(f"   Realized P&L: €{summary['realized_pnl']:+.2f}")
        self.logger.critical(f"   Unrealized P&L: €{summary['unrealized_pnl']:+.2f}")
        self.logger.critical(f"   Fees paid: €{summary['fees_paid']:.2f}")

    def can_open_position(
        self,
        symbol: str,
        size_eur: Decimal,
        correlation_id: Optional[str] = None
    ) -> tuple[bool, str]:
        """
        Check if opening a new position is allowed

        Args:
            symbol: Trading pair
            size_eur: Position size in EUR
            correlation_id: Optional correlation ID for event tracking

        Returns:
            Tuple of (allowed, reason)
        """
        if not self.trading_enabled:
            reason = f"Kill switch active: {self.kill_reason}"
            self._emit_risk_denial(
                symbol=symbol,
                reason_code=ReasonCode.DAILY_LOSS_LIMIT,  # Kill switch from daily loss
                reason_msg=reason,
                correlation_id=correlation_id,
                metadata={"size_eur": float(size_eur)}
            )
            return False, reason

        # Check max exposure per coin
        max_per_coin_pct = self.cfg.get("max_exposure_per_coin_pct", 40)
        max_per_coin_eur = self.pnl.starting_balance * Decimal(str(max_per_coin_pct)) / 100

        if size_eur > max_per_coin_eur:
            reason = f"Position size €{size_eur:.2f} > max €{max_per_coin_eur:.2f} ({max_per_coin_pct}%)"
            self._emit_risk_denial(
                symbol=symbol,
                reason_code=ReasonCode.EXPOSURE_LIMIT,
                reason_msg=reason,
                correlation_id=correlation_id,
                metadata={
                    "size_eur": float(size_eur),
                    "max_per_coin_eur": float(max_per_coin_eur),
                    "max_per_coin_pct": max_per_coin_pct,
                    "exposure_type": "per_coin"
                }
            )
            return False, reason

        # Check total exposure
        max_total_pct = self.cfg.get("max_total_exposure_pct", 80)
        max_total_eur = self.pnl.starting_balance * Decimal(str(max_total_pct)) / 100

        total_exposure = sum(p.notional_eur for p in self.pnl.positions.values())
        if total_exposure + size_eur > max_total_eur:
            reason = f"Total exposure €{total_exposure + size_eur:.2f} > max €{max_total_eur:.2f} ({max_total_pct}%)"
            self._emit_risk_denial(
                symbol=symbol,
                reason_code=ReasonCode.EXPOSURE_LIMIT,
                reason_msg=reason,
                correlation_id=correlation_id,
                metadata={
                    "size_eur": float(size_eur),
                    "current_total_exposure": float(total_exposure),
                    "max_total_eur": float(max_total_eur),
                    "max_total_pct": max_total_pct,
                    "exposure_type": "total"
                }
            )
            return False, reason

        return True, "Position allowed"

    def reset_kill_switch(self):
        """Manually reset kill switch (use with caution!)"""
        self.trading_enabled = True
        self.kill_reason = None
        self.logger.warning("⚠️  Kill switch MANUALLY RESET - trading re-enabled")
        self.alerter.warning("Kill switch manually reset - trading re-enabled")

    def _emit_risk_denial(
        self,
        symbol: str,
        reason_code: ReasonCode,
        reason_msg: str,
        correlation_id: Optional[str] = None,
        metadata: Optional[dict] = None
    ):
        """
        Emit gate_denied event for risk rejection.

        Args:
            symbol: Trading pair
            reason_code: ReasonCode enum value
            reason_msg: Human-readable reason
            correlation_id: Optional correlation ID
            metadata: Optional metadata dict
        """
        if not self.event_logger or not self.event_logger.enabled:
            return

        # Merge connector into metadata for filtering support
        final_metadata = {**(metadata or {})}
        if self.connector_name:
            final_metadata["connector"] = self.connector_name

        self.event_logger.emit_gate_denied(
            correlation_id=correlation_id,
            symbol=symbol,
            stage=Stage.RISK,
            reason_code=reason_code,
            reason_msg=reason_msg,
            metadata=final_metadata,
            connector=self.connector_name
        )

```

## Attachment: professional_risk_manager.py (479 lines)

```python
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
        self.max_correlation = max_correlation

        # Tracking
        self.daily_start_equity: Optional[Decimal] = None
        self.daily_reset_time: Optional[datetime] = None
        self.recent_trades: List[Dict] = []  # Last 20 trades for win rate
        self.position_high_water_marks: Dict[str, Decimal] = {}  # For profit tiers (peak tracking)
        self.position_last_fill_time: Dict[str, datetime] = {}  # For dead liquidity detection
        self.pause_until: Optional[datetime] = None  # Cooldown tracking
        self.pause_reason: Optional[str] = None

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
                    # Extend pause
                    self.pause_until = datetime.now() + timedelta(minutes=self.pause_cooldown_minutes)
                    return False, f"⏸️  Pause extended (last 10 trades PnL: {last_10_pnl:.2%} < {self.resume_min_pnl_pct:.1%})"
            # Resume OK
            logger.info("▶️  Resume trading after pause (conditions improved)")
            self.pause_until = None
            self.pause_reason = None

        # 1. Check daily loss limit (equity-based)
        if portfolio_risk.daily_pnl_pct <= -self.max_daily_loss_pct:
            return False, f"Daily loss limit reached: {portfolio_risk.daily_pnl_pct:.2f}% <= -{self.max_daily_loss_pct * 100:.1f}%"

        # 2. Check max positions
        if portfolio_risk.open_positions >= self.max_positions:
            return False, f"Max positions reached: {portfolio_risk.open_positions}/{self.max_positions}"

        # 3. Check rolling PnL + win rate (if we have enough history)
        if len(self.recent_trades) >= 10:
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

        # Calculate current win rate
        wins = sum(1 for t in self.recent_trades if t["is_win"])
        win_rate = wins / len(self.recent_trades) if self.recent_trades else 0.5

        logger.info(
            f"📊 Trade closed: {symbol} | "
            f"PnL: {pnl_pct:+.2f}% | "
            f"Reason: {close_reason} | "
            f"Win Rate: {win_rate:.1%} ({wins}/{len(self.recent_trades)})"
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

```

## Attachment: smart_entry_filter.py (829 lines)

```python
"""
SmartEntryFilter - ML-lite Entry Decision System

Besluit of een grid entry toegestaan is op basis van:
- RSI regime (overbought/oversold)
- VWAP mean-reversion potential
- Wick analysis (market structure)
- ATR-based volatility regime
- News/chaos detection (5m spikes)
- Trend acceleration (falling knife / blow-off top)
- 24h trend sanity checks
- VWAP Slope Guard (EPIC v3.4 Stories 2+9): momentum health detection
- Parabolic Detector (EPIC v3.4 Stories 3+10): blow-off top cooldowns with persistence
"""

import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, Optional, Tuple

from multi_coin_grid_pro.filters.parabolic_blacklist import ParabolicBlacklist

logger = logging.getLogger(__name__)


@dataclass
class CandleIndicators:
    """Technical indicators berekend van 5m candles"""
    price: Decimal              # Current price
    rsi_14: float               # RSI(14) - 0-100
    vwap: Decimal               # Session VWAP
    atr_pct: float              # ATR(14) / price * 100
    wick_ratio: float           # (high - close) / max((close - low), tiny)
    trend_1h_pct: float         # % change over last 1h
    trend_4h_pct: float         # % change over last 4h
    trend_24h_pct: float        # % change over last 24h
    change_5m_pct: float        # Last 5m candle % change


@dataclass
class SmartEntryConfig:
    """Configuration for SmartEntryFilter"""

    # RSI Regime
    rsi_buy_max: float = 60.0          # Koop alleen onder deze RSI
    rsi_extreme_low: float = 25.0      # Extreme dip - mogelijk falling knife
    rsi_block_min: float = 70.0        # Nooit kopen boven deze RSI (overbought)

    # VWAP Mean-Reversion (AANGEPAST: ruimer voor trends)
    vwap_max_deviation_pct: float = 3.0  # Max |price-vwap| in % (was 1.2, nu 3.0)

    # Wick Analysis (AANGEPAST: minder strict)
    min_wick_ratio: float = 0.25      # >= 0.25 = voldoende wicks (balanced threshold)

    # Volatility Regime via ATR
    max_atr_pct_for_grid: float = 6.0  # >6% ATR = te bruut, grid uit
    min_atr_pct_for_grid: float = 0.5  # <0.5% ATR = te dood, skip

    # News/Chaos Filter via 5m candle
    max_5m_spike_pct: float = 2.5     # Geen nieuwe buys als 5m move > 2.5%

    # Trend Acceleration (1h vs 4h)
    max_down_accel_pct: float = -1.0  # Als 1h-4h < -1% → falling knife
    max_up_accel_pct: float = 1.5     # Als 1h-4h > 1.5% → mogelijk blow-off top

    # 24h Trend Sanity Check
    max_trend_24h_pct: float = 8.0    # > +8% dagtrend → beter niet instappen
    min_trend_24h_pct: float = -12.0  # < -12% dagtrend → capitulatie risk

    # Slippage Protection (NEW - Phase 2)
    max_entry_spread_pct: float = 0.5  # Reject if bid-ask spread > 0.5%
    slippage_check_enabled: bool = True  # Enable spread checking

    # Order Book Depth (NEW - Phase 2)
    min_depth_multiplier: float = 3.0   # Need 3x order size on each side
    depth_check_enabled: bool = True    # Enable depth validation

    # VWAP Slope Guard (NEW - EPIC v3.4 Stories 2 + 9)
    vwap_slope_guard_enabled: bool = False  # Enable VWAP slope momentum guard
    vwap_slope_guard_shadow_mode: bool = True  # True = shadow mode (log only), False = live blocking
    vwap_slope_dual_confirmation: bool = True  # Story 9: Require BOTH 5m AND 15m slopes flat
    vwap_slope_deviation_high_pct: float = 15.0  # Baseline: check slope if dev >= 15%
    vwap_slope_min_pct_5m: float = 0.05      # Story 9: Baseline 5m slope threshold
    vwap_slope_min_pct_15m: float = 0.10     # Baseline: reject if 15m slope <= 0.10%
    vwap_slope_log_details: bool = True      # Log detailed guard decisions

    # Parabolic Detector (NEW - EPIC v3.4 Stories 3 + 10)
    parabolic_detector_enabled: bool = False  # Enable parabolic blow-off detector
    parabolic_detector_shadow_mode: bool = True  # True = shadow mode (log only), False = live blocking
    parabolic_cooldown_persist: bool = True   # Story 10: Persist cooldowns to SQLite
    parabolic_accel_5m_min_pct: float = 2.5   # Baseline: min 5m acceleration
    parabolic_accel_15m_min_pct: float = 6.0  # Baseline: min 15m acceleration
    parabolic_vwap_dev_min_pct: float = 18.0  # Baseline: min VWAP deviation
    parabolic_cooldown_minutes: int = 30      # Cooldown duration in minutes
    parabolic_blacklist_scope: str = "session"  # "session" or "persistent"
    parabolic_log_details: bool = True        # Log detailed detector decisions

    # Momentum Thresholds (NEW - EPIC v3.4 Story 5)
    momentum_thresholds: dict = None          # Regime-aware momentum thresholds (baseline + BULL/CHOP/BEAR overrides)

    # Market Exhaustion Warning (NEW - EPIC v3.4 Story 11)
    market_exhaustion_enabled: bool = False   # Enable market-wide exhaustion detection
    market_exhaustion_threshold_pct: float = 0.70  # Trigger if >= 70% of sample is parabolic
    market_exhaustion_sample_size: int = 10   # Evaluate top N candidates
    market_exhaustion_cooldown_min: int = 30  # Alert rate limit in minutes
    market_exhaustion_telegram: bool = False  # Send Telegram alerts (backward compat with config.prod.yaml)
    market_exhaustion_actions: list = None    # Actions: ['log', 'telegram'] (optional alternative format)

    @property
    def vwap_slope_guard_mode(self) -> str:
        """Convert boolean shadow_mode to string mode for backward compatibility"""
        return "shadow" if self.vwap_slope_guard_shadow_mode else "live"

    @property
    def parabolic_detector_mode(self) -> str:
        """Convert boolean shadow_mode to string mode for backward compatibility"""
        return "shadow" if self.parabolic_detector_shadow_mode else "live"

    @property
    def parabolic_cooldown_sec(self) -> int:
        """Convert minutes to seconds for backward compatibility"""
        return self.parabolic_cooldown_minutes * 60


class SmartEntryFilter:
    """
    Intelligent entry filter voor grid trading.
    Voorkomt entries tijdens:
    - Overbought/oversold extremes
    - News/chaos events
    - Falling knives / blow-off tops
    - Dead markets
    - Wide spreads (slippage protection)
    - Thin order books (depth protection)
    """

    def __init__(self, config: SmartEntryConfig = None, exchange=None, connector_name: str = None, event_logger=None, cooldown_store=None):
        self.config = config or SmartEntryConfig()
        self.exchange = exchange  # For order book queries
        self.connector_name = connector_name  # Store connector name for API calls
        self.parabolic_blacklist = ParabolicBlacklist()  # Session-scoped cooldown tracking
        self.cooldown_store = cooldown_store  # Story 10: Optional SQLite persistence
        self.event_logger = event_logger  # EPIC v3.4 Story 6: Structured event logging
        self._last_event_time = {}  # {symbol: timestamp} for rate limiting
        self._event_cooldown_sec = 60  # Max 1 event per symbol per 60 seconds

        # Story 10: Load active cooldowns from persistence if available
        if self.cooldown_store and self.connector_name:
            active_cooldowns = self.cooldown_store.load_active(connector=self.connector_name)
            if active_cooldowns:
                logger.info(f"Loaded {len(active_cooldowns)} active cooldowns from persistence")
                # Restore to in-memory blacklist
                for symbol, expires_at in active_cooldowns.items():
                    remaining = int(expires_at - time.time())
                    if remaining > 0:
                        self.parabolic_blacklist.blacklist[symbol] = expires_at

        logger.info("🧠 SmartEntryFilter initialized")
        logger.info(
            f"   RSI range: {self.config.rsi_extreme_low}-{self.config.rsi_buy_max} (block >{self.config.rsi_block_min})")  # noqa: E501
        logger.info(f"   ATR range: {self.config.min_atr_pct_for_grid}%-{self.config.max_atr_pct_for_grid}%")
        logger.info(f"   5m spike max: {self.config.max_5m_spike_pct}%")
        logger.info(f"   Trend accel: {self.config.max_down_accel_pct}% to +{self.config.max_up_accel_pct}%")
        logger.info(
            f"   Slippage protection: max spread {
                self.config.max_entry_spread_pct}% (enabled={
                self.config.slippage_check_enabled})")
        logger.info(
            f"   Depth protection: {
                self.config.min_depth_multiplier}x multiplier (enabled={
                self.config.depth_check_enabled})")
        if event_logger:
            logger.info("   📝 Entry guard event logging: ENABLED")

    def check_order_book_depth(self, symbol: str, order_size_eur: float) -> Tuple[bool, str]:
        """
        Check if order book has sufficient depth for order.

        Args:
            symbol: Trading pair (e.g., "SUI-EUR")
            order_size_eur: Order size in EUR

        Returns:
            (passes_check: bool, reason: str)
        """
        if not self.config.depth_check_enabled or not self.exchange:
            return True, "Depth check disabled or no exchange"

        try:
            required_depth = order_size_eur * self.config.min_depth_multiplier

            # Get current order book from exchange using the new API
            order_book = self.exchange.get_order_book(self.connector_name, symbol)

            if not order_book or 'bids' not in order_book or 'asks' not in order_book:
                logger.warning(f"[DEPTH] {symbol} - No order book data available")
                return True, "No order book data (skipping check)"

            # Sum BID side (people willing to buy from us = we sell)
            bid_total_eur = 0.0
            for bid_price, bid_volume in order_book['bids']:
                bid_total_eur += float(bid_price) * float(bid_volume)
                if bid_total_eur >= required_depth:
                    break

            # Sum ASK side (people willing to sell to us = we buy)
            ask_total_eur = 0.0
            for ask_price, ask_volume in order_book['asks']:
                ask_total_eur += float(ask_price) * float(ask_volume)
                if ask_total_eur >= required_depth:
                    break

            has_bid_depth = bid_total_eur >= required_depth
            has_ask_depth = ask_total_eur >= required_depth

            if not has_bid_depth or not has_ask_depth:
                return False, (
                    f"Insufficient liquidity: BID {bid_total_eur:.0f}/{required_depth:.0f} EUR, "
                    f"ASK {ask_total_eur:.0f}/{required_depth:.0f} EUR (need {self.config.min_depth_multiplier}x)"
                )

            logger.debug(
                f"[DEPTH] {symbol} ✓ BID: {bid_total_eur:.0f}/{required_depth:.0f} EUR, "
                f"ASK: {ask_total_eur:.0f}/{required_depth:.0f} EUR"
            )
            return True, f"Sufficient depth ({self.config.min_depth_multiplier}x confirmed)"

        except Exception as e:
            logger.warning(f"[DEPTH] {symbol} - Error checking depth: {e}")
            return True, f"Depth check failed (allowing entry): {e}"

    def check_spread(self, symbol: str, bid_price: Decimal, ask_price: Decimal) -> Tuple[bool, str]:
        """
        Check if bid-ask spread is acceptable.

        Args:
            symbol: Trading pair
            bid_price: Current bid price
            ask_price: Current ask price

        Returns:
            (passes_check: bool, reason: str)
        """
        if not self.config.slippage_check_enabled:
            return True, "Spread check disabled"

        if bid_price <= 0 or ask_price <= 0:
            logger.warning(f"[SPREAD] {symbol} - Invalid prices: bid={bid_price}, ask={ask_price}")
            return True, "Invalid prices (skipping check)"

        mid_price = (bid_price + ask_price) / 2
        spread_pct = float((ask_price - bid_price) / mid_price * 100)

        if spread_pct > self.config.max_entry_spread_pct:
            return False, (
                f"Spread too wide: {spread_pct:.3f}% > {self.config.max_entry_spread_pct}% "
                f"(bid={float(bid_price):.4f}, ask={float(ask_price):.4f})"
            )

        logger.debug(f"[SPREAD] {symbol} ✓ {spread_pct:.3f}% (< {self.config.max_entry_spread_pct}%)")
        return True, f"Spread OK: {spread_pct:.3f}%"

    def _emit_entry_guard_event(
        self,
        symbol: str,
        decision: str,
        regime: str,
        reject_reason: Optional[str] = None,
        metrics: Optional[Dict[str, Optional[float]]] = None,
        thresholds: Optional[Dict[str, float]] = None,
        cooldown_remaining_sec: Optional[int] = None,
        mode: str = "live",
        force: bool = False
    ) -> None:
        """
        Emit entry guard evaluation event with rate limiting (Story 6).

        Args:
            symbol: Trading pair
            decision: "ACCEPTED" or "REJECTED"
            regime: Market regime (BULL/CHOP/BEAR/NEUTRAL)
            reject_reason: Rejection reason code (if REJECTED)
            metrics: Momentum metrics
            thresholds: Thresholds used
            cooldown_remaining_sec: Cooldown remaining (if applicable)
            mode: "shadow" or "live"
            force: Force emit (ignore rate limit)
        """
        if not self.event_logger:
            return

        import time
        now = time.time()

        # Rate limiting: max 1 event per symbol per 60 seconds
        if not force:
            last_event = self._last_event_time.get(symbol, 0)
            if now - last_event < self._event_cooldown_sec:
                return  # Skip event (rate limited)

        self._last_event_time[symbol] = now

        # Emit event
        self.event_logger.emit_entry_guard_evaluation(
            connector=self.connector_name or "unknown",
            symbol=symbol,
            decision=decision,
            regime=regime,
            reject_reason=reject_reason,
            metrics=metrics or {},
            thresholds=thresholds or {},
            cooldown_remaining_sec=cooldown_remaining_sec,
            mode=mode
        )

    def _resolve_threshold(
        self,
        symbol: str,
        threshold_key: str,
        regime: str
    ) -> float:
        """
        Resolve threshold with precedence (Story 5 + Story 9).

        Precedence order:
        1. Coin profile override (if exists)
        2. Regime-specific value (BULL/CHOP/BEAR)
        3. Baseline default

        Args:
            symbol: Trading pair symbol
            threshold_key: Key to look up (e.g., "slope_min_pct_5m", "deviation_high_pct")
            regime: Market regime (BULL/CHOP/BEAR/NEUTRAL)

        Returns:
            Resolved threshold value
        """
        # Safety floors (cannot be overridden by coin profiles)
        SAFETY_FLOORS = {
            "slope_min_pct_5m": 0.00,     # Allow completely flat in lenient configs
            "slope_min_pct_15m": 0.01,
            "accel_5m_min_pct": 1.0,
            "accel_15m_min_pct": 3.0,
            "vwap_dev_min_pct": 8.0,
            "deviation_high_pct": 10.0,
        }

        # Try getting from momentum_thresholds config
        if self.config.momentum_thresholds:
            thresholds = self.config.momentum_thresholds

            # 1. Check coin profile (if exists) - TODO: implement per-symbol overrides
            # coin_profile = thresholds.get("coin_profiles", {}).get(symbol, {})
            # if threshold_key in coin_profile:
            #     value = coin_profile[threshold_key]
            #     floor = SAFETY_FLOORS.get(threshold_key)
            #     if floor and value < floor:
            #         return floor
            #     return value

            # 2. Check regime-specific
            if regime in ["BULL", "CHOP", "BEAR"]:
                regime_config = thresholds.get("regimes", {}).get(regime, {})
                if threshold_key in regime_config:
                    return regime_config[threshold_key]

            # 3. Check baseline
            baseline = thresholds.get("baseline", {})
            if threshold_key in baseline:
                return baseline[threshold_key]

        # Fallback to flat config attributes (backward compatibility)
        if threshold_key == "slope_min_pct_5m":
            return getattr(self.config, "vwap_slope_min_pct_5m", 0.05)
        elif threshold_key == "slope_min_pct_15m":
            return getattr(self.config, "vwap_slope_min_pct_15m", 0.10)
        elif threshold_key == "deviation_high_pct":
            return getattr(self.config, "vwap_slope_deviation_high_pct", 15.0)

        # Last resort: return safety floor or 0
        return SAFETY_FLOORS.get(threshold_key, 0.0)

    def allows_entry(
        self,
        symbol: str,
        ind: CandleIndicators,
        order_size_eur: float = None,
        bid_price: Decimal = None,
        ask_price: Decimal = None,
        vwap_slope_5m_pct: Optional[float] = None,  # Story 9: 5m slope for dual-window confirmation
        vwap_slope_15m_pct: Optional[float] = None,
        accel_5m_pct: Optional[float] = None,
        accel_15m_pct: Optional[float] = None,
        regime: str = "NEUTRAL",
    ) -> Tuple[bool, str]:
        """
        Besluit of entry toegestaan is.

        Args:
            symbol: Trading pair
            ind: Candle indicators
            order_size_eur: Order size for depth checking (optional)
            bid_price: Current bid for spread checking (optional)
            ask_price: Current ask for spread checking (optional)
            vwap_slope_5m_pct: VWAP slope over 5m (optional, for EPIC v3.4 Story 9)
            vwap_slope_15m_pct: VWAP slope over 15m (optional, for EPIC v3.4 Story 2)
            accel_5m_pct: Price acceleration over 5m (optional, for EPIC v3.4 Story 3)
            accel_15m_pct: Price acceleration over 15m (optional, for EPIC v3.4 Story 3)
            regime: Market regime (BULL/CHOP/BEAR, optional, for EPIC v3.4)

        Returns:
            (allowed: bool, reason: str)
        """

        # 0A) Slippage Protection - Check spread
        if bid_price and ask_price:
            spread_ok, spread_reason = self.check_spread(symbol, bid_price, ask_price)
            if not spread_ok:
                return False, f"{symbol}: NO BUY – {spread_reason}"

        # 0B) Order Book Depth Check
        if order_size_eur:
            depth_ok, depth_reason = self.check_order_book_depth(symbol, order_size_eur)
            if not depth_ok:
                return False, f"{symbol}: NO BUY – {depth_reason}"

        # 1) RSI Regime Check
        if ind.rsi_14 >= self.config.rsi_block_min:
            return False, f"{symbol}: BLOCKED – RSI too high ({ind.rsi_14:.1f} >= {self.config.rsi_block_min})"

        if ind.rsi_14 > self.config.rsi_buy_max:
            return False, f"{symbol}: NO BUY – RSI={ind.rsi_14:.1f} > buy_max={self.config.rsi_buy_max}"

        if ind.rsi_14 < self.config.rsi_extreme_low:
            # Extreme oversold - mogelijk falling knife
            return False, f"{symbol}: NO BUY – RSI={ind.rsi_14:.1f} (extreme oversold, falling knife risk)"

        # 2) VWAP Mean-Reversion Check
        vwap_dev_pct = 0.0
        if ind.vwap > 0:
            vwap_dev_pct = float((ind.price - ind.vwap) / ind.vwap * 100)
            if abs(vwap_dev_pct) > self.config.vwap_max_deviation_pct:
                return False, (
                    f"{symbol}: NO BUY – VWAP dev {vwap_dev_pct:.2f}% > "
                    f"{self.config.vwap_max_deviation_pct}% (too far from mean)"
                )

        # 2A) VWAP Slope Guard - Blow-off Top Detection (EPIC v3.4 Stories 2 + 9)
        if self.config.vwap_slope_guard_enabled:
            slope_ok, slope_reason = self.check_vwap_slope_guard(
                symbol=symbol,
                vwap_dev_pct=vwap_dev_pct,
                vwap_slope_5m_pct=vwap_slope_5m_pct,  # Story 9: Added 5m slope
                vwap_slope_15m_pct=vwap_slope_15m_pct,
                regime=regime
            )
            if not slope_ok:
                return False, f"{symbol}: NO BUY – {slope_reason}"

        # 2B) Parabolic Detector - Extreme Blow-off Top + Cooldown (EPIC v3.4)
        if self.config.parabolic_detector_enabled:
            parabolic_ok, parabolic_reason = self.check_parabolic_detector(
                symbol=symbol,
                vwap_dev_pct=vwap_dev_pct,
                accel_5m_pct=accel_5m_pct,
                accel_15m_pct=accel_15m_pct,
                regime=regime
            )
            if not parabolic_ok:
                return False, f"{symbol}: NO BUY – {parabolic_reason}"

        # 3) Wick Ratio Check - market structure
        # SMART LOGIC: wick_ratio 0.00 OK als RSI niet overbought (<65)
        # Perfect bullish candles zijn OK als de coin niet al te heet is
        if ind.wick_ratio < self.config.min_wick_ratio:
            # Exception: wick_ratio 0.00 toegestaan als RSI < 65 (nog niet overbought)
            if ind.wick_ratio == 0.00 and ind.rsi_14 < 65.0:
                logger.info(f"🎯 {symbol}: wick_ratio 0.00 accepted (RSI={ind.rsi_14:.1f} < 65, perfect bullish candle)")
            else:
                return False, (
                    f"{symbol}: NO BUY – wick_ratio {ind.wick_ratio:.2f} < "
                    f"{self.config.min_wick_ratio} (poor structure)"
                )

        # 4) Volatility Regime via ATR
        if ind.atr_pct < self.config.min_atr_pct_for_grid:
            return False, (
                f"{symbol}: NO BUY – ATR too low ({ind.atr_pct:.2f}%) → dead market"
            )

        if ind.atr_pct > self.config.max_atr_pct_for_grid:
            return False, (
                f"{symbol}: NO BUY – ATR too high ({ind.atr_pct:.2f}%) → news/chaos"
            )

        # 5) News/Chaos Filter via 5m candle spike
        if abs(ind.change_5m_pct) > self.config.max_5m_spike_pct:
            return False, (
                f"{symbol}: NO BUY – 5m move {ind.change_5m_pct:.2f}% > "
                f"{self.config.max_5m_spike_pct}% (likely news/impulse)"
            )

        # 6) Trend Acceleration Check (1h vs 4h)
        accel = ind.trend_1h_pct - ind.trend_4h_pct
        if accel < self.config.max_down_accel_pct:
            return False, (
                f"{symbol}: NO BUY – downside acceleration {accel:.2f}% "
                f"(1h << 4h, falling knife)"
            )

        if accel > self.config.max_up_accel_pct:
            return False, (
                f"{symbol}: NO BUY – upside acceleration {accel:.2f}% "
                f"(1h >> 4h, blow-off top risk)"
            )

        # 7) 24h Trend Sanity Check
        if ind.trend_24h_pct > self.config.max_trend_24h_pct:
            return False, (
                f"{symbol}: NO BUY – 24h trend too high ({ind.trend_24h_pct:.2f}%) "
                f"(extended run)"
            )

        if ind.trend_24h_pct < self.config.min_trend_24h_pct:
            return False, (
                f"{symbol}: NO BUY – 24h trend too low ({ind.trend_24h_pct:.2f}%) "
                f"(possible capitulation)"
            )

        # ✅ ALL CHECKS PASSED
        return True, (
            f"{symbol}: ✅ BUY ALLOWED – RSI={ind.rsi_14:.1f}, ATR={ind.atr_pct:.2f}%, "
            f"accel={accel:.2f}%, 24h={ind.trend_24h_pct:.2f}%"
        )

    def get_filter_stats(self, symbol: str, ind: CandleIndicators) -> dict:
        """
        Returns detailed stats voor debugging/monitoring.
        """
        accel = ind.trend_1h_pct - ind.trend_4h_pct
        vwap_dev = float((ind.price - ind.vwap) / ind.vwap * 100) if ind.vwap > 0 else 0.0

        return {
            "symbol": symbol,
            "rsi": ind.rsi_14,
            "atr_pct": ind.atr_pct,
            "vwap_dev_pct": vwap_dev,
            "wick_ratio": ind.wick_ratio,
            "change_5m_pct": ind.change_5m_pct,
            "acceleration": accel,
            "trend_1h_pct": ind.trend_1h_pct,
            "trend_4h_pct": ind.trend_4h_pct,
            "trend_24h_pct": ind.trend_24h_pct,
            "price": float(ind.price),
            "vwap": float(ind.vwap),
        }

    def check_vwap_slope_guard(
        self,
        symbol: str,
        vwap_dev_pct: float,
        vwap_slope_5m_pct: Optional[float],
        vwap_slope_15m_pct: Optional[float],
        regime: str = "NEUTRAL"
    ) -> Tuple[bool, Optional[str]]:
        """
        VWAP Slope Guard - Detects blow-off tops.

        Story 9: Dual-window confirmation - requires BOTH 5m AND 15m slopes flat
        to reduce false positives during healthy consolidations.

        Rejects entry when:
        1. Price is far above VWAP (deviation >= threshold)
        2. AND (single-window mode): VWAP 15m slope is flat/negative
           OR (dual-window mode): BOTH 5m AND 15m slopes are flat/negative

        Returns:
            (allowed, reject_reason) - (True, None) if passed, (False, reason) if rejected
        """
        if not self.config.vwap_slope_guard_enabled:
            return True, None

        # Only check if deviation is positive (price above VWAP)
        if vwap_dev_pct <= 0:
            return True, None

        # Check if deviation exceeds threshold (price too far above VWAP)
        deviation_threshold = self._resolve_threshold(symbol, "deviation_high_pct", regime)
        if vwap_dev_pct < deviation_threshold:
            # Not far enough above VWAP to check slope
            return True, None

        # Dual-window confirmation mode (Story 9)
        if self.config.vwap_slope_dual_confirmation:
            # Check both slopes available
            if vwap_slope_5m_pct is None or vwap_slope_15m_pct is None:
                if self.config.vwap_slope_log_details:
                    logger.debug(
                        f"[{self.config.vwap_slope_guard_mode.upper()}] {symbol}: "
                        f"VWAP slope data unavailable (5m={vwap_slope_5m_pct}, 15m={vwap_slope_15m_pct})"
                    )
                return True, None  # Don't reject if we can't calculate slopes

            # Get thresholds for both windows
            slope_threshold_5m = self._resolve_threshold(symbol, "slope_min_pct_5m", regime)
            slope_threshold_15m = self._resolve_threshold(symbol, "slope_min_pct_15m", regime)

            # Check if BOTH slopes are flat/negative
            slope_5m_flat = vwap_slope_5m_pct <= slope_threshold_5m
            slope_15m_flat = vwap_slope_15m_pct <= slope_threshold_15m

            if slope_5m_flat and slope_15m_flat:
                # BLOW-OFF TOP DETECTED: Both windows show dying momentum
                reason = (
                    f"VWAP_SLOPE_DUAL_FLAT_WHILE_DEVIATION_HIGH "
                    f"(dev={vwap_dev_pct:.1f}%, 5m={vwap_slope_5m_pct:.2f}%, 15m={vwap_slope_15m_pct:.2f}%, "
                    f"thresholds: dev>={deviation_threshold}%, 5m<={slope_threshold_5m}%, 15m<={slope_threshold_15m}%)"
                )

                # EPIC v3.4 Story 6: Emit structured event
                self._emit_entry_guard_event(
                    symbol=symbol,
                    decision="REJECTED",
                    regime=regime,
                    reject_reason="VWAP_SLOPE_DUAL_FLAT_WHILE_DEVIATION_HIGH",
                    metrics={
                        "vwap_deviation_pct": vwap_dev_pct,
                        "vwap_slope_5m_pct": vwap_slope_5m_pct,
                        "vwap_slope_15m_pct": vwap_slope_15m_pct
                    },
                    thresholds={
                        "deviation_high_pct": deviation_threshold,
                        "slope_min_5m": slope_threshold_5m,
                        "slope_min_15m": slope_threshold_15m
                    },
                    mode=self.config.vwap_slope_guard_mode
                )

                if self.config.vwap_slope_guard_mode == "live":
                    if self.config.vwap_slope_log_details:
                        logger.info(f"[LIVE] {symbol}: NO BUY – {reason}")
                    return False, reason
                else:
                    if self.config.vwap_slope_log_details:
                        logger.info(f"[SHADOW] {symbol}: Would reject by dual-slope guard – {reason}")
                        logger.info(f"[SHADOW] {symbol}: Entry proceeds despite shadow rejection")
                    return True, None
            else:
                # At least one window still has momentum - allow entry
                if self.config.vwap_slope_log_details and (slope_5m_flat or slope_15m_flat):
                    logger.debug(
                        f"{symbol}: Dual-window PASS (5m={'FLAT' if slope_5m_flat else 'OK'}, "
                        f"15m={'FLAT' if slope_15m_flat else 'OK'}) - at least one window has momentum"
                    )
                return True, None

        else:
            # Single-window mode (15m only - backward compatibility)
            if vwap_slope_15m_pct is None:
                if self.config.vwap_slope_log_details:
                    logger.debug(
                        f"[{self.config.vwap_slope_guard_mode.upper()}] {symbol}: "
                        f"VWAP 15m slope data unavailable (dev={vwap_dev_pct:.1f}%)"
                    )
                return True, None

            slope_threshold_15m = self._resolve_threshold(symbol, "slope_min_pct_15m", regime)

            if vwap_slope_15m_pct <= slope_threshold_15m:
                reason = (
                    f"VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH "
                    f"(dev={vwap_dev_pct:.1f}%, 15m={vwap_slope_15m_pct:.2f}%, "
                    f"thresholds: dev>={deviation_threshold}%, 15m<={slope_threshold_15m}%)"
                )

                self._emit_entry_guard_event(
                    symbol=symbol,
                    decision="REJECTED",
                    regime=regime,
                    reject_reason="VWAP_SLOPE_FLAT_WHILE_DEVIATION_HIGH",
                    metrics={
                        "vwap_deviation_pct": vwap_dev_pct,
                        "vwap_slope_15m_pct": vwap_slope_15m_pct
                    },
                    thresholds={
                        "deviation_high_pct": deviation_threshold,
                        "slope_min_pct_15m": slope_threshold_15m
                    },
                    mode=self.config.vwap_slope_guard_mode
                )

                if self.config.vwap_slope_guard_mode == "live":
                    if self.config.vwap_slope_log_details:
                        logger.info(f"[LIVE] {symbol}: NO BUY – {reason}")
                    return False, reason
                else:
                    if self.config.vwap_slope_log_details:
                        logger.info(f"[SHADOW] {symbol}: Would reject by slope guard – {reason}")
                        logger.info(f"[SHADOW] {symbol}: Entry proceeds despite shadow rejection")
                    return True, None

        # Passed: Price above VWAP but slope(s) still healthy
        return True, None

    def check_parabolic_detector(
        self,
        symbol: str,
        vwap_dev_pct: float,
        accel_5m_pct: Optional[float],
        accel_15m_pct: Optional[float],
        regime: str = "NEUTRAL"
    ) -> Tuple[bool, Optional[str]]:
        """
        Parabolic Detector - Detects extreme blow-off tops with cooldown.

        Triggers cooldown when ALL THREE conditions are met:
        1. VWAP deviation >= threshold (price far above VWAP)
        2. 5m acceleration >= threshold (extreme short-term momentum)
        3. 15m acceleration >= threshold (extreme medium-term momentum)

        Returns:
            (allowed, reject_reason) - (True, None) if passed, (False, reason) if rejected
        """
        if not self.config.parabolic_detector_enabled:
            return True, None

        # Check if already in cooldown
        is_blocked, remaining_sec = self.parabolic_blacklist.is_blocked(symbol)
        if is_blocked:
            reason = (
                f"PARABOLIC_COOLDOWN_ACTIVE "
                f"(remaining={remaining_sec}s of {self.config.parabolic_cooldown_sec}s)"
            )
            if self.config.parabolic_detector_mode == "live":
                if self.config.parabolic_log_details:
                    logger.info(f"[LIVE] {symbol}: NO BUY – {reason}")
                return False, reason
            else:
                if self.config.parabolic_log_details:
                    logger.info(f"[SHADOW] {symbol}: Would reject by cooldown – {reason}")
                    logger.info(f"[SHADOW] {symbol}: Entry proceeds despite shadow rejection")
                return True, None

        # Check data availability
        if accel_5m_pct is None or accel_15m_pct is None:
            if self.config.parabolic_log_details:
                logger.debug(
                    f"[{self.config.parabolic_detector_mode.upper()}] {symbol}: "
                    f"Acceleration data unavailable (accel_5m={accel_5m_pct}, accel_15m={accel_15m_pct})"
                )
            return True, None  # Don't reject if we can't calculate

        # Get thresholds (baseline only for now, regime-aware in Story 5)
        dev_threshold = self.config.parabolic_vwap_dev_min_pct
        accel_5m_threshold = self.config.parabolic_accel_5m_min_pct
        accel_15m_threshold = self.config.parabolic_accel_15m_min_pct

        # Check all three conditions
        condition_1 = vwap_dev_pct >= dev_threshold
        condition_2 = accel_5m_pct >= accel_5m_threshold
        condition_3 = accel_15m_pct >= accel_15m_threshold

        if condition_1 and condition_2 and condition_3:
            # PARABOLIC DETECTED: All three conditions met
            reason = (
                f"PARABOLIC_DETECTED "
                f"(dev={vwap_dev_pct:.1f}%>={dev_threshold}%, "
                f"accel5={accel_5m_pct:.2f}%>={accel_5m_threshold}%, "
                f"accel15={accel_15m_pct:.2f}%>={accel_15m_threshold}%)"
            )

            # Add to blacklist with cooldown (in-memory)
            self.parabolic_blacklist.add(symbol, self.config.parabolic_cooldown_sec)

            # Story 10: Persist to SQLite if enabled
            if self.cooldown_store and self.connector_name and self.config.parabolic_cooldown_persist:
                shadow_mode = self.config.parabolic_detector_mode == "shadow"
                self.cooldown_store.set_cooldown(
                    connector=self.connector_name,
                    symbol=symbol,
                    reason="PARABOLIC_DETECTED",
                    cooldown_sec=self.config.parabolic_cooldown_sec,
                    shadow_mode=shadow_mode
                )

            # EPIC v3.4 Story 6: Emit structured event
            self._emit_entry_guard_event(
                symbol=symbol,
                decision="REJECTED",
                regime=regime,
                reject_reason="PARABOLIC_DETECTED",
                metrics={
                    "vwap_deviation_pct": vwap_dev_pct,
                    "accel_5m_pct": accel_5m_pct,
                    "accel_15m_pct": accel_15m_pct
                },
                thresholds={
                    "vwap_dev_min_pct": dev_threshold,
                    "accel_5m_min_pct": accel_5m_threshold,
                    "accel_15m_min_pct": accel_15m_threshold
                },
                cooldown_remaining_sec=self.config.parabolic_cooldown_sec,
                mode=self.config.parabolic_detector_mode,
                force=True
            )

            if self.config.parabolic_detector_mode == "live":
                # Live mode: actually reject entry
                if self.config.parabolic_log_details:
                    logger.info(
                        f"[LIVE] {symbol}: NO BUY – {reason} "
                        f"→ COOLDOWN {self.config.parabolic_cooldown_sec}s"
                    )
                return False, reason
            else:
                # Shadow mode: log but don't reject
                if self.config.parabolic_log_details:
                    logger.info(
                        f"[SHADOW] {symbol}: Would reject by parabolic detector – {reason}"
                    )
                    logger.info(
                        f"[SHADOW] {symbol}: Would trigger cooldown {self.config.parabolic_cooldown_sec}s"
                    )
                    logger.info(f"[SHADOW] {symbol}: Entry proceeds despite shadow rejection")
                return True, None  # Allow in shadow mode

        # Passed: Not all conditions met
        return True, None

```

## Attachment: futures risk_guard.py (256 lines)

```python
"""
RiskGuard: Centralized kill-switch logic voor futures grids.

Principe:
- Één verantwoordelijkheid: "Mag deze grid nog leven?"
- Stateless voor marktdata, stateful per coin
- Retourneert óf None óf een StopExecutorAction

Guards:
1. Hard loss: maximaal verlies overschreden
2. Max time: grid draait te lang zonder winst
3. Grid depth: te veel buy orders gevuld (zitten vast in dalende markt)
4. Sell starvation: geen sells = geen profit = stuck
5. Trend break: 1h trend breekt negatief = markt keert om
6. ATR explosion: volatiliteit explodeert = te gevaarlijk
"""

from decimal import Decimal
from typing import Dict, Optional

from hummingbot.strategy_v2.models.executor_actions import StopExecutorAction


class RiskGuard:
    """Base interface voor risk guards."""

    def evaluate(self, coin: str) -> Optional[StopExecutorAction]:
        """Evalueer of coin gestopt moet worden. Retourneer StopExecutorAction of None."""
        raise NotImplementedError


class FuturesGridRiskGuard(RiskGuard):
    """
    Centralized kill-switch logic for futures grids.

    Houdt per coin bij:
    - Wanneer grid gestart is
    - Wanneer laatste sell was
    - ATR baseline voor volatiliteit check
    """

    def __init__(self, controller):
        """
        Args:
            controller: FuturesGridBitgetController instance met toegang tot:
                - market_data_provider.time()
                - position_manager.get_unrealized_pnl(coin)
                - grid_state.get(coin)
                - trend_calculator.get_trend(coin)
                - volatility_calculator.get_atr(coin)
                - config (met alle risk_guard_* parameters)
                - logger()
        """
        self.c = controller
        self.grid_start_ts: Dict[str, float] = {}
        self.last_sell_ts: Dict[str, float] = {}
        self.atr_baseline: Dict[str, Decimal] = {}

    def notify_grid_started(self, coin: str):
        """
        Notificatie: nieuwe grid is gestart voor coin.
        Reset alle tracking timestamps.
        """
        now = self.c.market_data_provider.time()
        self.grid_start_ts[coin] = now
        self.last_sell_ts[coin] = now

        # Sla huidige ATR op als baseline voor volatiliteit check
        atr = self.c.volatility_calculator.get_atr(coin) if hasattr(self.c, 'volatility_calculator') else None
        if atr:
            self.atr_baseline[coin] = atr

    def notify_sell_filled(self, coin: str):
        """
        Notificatie: sell order is gevuld voor coin.
        Update timestamp om sell starvation te voorkomen.
        """
        self.last_sell_ts[coin] = self.c.market_data_provider.time()

    def notify_grid_stopped(self, coin: str):
        """
        Notificatie: grid is gestopt voor coin.
        Cleanup alle tracking data.
        """
        self.grid_start_ts.pop(coin, None)
        self.last_sell_ts.pop(coin, None)
        self.atr_baseline.pop(coin, None)

    # ============================================================
    # GUARD CHECKS - Elke check retourneert bool: True = stop grid
    # ============================================================

    def _hard_loss(self, coin: str) -> bool:
        """
        Check 1: Hard loss - maximaal verlies overschreden.
        Gebruikt: risk_guard_max_loss_pct (default -8.0%)

        TEMPORARY DISABLED: position_manager.get_unrealized_pnl() not available
        TODO: Implement after verifying position_manager API
        """
        return False  # DISABLED - uncomment after implementing PnL tracking

    def _max_time(self, coin: str) -> bool:
        """
        Check 2: Max time - grid draait te lang.
        Gebruikt: risk_guard_max_grid_time_seconds (default 3600s = 1h)
        """
        start = self.grid_start_ts.get(coin)
        if not start:
            return False

        max_time = self.c.config.risk_guard_max_grid_time_seconds
        elapsed = self.c.market_data_provider.time() - start

        if elapsed > max_time:
            self.c.logger().warning(
                f"⏰ {coin} max time: {elapsed:.0f}s > {max_time}s"
            )
            return True
        return False

    def _grid_depth(self, coin: str) -> bool:
        """
        Check 3: Grid depth - te veel buy orders gevuld.
        Gebruikt: risk_guard_max_grid_depth_pct (default 0.65 = 65%)

        TEMPORARY DISABLED: grid_state not available
        TODO: Implement after verifying grid tracking API
        """
        return False  # DISABLED - uncomment after implementing grid depth tracking

    def _sell_starvation(self, coin: str) -> bool:
        """
        Check 4: Trade starvation - geen profit-taking trades.
        Gebruikt: risk_guard_sell_starvation_seconds (default 900s = 15min)

        Set to 0 to DISABLE this check (recommended for grid trading where
        sells are tracked internally by the grid executor).

        LONG: geen sells = geen profit (we verkopen om winst te nemen)
        SHORT: geen buys = geen profit (we kopen terug om winst te nemen)

        Voor nu: disabled voor SHORT mode omdat we geen buy tracking hebben.
        """
        # Disable voor SHORT mode - zou buy starvation moeten zijn
        trade_direction = getattr(self.c.config, 'trade_direction', 'long').lower()
        if trade_direction == 'short':
            return False  # TODO: implement buy starvation tracking for shorts

        max_starvation = self.c.config.risk_guard_sell_starvation_seconds

        # 0 = disabled
        if max_starvation <= 0:
            return False

        last = self.last_sell_ts.get(coin)
        if not last:
            return False

        time_since_sell = self.c.market_data_provider.time() - last

        if time_since_sell > max_starvation:
            self.c.logger().warning(
                f"🚫 {coin} sell starvation: {time_since_sell:.0f}s > {max_starvation}s sinds laatste sell"
            )
            return True
        return False

    def _trend_break(self, coin: str) -> bool:
        """
        Check 5: Trend break - trend keert om tegen je positie.

        Voor LONG: 1h trend < -1.5% = markt daalt = slecht
        Voor SHORT: 1h trend > +1.5% = markt stijgt = slecht

        Gebruikt: risk_guard_trend_break_pct (default -1.5% for LONG)
        """
        if not hasattr(self.c, 'trend_calculator'):
            return False

        trend = self.c.trend_calculator.get_trend(coin)
        if not trend or not hasattr(trend, 'trend_60m'):
            return False

        threshold = abs(self.c.config.risk_guard_trend_break_pct)
        trade_direction = getattr(self.c.config, 'trade_direction', 'long').lower()

        if trade_direction == 'short':
            # SHORT: trend break als markt STIJGT (positieve trend)
            if trend.trend_60m > threshold:
                self.c.logger().warning(
                    f"📈 {coin} trend break (SHORT): 1h {trend.trend_60m:+.2f}% > +{threshold:.2f}%"
                )
                return True
        else:
            # LONG: trend break als markt DAALT (negatieve trend)
            if trend.trend_60m < -threshold:
                self.c.logger().warning(
                    f"📉 {coin} trend break (LONG): 1h {trend.trend_60m:+.2f}% < -{threshold:.2f}%"
                )
                return True
        return False

    def _atr_explosion(self, coin: str) -> bool:
        """
        Check 6: ATR explosion - volatiliteit explodeert.
        Gebruikt: risk_guard_atr_explosion_multiplier (default 2.2x)

        TEMPORARY DISABLED: volatility_calculator not available
        TODO: Implement after verifying ATR calculation API
        """
        return False  # DISABLED - uncomment after implementing ATR tracking

    # ============================================================
    # PUBLIC API
    # ============================================================

    def evaluate(self, coin: str) -> Optional[StopExecutorAction]:
        """
        Evalueer alle risk guards voor coin.

        Returns:
            StopExecutorAction als één of meer guards triggeren
            None als alles OK is
        """
        # Skip als risk guard disabled
        if not self.c.config.risk_guard_enabled:
            return None

        reasons = []

        # Check alle guards
        if self._hard_loss(coin):
            reasons.append("hard_loss")
        if self._max_time(coin):
            reasons.append("max_time")
        if self._grid_depth(coin):
            reasons.append("grid_depth")
        if self._sell_starvation(coin):
            reasons.append("sell_starvation")
        if self._trend_break(coin):
            reasons.append("trend_break")
        if self._atr_explosion(coin):
            reasons.append("atr_explosion")

        # Als één of meer guards triggeren = stop grid
        if reasons:
            self.c.logger().critical(
                f"🛑 RiskGuard STOP voor {coin}: {', '.join(reasons)}"
            )
            return StopExecutorAction(
                executor_id=coin,  # Assuming executor_id is coin symbol
                reason=f"risk_guard: {', '.join(reasons)}"
            )

        return None

```

## Attachment: Data Snapshot (2026-03-08)

# Bot Data Snapshot — 8 March 2026

> **Snapshot date**: 2026-03-08 ~15:00 UTC
> **Purpose**: Attach this file as evidence when running a review round.
> **Shelf life**: Data becomes stale within days. Re-run the queries below
> to generate a fresh snapshot before each review round.

---

## How to regenerate this snapshot

Run from the repo root (`/home/mo/repos/hummingbot`):

```bash
# Activate the venv first
source .venv/bin/activate

# ──────────────────────────────────────────────────
# 1. DATABASE QUERIES  (repeat for each .sqlite DB)
# ──────────────────────────────────────────────────

# Per-pair performance
sqlite3 -header -column data/<DB>.sqlite "
SELECT json_extract(config, '\$.trading_pair') as pair,
    COUNT(*) as trades,
    SUM(CASE WHEN net_pnl_quote > 0 THEN 1 ELSE 0 END) as wins,
    SUM(CASE WHEN net_pnl_quote < 0 THEN 1 ELSE 0 END) as losses,
    SUM(CASE WHEN filled_amount_quote = 0 THEN 1 ELSE 0 END) as zero_fill,
    ROUND(SUM(net_pnl_quote), 4) as total_pnl,
    ROUND(SUM(cum_fees_quote), 4) as fees,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL
GROUP BY json_extract(config, '\$.trading_pair') ORDER BY total_pnl DESC;"

# Close type distribution
sqlite3 -header -column data/<DB>.sqlite "
SELECT close_type, COUNT(*) as cnt,
    ROUND(SUM(net_pnl_quote), 4) as sum_pnl,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL
GROUP BY close_type ORDER BY cnt DESC;"

# Date range + totals
sqlite3 -header -column data/<DB>.sqlite "
SELECT date(MIN(timestamp), 'unixepoch') as first,
    date(MAX(timestamp), 'unixepoch') as last,
    COUNT(*) as total,
    SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) as filled,
    ROUND(100.0 * SUM(CASE WHEN filled_amount_quote > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as fill_pct,
    ROUND(SUM(net_pnl_quote), 4) as pnl,
    ROUND(SUM(cum_fees_quote), 4) as fees,
    ROUND(SUM(filled_amount_quote), 2) as vol
FROM Executors WHERE close_type IS NOT NULL;"

# Futures only: filled trades by pair + close type
sqlite3 -header -column data/futures_grid_bitget.sqlite "
SELECT json_extract(config, '\$.trading_pair') as pair, close_type,
    COUNT(*) as cnt,
    SUM(CASE WHEN net_pnl_quote > 0 THEN 1 ELSE 0 END) as wins,
    ROUND(SUM(net_pnl_quote), 4) as total_pnl,
    ROUND(SUM(filled_amount_quote), 2) as volume
FROM Executors WHERE close_type IS NOT NULL AND filled_amount_quote > 0
GROUP BY pair, close_type ORDER BY total_pnl DESC;"

# ──────────────────────────────────────────────────
# 2. LOG ERROR FREQUENCY
# ──────────────────────────────────────────────────

# Find the most recent log for each bot:
ls -t logs/logs_multi_coin_grid_v2_usd_*.log | head -1   # Kraken USD
ls -t logs/logs_spot_grid_bitget_*.log | head -1          # Bitget Spot
ls -t logs/logs_futures_grid_bitget_*.log | head -1       # Bitget Futures

# Then for each:
grep -oP "(ERROR|WARNING|CRITICAL)" <logfile> | sort | uniq -c | sort -rn
grep "ERROR" <logfile> | grep -oP "ERROR - .*" | sort -u | head -15
grep -c "WSS_ERROR\|WebSocket\|websocket" <logfile>       # WebSocket count

# ──────────────────────────────────────────────────
# 3. WHY-NO-TRADE SUMMARIES
# ──────────────────────────────────────────────────

# Find the most recent report log:
ls -t logs/kraken_*report*.log | head -1
ls -t logs/bitget_*report*.log | head -1

# Extract the last few hours:
grep -B1 -A 15 "WHY-NO-TRADE SUMMARY" <report_log> | tail -60

# ──────────────────────────────────────────────────
# 4. ROTATION TIMEOUT EVENTS
# ──────────────────────────────────────────────────

grep -oP "MONITORING TIMEOUT: \K[A-Z]+-[A-Z]+" <logfile> | sort | uniq -c | sort -rn
grep -i "MONITORING TIMEOUT" <logfile> | tail -20
```

Replace `<DB>` with: `multi_coin_grid_v2.sqlite` (Kraken EUR),
`multi_coin_grid_v2_usd.sqlite` (Kraken USD), `spot_grid_bitget.sqlite`
(Bitget Spot), `futures_grid_bitget.sqlite` (Bitget Futures).

---

## Database files

| Database | Bot | Size | Period |
|----------|-----|------|--------|
| `data/multi_coin_grid_v2.sqlite` | Kraken EUR (retired) | 12 MB | 2025-11-20 → 2026-02-05 |
| `data/multi_coin_grid_v2_usd.sqlite` | Kraken USD (active) | 8.0 MB | 2026-01-21 → 2026-01-23 |
| `data/spot_grid_bitget.sqlite` | Bitget Spot (blocked) | 6.0 MB | 2026-01-06 → 2026-01-12 |
| `data/futures_grid_bitget.sqlite` | Bitget Futures (blocked) | 2.9 MB | 2026-02-01 → 2026-02-10 |

## Close type legend

| Code | Meaning |
|------|---------|
| 3 | TAKE_PROFIT |
| 5 | EARLY_STOP (no-fill, soft stop) |
| 7 | EXPIRED / no-fill timeout |
| 8 | STOP_LOSS |
| 11 | FAILED_TO_OPEN |
| 12 | SMART_SWITCH (rotation exit) |

---

## 1. Kraken EUR (historical, retired)

**Period**: 2025-11-20 → 2026-02-05 (77 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 2,209 | 34 | 1.5% | −€73.39 | €3.71 | €2,236.62 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 5 (EARLY_STOP) | 1,473 | +€11.83 | €1,767.85 |
| 7 (EXPIRED) | 704 | €0.00 | €0.00 |
| 3 (TAKE_PROFIT) | 11 | +€24.49 | €248.48 |
| 8 (STOP_LOSS) | 7 | −€109.72 | €220.29 |
| 11 (FAILED_TO_OPEN) | 11 | €0.00 | €0.00 |
| 12 (SMART_SWITCH) | 3 | €0.00 | €0.00 |

### Per-pair performance (pairs with fills only)
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| STRK-EUR | 10 | 1 | 0 | 9 | +€24.40 | €0.96 | €216.94 |
| TAO-EUR | 45 | 2 | 2 | 41 | +€1.96 | €0.00 | €115.44 |
| XTZ-EUR | 56 | 1 | 1 | 54 | −€0.30 | €0.01 | €139.54 |
| ATOM-EUR | 303 | 0 | 3 | 300 | −€0.32 | €0.01 | €174.54 |
| POL-EUR | 236 | 1 | 3 | 232 | −€0.50 | €0.01 | €279.26 |
| JASMY-EUR | 2 | 0 | 1 | 1 | −€0.68 | €0.00 | €104.09 |
| UNI-EUR | 13 | 0 | 1 | 12 | −€1.11 | €0.97 | €215.79 |
| SOL-EUR | 122 | 1 | 4 | 117 | −€2.32 | €1.73 | €557.85 |
| SUI-EUR | 95 | 0 | 1 | 94 | −€0.01 | €0.00 | €34.96 |
| DOT-EUR | 89 | 0 | 1 | 88 | −€0.02 | €0.00 | €34.95 |
| ALGO-EUR | 4 | 0 | 1 | 3 | −€15.56 | €0.00 | €31.47 |
| RENDER-EUR | 103 | 0 | 2 | 101 | −€15.63 | €0.00 | €66.40 |
| ADA-EUR | 104 | 0 | 1 | 103 | −€15.63 | €0.00 | €31.47 |
| CC-EUR | 26 | 1 | 4 | 21 | −€15.70 | €0.01 | €170.98 |
| AAVE-EUR | 30 | 0 | 1 | 29 | −€15.93 | €0.00 | €31.47 |
| PEPE-EUR | 1 | 0 | 1 | 0 | −€16.02 | €0.00 | €31.47 |

### Per-pair (zero-fill only, no trades — top 10 by executor count)
| Pair | Executors | All zero-fill |
|------|-----------|---------------|
| SAND-EUR | 152 | 152 |
| FIL-EUR | 157 | 157 |
| MANA-EUR | 127 | 127 |
| SNX-EUR | 124 | 124 |
| BNB-EUR | 92 | 92 |
| ZRO-EUR* | — | — |
| DOGE-EUR | 42 | 42 |
| KAS-EUR | 31 | 31 |
| BCH-EUR | 33 | 33 |
| OPEN-EUR | 29 | 29 |

---

## 2. Kraken USD (active, limited data)

**Period**: 2026-01-21 → 2026-01-23 (2 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 212 | 1 | 0.5% | −$0.26 | $0.00 | $33.04 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 7 (EXPIRED) | 210 | $0.00 | $0.00 |
| 11 (FAILED_TO_OPEN) | 1 | $0.00 | $0.00 |
| 5 (EARLY_STOP) | 1 | −$0.26 | $33.04 |

### Per-pair performance
| Pair | Trades | Wins | Losses | Zero-fill | PnL |
|------|--------|------|--------|-----------|-----|
| ZRO-USD | 68 | 0 | 0 | 68 | $0.00 |
| XCN-USD | 48 | 0 | 0 | 48 | $0.00 |
| TAO-USD | 8 | 0 | 0 | 8 | $0.00 |
| SOL-USD | 14 | 0 | 0 | 14 | $0.00 |
| SAND-USD | 8 | 0 | 0 | 8 | $0.00 |
| MANA-USD | 7 | 0 | 0 | 7 | $0.00 |
| AVAX-USD | 7 | 0 | 0 | 7 | $0.00 |
| ADA-USD | 10 | 0 | 0 | 10 | $0.00 |
| AXS-USD | 42 | 0 | 1 | 41 | −$0.26 |

---

## 3. Bitget Spot (capital-blocked)

**Period**: 2026-01-06 → 2026-01-12 (6 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 400 | 6 | 1.5% | −$0.72 | $0.36 | $242.77 |

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 5 (EARLY_STOP) | 382 | −$0.31 | $132.83 |
| 12 (SMART_SWITCH) | 9 | −$0.41 | $109.93 |
| 11 (FAILED_TO_OPEN) | 9 | $0.00 | $0.00 |

### Per-pair performance (pairs with fills only)
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| AVA-USDT | 99 | 0 | 1 | 98 | −$0.03 | $0.03 | $22.17 |
| ASTR-USDT | 4 | 0 | 1 | 3 | −$0.04 | $0.03 | $22.18 |
| CHZ-USDT | 8 | 0 | 1 | 7 | −$0.08 | $0.07 | $44.39 |
| SWCH-USDT | 57 | 0 | 3 | 54 | −$0.56 | $0.23 | $154.02 |

**Current state**: BLOCKED — $3.62 free capital < $30.00 minimum.
Stuck SONIC LIMIT SELL @ $0.046419 (1533 units) locking ~$71.

---

## 4. Bitget Futures (capital-depleted)

**Period**: 2026-02-01 → 2026-02-10 (9 days)

### Totals
| Executors | Had fills | Fill % | Total PnL | Fees | Volume |
|-----------|-----------|--------|-----------|------|--------|
| 932 | 23 | 2.5% | −$155.39 | −$0.09* | $472.90 |

*Negative fees = maker rebates on some trades.

### Close type distribution
| Close type | Count | Sum PnL | Volume |
|------------|-------|---------|--------|
| 3 (TAKE_PROFIT) | 737 | +$0.57 | $33.85 |
| 7 (EXPIRED) | 171 | $0.00 | $0.00 |
| 8 (STOP_LOSS) | 22 | −$155.96 | $439.05 |
| 11 (FAILED_TO_OPEN) | 2 | $0.00 | $0.00 |

### Per-pair performance
| Pair | Trades | Wins | Losses | Zero-fill | PnL | Fees | Volume |
|------|--------|------|--------|-----------|-----|------|--------|
| SOL-USDT | 101 | 2 | 0 | 99 | +$9.31 | −$0.01 | $67.83 |
| SUI-USDT | 72 | 1 | 1 | 70 | +$0.09 | −$0.01 | $31.53 |
| AVAX-USDT | 113 | 0 | 1 | 112 | −$5.42 | $0.00 | $10.90 |
| LINK-USDT | 175 | 0 | 1 | 174 | −$9.56 | $0.00 | $19.26 |
| DOGE-USDT | 28 | 1 | 3 | 24 | −$10.57 | −$0.01 | $42.33 |
| XRP-USDT | 217 | 1 | 2 | 214 | −$11.96 | −$0.01 | $46.37 |
| OP-USDT | 1 | 0 | 1 | 0 | −$12.61 | −$0.01 | $24.86 |
| ARB-USDT | 116 | 0 | 3 | 113 | −$23.05 | −$0.01 | $45.90 |
| BTC-USDT | 59 | 0 | 3 | 56 | −$28.84 | −$0.01 | $57.73 |
| ETH-USDT | 50 | 0 | 3 | 47 | −$62.78 | −$0.03 | $126.18 |

### Filled trades detail (close type breakdown)
| Pair | Close type | Count | Wins | PnL | Volume |
|------|------------|-------|------|-----|--------|
| SOL-USDT | 8 (STOP_LOSS) | 1 | 1 | +$8.74 | $33.98 |
| SOL-USDT | 3 (TAKE_PROFIT) | 1 | 1 | +$0.57 | $33.85 |
| SUI-USDT | 8 (STOP_LOSS) | 2 | 1 | +$0.09 | $31.53 |
| AVAX-USDT | 8 | 1 | 0 | −$5.42 | $10.90 |
| LINK-USDT | 8 | 1 | 0 | −$9.56 | $19.26 |
| DOGE-USDT | 8 | 4 | 1 | −$10.57 | $42.33 |
| XRP-USDT | 8 | 3 | 1 | −$11.96 | $46.37 |
| OP-USDT | 8 | 1 | 0 | −$12.61 | $24.86 |
| ARB-USDT | 8 | 3 | 0 | −$23.05 | $45.90 |
| BTC-USDT | 8 | 3 | 0 | −$28.84 | $57.73 |
| ETH-USDT | 8 | 3 | 0 | −$62.78 | $126.18 |

**Current state**: BLOCKED — $9.09–$9.41 free capital < $15.00 minimum.
−$155 on $50 capital = −310% return in 9 days.

---

## 5. Combined summary

| Bot | Period | Executors | Filled | Fill % | PnL | Capital | Return |
|-----|--------|-----------|--------|--------|-----|---------|--------|
| Kraken EUR | Nov 25 – Feb 26 | 2,209 | 34 | 1.5% | −€73.39 | €300 | −24.5% |
| Kraken USD | Jan 21–23 | 212 | 1 | 0.5% | −$0.26 | ~$300 | −0.1% |
| Bitget Spot | Jan 6–12 | 400 | 6 | 1.5% | −$0.72 | ~$100 | −0.7% |
| Bitget Futures | Feb 1–10 | 932 | 23 | 2.5% | −$155.39 | ~$50 | −310.8% |
| **Combined** | | **3,753** | **64** | **1.7%** | **≈ −€229** | | |

**Key observations**:
- Not a single bot instance is profitable
- 98.3% of all executors across all bots never get a single fill
- Futures shows highest fill rate (2.5%) but worst outcome (96% stopped out)
- Only 1 of 3 active bots can currently attempt to trade (Kraken USD)

---

## 6. Error frequency from logs

### Kraken USD
**Log**: `logs/logs_multi_coin_grid_v2_usd_2026-03-05-16-20-24.log`
**Session**: 2026-03-05 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 277 |
| ERROR | 225 |

**Unique errors**:
- `MQTT is already stopped!` — MQTT connection management issue
- `Unexpected error while listening to user stream. Retrying after 5 seconds...` — WebSocket instability

**WebSocket-related messages**: 336 occurrences

### Bitget Spot
**Log**: `logs/logs_spot_grid_bitget_2026-03-05-16-42-05.log`
**Session**: 2026-03-05 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 1,664 |
| ERROR | 368 |

**Single error (all 368 occurrences)**:
```
❌ Cannot create grid: Insufficient capital: $3.62 < $30.00 minimum (3 grids × $10)
```

### Bitget Futures
**Log**: `logs/logs_futures_grid_bitget_2026-02-28-13-34-36.log`
**Session**: 2026-02-28 → 2026-03-08

| Level | Count |
|-------|-------|
| WARNING | 37 |
| ERROR | 37 |

**Unique errors (all insufficient capital variations)**:
```
❌ Cannot create grid: Insufficient capital: $9.27 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.29 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.34 < $15.00 minimum (3 grids × $5)
❌ Cannot create grid: Insufficient capital: $9.41 < $15.00 minimum (3 grids × $5)
```

---

## 7. WHY-NO-TRADE summaries

### Kraken USD — 2026-03-08 (3 hourly reports)

**09:29 UTC** | 2,561 intents evaluated | 83.1% denied | 16.9% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 1,137 | 44.4% |
| RSI_OVERBOUGHT | 776 | 30.3% |
| STALE_PRICE | 157 | 6.1% |
| ATR_TOO_LOW | 35 | 1.4% |
| SPREAD_TOO_WIDE | 15 | 0.6% |
| RSI_OVERSOLD | 7 | 0.3% |

**10:30 UTC** | 1,827 intents | 57.0% denied | 43.0% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 666 | 36.5% |
| RSI_OVERBOUGHT | 265 | 14.5% |
| ATR_TOO_LOW | 93 | 5.1% |
| STALE_PRICE | 9 | 0.5% |
| RSI_OVERSOLD | 6 | 0.3% |
| SPREAD_TOO_WIDE | 2 | 0.1% |

**11:30 UTC** | 2,359 intents | 74.8% denied | 25.2% approved
| Rejection reason | Count | % of total |
|-----------------|-------|------------|
| NO_ORDERBOOK_DATA | 971 | 41.2% |
| RSI_OVERBOUGHT | 721 | 30.6% |
| STALE_PRICE | 70 | 3.0% |
| SPREAD_TOO_WIDE | 3 | 0.1% |

**Pattern**: NO_ORDERBOOK_DATA is consistently #1 (36–44%), RSI_OVERBOUGHT #2 (14–31%).

### Bitget Spot — 2026-03-05 to 2026-03-08

**20:42 (Mar 5)** | 99 intents | 70.7% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 40 | 40.4% |
| RSI_OVERBOUGHT | 10 | 10.1% |
| ATR_TOO_LOW | 10 | 10.1% |
| ACCEL_FALLING_KNIFE | 6 | 6.1% |
| VWAP_DEVIATION_TOO_HIGH | 4 | 4.0% |

**22:42 (Mar 5)** | 1,094 intents | 52.7% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 405 | 37.0% |
| RSI_OVERBOUGHT | 97 | 8.9% |
| ACCEL_FALLING_KNIFE | 60 | 5.5% |
| ATR_TOO_LOW | 12 | 1.1% |
| TREND_24H_OUT_OF_RANGE | 3 | 0.3% |

**10:47 (Mar 8)** | ~2,000 intents | ~70% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | ~40% | — |
| RSI_OVERBOUGHT | ~18% | — |
| ACCEL_FALLING_KNIFE | 83 | 4.0% |
| TREND_24H_OUT_OF_RANGE | 61 | 3.0% |
| SPREAD_TOO_WIDE | 37 | 1.8% |

**11:48 (Mar 8)** | 1,883 intents | 72.1% denied
| Rejection reason | Count | % |
|-----------------|-------|---|
| NO_ORDERBOOK_DATA | 746 | 39.6% |
| RSI_OVERBOUGHT | 342 | 18.2% |
| ACCEL_FALLING_KNIFE | 109 | 5.8% |
| WICK_RATIO_LOW | 65 | 3.5% |
| TREND_24H_OUT_OF_RANGE | 54 | 2.9% |
| STALE_PRICE | 35 | 1.9% |
| SPREAD_TOO_WIDE | 6 | 0.3% |

**After 12:48 (Mar 8)**: 0 intents evaluated — Bitget Spot stopped evaluating
(likely capital-blocked, no coins being monitored).

---

## 8. Rotation timeout events

### Kraken USD (current session)
| Coin | Timeouts |
|------|----------|
| SUI-USD | 2 |

### Bitget Spot (current session)
| Coin | Timeouts |
|------|----------|
| SONIC-USDT | 19 |
| HYPE-USDT | 2 |

**SONIC-USDT rotation loop**: Rotates every ~3.1 minutes without progress.
Sample (all from March 8):
```
12:08 → 12:12 → 12:15 → 12:18 → 12:21 → 12:24 → 12:28 → 12:31
→ 12:34 → 12:37 → 12:41 → 12:44 → 12:47 → 12:50 → 12:57 → 13:00
→ 13:03 → 13:07 → ...
```
19 consecutive "monitoring timeout" events for the same coin = rotation
logic doesn't detect that it keeps selecting the same stuck coin.

---

## 9. Critical observations

1. **Fill rate crisis**: 98.3% of executors never fill. This is the #1 problem.
2. **NO_ORDERBOOK_DATA**: #1 rejection reason (35–44%) across all bots. Likely a data pipeline issue, not a strategy issue.
3. **Capital adequacy**: 2 of 3 active bots cannot trade due to insufficient capital.
4. **Futures catastrophe**: −$155 on $50 capital. 96% of filled trades hit stop-loss. Grid + leverage = amplified losses.
5. **Rotation loops**: SONIC-USDT rotates 19 times without progress. The bot doesn't learn.
6. **Kraken WebSocket**: 336 WebSocket-related events in a 3-day session.
7. **Only SOL-USDT** is consistently profitable across all bots (+$9.31 futures, positive on spot).

---

## Review Rules

## Review Rules (include at bottom of every round)

```
Important rules for this review:
- Be brutally honest and specific
- Do not praise by default
- Do not give generic best-practice advice unless tied to this bot
- Every major claim must reference evidence from code, config, logs,
  database, or trade data
- Distinguish facts, inferences, and unknowns
- Prioritize recommendations by impact, urgency, and implementation effort
- Explicitly state what should be kept, what should be redesigned,
  and what should be removed
- Assume the goal is to evolve this system toward professional-grade
  live trading, not just academic correctness
- If data is missing to support a conclusion, say exactly what data
  you need rather than speculating
- Use the evidence table format for all major findings
```

---
