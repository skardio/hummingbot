"""Gate engine tests: every verdict path, driven only by policy and contract."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from typing import List

import pytest

from tools.evidence.bootstrap import BootstrapResult, block_bootstrap_mean
from tools.evidence.gate_engine import (
    ERROR,
    EXPLORATORY,
    FAIL,
    INSUFFICIENT_EVIDENCE,
    PASS,
    BaselineSummary,
    Contract,
    gate_engine,
)
from tools.evidence.metrics import ExecutorRecord
from tools.evidence.policy import load_policy

from .conftest import (
    BASE_TS,
    DAY_SECONDS,
    POLICY_PATH,
    base_config,
    build_gate_input,
    build_record,
    make_custom_info,
    make_order,
)

PAIRS = ["APE-USD", "SOL-USD", "LINK-USD", "DOT-USD", "AVAX-USD", "UNI-USD"]
POLICY_VERSION = load_policy(POLICY_PATH).version


def winning_population(policy, n: int = 120, days: int = 30) -> List[ExecutorRecord]:
    """A healthy cohort with a small, consistent positive edge."""
    records = []
    for i in range(n):
        win = i % 5 != 0  # 80% win rate, small wins, larger losses
        sell = "100.60" if win else "99.20"
        records.append(
            build_record(
                policy,
                executor_id=f"e{i}",
                day_offset=i % days,
                trading_pair=PAIRS[i % len(PAIRS)],
                fees="0.10",
                custom_info=make_custom_info([
                    make_order("BUY", "100", "100.00", f"b{i}"),
                    make_order("SELL", "100", sell, f"s{i}"),
                ]),
            )
        )
    return records


def losing_population(policy, n: int = 120, days: int = 30) -> List[ExecutorRecord]:
    records = []
    for i in range(n):
        win = i % 4 != 0
        sell = "100.20" if win else "98.50"
        records.append(
            build_record(
                policy,
                executor_id=f"e{i}",
                day_offset=i % days,
                trading_pair=PAIRS[i % len(PAIRS)],
                fees="0.10",
                custom_info=make_custom_info([
                    make_order("BUY", "100", "100.00", f"b{i}"),
                    make_order("SELL", "100", sell, f"s{i}"),
                ]),
            )
        )
    return records


def good_contract(**overrides) -> Contract:
    defaults = dict(
        experiment_id="EXP-TEST-001",
        policy_version=POLICY_VERSION,
        frozen_at=BASE_TS - DAY_SECONDS,
        period_start=BASE_TS,
        period_end=BASE_TS + 40 * DAY_SECONDS,
        venue="kraken",
        quote="USD",
        controller_id="multi_coin_grid_usd",
        primary_metric="expectancy_per_trade_matched_net",
        success_threshold=Decimal("0.10"),
        failure_threshold=Decimal("-0.05"),
        baseline_id="BL-TEST",
        mode="paper",
    )
    defaults.update(overrides)
    return Contract(**defaults)


def good_baseline(**overrides) -> BaselineSummary:
    defaults = dict(
        baseline_id="BL-TEST",
        policy_version=POLICY_VERSION,
        expectancy_per_trade=Decimal("0.05"),
        return_on_deployed=Decimal("0.0005"),
        pnl_sequence_drawdown=Decimal("-50"),
        operational_share_of_total=Decimal("0.20"),
    )
    defaults.update(overrides)
    return BaselineSummary(**defaults)


def positive_difference() -> BootstrapResult:
    return BootstrapResult(
        method="block_bootstrap_day_difference",
        n_resamples=10,
        confidence_level=0.95,
        seed=1,
        n_blocks=30,
        n_observations=240,
        point_estimate=0.25,
        ci_low=0.05,
        ci_high=0.45,
    )


# --------------------------------------------------------------------- G0 ---
def test_g0_blocks_on_broken_abc_identity(policy):
    """A broken classification identity must stop everything before any metric."""
    from tools.evidence.reconcile import ReconciliationResult, check_abc_identity

    records = winning_population(policy, n=120)
    gate_input = build_gate_input(policy, records)
    failing = ReconciliationResult(
        checks=(check_abc_identity(Decimal("10"), Decimal("999"), Decimal("1"), Decimal("0.01")),)
    )
    result = gate_engine(replace(gate_input, reconciliation=failing), policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.gate == "G0"
    assert result.reason_code == "DATA_INTEGRITY"


def test_g0_blocks_on_inconsistent_leg_identity(policy):
    """Fixtures that violate net_pnl == (sell - buy) - fees must be rejected."""
    records = [
        build_record(
            policy,
            executor_id=f"e{i}",
            day_offset=i % 30,
            trading_pair=PAIRS[i % len(PAIRS)],
            net_pnl="50.00",  # deliberately unrelated to the legs
            fees="0.10",
            custom_info=make_custom_info([
                make_order("BUY", "100", "100.00", f"b{i}"),
                make_order("SELL", "100", "100.60", f"s{i}"),
            ]),
        )
        for i in range(120)
    ]
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.gate == "G0"
    assert "leg_identity" in result.reason


# --------------------------------------------------------------------- G1 ---
def test_g1_mixed_cohort(policy):
    records = winning_population(policy, n=120)
    half = len(records) // 2
    other = base_config(**{"custom_info.max_hold_time_sec": 7200})
    from tools.evidence.fingerprint import fingerprint_config

    other_fp = fingerprint_config(other, policy).full
    records = [
        replace(record, fingerprint=other_fp) if i < half else record
        for i, record in enumerate(records)
    ]
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.gate == "G1"
    assert result.reason_code == "MIXED_COHORT"


def test_g1_denylist_stale(policy):
    records = winning_population(policy, n=20)
    records = [replace(record, fingerprint=f"fp-{i}") for i, record in enumerate(records)]
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.reason_code == "DENYLIST_STALE"


def test_g1_dust_sensitive(policy):
    records = winning_population(policy, n=120)
    gate_input = build_gate_input(
        policy, records, dust_sensitivity_stable=False, dust_sensitivity_detail="verdict flips at abs_quote=1.00"
    )
    result = gate_engine(gate_input, policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.reason_code == "DUST_SENSITIVE"


# --------------------------------------------------------------------- G2 ---
def test_g2_no_contract_yields_exploratory(policy):
    records = winning_population(policy, n=120)
    result = gate_engine(build_gate_input(policy, records), policy, None)
    assert result.verdict == EXPLORATORY
    assert result.reason_code == "NO_CONTRACT"


def test_g2_contract_frozen_too_late_can_never_pass(policy):
    records = winning_population(policy, n=120)
    late = good_contract(frozen_at=BASE_TS + 5 * DAY_SECONDS)
    result = gate_engine(build_gate_input(policy, records), policy, late)
    assert result.verdict == EXPLORATORY


def test_g2_policy_drift(policy):
    records = winning_population(policy, n=120)
    drifted = good_contract(policy_version="0.0.1-nonexistent")
    result = gate_engine(build_gate_input(policy, records), policy, drifted)
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.reason_code == "POLICY_DRIFT"


def test_g2_forbidden_primary_metric_is_an_error(policy):
    records = winning_population(policy, n=120)
    bad = good_contract(primary_metric="win_rate")
    result = gate_engine(build_gate_input(policy, records), policy, bad)
    assert result.verdict == ERROR
    assert result.reason_code == "INVALID_CONTRACT"


# --------------------------------------------------------------------- G3 ---
def test_g3_small_sample(policy):
    records = winning_population(policy, n=20, days=20)
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.gate == "G3"
    assert result.reason_code == "SAMPLE"
    assert "min_matched_trades" in result.reason


def test_g3_too_few_pairs(policy):
    records = winning_population(policy, n=120)
    records = [replace(record, trading_pair="APE-USD") for record in records]
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.reason_code == "SAMPLE"


# --------------------------------------------------------------------- G4 ---
def test_g4_abort_is_a_fail(policy):
    records = winning_population(policy, n=120)
    aborted = good_contract(abort_triggered=True, abort_detail="drawdown below -25 USD")
    result = gate_engine(build_gate_input(policy, records), policy, aborted)
    assert result.verdict == FAIL
    assert result.gate == "G4"
    assert result.reason_code == "ABORTED"


# --------------------------------------------------------------------- G5 ---
def test_g5_operational_noise(policy):
    records = winning_population(policy, n=120)
    records.append(
        build_record(
            policy,
            executor_id="orphan",
            day_offset=5,
            trading_pair="UNI-USD",
            close_type=8,
            fees="0.10",
            custom_info=make_custom_info([make_order("BUY", "500", "500.00", "bx")]),
        )
    )
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.gate == "G5"
    assert result.reason_code == "OPERATIONAL_NOISE"


# --------------------------------------------------------------------- G6 ---
def test_g6_negative_expectancy_fails(policy):
    records = losing_population(policy, n=120)
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert result.verdict == FAIL
    assert result.gate == "G6"
    assert result.reason_code in ("BELOW_FAILURE_THRESHOLD", "NEGATIVE_EXPECTANCY")


def test_g6_high_win_rate_cannot_rescue_a_negative_edge(policy):
    """75% win rate with negative expectancy must still FAIL."""
    records = losing_population(policy, n=120)
    gate_input = build_gate_input(policy, records)
    view_b = gate_input.metrics.views["B"]
    assert view_b.win_rate is not None and view_b.win_rate >= Decimal("0.70")
    assert view_b.expectancy_per_trade is not None and view_b.expectancy_per_trade < 0
    result = gate_engine(gate_input, policy, good_contract())
    assert result.verdict == FAIL


# --------------------------------------------------------------------- G7 ---
def test_g7_pass_requires_everything(policy):
    records = winning_population(policy, n=120)
    gate_input = build_gate_input(
        policy,
        records,
        baseline=good_baseline(),
        bootstrap_difference=positive_difference(),
    )
    result = gate_engine(gate_input, policy, good_contract())
    assert result.verdict == PASS
    assert result.gate == "G7"
    assert "PAPER" in result.reason


def test_g7_without_baseline_is_inconclusive(policy):
    records = winning_population(policy, n=120)
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.gate == "G7"
    assert result.reason_code == "INCONCLUSIVE"


def test_g7_ci_including_zero_is_inconclusive(policy):
    records = winning_population(policy, n=120)
    straddling = replace(positive_difference(), ci_low=-0.04, ci_high=0.33)
    gate_input = build_gate_input(
        policy, records, baseline=good_baseline(), bootstrap_difference=straddling
    )
    result = gate_engine(gate_input, policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.reason_code == "INCONCLUSIVE"
    assert "bootstrap_ci_lower_above_baseline" in result.reason


def test_g7_worse_drawdown_is_inconclusive(policy):
    records = winning_population(policy, n=120)
    tight = good_baseline(pnl_sequence_drawdown=Decimal("-0.50"))
    gate_input = build_gate_input(
        policy, records, baseline=tight, bootstrap_difference=positive_difference()
    )
    result = gate_engine(gate_input, policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert "drawdown_vs_baseline" in result.reason


# ----------------------------------------------------------------- order ---
def test_gate_order_is_respected(policy):
    """A G1 failure must win over a later G3 failure."""
    records = winning_population(policy, n=20, days=20)
    records = [replace(record, fingerprint=f"fp-{i}") for i, record in enumerate(records)]
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert result.gate == "G1"


def test_trace_is_populated_and_serialisable(policy):
    records = winning_population(policy, n=120)
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    payload = result.as_dict()
    assert payload["verdict"] == result.verdict
    assert payload["policy_version"] == POLICY_VERSION
    assert len(payload["trace"]) > 0
    for entry in payload["trace"]:
        assert set(entry) == {"gate", "name", "passed", "value", "limit", "policy_key", "detail", "advisory"}


def test_thresholds_come_from_policy_not_code(policy, tmp_path):
    """Loosening the policy must change the verdict without touching code."""
    import yaml

    records = winning_population(policy, n=20, days=20)
    strict = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert strict.reason_code == "SAMPLE"

    raw = dict(policy.raw)
    raw["sample"] = dict(raw["sample"])
    raw["sample"]["min_matched_trades"] = 10
    raw["sample"]["min_trading_days"] = 5
    raw["sample"]["min_distinct_pairs"] = 2
    path = tmp_path / "loose_policy.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    from tools.evidence.policy import load_policy

    loose = load_policy(path)
    relaxed = gate_engine(build_gate_input(loose, records), loose, good_contract())
    assert relaxed.reason_code != "SAMPLE"


# ------------------------------------------------------------ determinism ---
def test_bootstrap_is_deterministic(policy):
    daily = {f"2026-01-{day:02d}": [Decimal(day) / 10, Decimal(-day) / 20] for day in range(1, 26)}
    first = block_bootstrap_mean(daily, 500, 0.95, 20261004)
    second = block_bootstrap_mean(daily, 500, 0.95, 20261004)
    assert (first.ci_low, first.ci_high, first.point_estimate) == (
        second.ci_low,
        second.ci_high,
        second.point_estimate,
    )


def test_bootstrap_different_seed_differs(policy):
    daily = {f"2026-01-{day:02d}": [Decimal(day) / 10, Decimal(-day) / 20] for day in range(1, 26)}
    a = block_bootstrap_mean(daily, 500, 0.95, 1)
    b = block_bootstrap_mean(daily, 500, 0.95, 2)
    assert (a.ci_low, a.ci_high) != (b.ci_low, b.ci_high)


def test_bootstrap_empty_is_safe():
    result = block_bootstrap_mean({}, 100, 0.95, 1)
    assert result.available is False
    assert result.excludes_zero is None


def test_identical_input_yields_identical_verdict(policy):
    records = winning_population(policy, n=120)
    contract = good_contract()
    first = gate_engine(
        build_gate_input(policy, records, baseline=good_baseline(), bootstrap_difference=positive_difference()),
        policy,
        contract,
    )
    second = gate_engine(
        build_gate_input(policy, records, baseline=good_baseline(), bootstrap_difference=positive_difference()),
        policy,
        contract,
    )
    assert first.as_dict() == second.as_dict()


@pytest.mark.parametrize("verdict_attr", ["verdict", "gate", "reason_code"])
def test_verdict_fields_present(policy, verdict_attr):
    records = winning_population(policy, n=120)
    result = gate_engine(build_gate_input(policy, records), policy, good_contract())
    assert getattr(result, verdict_attr) is not None


def test_empty_cohort_reports_no_data_not_mixed(policy):
    """An empty window is not a mixed cohort; the reason code must say so.

    This surfaces on the very first monitoring run of a new experiment, when
    no executor has closed yet.
    """
    result = gate_engine(build_gate_input(policy, []), policy, good_contract())
    assert result.verdict == INSUFFICIENT_EVIDENCE
    assert result.gate == "G1"
    assert result.reason_code == "NO_DATA"
    assert "no closed executors" in result.reason
