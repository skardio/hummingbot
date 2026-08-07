# test_signal_momentum_config.py — unit tests for momentum_config.py
import pytest

from multi_coin_grid_pro.signals.momentum_config import CandidateFilters, ExchangeConfig, ScoringConfig, ServiceConfig

YAML_PATH = (
    "multi_coin_grid_pro/config/momentum_signal_service.yaml"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_valid_config(**kwargs) -> ServiceConfig:
    """Return a minimal valid ServiceConfig, overriding defaults with kwargs."""
    return ServiceConfig(mode="signal_only", **kwargs)


# ---------------------------------------------------------------------------
# ServiceConfig — valid construction
# ---------------------------------------------------------------------------

class TestServiceConfigValid:

    def test_default_mode_is_signal_only(self) -> None:
        cfg = ServiceConfig()
        assert cfg.mode == "signal_only"

    def test_explicit_signal_only_mode(self) -> None:
        cfg = ServiceConfig(mode="signal_only")
        assert cfg.mode == "signal_only"

    def test_defaults_are_sane(self) -> None:
        cfg = ServiceConfig()
        assert cfg.enabled is True
        assert cfg.scan_interval_seconds == 60
        assert cfg.top_n == 10
        assert cfg.exchanges == []

    def test_safety_merged_with_defaults(self) -> None:
        # Partial safety dict — defaults must fill in
        cfg = ServiceConfig(mode="signal_only", safety={})
        assert cfg.safety["allow_order_creation"] is False
        assert cfg.safety["read_only"] is True

    def test_safety_all_false_flags_pass(self) -> None:
        cfg = ServiceConfig(
            mode="signal_only",
            safety={
                "read_only": True,
                "allow_order_creation": False,
                "allow_executor_actions": False,
                "allow_budget_reservation": False,
                "allow_grid_state_writes": False,
            },
        )
        assert cfg.mode == "signal_only"

    def test_scoring_default_min_score(self) -> None:
        cfg = ServiceConfig()
        assert cfg.scoring.min_score == pytest.approx(0.70)

    def test_candidate_filters_defaults(self) -> None:
        cfg = ServiceConfig()
        cf = cfg.candidate_filters
        assert cf.min_price_change_5m_pct == pytest.approx(2.0)
        assert cf.max_spread_pct == pytest.approx(0.35)
        assert cf.exclude_blacklisted is True


# ---------------------------------------------------------------------------
# ServiceConfig — mode guard
# ---------------------------------------------------------------------------

class TestServiceConfigModeGuard:

    @pytest.mark.parametrize("bad_mode", ["paper", "live", "detect_only", "dry_run", ""])
    def test_bad_mode_raises(self, bad_mode: str) -> None:
        with pytest.raises((ValueError, AssertionError)):
            ServiceConfig(mode=bad_mode)

    def test_default_constructor_never_raises(self) -> None:
        # Constructing with no args must not raise
        cfg = ServiceConfig()
        assert cfg.mode == "signal_only"


# ---------------------------------------------------------------------------
# ServiceConfig — safety flags guard
# ---------------------------------------------------------------------------

class TestSafetyFlagsGuard:

    def test_allow_order_creation_true_raises(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            ServiceConfig(mode="signal_only", safety={"allow_order_creation": True})

    def test_allow_executor_actions_true_raises(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            ServiceConfig(mode="signal_only", safety={"allow_executor_actions": True})

    def test_allow_budget_reservation_true_raises(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            ServiceConfig(mode="signal_only", safety={"allow_budget_reservation": True})

    def test_allow_grid_state_writes_true_raises(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            ServiceConfig(mode="signal_only", safety={"allow_grid_state_writes": True})

    def test_read_only_false_raises(self) -> None:
        with pytest.raises((ValueError, AssertionError)):
            ServiceConfig(mode="signal_only", safety={"read_only": False})


# ---------------------------------------------------------------------------
# ExchangeConfig
# ---------------------------------------------------------------------------

class TestExchangeConfig:

    def test_required_fields(self) -> None:
        ex = ExchangeConfig(
            exchange="kraken",
            api_url="https://api.kraken.com",
            quote_assets=["USD"],
        )
        assert ex.exchange == "kraken"
        assert ex.quote_assets == ["USD"]

    def test_optional_paths_default_empty(self) -> None:
        ex = ExchangeConfig(
            exchange="okx",
            api_url="https://www.okx.com",
            quote_assets=["USDT"],
        )
        assert ex.grid_db_path == ""
        assert ex.blacklist_yaml == ""
        assert ex.cooldown_db_path == ""


# ---------------------------------------------------------------------------
# CandidateFilters + ScoringConfig — standalone
# ---------------------------------------------------------------------------

class TestSubConfigs:

    def test_candidate_filters_custom_values(self) -> None:
        cf = CandidateFilters(min_price_change_5m_pct=1.5, max_spread_pct=0.20)
        assert cf.min_price_change_5m_pct == pytest.approx(1.5)
        assert cf.max_spread_pct == pytest.approx(0.20)

    def test_scoring_config_custom_min_score(self) -> None:
        sc = ScoringConfig(min_score=0.80)
        assert sc.min_score == pytest.approx(0.80)


# ---------------------------------------------------------------------------
# from_yaml
# ---------------------------------------------------------------------------

class TestFromYaml:

    def test_loads_without_error(self) -> None:
        cfg = ServiceConfig.from_yaml(YAML_PATH)
        assert cfg.mode == "signal_only"

    def test_exchanges_loaded(self) -> None:
        cfg = ServiceConfig.from_yaml(YAML_PATH)
        assert len(cfg.exchanges) == 4
        names = [ex.exchange for ex in cfg.exchanges]
        assert "kraken" in names
        assert "bitvavo" in names

    def test_safety_loaded_and_merged(self) -> None:
        cfg = ServiceConfig.from_yaml(YAML_PATH)
        assert cfg.safety["allow_order_creation"] is False
        assert cfg.safety["read_only"] is True

    def test_top_n_loaded(self) -> None:
        cfg = ServiceConfig.from_yaml(YAML_PATH)
        assert cfg.top_n == 10

    def test_scoring_min_score(self) -> None:
        cfg = ServiceConfig.from_yaml(YAML_PATH)
        assert cfg.scoring.min_score == pytest.approx(0.30)  # lowered: REST service max ~0.375

    def test_candidate_filters_loaded(self) -> None:
        cfg = ServiceConfig.from_yaml(YAML_PATH)
        assert cfg.candidate_filters.min_volume_ratio == pytest.approx(2.3)  # updated: B+C strategy
        assert cfg.candidate_filters.exclude_blacklisted is True
