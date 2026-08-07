# test_signal_preselection.py — unit tests for momentum_preselection.py
# Pure logic tests. No HTTP calls, no DB, no asyncio.
from typing import Optional

from multi_coin_grid_pro.signals.momentum_config import PreselectionConfig, ServiceConfig, UniverseConfig
from multi_coin_grid_pro.signals.momentum_models import EnrichedCandidate
from multi_coin_grid_pro.signals.momentum_preselection import (
    REASON_PRESEL_ACTIVE_GRID,
    REASON_PRESEL_BLACKLISTED,
    REASON_PRESEL_MAJOR,
    REASON_PRESEL_METAL,
    REASON_PRESEL_STABLECOIN,
    _compute_pre_score,
    _passes_universe,
    apply_preselection,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(
    exchange: str = "kraken",
    pair: str = "SOL-USD",
    spread_pct: float = 0.05,
    quote_volume_24h: Optional[float] = 500_000.0,
    price_change_24h_pct: Optional[float] = 5.0,
    blacklisted: bool = False,
    active_grid_position: bool = False,
) -> EnrichedCandidate:
    return EnrichedCandidate(
        exchange=exchange,
        trading_pair=pair,
        price=100.0,
        bid=99.95,
        ask=100.05,
        spread_pct=spread_pct,
        quote_volume_24h=quote_volume_24h,
        price_change_24h_pct=price_change_24h_pct,
        blacklisted=blacklisted,
        active_grid_position=active_grid_position,
    )


def _config(
    exclude_stablecoins: bool = True,
    exclude_forex_pairs: bool = True,
    exclude_metals: bool = True,
    exclude_majors: bool = False,
    excluded_base_assets: list = None,
    preselection: Optional[PreselectionConfig] = None,
) -> ServiceConfig:
    return ServiceConfig(
        universe=UniverseConfig(
            exclude_stablecoins=exclude_stablecoins,
            exclude_forex_pairs=exclude_forex_pairs,
            exclude_tokenized_metals=exclude_metals,
            exclude_major_assets=exclude_majors,
            excluded_base_assets=excluded_base_assets or [],
        ),
        preselection=preselection or PreselectionConfig(),
    )


# ---------------------------------------------------------------------------
# _passes_universe — stablecoins / forex / metals / majors / blacklist / grid
# ---------------------------------------------------------------------------

class TestPassesUniverse:

    def test_stablecoin_rejected(self) -> None:
        c = _candidate(pair="USDT-USD")
        assert _passes_universe(c, _config()) == REASON_PRESEL_STABLECOIN

    def test_stablecoin_usdc_rejected(self) -> None:
        c = _candidate(pair="USDC-USDT")
        assert _passes_universe(c, _config()) == REASON_PRESEL_STABLECOIN

    def test_forex_pair_rejected(self) -> None:
        c = _candidate(pair="EUR-USD")
        assert _passes_universe(c, _config()) == REASON_PRESEL_STABLECOIN

    def test_metal_rejected(self) -> None:
        c = _candidate(pair="XAUT-USD")
        assert _passes_universe(c, _config()) == REASON_PRESEL_METAL

    def test_paxg_rejected(self) -> None:
        c = _candidate(pair="PAXG-USDT")
        assert _passes_universe(c, _config()) == REASON_PRESEL_METAL

    def test_major_rejected_when_enabled(self) -> None:
        c = _candidate(pair="BTC-USD")
        cfg = _config(exclude_majors=True, excluded_base_assets=["BTC", "ETH"])
        assert _passes_universe(c, cfg) == REASON_PRESEL_MAJOR

    def test_major_allowed_when_disabled(self) -> None:
        c = _candidate(pair="BTC-USD")
        cfg = _config(exclude_majors=False, excluded_base_assets=["BTC", "ETH"])
        assert _passes_universe(c, cfg) is None

    def test_blacklisted_rejected(self) -> None:
        c = _candidate(pair="SOL-USD", blacklisted=True)
        assert _passes_universe(c, _config()) == REASON_PRESEL_BLACKLISTED

    def test_active_grid_rejected(self) -> None:
        c = _candidate(pair="SOL-USD", active_grid_position=True)
        assert _passes_universe(c, _config()) == REASON_PRESEL_ACTIVE_GRID

    def test_normal_candidate_passes(self) -> None:
        c = _candidate(pair="SOL-USD")
        assert _passes_universe(c, _config()) is None


# ---------------------------------------------------------------------------
# apply_preselection — filters and ranking
# ---------------------------------------------------------------------------

class TestApplyPreselectionFilters:

    def test_excludes_stablecoins(self) -> None:
        candidates = [
            _candidate(pair="USDT-USD"),
            _candidate(pair="SOL-USD"),
        ]
        selected, report = apply_preselection(candidates, _config(), max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "USDT-USD" not in pairs
        assert "SOL-USD" in pairs

    def test_excludes_metals(self) -> None:
        candidates = [
            _candidate(pair="XAUT-USD"),
            _candidate(pair="SOL-USD"),
        ]
        selected, report = apply_preselection(candidates, _config(), max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "XAUT-USD" not in pairs

    def test_excludes_majors_when_enabled(self) -> None:
        cfg = _config(exclude_majors=True, excluded_base_assets=["BTC", "ETH"])
        candidates = [
            _candidate(pair="BTC-USD"),
            _candidate(pair="SOL-USD"),
        ]
        selected, _ = apply_preselection(candidates, cfg, max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "BTC-USD" not in pairs
        assert "SOL-USD" in pairs

    def test_excludes_blacklisted(self) -> None:
        candidates = [
            _candidate(pair="BAD-USD", blacklisted=True),
            _candidate(pair="SOL-USD"),
        ]
        selected, _ = apply_preselection(candidates, _config(), max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "BAD-USD" not in pairs

    def test_excludes_active_grid_pairs(self) -> None:
        candidates = [
            _candidate(pair="ACTIVE-USD", active_grid_position=True),
            _candidate(pair="SOL-USD"),
        ]
        selected, _ = apply_preselection(candidates, _config(), max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "ACTIVE-USD" not in pairs

    def test_excludes_low_volume(self) -> None:
        ps = PreselectionConfig(min_quote_volume_24h=500_000.0)
        candidates = [
            _candidate(pair="LOW-USD", quote_volume_24h=10_000.0),
            _candidate(pair="SOL-USD", quote_volume_24h=1_000_000.0),
        ]
        selected, _ = apply_preselection(candidates, _config(preselection=ps), max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "LOW-USD" not in pairs
        assert "SOL-USD" in pairs

    def test_excludes_tiny_24h_change(self) -> None:
        ps = PreselectionConfig(min_abs_24h_change_pct=2.0)
        candidates = [
            _candidate(pair="FLAT-USD", price_change_24h_pct=0.3),
            _candidate(pair="SOL-USD", price_change_24h_pct=5.0),
        ]
        selected, _ = apply_preselection(candidates, _config(preselection=ps), max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "FLAT-USD" not in pairs
        assert "SOL-USD" in pairs

    def test_excludes_crash_pairs(self) -> None:
        ps = PreselectionConfig(exclude_negative_24h_change_below_pct=-15.0)
        candidates = [
            _candidate(pair="CRASH-USD", price_change_24h_pct=-25.0),
            _candidate(pair="SOL-USD", price_change_24h_pct=5.0),
        ]
        selected, _ = apply_preselection(candidates, _config(preselection=ps), max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "CRASH-USD" not in pairs

    def test_excludes_high_spread(self) -> None:
        ps = PreselectionConfig(max_spread_pct=0.2)
        candidates = [
            _candidate(pair="WIDE-USD", spread_pct=0.5),
            _candidate(pair="SOL-USD", spread_pct=0.05),
        ]
        selected, _ = apply_preselection(candidates, _config(preselection=ps), max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "WIDE-USD" not in pairs


class TestApplyPreselectionRanking:

    def test_selects_max_per_exchange(self) -> None:
        candidates = [_candidate(pair=f"TOK{i}-USD", price_change_24h_pct=float(i)) for i in range(20)]
        selected, report = apply_preselection(candidates, _config(), max_per_exchange=5)
        assert len(selected) == 5

    def test_high_24h_mover_ranks_above_low_spread_only(self) -> None:
        """A coin near 24h high should rank above an equally-liquid coin near 24h low."""
        ps = PreselectionConfig()
        high_range = _candidate(
            pair="MOVER-USD",
            spread_pct=0.10,
            quote_volume_24h=500_000.0,
            price_change_24h_pct=5.0,
        )
        high_range.high_24h = 1.1
        high_range.low_24h = 1.0
        high_range.price = 1.09   # near high → range_pos ≈ 0.9

        low_range = _candidate(
            pair="LIQUID-USD",
            spread_pct=0.10,
            quote_volume_24h=500_000.0,
            price_change_24h_pct=5.0,
        )
        low_range.high_24h = 1.1
        low_range.low_24h = 1.0
        low_range.price = 1.01   # near low → range_pos ≈ 0.1

        selected, report = apply_preselection(
            [high_range, low_range],
            _config(preselection=ps),
            max_per_exchange=2,
        )
        examples = report.by_exchange[0].top_examples
        scores = {ex.trading_pair: ex.pre_score for ex in examples}
        assert scores["MOVER-USD"] > scores["LIQUID-USD"]

    def test_positive_24h_change_ranks_above_negative_same_abs(self) -> None:
        """Positive mover should rank above negative mover with same |change|."""
        ps = PreselectionConfig(
            prefer_positive_24h_change=True,
            positive_change_weight=0.20,
        )
        pos = _candidate(pair="POS-USD", price_change_24h_pct=5.0)
        neg = _candidate(pair="NEG-USD", price_change_24h_pct=-5.0)
        selected, report = apply_preselection(
            [pos, neg], _config(preselection=ps), max_per_exchange=2
        )
        examples = report.by_exchange[0].top_examples
        scores = {ex.trading_pair: ex.pre_score for ex in examples}
        assert scores["POS-USD"] > scores["NEG-USD"]

    def test_missing_24h_change_included_not_excluded(self) -> None:
        """Candidates with None price_change_24h_pct should still be eligible."""
        candidates = [
            _candidate(pair="NOCHANGE-USD", price_change_24h_pct=None, quote_volume_24h=2_000_000.0),
            _candidate(pair="SOL-USD", price_change_24h_pct=3.0),
        ]
        selected, _ = apply_preselection(candidates, _config(), max_per_exchange=10)
        pairs = {c.trading_pair for c in selected}
        assert "NOCHANGE-USD" in pairs


class TestApplyPreselectionReport:

    def test_report_has_correct_counts(self) -> None:
        candidates = [
            _candidate(pair="USDT-USD"),       # filtered: stablecoin
            _candidate(pair="SOL-USD", price_change_24h_pct=5.0),
            _candidate(pair="DOGE-USD", price_change_24h_pct=3.0),
        ]
        _, report = apply_preselection(candidates, _config(), max_per_exchange=10)
        stats = report.by_exchange[0]
        assert stats.universe_total == 3
        assert stats.eligible == 2
        assert stats.selected == 2

    def test_report_top_examples_have_pre_score(self) -> None:
        candidates = [_candidate(pair=f"T{i}-USD", price_change_24h_pct=float(i + 2)) for i in range(5)]
        _, report = apply_preselection(candidates, _config(), max_per_exchange=10)
        for ex in report.by_exchange[0].top_examples:
            assert 0.0 <= ex.pre_score <= 1.0

    def test_report_total_properties(self) -> None:
        candidates = [
            _candidate(exchange="kraken", pair="SOL-USD"),
            _candidate(exchange="okx", pair="SOL-USDT"),
        ]
        _, report = apply_preselection(candidates, _config(), max_per_exchange=10)
        assert report.total_universe == 2
        assert report.total_selected == 2

    def test_empty_candidates_returns_empty(self) -> None:
        selected, report = apply_preselection([], _config(), max_per_exchange=10)
        assert selected == []
        assert report.by_exchange == []

    def test_all_filtered_gives_zero_selected(self) -> None:
        candidates = [_candidate(pair="USDT-USD"), _candidate(pair="USDC-USD")]
        selected, report = apply_preselection(candidates, _config(), max_per_exchange=10)
        assert selected == []
        assert report.by_exchange[0].eligible == 0
        assert report.by_exchange[0].selected == 0


class TestMissingTickerChange:

    def test_missing_change_logs_warning(self, caplog) -> None:
        """Candidates missing 24h change should trigger MISSING_TICKER_24H_CHANGE log."""
        import logging
        candidates = [
            _candidate(pair="NOCHANGE-USD", price_change_24h_pct=None, quote_volume_24h=2_000_000.0),
        ]
        with caplog.at_level(logging.INFO, logger="multi_coin_grid_pro.signals.momentum_preselection"):
            apply_preselection(candidates, _config(), max_per_exchange=10)
        assert any("MISSING_TICKER_24H_CHANGE" in r.message for r in caplog.records)

    def test_no_warning_when_all_have_change(self, caplog) -> None:
        import logging
        candidates = [_candidate(pair="SOL-USD", price_change_24h_pct=5.0)]
        with caplog.at_level(logging.INFO, logger="multi_coin_grid_pro.signals.momentum_preselection"):
            apply_preselection(candidates, _config(), max_per_exchange=10)
        assert not any("MISSING_TICKER_24H_CHANGE" in r.message for r in caplog.records)


class TestComputePreScore:

    def test_score_in_range(self) -> None:
        ps = PreselectionConfig()
        c = _candidate()
        score, _, _ = _compute_pre_score(c, ps, max_vol=1_000_000.0)
        assert 0.0 <= score <= 1.0

    def test_zero_volume_zero_change_still_valid(self) -> None:
        ps = PreselectionConfig()
        c = _candidate(quote_volume_24h=0.0, price_change_24h_pct=0.0)
        score, _, _ = _compute_pre_score(c, ps, max_vol=1.0)
        assert 0.0 <= score <= 1.0

    def test_max_values_give_high_score(self) -> None:
        """A candidate at max volume + in-ideal-zone change + tight spread scores ≥ 0.85."""
        ps = PreselectionConfig(max_spread_pct=1.0)
        c = _candidate(quote_volume_24h=1_000_000.0, price_change_24h_pct=5.0, spread_pct=0.01)
        score, _, _ = _compute_pre_score(c, ps, max_vol=1_000_000.0)
        assert score >= 0.85

    def test_weights_sum_respected(self) -> None:
        """A coin near 24h high scores higher than same coin near 24h low."""
        ps = PreselectionConfig()
        high_range = _candidate(pair="HIGH-USD", quote_volume_24h=500_000.0, price_change_24h_pct=4.0)
        high_range.high_24h = 2.0
        high_range.low_24h = 1.0
        high_range.price = 1.95  # near high

        low_range = _candidate(pair="LOW-USD", quote_volume_24h=500_000.0, price_change_24h_pct=4.0)
        low_range.high_24h = 2.0
        low_range.low_24h = 1.0
        low_range.price = 1.05  # near low

        score_high, _, _ = _compute_pre_score(high_range, ps, max_vol=500_000.0)
        score_low, _, _ = _compute_pre_score(low_range, ps, max_vol=500_000.0)
        assert score_high > score_low
