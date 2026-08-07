# momentum_filters.py — stateless hard filter for EnrichedCandidate objects.
# No I/O, no exchange calls, no scoring. Pure candidate → FilterResult logic.
import time
from typing import List, Optional

from multi_coin_grid_pro.signals.momentum_config import CandidateFilters, ServiceConfig, UniverseConfig
from multi_coin_grid_pro.signals.momentum_models import EnrichedCandidate, FilterResult, RejectedCandidate

# ---------------------------------------------------------------------------
# Rejection reason constants
# ---------------------------------------------------------------------------

REASON_BLACKLISTED = "BLACKLISTED"
REASON_ACTIVE_GRID = "ACTIVE_GRID_POSITION"
REASON_IN_COOLDOWN = "IN_COOLDOWN"
REASON_SPREAD_TOO_HIGH = "SPREAD_TOO_HIGH"
REASON_STALE_ORDERBOOK = "STALE_ORDERBOOK"
REASON_EXTREME_PUMP = "EXTREME_PUMP"
REASON_MOMENTUM_TOO_LOW = "MOMENTUM_TOO_LOW"
REASON_VOLUME_TOO_LOW = "VOLUME_TOO_LOW"
REASON_SCORE_TOO_LOW = "SCORE_TOO_LOW"
# Fine-grained missing-data reasons (replace legacy MISSING_MOMENTUM_DATA)
REASON_MISSING_PRICE_CHANGE_5M = "MISSING_PRICE_CHANGE_5M"
REASON_MISSING_PRICE_CHANGE_15M = "MISSING_PRICE_CHANGE_15M"
REASON_MISSING_VOLUME_RATIO = "MISSING_VOLUME_RATIO"
# Deprecated alias — constant kept for backward compat but no longer emitted by the filter
REASON_MISSING_MOMENTUM_DATA = "MISSING_MOMENTUM_DATA"
REASON_STABLECOIN_OR_FOREX = "STABLECOIN_OR_FOREX"
REASON_EXCLUDED_ASSET_TYPE = "EXCLUDED_ASSET_TYPE"
REASON_EXCLUDED_MAJOR_ASSET = "EXCLUDED_MAJOR_ASSET"
# US-207: entry-quality rejection reasons
REASON_TOO_LATE_EXTENDED_MOVE = "TOO_LATE_EXTENDED_MOVE"
REASON_SPIKE_NO_CONTINUATION = "SPIKE_NO_CONTINUATION"
REASON_NO_SHORT_TERM_ACCELERATION = "NO_SHORT_TERM_ACCELERATION"
REASON_ORDERBOOK_TOO_THIN = "ORDERBOOK_TOO_THIN"
REASON_SPREAD_TOO_HIGH_FOR_ENTRY = "SPREAD_TOO_HIGH_FOR_ENTRY"
REASON_VOLUME_SPIKE_TOO_EXTREME = "VOLUME_SPIKE_TOO_EXTREME"

# ---------------------------------------------------------------------------
# Known asset sets for universe filtering
# ---------------------------------------------------------------------------

_KNOWN_STABLECOINS: frozenset = frozenset({
    "USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "GUSD",
    "LUSD", "FRAX", "USDE", "EURT", "RLUSD", "FDUSD", "PYUSD",
    "USDS", "CRVUSD",
})

_KNOWN_FIAT: frozenset = frozenset({
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD",
    "HKD", "SGD", "SEK", "NOK", "DKK",
})

_KNOWN_METALS: frozenset = frozenset({"XAUT", "PAXG", "XAGW", "GOLD"})


class HardFilter:
    """Stateless hard-filter pipeline for ``EnrichedCandidate`` objects.

    Collects ALL failing reasons per candidate.  A candidate is accepted only
    when no reasons apply.  Ordering of reason-checks: cheapest (flag-based)
    first, then data-quality checks, then numeric thresholds.

    This class has no I/O, no exchange calls, and no scoring dependency.
    """

    def apply(
        self,
        candidates: List[EnrichedCandidate],
        config: ServiceConfig,
        now: Optional[float] = None,
    ) -> FilterResult:
        """Filter *candidates* and return a :class:`FilterResult`.

        Args:
            candidates: list of enriched candidates to evaluate.
            config: service config providing filter thresholds.
            now: current epoch time (injectable for tests; defaults to time.time()).
        """
        if now is None:
            now = time.time()

        cf = config.candidate_filters
        uc = config.universe
        accepted: List[EnrichedCandidate] = []
        rejected: List[RejectedCandidate] = []

        for candidate in candidates:
            reasons = self._collect_reasons(candidate, cf, now, uc)
            if reasons:
                rejected.append(RejectedCandidate(
                    candidate=candidate,
                    rejection_reason=reasons[0],
                    all_reasons=reasons,
                ))
            else:
                accepted.append(candidate)

        return FilterResult(accepted=accepted, rejected=rejected)

    def _collect_reasons(
        self,
        candidate: EnrichedCandidate,
        cf: CandidateFilters,
        now: float,
        universe: Optional[UniverseConfig] = None,
    ) -> List[str]:
        reasons: List[str] = []

        # ── State-based (cheapest) ───────────────────────────────────────────
        if cf.exclude_blacklisted and candidate.blacklisted:
            reasons.append(REASON_BLACKLISTED)
        if cf.exclude_active_grid_positions and candidate.active_grid_position:
            reasons.append(REASON_ACTIVE_GRID)
        if cf.exclude_cooldown_pairs and candidate.in_cooldown:
            reasons.append(REASON_IN_COOLDOWN)

        # ── Universe filter ──────────────────────────────────────────────────
        if universe is not None:
            reasons.extend(self._universe_reasons(candidate, universe))

        # ── Missing momentum data — per-field (verplicht vóór numerieke checks) ─
        if candidate.price_change_5m_pct is None:
            reasons.append(REASON_MISSING_PRICE_CHANGE_5M)
        if candidate.price_change_15m_pct is None:
            reasons.append(REASON_MISSING_PRICE_CHANGE_15M)
        if candidate.volume_ratio is None:
            reasons.append(REASON_MISSING_VOLUME_RATIO)
        missing_data = (
            candidate.price_change_5m_pct is None
            or candidate.price_change_15m_pct is None
            or candidate.volume_ratio is None
        )

        # ── Data quality ─────────────────────────────────────────────────────
        if candidate.spread_pct > cf.max_spread_pct:
            reasons.append(REASON_SPREAD_TOO_HIGH)

        if candidate.ob_fetched_at > 0:
            ob_age = now - candidate.ob_fetched_at
            if ob_age > cf.max_orderbook_staleness_seconds:
                reasons.append(REASON_STALE_ORDERBOOK)

        # ── Numeric momentum/volume (alleen als data beschikbaar) ─────────────
        if not missing_data:
            p15 = candidate.price_change_15m_pct
            p5 = candidate.price_change_5m_pct

            if p15 > cf.max_price_change_15m_pct:  # type: ignore[operator]
                reasons.append(REASON_EXTREME_PUMP)

            momentum_fail = False
            if p5 < cf.min_price_change_5m_pct:  # type: ignore[operator]
                momentum_fail = True
            if p15 < cf.min_price_change_15m_pct:  # type: ignore[operator]
                momentum_fail = True
            if momentum_fail:
                reasons.append(REASON_MOMENTUM_TOO_LOW)

            vol = candidate.volume_ratio
            if vol < cf.min_volume_ratio:  # type: ignore[operator]
                reasons.append(REASON_VOLUME_TOO_LOW)

        # ── US-207: entry quality filters ────────────────────────────────────
        # TOO_LATE_EXTENDED_MOVE — 15m move too large for safe entry
        if cf.max_too_late_price_change_15m_pct > 0.0:
            p15e = candidate.price_change_15m_pct
            if p15e is not None and p15e > cf.max_too_late_price_change_15m_pct:
                reasons.append(REASON_TOO_LATE_EXTENDED_MOVE)

        # SPIKE_NO_CONTINUATION — single-candle spike, not sustainable
        if cf.max_price_change_5m_pct > 0.0:
            p5e = candidate.price_change_5m_pct
            if p5e is not None and p5e > cf.max_price_change_5m_pct:
                reasons.append(REASON_SPIKE_NO_CONTINUATION)

        # NO_SHORT_TERM_ACCELERATION — no recent 1m/3m movement or accel score = 0
        _no_accel = False
        if cf.min_price_change_1m_pct > 0.0:
            p1 = candidate.price_change_1m_pct
            if p1 is not None and p1 < cf.min_price_change_1m_pct:
                _no_accel = True
        if cf.min_price_change_3m_pct > 0.0:
            p3 = candidate.price_change_3m_pct
            if p3 is not None and p3 < cf.min_price_change_3m_pct:
                _no_accel = True
        if cf.require_acceleration:
            accel = candidate.acceleration_score
            if accel is None or accel == 0.0:
                _no_accel = True
        if _no_accel:
            reasons.append(REASON_NO_SHORT_TERM_ACCELERATION)

        # ORDERBOOK_TOO_THIN — slippage too high for €100 order
        if cf.max_estimated_slippage_pct > 0.0:
            slip = candidate.slippage_100eur
            if slip is not None and slip > cf.max_estimated_slippage_pct:
                reasons.append(REASON_ORDERBOOK_TOO_THIN)

        # SPREAD_TOO_HIGH_FOR_ENTRY — tighter spread check for entry quality
        # spread_pct is in percentage points (e.g. 0.15 means 0.15%, not 15%).
        if cf.max_spread_pct_entry > 0.0:
            if candidate.spread_pct > cf.max_spread_pct_entry:
                if REASON_SPREAD_TOO_HIGH not in reasons:  # avoid double-reporting
                    reasons.append(REASON_SPREAD_TOO_HIGH_FOR_ENTRY)

        # VOLUME_SPIKE_TOO_EXTREME — extremely high volume_ratio is a thin-market
        # artefact or already-over move; not informative for momentum entry.
        if cf.max_volume_ratio > 0.0:
            vol2 = candidate.volume_ratio
            if vol2 is not None and vol2 > cf.max_volume_ratio:
                reasons.append(REASON_VOLUME_SPIKE_TOO_EXTREME)

        return reasons

    def _universe_reasons(
        self,
        candidate: EnrichedCandidate,
        uc: UniverseConfig,
    ) -> List[str]:
        """Return rejection reasons driven by universe config."""
        reasons: List[str] = []
        pair = candidate.trading_pair
        base = pair.split("-")[0] if "-" in pair else pair

        if uc.exclude_stablecoins and base in _KNOWN_STABLECOINS:
            reasons.append(REASON_STABLECOIN_OR_FOREX)
        elif uc.exclude_forex_pairs and base in _KNOWN_FIAT:
            reasons.append(REASON_STABLECOIN_OR_FOREX)

        if uc.exclude_tokenized_metals and base in _KNOWN_METALS:
            reasons.append(REASON_EXCLUDED_ASSET_TYPE)

        excluded_set = set(uc.excluded_base_assets)
        if (
            uc.exclude_major_assets
            and base in excluded_set
            and REASON_STABLECOIN_OR_FOREX not in reasons
            and REASON_EXCLUDED_ASSET_TYPE not in reasons
        ):
            reasons.append(REASON_EXCLUDED_MAJOR_ASSET)

        return reasons
