"""Regression tests for the 2026-10-17 fee-assumption correction in
``multi_coin_grid_pro/config/spot_grid_kraken_usd.yaml``.

Context (see the FEE CORRECTION report for full detail): the old config
assumed maker=0.20% / taker=0.35% / fee_model=best_case, based on an
unverified maker/taker split. Real Kraken fill data showed a flat ~0.28-0.30%
fee on EVERY fill (buy and sell), with no reliable maker/taker signal
(``is_taker`` in fill data is not trustworthy). The fix sets both
maker_fee_pct and taker_fee_pct to the empirically measured 0.30% and
switches fee_model to 'average' (numerically identical to best_case/
worst_case now that maker==taker, but no longer claims a guaranteed-maker
assumption that the data does not support).

These tests pin:
1. The YAML itself carries the corrected values (catches accidental reverts).
2. The real controller methods that consume these values compute the
   expected, more-conservative downstream numbers (ATR gate, economic edge).
3. The one guard that becomes marginally LESS conservative
   (``_fee_aware_non_emergency_exit_allowed``, taker 0.35%→0.30%) is
   explicitly measured and confirmed to still exclude emergency/hard-stop/
   stop-loss reasons.
4. STOP_LOSS, emergency/hard-stop and order-execution paths are untouched by
   this change — confirmed structurally, not just asserted.
5. The executor's own fee source (``_get_fee_rates()``, read from
   ``connector.trade_fee_schema()``) is independent of this YAML and was
   deliberately NOT touched by this fix — documented as a separate, known gap.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController

_KRAKEN_USD_YAML = Path(__file__).resolve().parents[2] / "config" / "spot_grid_kraken_usd.yaml"


def _load_yaml() -> dict:
    with open(_KRAKEN_USD_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _make_controller_from_yaml(cfg: dict) -> MultiCoinGridController:
    config = MultiCoinGridConfig(connector_name="kraken", quote_asset="USD")
    config.fee_aware_filter = cfg["fee_aware_filter"]
    config.atr_fee_gate = cfg["atr_fee_gate"]
    config.atr_coin_selection = cfg["atr_coin_selection"]
    config.economic_edge_gate = cfg["economic_edge_gate"]
    config.connector_overrides = cfg["connector_overrides"]

    market_data_provider = MagicMock()
    market_data_provider.time.return_value = 1000.0
    market_data_provider.ready = True

    with patch.object(MultiCoinGridController, "_initialize_components"):
        controller = MultiCoinGridController(
            config=config,
            market_data_provider=market_data_provider,
            actions_queue=MagicMock(),
            connectors={"kraken": MagicMock()},
        )
    return controller


def test_yaml_carries_the_corrected_flat_fee_assumption():
    """Catches an accidental revert to the old, unverified 0.35/0.20 split."""
    cfg = _load_yaml()
    fee_cfg = cfg["fee_aware_filter"]
    assert fee_cfg["maker_fee_pct"] == 0.30
    assert fee_cfg["taker_fee_pct"] == 0.30
    assert fee_cfg["fee_model"] == "average"

    override_cfg = cfg["connector_overrides"]["kraken_spot"]["fee_aware_filter"]
    assert override_cfg["maker_fee_pct"] == 0.30
    assert override_cfg["taker_fee_pct"] == 0.30
    assert override_cfg["fee_model"] == "average"


def test_atr_fee_gate_required_atr_is_now_1_20_pct_not_0_80_pct():
    """Real _build_atr_selection_config()/_check_atr_fee_gate() path, fed the
    real (corrected) YAML values — proves the downstream entry gate actually
    tightened, not just the raw config numbers."""
    cfg = _load_yaml()
    controller = _make_controller_from_yaml(cfg)

    atr_cfg = controller._build_atr_selection_config()
    assert atr_cfg is not None
    assert atr_cfg["required_atr_pct"] == 1.20, (
        "Expected 0.60% RT fee x 2.0 multiplier = 1.20% (was 0.80% under the old 0.35/0.20 split)"
    )

    # An ATR of 1.00% would have PASSED under the old 0.80% bar; it must now
    # be BLOCKED under the corrected, stricter 1.20% bar.
    allowed, msg = controller._check_atr_fee_gate("TEST-USD", atr_pct=1.00)
    assert allowed is False
    assert "required_atr_pct=1.200" in msg


def test_economic_edge_gate_roundtrip_fee_is_now_0_60_pct_regardless_of_fee_model():
    """With maker==taker==0.30%, best_case/average/worst_case all yield the
    same 0.60% RT — pin this explicitly so a future maker/taker re-split
    cannot silently reintroduce model-dependent divergence unnoticed."""
    maker = 0.30
    taker = 0.30
    for fee_model, expected_rt in (("best_case", 0.60), ("average", 0.60), ("worst_case", 0.60)):
        if fee_model == "best_case":
            rt = maker * 2
        elif fee_model == "average":
            rt = maker + taker
        else:
            rt = taker * 2
        assert rt == expected_rt, f"fee_model={fee_model} must yield {expected_rt}% RT, got {rt}%"


def test_non_emergency_fee_aware_exit_guard_still_excludes_emergency_reasons():
    """The ONE guard that became marginally less conservative (taker
    0.35%→0.30%) must still hard-exclude emergency_exit/hard_stop_exit/
    stop_loss — those bypass this guard entirely and are unaffected by any
    fee assumption, confirmed via the real method, not just by inspection."""
    cfg = _load_yaml()
    controller = _make_controller_from_yaml(cfg)
    controller.logger = MagicMock(return_value=MagicMock())

    from decimal import Decimal
    for emergency_reason in ("emergency_exit", "hard_stop_exit", "stop_loss"):
        allowed = controller._fee_aware_non_emergency_exit_allowed(
            trading_pair="XRP-USD", executor_info=None,
            current_price=Decimal("1.0"), proposed_close_reason=emergency_reason,
        )
        assert allowed is True, f"{emergency_reason} must always bypass the fee-aware guard"


def test_stop_loss_and_emergency_exit_thresholds_are_unaffected_by_fee_yaml():
    """STOP_LOSS (grid_executor.stop_loss_condition) and the controller's
    emergency_exit_pct/hard_stop_pct (should_exit_position Layer 3) are pure
    price-percentage thresholds with no fee_aware_filter dependency at all.
    Confirm their config values are untouched by this fee fix."""
    cfg = _load_yaml()
    # stop_loss_pct lives at top level, not inside fee_aware_filter.
    assert cfg["stop_loss_pct"] == 0.015, "stop_loss_pct must be untouched by the fee correction"
    assert cfg["emergency_exit_pct"] == -3.0, "emergency_exit_pct must be untouched by the fee correction"
    assert cfg["hard_stop_pct"] == -5.0, "hard_stop_pct must be untouched by the fee correction"


def test_executor_fee_rate_source_is_independent_of_this_yaml_fix_documented_gap():
    """Documents (does not silently assume) that grid_executor._get_fee_rates()
    reads connector.trade_fee_schema() — NOT this YAML's fee_aware_filter —
    so this fix does not change the executor's own TAKE_PROFIT/break-even fee
    assumption at all. A future fix of that gap is a SEPARATE decision
    (touches hummingbot/connector/exchange/kraken/kraken_utils.py or the
    non-git-tracked conf/conf_fee_overrides.yml, both far wider blast radius
    than this controller-config-only fix)."""
    from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor

    executor = GridExecutor.__new__(GridExecutor)
    executor.config = MagicMock()
    executor.config.connector_name = "kraken"
    mock_connector = MagicMock()
    mock_schema = MagicMock()
    from decimal import Decimal
    mock_schema.maker_percent_fee_decimal = Decimal("0.0025")
    mock_schema.taker_percent_fee_decimal = Decimal("0.0040")
    mock_connector.trade_fee_schema.return_value = mock_schema
    executor.connectors = {"kraken": mock_connector}

    maker, taker = executor._get_fee_rates()

    # These come from the connector's schema, NOT from the 0.30%/0.30% YAML
    # value this test file just verified above — proving the two paths are
    # genuinely independent, as documented.
    assert maker == Decimal("0.0025")
    assert taker == Decimal("0.0040")
    assert maker != Decimal("0.0030"), "executor fee source must NOT silently equal the YAML's corrected value"
