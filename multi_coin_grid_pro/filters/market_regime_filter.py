"""
Market Regime Filter - BTC Trend Following & Market Breadth Analysis

Bepaalt of de OVERALL crypto market in een gunstige toestand is voor trading.
Bot pauzeerd automatisch tijdens:
- BTC dumps/crashes
- Bearish market regime
- Lage altcoin breadth (weinig coins bullish)
- Recovery cooldown periodes

Dit is een MACRO filter - checkt VOOR coin selection of trading überhaupt slim is.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class MarketRegimeConfig:
    """Configuration for Market Regime Filter"""

    # BTC Reference (de marktleider)
    btc_reference_pair: str = "BTC-EUR"
    btc_trend_weight: float = 0.6              # BTC trend = 60% van beslissing

    # BTC Trend Thresholds
    btc_min_trend_1h: float = -2.0             # BTC mag max -2% in 1h
    btc_min_trend_4h: float = 0.0              # BTC 4h moet minimaal flat zijn
    btc_min_trend_24h: float = -5.0            # BTC 24h mag -5% (normale correctie)

    # Altcoin Market Breadth
    altcoin_breadth_enabled: bool = True
    altcoin_breadth_min: float = 0.30          # Min 30% altcoins moet bullish zijn
    altcoin_breadth_pairs: List[str] = None    # Sample coins om te checken
    altcoin_breadth_threshold_1h: float = 0.5  # Altcoin bullish = 1h trend > +0.5%

    # Dump Detection & Cooldown
    pause_on_btc_dump: bool = True
    btc_dump_threshold_1h: float = -5.0        # BTC -5% in 1h = dump
    btc_dump_cooldown_minutes: int = 60        # Wacht 1h na dump

    # Recovery Detection
    resume_on_recovery: bool = True
    recovery_threshold_pct: float = 2.0        # BTC +2% = recovery signal

    def __post_init__(self):
        """Set defaults for mutable fields"""
        if self.altcoin_breadth_pairs is None:
            self.altcoin_breadth_pairs = [
                "ETH-EUR",
                "SOL-EUR",
                "BNB-EUR",
                "AVAX-EUR",
                "LINK-EUR",
            ]


@dataclass
class BTCTrendData:
    """BTC trend data"""
    price: Decimal
    trend_1h_pct: float
    trend_4h_pct: float
    trend_24h_pct: float
    timestamp: datetime


@dataclass
class MarketRegimeState:
    """Current market regime state"""
    is_favorable: bool
    reason: str
    btc_trend_1h: float
    btc_trend_4h: float
    btc_trend_24h: float
    altcoin_breadth: float
    in_dump_cooldown: bool
    cooldown_remaining_minutes: int
    last_updated: datetime


class MarketRegimeFilter:
    """
    Macro market regime filter.

    Voorkomt trading tijdens unfavorable market conditions:
    - BTC bearish trends
    - Market-wide dumps
    - Low altcoin breadth
    - Post-dump cooldown periods
    """

    def __init__(self, config: MarketRegimeConfig = None):
        self.config = config or MarketRegimeConfig()
        self.last_dump_time: Optional[datetime] = None
        self.last_regime_check: Optional[datetime] = None
        self.cached_regime_state: Optional[MarketRegimeState] = None

        logger.info("🌍 MarketRegimeFilter initialized")
        logger.info(f"   BTC ref: {self.config.btc_reference_pair}")
        logger.info(f"   BTC min trends: 1h={self.config.btc_min_trend_1h}%, "
                    f"4h={self.config.btc_min_trend_4h}%, 24h={self.config.btc_min_trend_24h}%")
        logger.info(f"   Altcoin breadth: min {self.config.altcoin_breadth_min * 100:.0f}% bullish")
        logger.info(
            f"   Dump detection: {
                self.config.btc_dump_threshold_1h}% → {
                self.config.btc_dump_cooldown_minutes}min cooldown")

    def check_market_regime(
        self,
        btc_trend_data: BTCTrendData,
        altcoin_trends: Optional[Dict[str, float]] = None,
    ) -> MarketRegimeState:
        """
        Check if market regime is favorable for trading.

        Args:
            btc_trend_data: BTC trend data (1h, 4h, 24h)
            altcoin_trends: Dict of {symbol: trend_1h_pct} for breadth calculation

        Returns:
            MarketRegimeState with decision and reasoning
        """
        now = datetime.now()

        # Check if we're in dump cooldown
        in_cooldown, cooldown_remaining = self._check_dump_cooldown(now)

        # Check BTC dump (potential new dump)
        is_dump = self._is_btc_dump(btc_trend_data, now)

        if is_dump and not in_cooldown:
            # New dump detected!
            self.last_dump_time = now
            in_cooldown = True
            cooldown_remaining = self.config.btc_dump_cooldown_minutes
            logger.warning(f"🚨 BTC DUMP DETECTED: {btc_trend_data.trend_1h_pct:.2f}% in 1h "
                           f"→ Pausing trading for {cooldown_remaining} minutes")

        # Check recovery (can override cooldown)
        is_recovery = self._is_recovery(btc_trend_data)
        if is_recovery and in_cooldown and self.config.resume_on_recovery:
            logger.info(f"✅ BTC RECOVERY detected: {btc_trend_data.trend_1h_pct:.2f}% "
                        f"→ Resuming trading (cooldown cancelled)")
            self.last_dump_time = None
            in_cooldown = False
            cooldown_remaining = 0

        # If in cooldown, block trading
        if in_cooldown:
            return MarketRegimeState(
                is_favorable=False,
                reason=f"In post-dump cooldown ({cooldown_remaining}min remaining)",
                btc_trend_1h=btc_trend_data.trend_1h_pct,
                btc_trend_4h=btc_trend_data.trend_4h_pct,
                btc_trend_24h=btc_trend_data.trend_24h_pct,
                altcoin_breadth=0.0,
                in_dump_cooldown=True,
                cooldown_remaining_minutes=cooldown_remaining,
                last_updated=now,
            )

        # Check BTC trend thresholds
        btc_ok, btc_reason = self._check_btc_trends(btc_trend_data)

        # Check altcoin breadth
        breadth = 0.0
        breadth_ok = True
        if self.config.altcoin_breadth_enabled and altcoin_trends:
            breadth = self._calculate_altcoin_breadth(altcoin_trends)
            breadth_ok = breadth >= self.config.altcoin_breadth_min
            if not breadth_ok:
                btc_reason = f"Low altcoin breadth ({
                    breadth
                    * 100:.0f}% < {
                    self.config.altcoin_breadth_min
                    * 100:.0f}%)"

        # Final decision
        is_favorable = btc_ok and breadth_ok

        if is_favorable:
            reason = f"✅ Favorable - BTC: 1h={btc_trend_data.trend_1h_pct:.1f}% " \
                f"4h={btc_trend_data.trend_4h_pct:.1f}% 24h={btc_trend_data.trend_24h_pct:.1f}%"
            if breadth > 0:
                reason += f", Breadth: {breadth * 100:.0f}%"
        else:
            reason = f"❌ Unfavorable - {btc_reason}"

        state = MarketRegimeState(
            is_favorable=is_favorable,
            reason=reason,
            btc_trend_1h=btc_trend_data.trend_1h_pct,
            btc_trend_4h=btc_trend_data.trend_4h_pct,
            btc_trend_24h=btc_trend_data.trend_24h_pct,
            altcoin_breadth=breadth,
            in_dump_cooldown=False,
            cooldown_remaining_minutes=0,
            last_updated=now,
        )

        # Cache the result
        self.cached_regime_state = state
        self.last_regime_check = now

        # Log periodically (every 5 minutes)
        if not hasattr(self, '_last_log_time') or (now - self._last_log_time).seconds > 300:
            logger.info(f"🌍 Market Regime: {reason}")
            self._last_log_time = now

        return state

    def _check_btc_trends(self, btc: BTCTrendData) -> Tuple[bool, str]:
        """Check if BTC trends meet minimum requirements"""

        # Check 1h trend
        if btc.trend_1h_pct < self.config.btc_min_trend_1h:
            return False, f"BTC 1h too bearish ({btc.trend_1h_pct:.1f}% < {self.config.btc_min_trend_1h}%)"

        # Check 4h trend
        if btc.trend_4h_pct < self.config.btc_min_trend_4h:
            return False, f"BTC 4h too bearish ({btc.trend_4h_pct:.1f}% < {self.config.btc_min_trend_4h}%)"

        # Check 24h trend
        if btc.trend_24h_pct < self.config.btc_min_trend_24h:
            return False, f"BTC 24h too bearish ({btc.trend_24h_pct:.1f}% < {self.config.btc_min_trend_24h}%)"

        return True, "BTC trends OK"

    def _is_btc_dump(self, btc: BTCTrendData, now: datetime) -> bool:
        """Detect if BTC is dumping hard"""
        if not self.config.pause_on_btc_dump:
            return False

        return btc.trend_1h_pct <= self.config.btc_dump_threshold_1h

    def _is_recovery(self, btc: BTCTrendData) -> bool:
        """Detect if BTC is recovering strongly"""
        if not self.config.resume_on_recovery:
            return False

        return btc.trend_1h_pct >= self.config.recovery_threshold_pct

    def _check_dump_cooldown(self, now: datetime) -> Tuple[bool, int]:
        """
        Check if we're in post-dump cooldown period.

        Returns:
            (in_cooldown: bool, minutes_remaining: int)
        """
        if self.last_dump_time is None:
            return False, 0

        elapsed = (now - self.last_dump_time).total_seconds() / 60
        remaining = max(0, self.config.btc_dump_cooldown_minutes - int(elapsed))

        if remaining > 0:
            return True, remaining
        else:
            # Cooldown expired
            self.last_dump_time = None
            return False, 0

    def _calculate_altcoin_breadth(self, altcoin_trends: Dict[str, float]) -> float:
        """
        Calculate market breadth: percentage of altcoins that are bullish.

        Args:
            altcoin_trends: Dict of {symbol: trend_1h_pct}

        Returns:
            Breadth as fraction (0.0 to 1.0)
        """
        if not altcoin_trends:
            return 0.0

        # Filter to only configured breadth pairs
        relevant_pairs = [
            symbol for symbol in self.config.altcoin_breadth_pairs
            if symbol in altcoin_trends
        ]

        if not relevant_pairs:
            logger.warning("⚠️ No altcoin breadth data available")
            return 0.0

        # Count how many are bullish
        bullish_count = sum(
            1 for symbol in relevant_pairs
            if altcoin_trends[symbol] >= self.config.altcoin_breadth_threshold_1h
        )

        breadth = bullish_count / len(relevant_pairs)

        return breadth

    def get_cached_state(self) -> Optional[MarketRegimeState]:
        """Get last cached regime state (for monitoring/logging)"""
        return self.cached_regime_state

    def reset_cooldown(self):
        """Manually reset dump cooldown (for testing or emergency override)"""
        logger.info("🔄 Manually resetting dump cooldown")
        self.last_dump_time = None

    def force_pause(self, reason: str, duration_minutes: int = 60):
        """Manually force a pause (e.g., for manual intervention)"""
        logger.warning(f"⏸️ MANUAL PAUSE: {reason} for {duration_minutes} minutes")
        self.last_dump_time = datetime.now()
        # Override cooldown duration temporarily
        self._manual_pause_duration = duration_minutes
