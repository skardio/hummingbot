"""
Tests for ST-02: Universe Quality Gate prefilter.
"""
import pytest

from multi_coin_grid_pro.utils.universe_quality_gate import QualityGateConfig, apply_quality_gate


@pytest.fixture
def sample_candidates():
    """Realistic candidate list with stablecoins, leveraged, and normal coins."""
    return [
        ("BTC-USD", 5_000_000, 0.001),
        ("ETH-USD", 3_000_000, 0.001),
        ("USDT-USD", 2_000_000, 0.0005),   # stablecoin
        ("USDC-USD", 1_500_000, 0.0004),   # stablecoin
        ("DAI-USD", 500_000, 0.001),        # stablecoin
        ("SOL-USD", 1_200_000, 0.002),
        ("WBTC-USD", 800_000, 0.002),       # wrapped duplicate
        ("ALGO-USD", 400_000, 0.003),
        ("ADA-USD", 900_000, 0.002),
    ]


class TestQualityGateStablecoins:
    def test_removes_stablecoins(self, sample_candidates):
        result = apply_quality_gate(sample_candidates, "USD")
        passed_pairs = {p for p, _, _ in result.passed}
        assert "USDT-USD" not in passed_pairs
        assert "USDC-USD" not in passed_pairs
        assert "DAI-USD" not in passed_pairs

    def test_keeps_normal_coins(self, sample_candidates):
        result = apply_quality_gate(sample_candidates, "USD")
        passed_pairs = {p for p, _, _ in result.passed}
        assert "BTC-USD" in passed_pairs
        assert "ETH-USD" in passed_pairs
        assert "SOL-USD" in passed_pairs

    def test_stablecoin_filter_disabled(self, sample_candidates):
        cfg = QualityGateConfig(exclude_stablecoins=False)
        result = apply_quality_gate(sample_candidates, "USD", config=cfg)
        passed_pairs = {p for p, _, _ in result.passed}
        assert "USDT-USD" in passed_pairs


class TestQualityGateLeveraged:
    def test_removes_leveraged_tokens(self):
        candidates = [
            ("BTC3L-USD", 100_000, 0.01),
            ("ETH3S-USD", 80_000, 0.01),
            ("BTCBULL-USD", 50_000, 0.01),
            ("ETHBEAR-USD", 40_000, 0.01),
            ("BTC-USD", 5_000_000, 0.001),
        ]
        result = apply_quality_gate(candidates, "USD")
        passed_pairs = {p for p, _, _ in result.passed}
        assert "BTC3L-USD" not in passed_pairs
        assert "ETH3S-USD" not in passed_pairs
        assert "BTC-USD" in passed_pairs

    def test_leveraged_filter_disabled(self):
        candidates = [("BTC3L-USD", 100_000, 0.01)]
        cfg = QualityGateConfig(exclude_leveraged=False)
        result = apply_quality_gate(candidates, "USD", config=cfg)
        assert len(result.passed) == 1


class TestQualityGateWrapped:
    def test_removes_wrapped_when_native_exists(self, sample_candidates):
        result = apply_quality_gate(sample_candidates, "USD")
        passed_pairs = {p for p, _, _ in result.passed}
        assert "WBTC-USD" not in passed_pairs
        assert "BTC-USD" in passed_pairs

    def test_keeps_wrapped_when_no_native(self):
        candidates = [
            ("WBTC-USD", 800_000, 0.002),
            ("ETH-USD", 3_000_000, 0.001),
        ]
        result = apply_quality_gate(candidates, "USD")
        passed_pairs = {p for p, _, _ in result.passed}
        # BTC not in universe, so WBTC should stay
        assert "WBTC-USD" in passed_pairs


class TestQualityGateBlacklist:
    def test_extra_blacklist(self, sample_candidates):
        cfg = QualityGateConfig(extra_blacklist={"ALGO"})
        result = apply_quality_gate(sample_candidates, "USD", config=cfg)
        passed_pairs = {p for p, _, _ in result.passed}
        assert "ALGO-USD" not in passed_pairs
        assert "BTC-USD" in passed_pairs


class TestQualityGateMarketQuality:
    def test_min_volume_rejects_low_volume_before_ranking(self):
        candidates = [
            ("BTC-USD", 5_000_000, 0.001),
            ("MICRO-USD", 50_000, 0.001),
        ]
        cfg = QualityGateConfig(min_24h_volume=500_000)
        result = apply_quality_gate(candidates, "USD", config=cfg)
        passed_pairs = {p for p, _, _ in result.passed}
        assert "BTC-USD" in passed_pairs
        assert "MICRO-USD" not in passed_pairs
        assert result.rejected["MICRO-USD"] == "LOW_VOLUME"

    def test_max_spread_rejects_wide_fractional_spread(self):
        candidates = [
            ("BTC-USD", 5_000_000, 0.001),  # 0.1%
            ("WIDE-USD", 5_000_000, 0.008),  # 0.8%
        ]
        cfg = QualityGateConfig(max_spread_pct=0.5)
        result = apply_quality_gate(candidates, "USD", config=cfg)
        passed_pairs = {p for p, _, _ in result.passed}
        assert "BTC-USD" in passed_pairs
        assert "WIDE-USD" not in passed_pairs
        assert result.rejected["WIDE-USD"] == "WIDE_SPREAD"

    def test_max_spread_handles_percent_input_above_one(self):
        candidates = [
            ("OK-USD", 5_000_000, 0.4),
            ("WIDE-USD", 5_000_000, 1.2),
        ]
        cfg = QualityGateConfig(max_spread_pct=0.5)
        result = apply_quality_gate(candidates, "USD", config=cfg)
        passed_pairs = {p for p, _, _ in result.passed}
        assert "OK-USD" not in passed_pairs  # 0.4 fraction means 40%
        assert "WIDE-USD" not in passed_pairs


class TestQualityGateStats:
    def test_stats_populated(self, sample_candidates):
        result = apply_quality_gate(sample_candidates, "USD")
        assert result.stats.get("STABLECOIN", 0) == 3
        assert result.stats.get("WRAPPED_DUPLICATE(BTC)", 0) == 1
        assert len(result.rejected) == 4  # 3 stables + 1 wrapped

    def test_disabled_gate_passes_everything(self, sample_candidates):
        cfg = QualityGateConfig(enabled=False)
        result = apply_quality_gate(sample_candidates, "USD", config=cfg)
        assert len(result.passed) == len(sample_candidates)
        assert len(result.rejected) == 0


class TestQualityGateEUR:
    def test_works_with_eur_pairs(self):
        candidates = [
            ("BTC-EUR", 4_000_000, 0.001),
            ("USDT-EUR", 1_000_000, 0.0005),
            ("ETH-EUR", 2_000_000, 0.001),
        ]
        result = apply_quality_gate(candidates, "EUR")
        passed_pairs = {p for p, _, _ in result.passed}
        assert "BTC-EUR" in passed_pairs
        assert "USDT-EUR" not in passed_pairs
