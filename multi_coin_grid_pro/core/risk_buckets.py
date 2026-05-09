"""
Risk Buckets -- per-category portfolio exposure limits.

Classifies coins into risk buckets and enforces max allocation per bucket.
Fail-closed by design: coins that cannot be classified default to BLOCKED (0% cap).

Part of the 17-upgrade trading bot roadmap:
  Item 9 -- Risk Buckets

Design
------
* RiskBucketClassifier  -- hybrid: manual overrides first, then data-driven.
* RiskBucketExposureTracker -- coin-level state is source of truth; bucket totals
  are always derived (never tracked incrementally), preventing drift.
* BucketExposureTracker -- backward-compatible alias for the controller import.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

# -- Bucket enum ---------------------------------------------------------------


class CoinBucket(str, Enum):
    L1 = "L1"               # BTC, ETH -- blue-chip
    L2 = "L2"               # SOL, DOT, established alts
    MEME = "MEME"           # DOGE, SHIB, PEPE, meme coins
    ILLIQUID = "ILLIQUID"   # low-volume / high-spread assets
    BLOCKED = "BLOCKED"     # fail-closed default -- cannot trade


# -- Manual overrides -- pre-classified, well-known assets --------------------

_MANUAL_L1 = {"BTC", "XBT", "ETH"}

_MANUAL_L2 = {
    "SOL", "DOT", "AVAX", "ADA", "LINK", "MATIC", "POL", "XRP", "LTC",
    "TRX", "ATOM", "NEAR", "OP", "ARB", "INJ", "SUI", "APT", "FTM", "S",
    "HBAR", "XLM", "VET", "ALGO", "FIL", "UNI", "AAVE", "CRV",
    # Kraken USD universe -- actively traded by this bot
    "TAO", "ONDO", "AKT", "HYPE", "DASH", "ORCA", "RENDER", "AERO",
    "PENDLE", "BIO", "RAVE", "XDC", "MON", "ASSET", "CC", "PLAY",
    "AKT", "SUI", "AVAX",  # already above, no harm repeating in set
}

_MANUAL_MEME = {
    "DOGE", "SHIB", "PEPE", "PENGU", "WIF", "BONK", "FLOKI", "POPCAT",
    "MEW", "TRUMP", "FARTCOIN",
    # High-risk speculative (meme-tier risk)
    "APE", "LUNA", "AI", "BCN",
}

_MANUAL_OVERRIDES: Dict[str, CoinBucket] = {
    **{c: CoinBucket.L1 for c in _MANUAL_L1},
    **{c: CoinBucket.L2 for c in _MANUAL_L2},
    **{c: CoinBucket.MEME for c in _MANUAL_MEME},
}

# Kept for external reference / backward compat
COIN_BUCKET_MAP: Dict[str, CoinBucket] = _MANUAL_OVERRIDES


# -- Configuration -------------------------------------------------------------

@dataclass
class RiskBucketConfig:
    """Configurable limits and data-driven thresholds for the risk bucket system."""

    limits: Dict[CoinBucket, float] = field(default_factory=lambda: {
        CoinBucket.L1: 40.0,
        CoinBucket.L2: 25.0,
        CoinBucket.MEME: 15.0,
        CoinBucket.ILLIQUID: 3.0,
        CoinBucket.BLOCKED: 0.0,
    })

    # Data-driven classification thresholds
    illiquid_min_volume_usd: float = 5_000_000.0   # below -> ILLIQUID
    illiquid_max_spread_pct: float = 2.0            # above -> ILLIQUID

    def __post_init__(self) -> None:
        for bucket in CoinBucket:
            if bucket not in self.limits:
                raise ValueError(
                    f"RiskBucketConfig.limits missing bucket: {bucket.value}"
                )
        for bucket, pct in self.limits.items():
            if not (0.0 <= pct <= 100.0):
                raise ValueError(
                    f"RiskBucketConfig.limits[{bucket.value}]={pct} must be in [0, 100]"
                )
        if self.illiquid_min_volume_usd < 0:
            raise ValueError(
                f"illiquid_min_volume_usd must be >= 0, got {self.illiquid_min_volume_usd}"
            )
        if self.illiquid_max_spread_pct < 0:
            raise ValueError(
                f"illiquid_max_spread_pct must be >= 0, got {self.illiquid_max_spread_pct}"
            )


# -- Data models ---------------------------------------------------------------

@dataclass
class MarketMetrics:
    """Market quality snapshot used for data-driven classification."""
    volume_24h_usd: float
    spread_pct: float

    def __post_init__(self) -> None:
        if self.volume_24h_usd < 0:
            raise ValueError(f"volume_24h_usd must be >= 0, got {self.volume_24h_usd}")
        if self.spread_pct < 0:
            raise ValueError(f"spread_pct must be >= 0, got {self.spread_pct}")


@dataclass
class TradabilityProfile:
    """Result of classifying a single coin."""
    symbol: str
    base: str
    bucket: CoinBucket
    reason: str

    @property
    def is_blocked(self) -> bool:
        return self.bucket == CoinBucket.BLOCKED


# -- Symbol normalisation ------------------------------------------------------

def _normalize_base(symbol: str) -> str:
    """
    Extract and normalise the base asset from dash- or slash-separated pairs.

    Supported formats:
        BTC-USDT  -> BTC
        BTC/USDT  -> BTC
        XBT-USD   -> BTC  (Kraken alias)
        eth       -> ETH

    Not supported: concatenated symbols without separator (e.g. BTCUSDT).
    """
    base = symbol.replace("/", "-").split("-")[0].upper()
    if base == "XBT":
        base = "BTC"
    return base


# -- Classifier ----------------------------------------------------------------

class RiskBucketClassifier:
    """
    Hybrid coin classifier:

    1. Manual overrides for known assets (fast, deterministic).
    2. Data-driven for unrecognised assets (volume + spread thresholds).
    3. Fail-closed: BLOCKED when market data is unavailable.
    """

    def __init__(
        self,
        config: Optional[RiskBucketConfig] = None,
        overrides: Optional[Dict[str, CoinBucket]] = None,
    ):
        self._config = config or RiskBucketConfig()
        self._overrides: Dict[str, CoinBucket] = dict(_MANUAL_OVERRIDES)
        if overrides:
            self._overrides.update({k.upper(): v for k, v in overrides.items()})

    def classify(
        self,
        symbol: str,
        metrics: Optional[MarketMetrics] = None,
    ) -> TradabilityProfile:
        """
        Classify *symbol* and return a TradabilityProfile with an explanation.

        Parameters
        ----------
        symbol:
            Trading pair or base asset (e.g. "PENGU-USD", "BTC/USDT", "XBT-EUR").
        metrics:
            Optional live market data.  Required for data-driven classification
            of unrecognised assets; without it unknown coins fall back to BLOCKED.
        """
        base = _normalize_base(symbol)

        # 1. Manual override (highest priority)
        if base in self._overrides:
            bucket = self._overrides[base]
            return TradabilityProfile(
                symbol=symbol,
                base=base,
                bucket=bucket,
                reason=f"{bucket.value} via manual override",
            )

        # 2. No override and no market data -> fail-closed
        if metrics is None:
            return TradabilityProfile(
                symbol=symbol,
                base=base,
                bucket=CoinBucket.BLOCKED,
                reason="BLOCKED -- no market data available for safe classification",
            )

        # 3. Data-driven: volume check
        cfg = self._config
        if metrics.volume_24h_usd < cfg.illiquid_min_volume_usd:
            return TradabilityProfile(
                symbol=symbol,
                base=base,
                bucket=CoinBucket.ILLIQUID,
                reason=(
                    f"ILLIQUID -- 24h volume ${metrics.volume_24h_usd:,.0f}"
                    f" < threshold ${cfg.illiquid_min_volume_usd:,.0f}"
                ),
            )

        # 4. Data-driven: spread check
        if metrics.spread_pct > cfg.illiquid_max_spread_pct:
            return TradabilityProfile(
                symbol=symbol,
                base=base,
                bucket=CoinBucket.ILLIQUID,
                reason=(
                    f"ILLIQUID -- spread {metrics.spread_pct:.2f}%"
                    f" > threshold {cfg.illiquid_max_spread_pct:.2f}%"
                ),
            )

        # 5. Sufficient liquidity but bucket unknown -> conservative policy fallback
        return TradabilityProfile(
            symbol=symbol,
            base=base,
            bucket=CoinBucket.ILLIQUID,
            reason="ILLIQUID policy fallback -- unclassified asset, conservative downgrade",
        )


# -- Exposure tracker ----------------------------------------------------------

class RiskBucketExposureTracker:
    """
    Tracks per-coin exposure (filled + pending) and enforces bucket caps.

    Coin-level state is the single source of truth.  Bucket totals are always
    derived by summing coin exposures -- never tracked with incremental bucket
    counters -- so there is no risk of state drift.

    Usage
    -----
    1. Create at startup with the reference portfolio value.
    2. Before opening a position, call ``can_add``.
    3. After a fill, call ``set_filled`` to record the position.
    4. While tracking open orders, call ``set_pending``.
    5. On close or cancel, call ``clear_coin``.
    6. If the reference balance changes, call ``update_portfolio``.
    """

    def __init__(
        self,
        portfolio_value: float,
        config: Optional[RiskBucketConfig] = None,
        classifier: Optional[RiskBucketClassifier] = None,
    ):
        if portfolio_value <= 0:
            raise ValueError(f"portfolio_value must be > 0, got {portfolio_value}")
        self._portfolio = portfolio_value
        self._config = config or RiskBucketConfig()
        self._classifier = classifier or RiskBucketClassifier(self._config)
        self._filled: Dict[str, float] = {}              # base -> notional (filled positions)
        self._pending: Dict[str, float] = {}             # base -> notional (open orders)
        self._profiles: Dict[str, TradabilityProfile] = {}  # base -> assigned bucket profile

    def update_portfolio(self, value: float) -> None:
        """Update the reference portfolio value (must be > 0)."""
        if value <= 0:
            raise ValueError(f"portfolio_value must be > 0, got {value}")
        self._portfolio = value

    # -- Mutations -------------------------------------------------------------

    def set_filled(
        self,
        symbol: str,
        notional: float,
        metrics: Optional[MarketMetrics] = None,
    ) -> None:
        """
        Replace the filled position notional for *symbol*, storing its bucket profile.

        For non-manual assets without a stored profile, *metrics* is required.
        Manual-override assets (BTC, ETH, PENGU, ...) never need metrics.
        Subsequent calls for a coin that already has a stored profile may omit metrics.

        Raises
        ------
        ValueError
            If *notional* < 0, or if the coin is a new non-manual asset and *metrics*
            is None (prevents silent BLOCKED profile assignment on restore paths).
        """
        if notional < 0:
            raise ValueError(f"notional must be >= 0, got {notional}")
        base = _normalize_base(symbol)
        if base not in self._profiles:
            if base not in self._classifier._overrides and metrics is None:
                raise ValueError(
                    f"metrics required for new non-manual asset '{base}': "
                    f"cannot assign bucket without market data"
                )
            self._profiles[base] = self._classifier.classify(symbol, metrics)
        self._filled[base] = notional

    def set_pending(
        self,
        symbol: str,
        notional: float,
        metrics: Optional[MarketMetrics] = None,
    ) -> None:
        """
        Replace the pending/open-order notional for *symbol*, storing its bucket profile.

        For non-manual assets without a stored profile, *metrics* is required.
        Subsequent calls for a coin that already has a stored profile may omit metrics.

        Raises
        ------
        ValueError
            If *notional* < 0, or if the coin is a new non-manual asset and *metrics*
            is None.
        """
        if notional < 0:
            raise ValueError(f"notional must be >= 0, got {notional}")
        base = _normalize_base(symbol)
        if base not in self._profiles:
            if base not in self._classifier._overrides and metrics is None:
                raise ValueError(
                    f"metrics required for new non-manual asset '{base}': "
                    f"cannot assign bucket without market data"
                )
            self._profiles[base] = self._classifier.classify(symbol, metrics)
        self._pending[base] = notional

    def clear_coin(self, symbol: str) -> None:
        """Remove all tracked exposure (filled + pending) and stored profile for *symbol*."""
        base = _normalize_base(symbol)
        self._filled.pop(base, None)
        self._pending.pop(base, None)
        self._profiles.pop(base, None)

    # -- Derived reads ---------------------------------------------------------

    def get_coin_total(self, symbol: str) -> float:
        """Return total (filled + pending) notional for *symbol*."""
        base = _normalize_base(symbol)
        return self._filled.get(base, 0.0) + self._pending.get(base, 0.0)

    def _get_stored_profile(self, base: str) -> TradabilityProfile:
        """
        Return the stored profile for *base*, falling back to a no-metrics
        classification for coins that were never passed through can_add().
        For manually-overridden coins (BTC/ETH/DOGE/...) this is always correct.
        For data-driven coins this returns BLOCKED, which is the safe default.
        """
        return self._profiles.get(base) or self._classifier.classify(base)

    def get_bucket_total(self, bucket: CoinBucket) -> float:
        """Return total notional allocated to *bucket*, derived from stored coin profiles."""
        all_bases = set(self._filled) | set(self._pending)
        total = 0.0
        for base in all_bases:
            if self._get_stored_profile(base).bucket == bucket:
                total += self._filled.get(base, 0.0) + self._pending.get(base, 0.0)
        return total

    def get_bucket_pct(self, bucket: CoinBucket) -> float:
        """Return current allocation percentage for *bucket*."""
        return (self.get_bucket_total(bucket) / self._portfolio) * 100.0

    # -- Pre-trade check -------------------------------------------------------

    def can_add(
        self,
        symbol: str,
        additional_notional: float,
        metrics: Optional[MarketMetrics] = None,
    ) -> tuple[bool, str]:
        """
        Check whether adding *additional_notional* for *symbol* stays within limits.

        This method is read-only -- it does **not** mutate state.  Profile storage
        happens in ``set_pending()`` / ``set_filled()`` after the order is placed.

        If the coin already has a stored profile (i.e. it already has exposure),
        that profile is reused -- the bucket does not change mid-position.
        For new coins, classification is done fresh with *metrics*.

        Returns
        -------
        (allowed, reason) : tuple[bool, str]
            *reason* always includes bucket, current %, requested %, projected %,
            and configured max % for easy diagnostics.
        """
        if additional_notional <= 0:
            return False, f"invalid additional_notional={additional_notional} (must be > 0)"

        base = _normalize_base(symbol)

        # If the coin already has a stored profile (existing exposure), reuse it.
        # This locks the bucket for the duration of the position.
        # For new coins, classify fresh -- profile is NOT stored here.
        if base in self._profiles:
            profile = self._profiles[base]
        else:
            profile = self._classifier.classify(symbol, metrics)

        if profile.is_blocked:
            return False, f"BLOCKED -- {profile.reason}"

        bucket = profile.bucket
        max_pct = self._config.limits.get(bucket, 0.0)
        current_total = self.get_bucket_total(bucket)
        current_pct = (current_total / self._portfolio) * 100.0
        added_pct = (additional_notional / self._portfolio) * 100.0
        projected_pct = current_pct + added_pct

        if projected_pct > max_pct:
            return (
                False,
                (
                    f"bucket={bucket.value}"
                    f" current={current_pct:.1f}%"
                    f" + requested={added_pct:.1f}%"
                    f" = projected={projected_pct:.1f}%"
                    f" > max={max_pct:.1f}%"
                    f" | {profile.reason}"
                ),
            )

        return True, f"ok | {profile.reason}"


# -- Backward-compatible shims -------------------------------------------------

# Controller imports BucketExposureTracker by name -- keep the alias.
BucketExposureTracker = RiskBucketExposureTracker


def get_bucket(coin: str) -> CoinBucket:
    """
    Return the bucket for *coin* using manual overrides only (no market data).

    Unknown coins return BLOCKED. For data-driven classification, use
    RiskBucketClassifier.classify(symbol, metrics) directly.
    """
    return RiskBucketClassifier().classify(coin).bucket


def get_max_pct(coin: str) -> float:
    """
    Return the configured max allocation percentage for *coin*'s bucket.

    Uses manual overrides only -- unknown coins return the BLOCKED limit (0%).
    """
    return RiskBucketConfig().limits[get_bucket(coin)]


BUCKET_MAX_PCT: Dict[CoinBucket, float] = RiskBucketConfig().limits
