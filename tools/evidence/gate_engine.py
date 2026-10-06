"""The gate engine: the only place where a verdict is decided.

``gate_engine(metrics, policy, contract) -> VerdictResult``

The function is pure. It performs no database I/O, reads no files and consults
no clock. Every threshold arrives through ``policy``; every experiment-specific
value arrives through ``contract``.

Gates are evaluated in strict order G0..G7. The first gate that trips decides
the outcome. A later gate can never rescue an earlier failure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .bootstrap import BootstrapResult
from .classify import UNMATCHED_BUY
from .fingerprint import FingerprintDistribution
from .metrics import MetricsBundle, ViewMetrics
from .policy import Policy
from .reconcile import ReconciliationResult

# --- verdicts --------------------------------------------------------------
PASS = "PASS"
FAIL = "FAIL"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
EXPLORATORY = "EXPLORATORY"
ERROR = "ERROR"

VALID_VERDICTS = (PASS, FAIL, INSUFFICIENT_EVIDENCE, EXPLORATORY, ERROR)

#: Metric name -> attribute on the view-B metrics.
PRIMARY_METRIC_SOURCES: Mapping[str, str] = {
    "expectancy_per_trade_matched_net": "expectancy_per_trade",
    "return_on_deployed_matched_net": "return_on_deployed",
}


@dataclass(frozen=True)
class CohortInfo:
    """Identity and composition of the cohort under evaluation."""

    venue: str
    quote: str
    controller_id: str
    fingerprint_distribution: FingerprintDistribution
    period_start: Optional[int] = None
    period_end: Optional[int] = None


@dataclass(frozen=True)
class BaselineSummary:
    """The frozen comparison point. Absent means no comparison is possible."""

    baseline_id: str
    policy_version: str
    expectancy_per_trade: Optional[Decimal]
    return_on_deployed: Optional[Decimal]
    pnl_sequence_drawdown: Decimal
    operational_share_of_total: Optional[Decimal]
    daily_pnl_matched: Mapping[str, Sequence[Decimal]] = field(default_factory=dict)
    period_start: Optional[int] = None
    period_end: Optional[int] = None


@dataclass(frozen=True)
class Contract:
    """Minimal pre-registered experiment contract."""

    experiment_id: str
    policy_version: str
    frozen_at: int
    period_start: int
    period_end: int
    venue: str
    quote: str
    controller_id: str
    primary_metric: str
    success_threshold: Decimal
    failure_threshold: Decimal
    baseline_id: Optional[str] = None
    abort_triggered: bool = False
    abort_detail: str = ""
    mode: str = "paper"


@dataclass(frozen=True)
class GateInput:
    """Everything the gate engine needs, all of it already computed."""

    metrics: MetricsBundle
    reconciliation: ReconciliationResult
    cohort: CohortInfo
    bootstrap: Optional[BootstrapResult] = None
    bootstrap_difference: Optional[BootstrapResult] = None
    baseline: Optional[BaselineSummary] = None
    dust_sensitivity_stable: Optional[bool] = None
    dust_sensitivity_detail: str = ""


@dataclass(frozen=True)
class GateTrace:
    """One evaluated gate, reproducible from the report alone."""

    gate: str
    name: str
    passed: bool
    value: Optional[str]
    limit: Optional[str]
    policy_key: Optional[str]
    detail: str = ""
    advisory: bool = False


@dataclass(frozen=True)
class VerdictResult:
    """The single authoritative outcome."""

    verdict: str
    gate: Optional[str]
    reason_code: Optional[str]
    reason: str
    trace: Tuple[GateTrace, ...]
    policy_version: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "gate": self.gate,
            "reason_code": self.reason_code,
            "reason": self.reason,
            "policy_version": self.policy_version,
            "trace": [
                {
                    "gate": item.gate,
                    "name": item.name,
                    "passed": item.passed,
                    "value": item.value,
                    "limit": item.limit,
                    "policy_key": item.policy_key,
                    "detail": item.detail,
                    "advisory": item.advisory,
                }
                for item in self.trace
            ],
        }


def _fmt(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _primary_metric_value(metric: str, view_b: ViewMetrics) -> Optional[Decimal]:
    attribute = PRIMARY_METRIC_SOURCES.get(metric)
    if attribute is None:
        return None
    return getattr(view_b, attribute)


def _edge_is_mathematically_negative(view_b: ViewMetrics) -> Optional[bool]:
    """Kelly-style sanity check: payoff * wr / (1 - wr) <= 1 means no edge.

    Returns None when it cannot be evaluated.
    """
    if view_b.payoff_ratio is None or view_b.win_rate is None:
        return None
    win_rate = view_b.win_rate
    if win_rate >= 1:
        return False
    if win_rate <= 0:
        return True
    return (view_b.payoff_ratio * win_rate / (Decimal(1) - win_rate)) <= Decimal(1)


def _periods_overlap(a_start, a_end, b_start, b_end) -> Optional[bool]:
    if None in (a_start, a_end, b_start, b_end):
        return None
    return a_start <= b_end and b_start <= a_end


def gate_engine(  # noqa: C901 - an explicit linear gate chain is the point
    metrics: GateInput,
    policy: Policy,
    contract: Optional[Contract] = None,
) -> VerdictResult:
    """Evaluate G0..G7 in order and return the single authoritative verdict."""
    trace: List[GateTrace] = []
    bundle = metrics.metrics
    view_b = bundle.views["B"]

    def finish(verdict: str, gate: Optional[str], code: Optional[str], reason: str) -> VerdictResult:
        return VerdictResult(
            verdict=verdict,
            gate=gate,
            reason_code=code,
            reason=reason,
            trace=tuple(trace),
            policy_version=policy.version,
        )

    # ---------------------------------------------------------------- G0 ---
    for check in metrics.reconciliation.checks:
        trace.append(
            GateTrace(
                gate="G0",
                name=check.name,
                passed=check.passed,
                value=_fmt(check.value),
                limit=_fmt(check.limit),
                policy_key="data_integrity",
                detail=check.detail,
            )
        )
    if not metrics.reconciliation.passed:
        failed = ", ".join(check.name for check in metrics.reconciliation.failures)
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G0",
            "DATA_INTEGRITY",
            f"data integrity failed: {failed}. No metrics may be reported.",
        )

    # ---------------------------------------------------------------- G1 ---
    distribution = metrics.cohort.fingerprint_distribution
    if distribution.total == 0:
        trace.append(
            GateTrace(
                gate="G1",
                name="cohort_not_empty",
                passed=False,
                value="0",
                limit="> 0",
                policy_key=None,
                detail="no closed executors in the selected window",
            )
        )
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G1",
            "NO_DATA",
            "no closed executors in the selected window; nothing to adjudicate.",
        )

    stale_limit = float(policy.get("cohort.fingerprint_health_stale"))
    health = distribution.health
    health_ok = health <= stale_limit
    trace.append(
        GateTrace(
            gate="G1",
            name="fingerprint_health",
            passed=health_ok,
            value=f"{health:.4f}",
            limit=f"{stale_limit:.4f}",
            policy_key="cohort.fingerprint_health_stale",
            detail="distinct fingerprints / n executors",
        )
    )
    if not health_ok:
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G1",
            "DENYLIST_STALE",
            f"fingerprint health {health:.2f} exceeds {stale_limit:.2f}; a new volatile config field is present.",
        )

    min_share = float(policy.get("cohort.min_dominant_fingerprint_share"))
    share = distribution.dominant_share
    share_ok = share >= min_share
    trace.append(
        GateTrace(
            gate="G1",
            name="dominant_fingerprint_share",
            passed=share_ok,
            value=f"{share:.4f}",
            limit=f"{min_share:.4f}",
            policy_key="cohort.min_dominant_fingerprint_share",
            detail=f"{distribution.distinct} distinct fingerprints over {distribution.total} executors",
        )
    )
    if not share_ok:
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G1",
            "MIXED_COHORT",
            f"dominant config fingerprint covers only {share:.0%} of the cohort "
            f"({distribution.distinct} distinct fingerprints); trades cannot be pooled.",
        )

    if metrics.dust_sensitivity_stable is False:
        trace.append(
            GateTrace(
                gate="G1",
                name="dust_sensitivity",
                passed=False,
                value="UNSTABLE",
                limit="STABLE",
                policy_key="classification.require_verdict_stability",
                detail=metrics.dust_sensitivity_detail,
            )
        )
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G1",
            "DUST_SENSITIVE",
            f"verdict changes within the dust sensitivity sweep: {metrics.dust_sensitivity_detail}",
        )
    if metrics.dust_sensitivity_stable is True:
        trace.append(
            GateTrace(
                gate="G1",
                name="dust_sensitivity",
                passed=True,
                value="STABLE",
                limit="STABLE",
                policy_key="classification.dust_sensitivity_sweep",
                detail=metrics.dust_sensitivity_detail,
            )
        )

    # ---------------------------------------------------------------- G2 ---
    exploratory_reason = ""
    if contract is None:
        exploratory_reason = "no pre-registered experiment contract"
    elif contract.policy_version != policy.version:
        trace.append(
            GateTrace(
                gate="G2",
                name="policy_version_match",
                passed=False,
                value=contract.policy_version,
                limit=policy.version,
                policy_key="policy_version",
                detail="contract was frozen under a different policy version",
            )
        )
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G2",
            "POLICY_DRIFT",
            f"contract policy_version {contract.policy_version} does not match active {policy.version}.",
        )
    elif contract.frozen_at > contract.period_start:
        exploratory_reason = "contract was frozen after the measurement period started"
    elif contract.primary_metric in set(policy.get("decision.forbidden_primary_metrics")):
        trace.append(
            GateTrace(
                gate="G2",
                name="primary_metric_allowed",
                passed=False,
                value=contract.primary_metric,
                limit="not in forbidden_primary_metrics",
                policy_key="decision.forbidden_primary_metrics",
                detail="a forbidden metric may never carry a verdict",
            )
        )
        return finish(
            ERROR,
            "G2",
            "INVALID_CONTRACT",
            f"primary_metric '{contract.primary_metric}' is forbidden by policy.",
        )
    elif contract.primary_metric not in set(policy.get("decision.primary_metric_allowlist")):
        trace.append(
            GateTrace(
                gate="G2",
                name="primary_metric_allowed",
                passed=False,
                value=contract.primary_metric,
                limit="in primary_metric_allowlist",
                policy_key="decision.primary_metric_allowlist",
                detail="unknown primary metric",
            )
        )
        return finish(
            ERROR,
            "G2",
            "INVALID_CONTRACT",
            f"primary_metric '{contract.primary_metric}' is not in the policy allowlist.",
        )

    trace.append(
        GateTrace(
            gate="G2",
            name="contract_present",
            passed=not exploratory_reason,
            value=contract.experiment_id if contract else None,
            limit="frozen before period_start",
            policy_key=None,
            detail=exploratory_reason or "valid pre-registered contract",
        )
    )

    advisory = bool(exploratory_reason)

    # ---------------------------------------------------------------- G3 ---
    sample_checks: List[Tuple[str, bool, Any, Any, str]] = [
        (
            "min_matched_trades",
            view_b.n >= int(policy.get("sample.min_matched_trades")),
            view_b.n,
            policy.get("sample.min_matched_trades"),
            "sample.min_matched_trades",
        ),
        (
            "min_trading_days",
            view_b.trading_days >= int(policy.get("sample.min_trading_days")),
            view_b.trading_days,
            policy.get("sample.min_trading_days"),
            "sample.min_trading_days",
        ),
        (
            "min_distinct_pairs",
            view_b.distinct_pairs >= int(policy.get("sample.min_distinct_pairs")),
            view_b.distinct_pairs,
            policy.get("sample.min_distinct_pairs"),
            "sample.min_distinct_pairs",
        ),
    ]
    max_pair = bundle.max_pair_pnl_share
    if max_pair is not None:
        sample_checks.append(
            (
                "max_pair_pnl_share",
                max_pair <= policy.decimal("sample.max_pair_pnl_share"),
                max_pair,
                policy.get("sample.max_pair_pnl_share"),
                "sample.max_pair_pnl_share",
            )
        )
    max_trade = bundle.max_single_trade_pnl_share
    if max_trade is not None:
        sample_checks.append(
            (
                "max_single_trade_pnl_share",
                max_trade <= policy.decimal("sample.max_single_trade_pnl_share"),
                max_trade,
                policy.get("sample.max_single_trade_pnl_share"),
                "sample.max_single_trade_pnl_share",
            )
        )

    sample_failures: List[str] = []
    for name, passed, value, limit, key in sample_checks:
        trace.append(
            GateTrace(
                gate="G3",
                name=name,
                passed=passed,
                value=_fmt(value),
                limit=_fmt(limit),
                policy_key=key,
                advisory=advisory,
            )
        )
        if not passed:
            sample_failures.append(f"{name}={_fmt(value)} (required {_fmt(limit)})")

    if sample_failures and not advisory:
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G3",
            "SAMPLE",
            "sample too small or too concentrated: " + "; ".join(sample_failures),
        )

    # ---------------------------------------------------------------- G5 ---
    # (G4 needs a contract and is evaluated below, after the contract branch.)
    operational_share = bundle.operational_share_of_total
    op_limit = policy.decimal("operational.max_operational_share_of_total")
    op_ok = operational_share is None or operational_share <= op_limit
    trace.append(
        GateTrace(
            gate="G5",
            name="operational_share_of_total",
            passed=op_ok,
            value=_fmt(operational_share),
            limit=_fmt(op_limit),
            policy_key="operational.max_operational_share_of_total",
            detail="|pnl(C)| / |pnl(A)|",
            advisory=advisory,
        )
    )

    unmatched_rate = bundle.unmatched_buy_rate
    ub_limit = policy.decimal("operational.max_unmatched_buy_rate")
    ub_ok = unmatched_rate is None or unmatched_rate <= ub_limit
    trace.append(
        GateTrace(
            gate="G5",
            name="unmatched_buy_rate",
            passed=ub_ok,
            value=_fmt(unmatched_rate),
            limit=_fmt(ub_limit),
            policy_key="operational.max_unmatched_buy_rate",
            detail=f"{bundle.class_distribution.get(UNMATCHED_BUY, 0)} unmatched buy executors",
            advisory=advisory,
        )
    )

    if not advisory and not (op_ok and ub_ok):
        reason = []
        if not op_ok:
            reason.append(f"operational share {_fmt(operational_share)} exceeds {_fmt(op_limit)}")
        if not ub_ok:
            reason.append(f"unmatched buy rate {_fmt(unmatched_rate)} exceeds {_fmt(ub_limit)}")
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G5",
            "OPERATIONAL_NOISE",
            "; ".join(reason) + ". View B is not representative of the strategy.",
        )

    if advisory:
        return finish(
            EXPLORATORY,
            "G2",
            "NO_CONTRACT",
            f"{exploratory_reason}; result is descriptive only and can never become PASS.",
        )

    assert contract is not None  # guaranteed: advisory is False

    # ---------------------------------------------------------------- G4 ---
    trace.append(
        GateTrace(
            gate="G4",
            name="abort_condition",
            passed=not contract.abort_triggered,
            value="triggered" if contract.abort_triggered else "not triggered",
            limit="not triggered",
            policy_key=None,
            detail=contract.abort_detail,
        )
    )
    if contract.abort_triggered:
        return finish(FAIL, "G4", "ABORTED", f"abort condition triggered: {contract.abort_detail}")

    # ---------------------------------------------------------------- G6 ---
    primary = _primary_metric_value(contract.primary_metric, view_b)
    if primary is None:
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G6",
            "METRIC_UNAVAILABLE",
            f"primary metric '{contract.primary_metric}' could not be computed for view B.",
        )

    below_failure = primary <= contract.failure_threshold
    trace.append(
        GateTrace(
            gate="G6",
            name="failure_threshold",
            passed=not below_failure,
            value=_fmt(primary),
            limit=_fmt(contract.failure_threshold),
            policy_key=None,
            detail=contract.primary_metric,
        )
    )
    if below_failure:
        return finish(
            FAIL,
            "G6",
            "BELOW_FAILURE_THRESHOLD",
            f"{contract.primary_metric}={_fmt(primary)} at or below failure threshold "
            f"{_fmt(contract.failure_threshold)}.",
        )

    require_positive = bool(policy.get("decision.require_positive_expectancy_after_fees"))
    expectancy = view_b.expectancy_per_trade
    expectancy_ok = not require_positive or (expectancy is not None and expectancy > 0)
    trace.append(
        GateTrace(
            gate="G6",
            name="positive_expectancy_after_fees",
            passed=expectancy_ok,
            value=_fmt(expectancy),
            limit="> 0",
            policy_key="decision.require_positive_expectancy_after_fees",
        )
    )
    if not expectancy_ok:
        return finish(
            FAIL,
            "G6",
            "NEGATIVE_EXPECTANCY",
            f"expectancy per matched trade is {_fmt(expectancy)} after fees.",
        )

    negative_edge = _edge_is_mathematically_negative(view_b)
    trace.append(
        GateTrace(
            gate="G6",
            name="mathematical_edge",
            passed=negative_edge is not True,
            value=_fmt(view_b.payoff_ratio),
            limit="payoff * wr / (1 - wr) > 1",
            policy_key=None,
            detail="a high win rate alone can never carry a PASS",
        )
    )
    if negative_edge is True:
        return finish(
            FAIL,
            "G6",
            "NEGATIVE_EDGE",
            "payoff ratio and win rate combine to a non-positive edge.",
        )

    # ---------------------------------------------------------------- G7 ---
    conditions: List[Tuple[str, Optional[bool], Any, Any, Optional[str]]] = []

    conditions.append(
        (
            "success_threshold",
            primary >= contract.success_threshold,
            primary,
            contract.success_threshold,
            None,
        )
    )

    difference = metrics.bootstrap_difference
    if difference is None or not difference.available:
        ci_ok: Optional[bool] = None
        ci_value: Any = None
    else:
        ci_ok = difference.ci_low > 0.0
        ci_value = difference.ci_low
    conditions.append(("bootstrap_ci_lower_above_baseline", ci_ok, ci_value, "> 0", "statistics"))

    baseline = metrics.baseline
    if baseline is None:
        conditions.append(("drawdown_vs_baseline", None, None, None, "decision.max_drawdown_ratio_vs_baseline"))
        conditions.append(("operational_rate_vs_baseline", None, None, None, "decision.require_operational_rate_not_worse"))
    else:
        ratio_limit = policy.decimal("decision.max_drawdown_ratio_vs_baseline")
        base_dd = abs(baseline.pnl_sequence_drawdown)
        test_dd = abs(view_b.pnl_sequence_drawdown)
        dd_ok = True if base_dd == 0 else test_dd <= base_dd * ratio_limit
        conditions.append(("drawdown_vs_baseline", dd_ok, test_dd, base_dd * ratio_limit, "decision.max_drawdown_ratio_vs_baseline"))

        if bool(policy.get("decision.require_operational_rate_not_worse")):
            base_op = baseline.operational_share_of_total
            if base_op is None or operational_share is None:
                op_vs = None
            else:
                op_vs = operational_share <= base_op
            conditions.append(("operational_rate_vs_baseline", op_vs, operational_share, base_op, "decision.require_operational_rate_not_worse"))

    unresolved: List[str] = []
    failed: List[str] = []
    for name, outcome, value, limit, key in conditions:
        trace.append(
            GateTrace(
                gate="G7",
                name=name,
                passed=bool(outcome),
                value=_fmt(value),
                limit=_fmt(limit),
                policy_key=key,
                detail="" if outcome is not None else "not evaluable",
            )
        )
        if outcome is None:
            unresolved.append(name)
        elif not outcome:
            failed.append(name)

    if unresolved:
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G7",
            "INCONCLUSIVE",
            "cannot be evaluated without a baseline or bootstrap: " + ", ".join(unresolved),
        )
    if failed:
        return finish(
            INSUFFICIENT_EVIDENCE,
            "G7",
            "INCONCLUSIVE",
            "not all success conditions met: " + ", ".join(failed),
        )

    suffix = " (PAPER)" if contract.mode == "paper" else ""
    return finish(
        PASS,
        "G7",
        "ALL_CONDITIONS_MET",
        f"all success conditions met{suffix}; promotion to live remains a separate human decision.",
    )
