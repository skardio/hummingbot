"""Orchestration: database -> classification -> metrics -> gates -> verdict.

This module wires the pure components together and is the only place that
combines I/O with computation. The verdict itself is still produced exclusively
by :func:`tools.evidence.gate_engine.gate_engine`.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .bootstrap import BootstrapResult, block_bootstrap_difference, block_bootstrap_mean
from .classify import Classification, classify, extract_facts
from .db import RawExecutor, TradeFillAttribution, load_closed_executors, tradefill_attribution
from .fingerprint import field_volatility, fingerprint_config, fingerprint_distribution
from .gate_engine import BaselineSummary, CohortInfo, Contract, GateInput, VerdictResult, gate_engine
from .metrics import ExecutorRecord, MetricsBundle, compute_metrics
from .policy import Policy
from .reconcile import ReconciliationResult, reconcile


@dataclass(frozen=True)
class EvidenceReport:
    """Everything a report renderer or agent needs. The verdict is authoritative."""

    verdict: VerdictResult
    metrics: MetricsBundle
    reconciliation: ReconciliationResult
    cohort: CohortInfo
    bootstrap: Optional[BootstrapResult]
    bootstrap_difference: Optional[BootstrapResult]
    dust_sensitivity: Mapping[str, Any]
    attribution: TradeFillAttribution
    field_volatility: Sequence[Any]
    input_hash: str
    database: str
    policy_version: str
    n_raw_executors: int


def _classify_one(custom_info: Mapping[str, Any], policy: Policy,
                  dust_abs: Decimal, dust_rel: Decimal) -> Tuple[Classification, Any]:
    facts = extract_facts(custom_info)
    classification = classify(
        facts,
        dust_abs_quote=dust_abs,
        dust_rel_pct=dust_rel,
        zero_residual_epsilon_base=policy.decimal("classification.zero_residual_epsilon_base"),
        dust_signature_epsilon_quote=policy.decimal("classification.dust_signature_epsilon_quote"),
    )
    return classification, facts


def build_records(
    executors: Sequence[RawExecutor],
    policy: Policy,
    dust_abs: Decimal,
    dust_rel: Decimal,
) -> List[ExecutorRecord]:
    """Classify and fingerprint raw executors into analysable records."""
    records: List[ExecutorRecord] = []
    for raw in executors:
        classification, facts = _classify_one(raw.custom_info, policy, dust_abs, dust_rel)
        stored_buy = facts.stored_realized_buy_quote
        realized_buy = stored_buy if stored_buy is not None else facts.buy_quote
        realized_sell = _decimal_field(raw.custom_info, "realized_sell_size_quote", facts.sell_quote)
        position_size = _decimal_field(raw.custom_info, "position_size_quote", Decimal(0))
        records.append(
            ExecutorRecord(
                executor_id=raw.executor_id,
                close_timestamp=int(raw.close_timestamp or 0),
                trading_pair=raw.trading_pair,
                close_type=raw.close_type,
                net_pnl_quote=raw.net_pnl_quote,
                cum_fees_quote=raw.cum_fees_quote,
                filled_amount_quote=raw.filled_amount_quote,
                realized_buy_size_quote=realized_buy,
                realized_sell_size_quote=realized_sell,
                position_size_quote=position_size,
                classification=classification,
                fingerprint=fingerprint_config(raw.config, policy).full,
            )
        )
    return records


def _decimal_field(payload: Mapping[str, Any], key: str, default: Decimal) -> Decimal:
    value = payload.get(key)
    if value is None:
        return default
    try:
        parsed = Decimal(str(value))
    except Exception:  # noqa: BLE001 - malformed values fall back to the default
        return default
    return parsed if parsed.is_finite() else default


def run_reconciliation(bundle: MetricsBundle, policy: Policy, n_records: int) -> ReconciliationResult:
    low, high = policy.get("data_integrity.fee_rate_plausible_range")
    return reconcile(
        net_pnl=bundle.totals["net_pnl"],
        buy_quote=bundle.totals["buy_quote"],
        sell_quote=bundle.totals["sell_quote"],
        fees=bundle.totals["fees"],
        pnl_a=bundle.views["A"].net_pnl,
        pnl_b=bundle.views["B"].net_pnl,
        pnl_c=bundle.views["C"].net_pnl,
        traded_notional=bundle.totals["buy_quote"] + bundle.totals["sell_quote"],
        total_executors=n_records,
        classified_executors=sum(bundle.class_distribution.values()),
        residual_rel=policy.decimal("data_integrity.reconciliation_residual_rel"),
        residual_abs=policy.decimal("data_integrity.reconciliation_residual_abs"),
        abc_tolerance=policy.decimal("data_integrity.abc_identity_tolerance_abs"),
        allow_negative_fees=bool(policy.get("data_integrity.allow_negative_fees")),
        fee_rate_range=(Decimal(str(low)), Decimal(str(high))),
    )


def _cohort_info(records: Sequence[ExecutorRecord], executors: Sequence[RawExecutor],
                 controller_id: Optional[str], quote: str) -> CohortInfo:
    venue = executors[0].connector_name if executors else "UNKNOWN"
    controller = controller_id or (executors[0].controller_id if executors else "UNKNOWN")
    return CohortInfo(
        venue=venue,
        quote=quote,
        controller_id=str(controller),
        fingerprint_distribution=fingerprint_distribution([r.fingerprint for r in records]),
        period_start=min((r.close_timestamp for r in records), default=None),
        period_end=max((r.close_timestamp for r in records), default=None),
    )


def _verdict_for(
    executors: Sequence[RawExecutor],
    policy: Policy,
    contract: Optional[Contract],
    baseline: Optional[BaselineSummary],
    dust_abs: Decimal,
    dust_rel: Decimal,
    quote: str,
    controller_id: Optional[str],
    with_bootstrap: bool,
) -> Tuple[VerdictResult, MetricsBundle, ReconciliationResult, CohortInfo,
           Optional[BootstrapResult], Optional[BootstrapResult]]:
    """Run the full chain for one pair of dust thresholds."""
    records = build_records(executors, policy, dust_abs, dust_rel)
    bundle = compute_metrics(records)
    recon = run_reconciliation(bundle, policy, len(records))
    cohort = _cohort_info(records, executors, controller_id, quote)

    boot: Optional[BootstrapResult] = None
    boot_diff: Optional[BootstrapResult] = None
    if with_bootstrap:
        boot = block_bootstrap_mean(
            bundle.daily_pnl_matched,
            int(policy.get("statistics.n_resamples")),
            float(policy.get("statistics.confidence_level")),
            int(policy.get("statistics.random_seed")),
        )
        if baseline is not None and baseline.daily_pnl_matched:
            boot_diff = block_bootstrap_difference(
                bundle.daily_pnl_matched,
                baseline.daily_pnl_matched,
                int(policy.get("statistics.n_resamples")),
                float(policy.get("statistics.confidence_level")),
                int(policy.get("statistics.random_seed")),
            )

    gate_input = GateInput(
        metrics=bundle,
        reconciliation=recon,
        cohort=cohort,
        bootstrap=boot,
        bootstrap_difference=boot_diff,
        baseline=baseline,
        dust_sensitivity_stable=None,
    )
    return gate_engine(gate_input, policy, contract), bundle, recon, cohort, boot, boot_diff


def run_dust_sweep(
    executors: Sequence[RawExecutor],
    policy: Policy,
    contract: Optional[Contract],
    baseline: Optional[BaselineSummary],
    quote: str,
    controller_id: Optional[str],
) -> Dict[str, Any]:
    """Re-run the gate chain across the dust sensitivity sweep.

    The verdict must be identical at every point; otherwise an arbitrary
    threshold would be carrying the conclusion.
    """
    sweep = policy.get("classification.dust_sensitivity_sweep")
    points: List[Dict[str, Any]] = []
    verdicts = set()
    for abs_quote in sweep["abs_quote"]:
        for rel_pct in sweep["rel_pct"]:
            verdict, bundle, _, _, _, _ = _verdict_for(
                executors, policy, contract, baseline,
                Decimal(str(abs_quote)), Decimal(str(rel_pct)),
                quote, controller_id, with_bootstrap=baseline is not None,
            )
            verdicts.add((verdict.verdict, verdict.gate, verdict.reason_code))
            points.append(
                {
                    "dust_abs_quote": str(abs_quote),
                    "dust_rel_pct": str(rel_pct),
                    "verdict": verdict.verdict,
                    "gate": verdict.gate,
                    "reason_code": verdict.reason_code,
                    "n_view_b": bundle.views["B"].n,
                    "pnl_view_b": format(bundle.views["B"].net_pnl, "f"),
                }
            )

    stable = len(verdicts) <= 1
    sizes = [point["n_view_b"] for point in points]
    size_min, size_max = (min(sizes), max(sizes)) if sizes else (0, 0)
    spread = (size_max - size_min) / size_max if size_max else 0.0
    blocking_gates = {point["gate"] for point in points}
    # A verdict can be "stable" simply because an earlier gate blocks every
    # point. In that case the sweep proves nothing about the dust threshold, so
    # the masking is reported explicitly rather than hidden behind stable=True.
    masked = stable and blocking_gates.issubset({"G0", "G1", "G2", "G3", "G5"})

    detail = (
        "verdict identical across the full sweep"
        if stable
        else "verdict varies: " + "; ".join(sorted(f"{v}/{g}/{r}" for v, g, r in verdicts))
    )
    if stable and masked and spread > 0:
        detail += (
            f" (but view B composition varies {size_min}..{size_max}; stability is masked by "
            f"gate {sorted(blocking_gates)[0]} blocking every point)"
        )
    return {
        "stable": stable,
        "detail": detail,
        "points": points,
        "n_points": len(points),
        "n_view_b_min": size_min,
        "n_view_b_max": size_max,
        "composition_spread": spread,
        "stability_masked_by_earlier_gate": masked,
    }


def compute_input_hash(database: Path, policy: Policy, contract: Optional[Contract],
                       controller_id: Optional[str],
                       period_start: Optional[int] = None,
                       period_end: Optional[int] = None) -> str:
    """Identity of this run: identical hash must yield identical output."""
    stat = database.stat()
    payload = {
        "policy_version": policy.version,
        "database": database.name,
        "db_size": stat.st_size,
        "db_mtime": int(stat.st_mtime),
        "controller_id": controller_id,
        "period_start": period_start,
        "period_end": period_end,
        "contract": contract.experiment_id if contract else None,
        "contract_frozen_at": contract.frozen_at if contract else None,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def run_evidence(
    database: str | Path,
    policy: Policy,
    *,
    contract: Optional[Contract] = None,
    baseline: Optional[BaselineSummary] = None,
    controller_id: Optional[str] = None,
    quote: str = "UNKNOWN",
    period_start: Optional[int] = None,
    period_end: Optional[int] = None,
) -> EvidenceReport:
    """Produce a complete evidence report for one database and cohort."""
    db_path = Path(database)
    executors = load_closed_executors(
        db_path, controller_id=controller_id, period_start=period_start, period_end=period_end
    )

    sweep = run_dust_sweep(executors, policy, contract, baseline, quote, controller_id)

    verdict, bundle, recon, cohort, boot, boot_diff = _verdict_for(
        executors,
        policy,
        contract,
        baseline,
        policy.decimal("classification.dust_abs_quote"),
        policy.decimal("classification.dust_rel_pct"),
        quote,
        controller_id,
        with_bootstrap=True,
    )

    # Re-evaluate with the sweep outcome so G1 can block a threshold-dependent verdict.
    final_input = GateInput(
        metrics=bundle,
        reconciliation=recon,
        cohort=cohort,
        bootstrap=boot,
        bootstrap_difference=boot_diff,
        baseline=baseline,
        dust_sensitivity_stable=sweep["stable"] if bool(policy.get("classification.require_verdict_stability")) else None,
        dust_sensitivity_detail=sweep["detail"],
    )
    verdict = gate_engine(final_input, policy, contract)

    return EvidenceReport(
        verdict=verdict,
        metrics=bundle,
        reconciliation=recon,
        cohort=cohort,
        bootstrap=boot,
        bootstrap_difference=boot_diff,
        dust_sensitivity=sweep,
        field_volatility=field_volatility(
            [executor.config for executor in executors], policy
        ),
        attribution=tradefill_attribution(db_path, executors),
        input_hash=compute_input_hash(db_path, policy, contract, controller_id, period_start, period_end),
        database=str(db_path),
        policy_version=policy.version,
        n_raw_executors=len(executors),
    )
