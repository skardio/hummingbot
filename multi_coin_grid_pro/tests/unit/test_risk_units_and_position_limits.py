"""Regression tests for risk unit normalisation, position limits and the live risk reference."""
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from multi_coin_grid_pro.config.config_manager import ConfigManager
from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.core.risk_units import exposure_pct_to_fraction, pct_to_fraction
from multi_coin_grid_pro.risk.professional_risk_manager import PortfolioRisk
from multi_coin_grid_pro.spot_bitget.config_manager import SpotGridBitgetConfigManager
from multi_coin_grid_pro.spot_bitget.config_schema import SpotGridBitgetConfig
from multi_coin_grid_pro.spot_okx.config_manager import SpotGridOKXConfigManager
from multi_coin_grid_pro.spot_okx.config_schema import SpotGridOKXConfig


def _make_controller(reference="1000", per_coin="50.0", total="70.0", daily_loss="3.0",
                     use_live=False, total_amount_quote="50000"):
    config = MultiCoinGridConfig(
        connector_name="kraken",
        quote_asset="USD",
        total_amount_quote=Decimal(total_amount_quote),
        max_coins_to_monitor=5,
        min_24h_volume_eur=Decimal("50000"),
        max_exposure_per_coin_pct=Decimal(per_coin),
        max_total_exposure_pct=Decimal(total),
        max_daily_loss_pct=float(daily_loss),
        risk_reference_balance_quote=Decimal(reference),
        risk_reference_use_live_balance=use_live,
        risk_max_daily_loss_pct=Decimal("3"),
        risk_max_balance_per_trade_pct=Decimal("100"),
        risk_max_total_open_risk_pct=Decimal("100"),
    )
    connector = AsyncMock()
    connector.name = "kraken"
    connector.get_fee = Mock(return_value=Decimal("0.0016"))
    provider = MagicMock()
    provider.time = Mock(return_value=datetime.now().timestamp())
    with patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.CoinDiscovery'), \
            patch('multi_coin_grid_pro.controllers.multi_coin_grid_controller.TrendCalculator'):
        controller = MultiCoinGridController(
            config=config,
            market_data_provider=provider,
            actions_queue=[],
            connectors={"kraken": connector},
            update_interval=10.0,
        )
    controller.trend_calculator = MagicMock()
    controller.event_logger = None
    controller.active_coin = None
    controller.total_exposure = Decimal("0")
    controller.current_exposure_per_coin = {}
    controller._next_allocation_quote = None
    return controller


class TestUnitNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("0.5", "0.5"), ("50", "0.5"), ("50.0", "0.5"), ("0.70", "0.7"), ("70", "0.7"),
        ("1", "1"), ("100", "1"), ("55", "0.55"), ("95", "0.95"),
    ])
    def test_exposure_values_normalise_to_fractions(self, raw, expected):
        assert exposure_pct_to_fraction(raw) == Decimal(expected)

    @pytest.mark.parametrize("raw", ["0", "-5", "100.01", "250"])
    def test_invalid_exposure_values_raise(self, raw):
        with pytest.raises(ValueError):
            exposure_pct_to_fraction(raw)

    def test_daily_loss_percent_becomes_fraction(self):
        assert pct_to_fraction(3.0) == pytest.approx(0.03)

    def test_bitget_yaml_exposure_limits_are_fractions(self):
        cfg = SpotGridBitgetConfig(**SpotGridBitgetConfigManager().load_config())
        assert cfg.max_exposure_per_coin_pct == Decimal("0.5")
        assert cfg.max_total_exposure_pct == Decimal("0.7")

    def test_okx_yaml_keeps_intended_semantics(self):
        cfg = SpotGridOKXConfig(**SpotGridOKXConfigManager().load_config())
        assert cfg.max_exposure_per_coin_pct == Decimal("0.5")
        assert cfg.max_total_exposure_pct == Decimal("0.7")
        assert cfg.risk_reference_use_live_balance is False

    def test_kraken_yaml_keeps_intended_semantics(self):
        cfg = MultiCoinGridConfig(**ConfigManager().load_config("spot_grid_kraken_usd"))
        assert cfg.max_exposure_per_coin_pct == Decimal("0.55")
        assert cfg.max_total_exposure_pct == Decimal("0.95")
        assert cfg.risk_reference_use_live_balance is True
        assert "risk_reference_balance_quote" not in cfg.model_fields_set


class TestPositionLimits:
    def test_riskguard_receives_percent_form_of_normalised_limits(self):
        for per_coin, total in (("50.0", "70.0"), ("0.5", "0.7")):
            ctrl = _make_controller(per_coin=per_coin, total=total)
            assert ctrl.risk_guard_v2.cfg["max_exposure_per_coin_pct"] == pytest.approx(50.0)
            assert ctrl.risk_guard_v2.cfg["max_total_exposure_pct"] == pytest.approx(70.0)

    def test_per_coin_limit_blocks_above_50pct_of_reference(self):
        ctrl = _make_controller(reference="1000")
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("500")) is True
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("501")) is False

    def test_per_coin_limit_applies_to_new_coin_not_only_active_coin(self):
        ctrl = _make_controller(reference="1000", total="100")
        ctrl.risk_guard_v2.can_open_position = MagicMock(return_value=(True, "ok"))
        ctrl.active_coin = "BBB-USD"
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("600")) is False

    def test_total_limit_applies_to_first_position(self):
        ctrl = _make_controller(reference="1000", per_coin="50.0", total="30.0")
        ctrl.risk_guard_v2.can_open_position = MagicMock(return_value=(True, "ok"))
        assert ctrl.total_exposure == Decimal("0")
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("400")) is False
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("300")) is True

    def test_total_limit_70pct_with_existing_exposure(self):
        ctrl = _make_controller(reference="1000")
        ctrl.risk_guard_v2.can_open_position = MagicMock(return_value=(True, "ok"))
        ctrl.total_exposure = Decimal("300")
        ctrl.current_exposure_per_coin = {"BBB-USD": Decimal("300")}
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("400")) is True
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("401")) is False

    def test_exception_in_exposure_check_blocks(self):
        ctrl = _make_controller()
        ctrl.risk_guard_v2.can_open_position = MagicMock(side_effect=RuntimeError("boom"))
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("10")) is False

    def test_invalid_limit_config_blocks(self):
        ctrl = _make_controller()
        ctrl.config.__dict__["max_total_exposure_pct"] = Decimal("0")  # bypass assignment validation
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("10")) is False

    def test_non_positive_reference_blocks(self):
        ctrl = _make_controller()
        ctrl.config.__dict__["risk_reference_balance_quote"] = Decimal("0")  # bypass assignment validation
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("10")) is False

    def test_kraken_reference_300_keeps_55_and_95_percent_semantics(self):
        ctrl = _make_controller(reference="300", per_coin="55", total="95")
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("165")) is True
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("166")) is False
        ctrl.total_exposure = Decimal("200")
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("85")) is True
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("86")) is False

    def test_okx_reference_150_keeps_50_and_70_percent_semantics(self):
        ctrl = _make_controller(reference="150", per_coin="50.0", total="70.0")
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("75")) is True
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("76")) is False


class TestDailyLossLimit:
    @staticmethod
    def _portfolio(daily_pnl_pct):
        return PortfolioRisk(
            total_equity=Decimal("1000"), daily_pnl=Decimal("0"), daily_pnl_pct=daily_pnl_pct,
            max_daily_loss_pct=0.0, open_positions=0, max_positions=3, recent_wins=0, recent_losses=0,
            win_rate=0.5, highly_correlated_positions=[], correlation_risk_score=0.0,
        )

    def test_three_percent_is_interpreted_as_fraction(self):
        ctrl = _make_controller(daily_loss="3.0")
        assert ctrl.professional_risk_manager.max_daily_loss_pct == pytest.approx(0.03)

    def test_loss_beyond_three_percent_blocks_and_within_limit_allows(self):
        ctrl = _make_controller(daily_loss="3.0")
        manager = ctrl.professional_risk_manager
        blocked, _ = manager.can_open_new_position("AAA-USD", 0.7, self._portfolio(-0.031))
        allowed, _ = manager.can_open_new_position("AAA-USD", 0.7, self._portfolio(-0.029))
        assert blocked is False
        assert allowed is True


def _connector_with(total, available=None):
    connector = MagicMock()
    connector.get_balance.return_value = Decimal(str(total))
    connector.get_available_balance.return_value = Decimal(str(total if available is None else available))
    connector.get_all_balances.return_value = {}
    return connector


class TestLiveRiskReference:
    def test_disabled_flag_keeps_configured_reference(self):
        ctrl = _make_controller(reference="50000", use_live=False)
        ctrl.connector = _connector_with(1000)
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == Decimal("50000")
        ctrl.connector.get_balance.assert_not_called()

    def test_live_balance_caps_reference_and_propagates(self):
        ctrl = _make_controller(reference="50000", use_live=True)
        ctrl.connector = _connector_with(1000)
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == Decimal("1000")
        assert ctrl.risk_manager._reference_balance_quote == Decimal("1000")
        assert ctrl.pnl_tracker_v2.starting_balance == Decimal("1000")
        assert ctrl.pnl_tracker_v2.daily_start_equity == Decimal("1000")
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("500")) is True
        assert ctrl._check_position_limits("AAA-USD", requested_allocation=Decimal("501")) is False

    def test_live_balance_raises_reference_and_operator_cap_limits_it(self):
        ctrl = _make_controller(reference="300", use_live=True)
        ctrl.connector = _connector_with(2000)
        assert ctrl._ensure_risk_reference() is True
        assert ctrl.config.risk_reference_balance == Decimal("2000")
        capped = _make_controller(reference="300", use_live=True)
        capped._risk_capital_cap = Decimal("300")
        capped.connector = _connector_with(2000)
        assert capped._ensure_risk_reference() is True
        assert capped.config.risk_reference_balance == Decimal("300")

    @pytest.mark.parametrize("live", [Decimal("0"), RuntimeError("no balance")])
    def test_unreadable_live_balance_blocks_entries(self, live):
        ctrl = _make_controller(reference="50000", use_live=True)
        ctrl.connector = _connector_with(0)
        if isinstance(live, Exception):
            ctrl.connector.get_balance.side_effect = live
        assert ctrl._ensure_risk_reference() is False
        assert ctrl.config.risk_reference_balance == Decimal("50000")

    def test_unresolved_reference_stops_new_entries_in_decision_loop(self):
        ctrl = _make_controller(reference="50000", use_live=True)
        ctrl._sync_risk_state = MagicMock()
        ctrl._check_professional_exit_signals = MagicMock(return_value=[])
        ctrl._ensure_risk_reference = MagicMock(return_value=False)
        ctrl.time_based_filter = MagicMock()
        assert ctrl.determine_executor_actions() == []
        ctrl.time_based_filter.check_trading_permission.assert_not_called()

    def test_pnl_tracker_rebase_keeps_accumulated_pnl(self):
        ctrl = _make_controller(reference="50000", use_live=True)
        tracker = ctrl.pnl_tracker_v2
        tracker.current_balance += Decimal("-20")
        tracker.rebase_reference(Decimal("1000"))
        assert tracker.starting_balance == Decimal("1000")
        assert tracker.equity() == Decimal("980")
        assert tracker.daily_start_equity == Decimal("1000")
        assert tracker.daily_pnl() == Decimal("-20")
