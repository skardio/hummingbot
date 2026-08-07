# test_signal_momentum_filters.py — unit tests for momentum_filters.py
import pytest

from multi_coin_grid_pro.signals.momentum_config import CandidateFilters, ServiceConfig
from multi_coin_grid_pro.signals.momentum_filters import (
    REASON_ACTIVE_GRID,
    REASON_BLACKLISTED,
    REASON_EXTREME_PUMP,
    REASON_IN_COOLDOWN,
    REASON_MISSING_PRICE_CHANGE_5M,
    REASON_MISSING_PRICE_CHANGE_15M,
    REASON_MISSING_VOLUME_RATIO,
    REASON_MOMENTUM_TOO_LOW,
    REASON_NO_SHORT_TERM_ACCELERATION,
    REASON_ORDERBOOK_TOO_THIN,
    REASON_SCORE_TOO_LOW,
    REASON_SPIKE_NO_CONTINUATION,
    REASON_SPREAD_TOO_HIGH,
    REASON_SPREAD_TOO_HIGH_FOR_ENTRY,
    REASON_STALE_ORDERBOOK,
    REASON_TOO_LATE_EXTENDED_MOVE,
    REASON_VOLUME_TOO_LOW,
    HardFilter,
)
from multi_coin_grid_pro.signals.momentum_models import EnrichedCandidate, FilterResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

NOW = 1_700_000_000.0


def make_candidate(**kwargs) -> EnrichedCandidate:
    """Return a valid passing candidate; override any field via kwargs."""
    defaults = dict(
        exchange="kraken",
        trading_pair="BTC-USD",
        price=100.0,
        bid=99.9,
        ask=100.1,
        spread_pct=0.10,           # well below max 0.35
        price_change_5m_pct=3.0,   # above min 2.0
        price_change_15m_pct=5.0,  # above min 4.0, below max 35.0
        volume_ratio=4.0,          # above min 3.0
        ob_fetched_at=NOW - 2.0,   # 2 s ago — fresh
        blacklisted=False,
        active_grid_position=False,
        in_cooldown=False,
    )
    defaults.update(kwargs)
    return EnrichedCandidate(**defaults)


def run_filter(candidates, **config_overrides) -> FilterResult:
    """Run HardFilter with default config, optional CandidateFilter overrides."""
    cf = CandidateFilters(**config_overrides) if config_overrides else CandidateFilters()
    cfg = ServiceConfig(mode="signal_only", candidate_filters=cf)
    return HardFilter().apply(candidates, config=cfg, now=NOW)


# ---------------------------------------------------------------------------
# Basic acceptance
# ---------------------------------------------------------------------------

class TestBasicAcceptance:

    def test_clean_candidate_is_accepted(self) -> None:
        result = run_filter([make_candidate()])
        assert result.n_accepted == 1
        assert result.n_rejected == 0

    def test_returns_filter_result_type(self) -> None:
        result = run_filter([make_candidate()])
        assert isinstance(result, FilterResult)

    def test_empty_input_returns_empty_result(self) -> None:
        result = run_filter([])
        assert result.n_accepted == 0
        assert result.n_rejected == 0

    def test_all_optional_fields_none_is_rejected(self) -> None:
        """Candidate with no momentum data is rejected; first reason is MISSING_PRICE_CHANGE_5M."""
        cand = EnrichedCandidate(
            exchange="kraken", trading_pair="ETH-USD",
            price=1.0, bid=0.99, ask=1.01, spread_pct=0.10,
            # All optional fields left as None / 0.0 defaults
        )
        result = run_filter([cand])
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_MISSING_PRICE_CHANGE_5M
        reasons = result.rejected[0].all_reasons
        assert REASON_MISSING_PRICE_CHANGE_15M in reasons
        assert REASON_MISSING_VOLUME_RATIO in reasons

    def test_multiple_clean_candidates_all_accepted(self) -> None:
        candidates = [make_candidate(trading_pair=f"C{i}-USD") for i in range(5)]
        result = run_filter(candidates)
        assert result.n_accepted == 5
        assert result.n_rejected == 0


# ---------------------------------------------------------------------------
# State-based filters
# ---------------------------------------------------------------------------

class TestStatBasedFilters:

    def test_blacklisted_is_rejected(self) -> None:
        result = run_filter([make_candidate(blacklisted=True)])
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_BLACKLISTED

    def test_active_grid_position_is_rejected(self) -> None:
        result = run_filter([make_candidate(active_grid_position=True)])
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_ACTIVE_GRID

    def test_in_cooldown_is_rejected(self) -> None:
        result = run_filter([make_candidate(in_cooldown=True)])
        assert result.n_rejected == 1
        assert result.rejected[0].rejection_reason == REASON_IN_COOLDOWN

    def test_blacklisted_not_excluded_when_flag_off(self) -> None:
        cf = CandidateFilters(exclude_blacklisted=False)
        cfg = ServiceConfig(mode="signal_only", candidate_filters=cf)
        cand = make_candidate(blacklisted=True)
        result = HardFilter().apply([cand], config=cfg, now=NOW)
        assert result.n_accepted == 1

    def test_active_grid_not_excluded_when_flag_off(self) -> None:
        cf = CandidateFilters(exclude_active_grid_positions=False)
        cfg = ServiceConfig(mode="signal_only", candidate_filters=cf)
        cand = make_candidate(active_grid_position=True)
        result = HardFilter().apply([cand], config=cfg, now=NOW)
        assert result.n_accepted == 1


# ---------------------------------------------------------------------------
# Spread filter
# ---------------------------------------------------------------------------

class TestSpreadFilter:

    def test_spread_too_high_rejected(self) -> None:
        result = run_filter([make_candidate(spread_pct=1.0)])  # > 0.35
        assert result.n_rejected == 1
        assert REASON_SPREAD_TOO_HIGH in result.rejected[0].all_reasons

    def test_spread_exactly_at_max_passes(self) -> None:
        result = run_filter([make_candidate(spread_pct=0.35)])
        assert result.n_accepted == 1

    def test_spread_just_above_max_rejected(self) -> None:
        result = run_filter([make_candidate(spread_pct=0.36)])
        assert result.n_rejected == 1


# ---------------------------------------------------------------------------
# Orderbook staleness filter
# ---------------------------------------------------------------------------

class TestStalenessFilter:

    def test_stale_orderbook_rejected(self) -> None:
        stale_time = NOW - 10.0   # 10 s ago, max is 5 s
        result = run_filter([make_candidate(ob_fetched_at=stale_time)])
        assert result.n_rejected == 1
        assert REASON_STALE_ORDERBOOK in result.rejected[0].all_reasons

    def test_fresh_orderbook_passes(self) -> None:
        fresh_time = NOW - 3.0    # 3 s ago
        result = run_filter([make_candidate(ob_fetched_at=fresh_time)])
        assert result.n_accepted == 1

    def test_ob_fetched_at_zero_skips_staleness_check(self) -> None:
        """ob_fetched_at=0.0 means orderbook not yet fetched — skip check."""
        result = run_filter([make_candidate(ob_fetched_at=0.0)])
        assert result.n_accepted == 1


# ---------------------------------------------------------------------------
# Extreme pump filter
# ---------------------------------------------------------------------------

class TestExtremePumpFilter:

    def test_extreme_pump_rejected(self) -> None:
        result = run_filter([make_candidate(price_change_15m_pct=40.0)])  # > 35.0
        assert result.n_rejected == 1
        assert REASON_EXTREME_PUMP in result.rejected[0].all_reasons

    def test_just_below_extreme_pump_passes(self) -> None:
        result = run_filter([make_candidate(price_change_15m_pct=34.9)])
        assert result.n_accepted == 1

    def test_price_change_15m_none_causes_missing_data_rejection(self) -> None:
        """price_change_15m_pct=None → REASON_MISSING_PRICE_CHANGE_15M rejection."""
        result = run_filter([make_candidate(price_change_15m_pct=None)])
        assert result.n_rejected == 1
        assert REASON_MISSING_PRICE_CHANGE_15M in result.rejected[0].all_reasons


# ---------------------------------------------------------------------------
# Momentum too low filter
# ---------------------------------------------------------------------------

class TestMomentumTooLowFilter:

    def test_p5_too_low_rejected(self) -> None:
        result = run_filter([make_candidate(price_change_5m_pct=0.5)])  # < 2.0
        assert result.n_rejected == 1
        assert REASON_MOMENTUM_TOO_LOW in result.rejected[0].all_reasons

    def test_p15_too_low_rejected(self) -> None:
        result = run_filter([make_candidate(price_change_15m_pct=1.0)])  # < 4.0
        assert result.n_rejected == 1
        assert REASON_MOMENTUM_TOO_LOW in result.rejected[0].all_reasons

    def test_both_too_low_only_one_reason_added(self) -> None:
        result = run_filter([make_candidate(price_change_5m_pct=0.1, price_change_15m_pct=0.5)])
        reasons = result.rejected[0].all_reasons
        assert reasons.count(REASON_MOMENTUM_TOO_LOW) == 1

    def test_none_p5_p15_causes_missing_data_rejection(self) -> None:
        """None price-change fields → specific MISSING_PRICE_CHANGE_* rejections."""
        result = run_filter([make_candidate(price_change_5m_pct=None, price_change_15m_pct=None)])
        assert result.n_rejected == 1
        reasons = result.rejected[0].all_reasons
        assert REASON_MISSING_PRICE_CHANGE_5M in reasons
        assert REASON_MISSING_PRICE_CHANGE_15M in reasons


# ---------------------------------------------------------------------------
# Volume filter
# ---------------------------------------------------------------------------

class TestVolumeFilter:

    def test_volume_too_low_rejected(self) -> None:
        result = run_filter([make_candidate(volume_ratio=1.0)])  # < 3.0
        assert result.n_rejected == 1
        assert REASON_VOLUME_TOO_LOW in result.rejected[0].all_reasons

    def test_volume_at_min_passes(self) -> None:
        result = run_filter([make_candidate(volume_ratio=3.0)])
        assert result.n_accepted == 1

    def test_volume_none_causes_missing_data_rejection(self) -> None:
        """volume_ratio=None → REASON_MISSING_VOLUME_RATIO rejection."""
        result = run_filter([make_candidate(volume_ratio=None)])
        assert result.n_rejected == 1
        assert REASON_MISSING_VOLUME_RATIO in result.rejected[0].all_reasons


# ---------------------------------------------------------------------------
# Multiple reasons
# ---------------------------------------------------------------------------

class TestMultipleReasons:

    def test_multiple_failures_all_collected(self) -> None:
        cand = make_candidate(
            blacklisted=True,
            spread_pct=1.0,
            volume_ratio=0.5,
        )
        result = run_filter([cand])
        reasons = result.rejected[0].all_reasons
        assert REASON_BLACKLISTED in reasons
        assert REASON_SPREAD_TOO_HIGH in reasons
        assert REASON_VOLUME_TOO_LOW in reasons

    def test_primary_reason_is_first_in_all_reasons(self) -> None:
        cand = make_candidate(blacklisted=True, spread_pct=1.0)
        result = run_filter([cand])
        rej = result.rejected[0]
        assert rej.rejection_reason == rej.all_reasons[0]

    def test_mixed_accepted_and_rejected(self) -> None:
        good = make_candidate(trading_pair="BTC-USD")
        bad = make_candidate(trading_pair="ETH-USD", blacklisted=True)
        result = run_filter([good, bad])
        assert result.n_accepted == 1
        assert result.n_rejected == 1
        assert result.accepted[0].trading_pair == "BTC-USD"
        assert result.rejected[0].candidate.trading_pair == "ETH-USD"


# ---------------------------------------------------------------------------
# FilterResult properties
# ---------------------------------------------------------------------------

class TestFilterResultProperties:

    def test_rejection_breakdown_counts(self) -> None:
        b = make_candidate(trading_pair="A-USD", blacklisted=True)
        s = make_candidate(trading_pair="B-USD", spread_pct=1.0)
        b2 = make_candidate(trading_pair="C-USD", blacklisted=True)
        result = run_filter([b, s, b2])
        bd = result.rejection_breakdown
        assert bd[REASON_BLACKLISTED] == 2
        assert bd[REASON_SPREAD_TOO_HIGH] == 1

    def test_now_injectable_for_determinism(self) -> None:
        """Passing now= must give deterministic results regardless of wall clock."""
        cand = make_candidate(ob_fetched_at=NOW - 2.0)
        cfg = ServiceConfig(mode="signal_only")
        r1 = HardFilter().apply([cand], config=cfg, now=NOW)
        r2 = HardFilter().apply([cand], config=cfg, now=NOW)
        assert r1.n_accepted == r2.n_accepted


# ---------------------------------------------------------------------------
# Reason constants existence (simple smoke test)
# ---------------------------------------------------------------------------

class TestReasonConstants:

    def test_reason_constants_are_strings(self) -> None:
        for reason in (
            REASON_BLACKLISTED, REASON_ACTIVE_GRID, REASON_IN_COOLDOWN,
            REASON_SPREAD_TOO_HIGH, REASON_STALE_ORDERBOOK, REASON_EXTREME_PUMP,
            REASON_MOMENTUM_TOO_LOW, REASON_VOLUME_TOO_LOW, REASON_SCORE_TOO_LOW,
            REASON_MISSING_PRICE_CHANGE_5M, REASON_MISSING_PRICE_CHANGE_15M,
            REASON_MISSING_VOLUME_RATIO,
            # US-207
            REASON_TOO_LATE_EXTENDED_MOVE, REASON_SPIKE_NO_CONTINUATION,
            REASON_NO_SHORT_TERM_ACCELERATION, REASON_ORDERBOOK_TOO_THIN,
            REASON_SPREAD_TOO_HIGH_FOR_ENTRY,
        ):
            assert isinstance(reason, str)
            assert len(reason) > 0

    @pytest.mark.parametrize("reason,expected", [
        (REASON_BLACKLISTED, "BLACKLISTED"),
        (REASON_ACTIVE_GRID, "ACTIVE_GRID_POSITION"),
        (REASON_SCORE_TOO_LOW, "SCORE_TOO_LOW"),
        (REASON_TOO_LATE_EXTENDED_MOVE, "TOO_LATE_EXTENDED_MOVE"),
        (REASON_SPIKE_NO_CONTINUATION, "SPIKE_NO_CONTINUATION"),
        (REASON_NO_SHORT_TERM_ACCELERATION, "NO_SHORT_TERM_ACCELERATION"),
        (REASON_ORDERBOOK_TOO_THIN, "ORDERBOOK_TOO_THIN"),
        (REASON_SPREAD_TOO_HIGH_FOR_ENTRY, "SPREAD_TOO_HIGH_FOR_ENTRY"),
    ])
    def test_reason_values(self, reason: str, expected: str) -> None:
        assert reason == expected


# ---------------------------------------------------------------------------
# US-207: entry quality filters
# ---------------------------------------------------------------------------

class TestUS207EntryQualityFilters:
    """Tests for the new hard-filter checks introduced in US-207."""

    # ── TOO_LATE_EXTENDED_MOVE ───────────────────────────────────────────────

    def test_too_late_extended_move_rejected(self) -> None:
        c = make_candidate(price_change_15m_pct=10.0)
        result = run_filter([c], max_too_late_price_change_15m_pct=9.0)
        assert REASON_TOO_LATE_EXTENDED_MOVE in result.rejected[0].all_reasons

    def test_too_late_exactly_at_threshold_passes(self) -> None:
        c = make_candidate(price_change_15m_pct=9.0)
        result = run_filter([c], max_too_late_price_change_15m_pct=9.0)
        assert REASON_TOO_LATE_EXTENDED_MOVE not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_too_late_disabled_when_zero(self) -> None:
        c = make_candidate(price_change_15m_pct=20.0)
        # max_too_late_price_change_15m_pct=0.0 = disabled; only EXTREME_PUMP at 35%
        result = run_filter([c], max_too_late_price_change_15m_pct=0.0)
        assert REASON_TOO_LATE_EXTENDED_MOVE not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_too_late_15m_none_does_not_raise(self) -> None:
        c = make_candidate(price_change_15m_pct=None)
        result = run_filter([c], max_too_late_price_change_15m_pct=9.0)
        # price_change_15m_pct=None → MISSING_PRICE_CHANGE_15M, not TOO_LATE
        reasons = result.rejected[0].all_reasons
        assert REASON_MISSING_PRICE_CHANGE_15M in reasons
        assert REASON_TOO_LATE_EXTENDED_MOVE not in reasons

    # ── SPIKE_NO_CONTINUATION ────────────────────────────────────────────────

    def test_spike_rejected(self) -> None:
        c = make_candidate(price_change_5m_pct=5.0)
        result = run_filter([c], max_price_change_5m_pct=4.5)
        assert REASON_SPIKE_NO_CONTINUATION in result.rejected[0].all_reasons

    def test_spike_exactly_at_threshold_passes(self) -> None:
        c = make_candidate(price_change_5m_pct=4.5)
        result = run_filter([c], max_price_change_5m_pct=4.5)
        assert REASON_SPIKE_NO_CONTINUATION not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_spike_disabled_when_zero(self) -> None:
        c = make_candidate(price_change_5m_pct=99.0)
        result = run_filter([c], max_price_change_5m_pct=0.0)
        assert REASON_SPIKE_NO_CONTINUATION not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    # ── NO_SHORT_TERM_ACCELERATION ───────────────────────────────────────────

    def test_1m_too_low_rejected(self) -> None:
        c = make_candidate(price_change_1m_pct=0.10)
        result = run_filter([c], min_price_change_1m_pct=0.20)
        assert REASON_NO_SHORT_TERM_ACCELERATION in result.rejected[0].all_reasons

    def test_1m_above_threshold_passes(self) -> None:
        c = make_candidate(price_change_1m_pct=0.30)
        result = run_filter([c], min_price_change_1m_pct=0.20)
        assert REASON_NO_SHORT_TERM_ACCELERATION not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_3m_too_low_rejected(self) -> None:
        c = make_candidate(price_change_3m_pct=0.30)
        result = run_filter([c], min_price_change_3m_pct=0.70)
        assert REASON_NO_SHORT_TERM_ACCELERATION in result.rejected[0].all_reasons

    def test_1m_none_skips_check(self) -> None:
        """If 1m data is None, the check is skipped (not rejected for missing data here)."""
        c = make_candidate(price_change_1m_pct=None)
        result = run_filter([c], min_price_change_1m_pct=0.20)
        assert REASON_NO_SHORT_TERM_ACCELERATION not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_require_acceleration_zero_score_rejected(self) -> None:
        c = make_candidate(acceleration_score=0.0)
        result = run_filter([c], require_acceleration=True)
        assert REASON_NO_SHORT_TERM_ACCELERATION in result.rejected[0].all_reasons

    def test_require_acceleration_none_score_rejected(self) -> None:
        c = make_candidate(acceleration_score=None)
        result = run_filter([c], require_acceleration=True)
        assert REASON_NO_SHORT_TERM_ACCELERATION in result.rejected[0].all_reasons

    def test_require_acceleration_positive_score_passes(self) -> None:
        c = make_candidate(acceleration_score=0.7)
        result = run_filter([c], require_acceleration=True)
        assert REASON_NO_SHORT_TERM_ACCELERATION not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_require_acceleration_false_allows_zero_score(self) -> None:
        c = make_candidate(acceleration_score=0.0)
        result = run_filter([c], require_acceleration=False)
        assert REASON_NO_SHORT_TERM_ACCELERATION not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    # ── ORDERBOOK_TOO_THIN ───────────────────────────────────────────────────

    def test_slippage_too_high_rejected(self) -> None:
        c = make_candidate(slippage_100eur=0.50)
        result = run_filter([c], max_estimated_slippage_pct=0.40)
        assert REASON_ORDERBOOK_TOO_THIN in result.rejected[0].all_reasons

    def test_slippage_below_threshold_passes(self) -> None:
        c = make_candidate(slippage_100eur=0.30)
        result = run_filter([c], max_estimated_slippage_pct=0.40)
        assert REASON_ORDERBOOK_TOO_THIN not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_slippage_none_skips_check(self) -> None:
        """No orderbook data → slippage is None → skip check (not rejected)."""
        c = make_candidate(slippage_100eur=None)
        result = run_filter([c], max_estimated_slippage_pct=0.40)
        assert REASON_ORDERBOOK_TOO_THIN not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_slippage_disabled_when_zero(self) -> None:
        c = make_candidate(slippage_100eur=99.0)
        result = run_filter([c], max_estimated_slippage_pct=0.0)
        assert REASON_ORDERBOOK_TOO_THIN not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    # ── SPREAD_TOO_HIGH_FOR_ENTRY ────────────────────────────────────────────

    def test_spread_entry_rejected(self) -> None:
        c = make_candidate(spread_pct=0.30)
        result = run_filter([c], max_spread_pct_entry=0.25)
        assert REASON_SPREAD_TOO_HIGH_FOR_ENTRY in result.rejected[0].all_reasons

    def test_spread_entry_below_threshold_passes(self) -> None:
        c = make_candidate(spread_pct=0.20)
        result = run_filter([c], max_spread_pct_entry=0.25)
        assert REASON_SPREAD_TOO_HIGH_FOR_ENTRY not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_spread_entry_disabled_when_zero(self) -> None:
        c = make_candidate(spread_pct=0.99)
        # max_spread_pct_entry=0 = disabled; existing SPREAD_TOO_HIGH check still fires
        result = run_filter([c], max_spread_pct=0.50, max_spread_pct_entry=0.0)
        assert REASON_SPREAD_TOO_HIGH_FOR_ENTRY not in (
            result.rejected[0].all_reasons if result.n_rejected else []
        )

    def test_spread_entry_no_double_reason_when_also_too_high(self) -> None:
        """If SPREAD_TOO_HIGH already fired, SPREAD_TOO_HIGH_FOR_ENTRY is not added."""
        c = make_candidate(spread_pct=0.40)  # above both thresholds
        result = run_filter([c], max_spread_pct=0.35, max_spread_pct_entry=0.25)
        reasons = result.rejected[0].all_reasons
        assert REASON_SPREAD_TOO_HIGH in reasons
        assert REASON_SPREAD_TOO_HIGH_FOR_ENTRY not in reasons
