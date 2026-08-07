# momentum_preselection.py — pre-enrichment filtering and ranking.
# Pure logic module: no I/O, no HTTP, no exchange calls, no order creation.
# Applied before candle/orderbook enrichment to pick the most promising
# momentum candidates from the full ticker universe.
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from multi_coin_grid_pro.signals.momentum_config import PreselectionConfig, ServiceConfig
from multi_coin_grid_pro.signals.momentum_filters import _KNOWN_FIAT, _KNOWN_METALS, _KNOWN_STABLECOINS
from multi_coin_grid_pro.signals.momentum_models import (
    EnrichedCandidate,
    ExchangePreselectionStats,
    PreselectionCandidate,
    PreselectionReport,
)

logger = logging.getLogger(__name__)

# Rejection reasons used in debug logging
REASON_PRESEL_STABLECOIN = "PRESEL_STABLECOIN_OR_FOREX"
REASON_PRESEL_METAL = "PRESEL_METAL"
REASON_PRESEL_MAJOR = "PRESEL_MAJOR_ASSET"
REASON_PRESEL_BLACKLISTED = "PRESEL_BLACKLISTED"
REASON_PRESEL_ACTIVE_GRID = "PRESEL_ACTIVE_GRID"
REASON_PRESEL_SPREAD = "PRESEL_SPREAD_TOO_HIGH"
REASON_PRESEL_VOLUME = "PRESEL_VOLUME_TOO_LOW"
REASON_PRESEL_CHANGE_TOO_SMALL = "PRESEL_ABS_CHANGE_TOO_SMALL"
REASON_PRESEL_CRASH = "PRESEL_CRASH_EXCLUDED"

_RR_INDEX: Dict[str, int] = {}  # round-robin state per exchange


def _base_asset(pair: str) -> str:
    return pair.split("-")[0] if "-" in pair else pair


def _passes_universe(candidate: EnrichedCandidate, config: ServiceConfig) -> Optional[str]:
    """Return rejection reason string, or None if candidate passes universe filter."""
    base = _base_asset(candidate.trading_pair)
    uc = config.universe

    if uc.exclude_stablecoins and base in _KNOWN_STABLECOINS:
        return REASON_PRESEL_STABLECOIN
    if uc.exclude_forex_pairs and base in _KNOWN_FIAT:
        return REASON_PRESEL_STABLECOIN
    if uc.exclude_tokenized_metals and base in _KNOWN_METALS:
        return REASON_PRESEL_METAL
    if uc.exclude_major_assets and base in set(uc.excluded_base_assets):
        return REASON_PRESEL_MAJOR
    if candidate.blacklisted:
        return REASON_PRESEL_BLACKLISTED
    if candidate.active_grid_position:
        return REASON_PRESEL_ACTIVE_GRID
    return None


def _change_24h_context_score(change: float, ctx) -> float:
    """Piecewise linear score [0, 1] for 24h change as context (not main criterion).

    Ideal zone → 1.0; heavy over-extension or deep red → near 0.0.
    Never hard-rejects — only adjusts the score component.
    """
    ideal_min = ctx.ideal_min_pct
    ideal_max = ctx.ideal_max_pct
    soft_low = ctx.soft_penalty_below_pct
    heavy_low = ctx.heavy_penalty_below_pct
    soft_high = ctx.soft_penalty_above_pct
    extreme_high = ctx.extreme_penalty_above_pct

    if ideal_min <= change <= ideal_max:
        return 1.0
    if change < ideal_min:
        if change >= soft_low:  # e.g. -8% to -2%: moderate penalty
            t = (change - soft_low) / (ideal_min - soft_low)
            return 0.5 + 0.5 * t
        if change >= heavy_low:  # e.g. -15% to -8%: heavy penalty
            t = (change - heavy_low) / (soft_low - heavy_low)
            return 0.15 + 0.35 * t
        return max(0.0, 0.15 + 0.15 * (change - heavy_low) / heavy_low)
    # change > ideal_max
    if change <= soft_high:  # e.g. +8% to +15%: light to moderate penalty
        t = (soft_high - change) / (soft_high - ideal_max)
        return 0.5 + 0.5 * t
    if change <= extreme_high:  # e.g. +15% to +25%: heavy penalty
        t = (extreme_high - change) / (extreme_high - soft_high)
        return 0.1 + 0.4 * t
    return max(0.0, 0.1 - 0.1 * (change - extreme_high) / extreme_high)


def _compute_pre_score(
    candidate: EnrichedCandidate,
    ps: PreselectionConfig,
    max_vol: float,
) -> Tuple[float, Dict]:
    """Compute a normalized pre_score in [0.0, 1.0] and a full breakdown dict.

    New weights:
      quote_volume_24h_weight  — primary: liquidity
      spread_quality_weight    — secondary: entry cost
      range_position_24h_weight — tertiary: proximity to 24h high
      change_24h_context_weight — context: not too extended, not too red
    """
    import math
    fallbacks_used: list = []

    # 1. Volume score [0, 1] — log-normalised to reduce dominance of outliers
    vol = candidate.quote_volume_24h or 0.0
    if max_vol > 0 and vol > 0:
        norm_vol = math.log1p(vol) / math.log1p(max_vol)
    else:
        norm_vol = 0.0

    # 2. Spread quality [0, 1] — tighter is better
    max_spread = ps.max_spread_pct if ps.max_spread_pct > 0 else 1.0
    spread_quality = max(0.0, 1.0 - candidate.spread_pct / max_spread)

    # 3. Range position [0, 1] — close to 24h high = more strength
    h = candidate.high_24h
    low = candidate.low_24h
    price = candidate.price
    if h is not None and low is not None and h > low:
        range_pos = (price - low) / (h - low)
        range_source = "high_low"
    elif h is not None and low is not None and h == low:
        range_pos = 0.5
        range_source = "fallback_flat_range"
        fallbacks_used.append("high_equals_low")
    else:
        range_pos = 0.5
        range_source = "fallback_missing_high_low"
        if h is None:
            fallbacks_used.append("missing_high_24h")
        if low is None:
            fallbacks_used.append("missing_low_24h")
    range_pos = min(1.0, max(0.0, range_pos))

    # 4. 24h change context score [0, 1]
    change = candidate.price_change_24h_pct or 0.0
    ctx_score = _change_24h_context_score(change, ps.change_24h_context)

    score = (
        ps.quote_volume_24h_weight * norm_vol
        + ps.spread_quality_weight * spread_quality
        + ps.range_position_24h_weight * range_pos
        + ps.change_24h_context_weight * ctx_score
    )
    final_score = min(1.0, max(0.0, score))

    breakdown: Dict = {
        "quote_volume_24h": vol if vol > 0 else None,
        "quote_volume_score": round(norm_vol, 4),
        "spread_pct": round(candidate.spread_pct, 4),
        "spread_score": round(spread_quality, 4),
        "high_24h": h,
        "low_24h": low,
        "range_position_24h": round(range_pos, 4),
        "range_position_source": range_source,
        "price_change_24h_pct": round(change, 4) if change else None,
        "change_24h_context_score": round(ctx_score, 4),
        "preselection_score": round(final_score, 4),
        "fallbacks_used": fallbacks_used,
    }
    # compact summary for internal use
    _summary = {
        "vol": round(norm_vol, 3),
        "spread": round(spread_quality, 3),
        "range": round(range_pos, 3),
        "ctx": round(ctx_score, 3),
    }
    return final_score, breakdown, _summary


def apply_preselection(
    candidates: List[EnrichedCandidate],
    config: ServiceConfig,
    max_per_exchange: int,
) -> Tuple[List[EnrichedCandidate], PreselectionReport]:
    """Apply pre-enrichment filters + ranking. Returns (selected, report).

    ``candidates`` must already have ``blacklisted`` and ``active_grid_position``
    flags set by ``_annotate()`` in the service.

    Selection uses three buckets (configurable via preselection.buckets):
    - top_score: best coins by composite pre_score
    - top_quote_volume: most liquid coins not already in top_score
    - rotating_round_robin: rotating coverage to avoid blind spots

    The function is pure except for logging and the module-level _RR_INDEX state.
    """
    ps = config.preselection
    bkt = ps.buckets

    # Build lookup for exchange metadata
    exchange_cfg_map = {cfg.exchange.lower(): cfg for cfg in config.exchanges}

    # Group by exchange
    by_exchange: Dict[str, List[EnrichedCandidate]] = {}
    for c in candidates:
        by_exchange.setdefault(c.exchange.lower(), []).append(c)

    selected_all: List[EnrichedCandidate] = []
    stats_by_exchange: List[ExchangePreselectionStats] = []

    for exchange, exc_candidates in by_exchange.items():
        exc_cfg = exchange_cfg_map.get(exchange)
        stats = ExchangePreselectionStats(
            exchange=exchange,
            universe_total=len(exc_candidates),
            region=exc_cfg.region if exc_cfg is not None else "global",
            allowed_quote_assets=(
                exc_cfg.effective_quote_assets() if exc_cfg is not None else []
            ),
            enabled=exc_cfg.enabled if exc_cfg is not None else True,
        )

        # 1. Universe + basic pre-filters
        eligible: List[EnrichedCandidate] = []
        n_missing_change = 0

        for c in exc_candidates:
            reason = _passes_universe(c, config)
            if reason is not None:
                continue

            if c.spread_pct > ps.max_spread_pct:
                continue

            if c.quote_volume_24h is not None and c.quote_volume_24h < ps.min_quote_volume_24h:
                continue

            change = c.price_change_24h_pct
            if change is None:
                n_missing_change += 1
            else:
                if abs(change) < ps.min_abs_24h_change_pct:
                    continue
                # Hard reject only when explicitly configured (default -20 is very permissive)
                if ps.exclude_negative_24h_change_below_pct > -100.0 and change < ps.exclude_negative_24h_change_below_pct:
                    continue

            eligible.append(c)

        if n_missing_change > 0:
            logger.info(
                "[MISSING_TICKER_24H_CHANGE] %s: %d/%d eligible pairs missing 24h change data",
                exchange, n_missing_change, len(eligible),
            )

        stats.eligible = len(eligible)

        if not eligible:
            stats_by_exchange.append(stats)
            continue

        # 2. Compute pre_score (log-normalised volume within this exchange)
        volumes = [c.quote_volume_24h for c in eligible if c.quote_volume_24h is not None]
        max_vol = max(volumes) if volumes else 1.0

        scored: List[Tuple[EnrichedCandidate, float, Dict, Dict]] = []
        for c in eligible:
            score, breakdown, summary = _compute_pre_score(c, ps, max_vol)
            scored.append((c, score, breakdown, summary))

        scored.sort(key=lambda x: -x[1])

        # Annotate each eligible candidate with its rank and score
        rank_map: Dict[str, Tuple[int, float, Dict, Dict]] = {}
        for rank_idx, (c, score, breakdown, summary) in enumerate(scored, start=1):
            rank_map[c.trading_pair] = (rank_idx, score, breakdown, summary)

        # 3. Bucket selection
        selected_pairs: set = set()
        selected: List[EnrichedCandidate] = []

        def _annotate_candidate(candidate: EnrichedCandidate, bucket: str) -> None:
            rank_idx, score, breakdown, _ = rank_map.get(
                candidate.trading_pair, (None, None, {}, {})
            )
            bd = dict(breakdown)
            bd["selected_bucket"] = bucket
            candidate.preselection_score = score
            candidate.preselection_rank = rank_idx
            candidate.preselection_bucket = bucket
            candidate.preselection_breakdown = bd

        # Bucket A: top_score
        n_a = min(bkt.top_score, max_per_exchange)
        for c, score, _, _ in scored[:n_a]:
            selected_pairs.add(c.trading_pair)
            _annotate_candidate(c, "top_score")
            selected.append(c)

        # Bucket B: top_quote_volume (liquidity coverage, not already in A)
        n_b = min(bkt.top_quote_volume, max_per_exchange - len(selected))
        by_volume = sorted(
            eligible, key=lambda c: c.quote_volume_24h or 0.0, reverse=True
        )
        for c in by_volume:
            if n_b <= 0:
                break
            if c.trading_pair not in selected_pairs:
                selected_pairs.add(c.trading_pair)
                _annotate_candidate(c, "top_quote_volume")
                selected.append(c)
                n_b -= 1

        # Bucket C: round-robin (avoid blind spots)
        n_c = min(bkt.rotating_round_robin, max_per_exchange - len(selected))
        if n_c > 0:
            rr_pool = [c for c in eligible if c.trading_pair not in selected_pairs]
            if rr_pool:
                idx = _RR_INDEX.get(exchange, 0) % len(rr_pool)
                for i in range(n_c):
                    c = rr_pool[(idx + i) % len(rr_pool)]
                    if c.trading_pair not in selected_pairs:
                        selected_pairs.add(c.trading_pair)
                        _annotate_candidate(c, "rotating_round_robin")
                        selected.append(c)
                _RR_INDEX[exchange] = (idx + n_c) % len(rr_pool)

        stats.selected = len(selected)

        # 4. Top examples for the report (up to 10, from top_score bucket)
        top_examples: List[PreselectionCandidate] = []
        for c, score, breakdown, summary in scored[:10]:
            logger.debug(
                "[PRESEL] %s %s score=%.3f vol=%.3f spread=%.3f range=%.3f ctx=%.3f",
                exchange, c.trading_pair, score,
                summary["vol"], summary["spread"],
                summary["range"], summary["ctx"],
            )
            top_examples.append(PreselectionCandidate(
                exchange=c.exchange,
                trading_pair=c.trading_pair,
                spread_pct=c.spread_pct,
                quote_volume_24h=c.quote_volume_24h,
                price_change_24h_pct=c.price_change_24h_pct,
                pre_score=score,
            ))
        stats.top_examples = top_examples

        selected_all.extend(selected)
        stats_by_exchange.append(stats)

    return selected_all, PreselectionReport(by_exchange=stats_by_exchange)
