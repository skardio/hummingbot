"""Command-line entry point for the Evidence Engine.

Without a pre-registered experiment contract the engine runs in EXPLORATORY
mode: it reports the measurements but can never return PASS.

    python -m tools.evidence.cli --database data/spot_grid_bitget.sqlite --quote USDT
"""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from .pipeline import EvidenceReport, run_evidence
from .policy import DEFAULT_POLICY_PATH, load_policy

LINE = "=" * 72


def _num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, Decimal):
        return f"{value:,.{digits}f}"
    if isinstance(value, float):
        return f"{value:,.{digits}f}"
    return str(value)


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def render_text(report: EvidenceReport) -> str:
    bundle = report.metrics
    out = [LINE, "EVIDENCE REPORT", LINE]
    out.append(f"Database       : {report.database}")
    out.append(f"Venue / quote  : {report.cohort.venue} / {report.cohort.quote}")
    out.append(f"Controller     : {report.cohort.controller_id}")
    out.append(f"Policy version : {report.policy_version}")
    out.append(f"Input hash     : {report.input_hash[:16]}")
    out.append(f"Closed execs   : {report.n_raw_executors}")

    out.append("")
    out.append("--- DATA QUALITY " + "-" * 55)
    for check in report.reconciliation.checks:
        status = "OK " if check.passed else "FAIL"
        out.append(f"  {status} {check.name:<24} value={_num(check.value, 4):>14}  limit={_num(check.limit, 4):>14}")
    coverage = report.attribution
    if coverage.attributable:
        ratio = coverage.attribution_ratio
        out.append(f"       tradefill_attribution    {_pct(ratio):>14}"
                   f"  ({_num(coverage.attributed_volume, 1)} / {_num(coverage.executor_volume, 1)})")
        out.append(f"       matched fills            {coverage.n_matched_fills:>14}"
                   f"  of {coverage.n_total_fills} rows, via {coverage.n_order_ids} order ids")
        out.append(f"       effective fee rate       {_pct(coverage.effective_fee_rate):>14}  (per side)")
    else:
        out.append(f"       TRADEFILL ATTRIBUTION: NOT MEASURABLE PER CONTROLLER ({coverage.reason})")
    if len(coverage.controller_ids) > 1:
        out.append(f"       NOTE: database holds {len(coverage.controller_ids)} controllers "
                   f"{list(coverage.controller_ids)}; attribution is per executor and stays valid.")

    out.append("")
    out.append("--- CLASS DISTRIBUTION " + "-" * 49)
    out.append(f"  {'class':<26} {'n':>6} {'pnl':>12} {'share':>8}")
    total_pnl = bundle.views["A"].net_pnl
    for cls in sorted(bundle.class_distribution, key=lambda c: -abs(bundle.class_pnl.get(c, Decimal(0)))):
        pnl = bundle.class_pnl.get(cls, Decimal(0))
        share = f"{float(pnl / total_pnl) * 100:.1f}%" if total_pnl else "n/a"
        out.append(f"  {cls:<26} {bundle.class_distribution[cls]:>6} {_num(pnl, 2):>12} {share:>8}")

    out.append("")
    out.append("--- VIEWS A / B / C " + "-" * 52)
    header = f"  {'metric':<26} {'A ALL-IN':>14} {'B STRATEGY':>14} {'C OPERATIONAL':>15}"
    out.append(header)
    rows = [
        ("executors", "n", 0),
        ("net pnl", "net_pnl", 2),
        ("fees", "fees", 2),
        ("gross pnl", "gross_pnl", 2),
        ("deployed capital", "deployed_capital", 1),
        ("expectancy / trade", "expectancy_per_trade", 4),
        ("return on deployed", "return_on_deployed", 5),
        ("win rate", "win_rate", 4),
        ("avg win", "avg_win", 4),
        ("avg loss", "avg_loss", 4),
        ("payoff ratio", "payoff_ratio", 3),
        ("profit factor", "profit_factor", 3),
        ("worst trade", "worst_trade", 2),
        ("pnl-seq drawdown", "pnl_sequence_drawdown", 2),
        ("max consec losses", "max_consecutive_losses", 0),
        ("trading days", "trading_days", 0),
        ("distinct pairs", "distinct_pairs", 0),
    ]
    for label, attribute, digits in rows:
        values = [_num(getattr(bundle.views[view], attribute), digits) for view in ("A", "B", "C")]
        out.append(f"  {label:<26} {values[0]:>14} {values[1]:>14} {values[2]:>15}")
    out.append("  NOTE: pnl-seq drawdown is NOT equity drawdown (no equity snapshots exist).")

    out.append("")
    out.append("--- RECONCILIATION A = B + C " + "-" * 43)
    a, b, c = (bundle.views[v].net_pnl for v in ("A", "B", "C"))
    out.append(f"  A={_num(a, 4)}   B={_num(b, 4)}   C={_num(c, 4)}   residual={_num(a - (b + c), 6)}")
    out.append(f"  legs: buy={_num(bundle.totals['buy_quote'], 2)}  sell={_num(bundle.totals['sell_quote'], 2)}"
               f"  fees={_num(bundle.totals['fees'], 2)}")

    out.append("")
    out.append("--- FINGERPRINT " + "-" * 56)
    dist = report.cohort.fingerprint_distribution
    out.append(f"  distinct={dist.distinct}  total={dist.total}"
               f"  dominant_share={dist.dominant_share * 100:.1f}%  health={dist.health:.3f}")
    for fingerprint, count in sorted(dist.counts.items(), key=lambda kv: -kv[1])[:8]:
        out.append(f"    {fingerprint[:10]}  n={count}")
    if report.field_volatility:
        out.append("  fields driving fragmentation (operator must judge parameter vs observation):")
        for item in report.field_volatility[:6]:
            out.append(f"    {item.key:<46} distinct={item.distinct:<4} e.g. {list(item.examples)}")

    out.append("")
    out.append("--- OPERATIONAL " + "-" * 56)
    out.append(f"  operational share of |A| : {_pct(bundle.operational_share_of_total)}")
    out.append(f"  unmatched buy rate       : {_pct(bundle.unmatched_buy_rate)}")
    out.append(f"  heuristic share of B     : {_pct(bundle.heuristic_share_of_b)}")

    out.append("")
    out.append("--- DUST SENSITIVITY " + "-" * 51)
    sweep = report.dust_sensitivity
    out.append(f"  points={sweep['n_points']}  stable={sweep['stable']}")
    out.append(f"  view B size across sweep : {sweep['n_view_b_min']} .. {sweep['n_view_b_max']}"
               f"  (spread {sweep['composition_spread'] * 100:.1f}%)")
    if sweep.get("stability_masked_by_earlier_gate") and sweep["composition_spread"] > 0:
        out.append("  WARNING: stability is masked by an earlier blocking gate;")
        out.append("           the sweep proves nothing about the dust threshold here.")
    out.append(f"  {sweep['detail']}")

    out.append("")
    out.append("--- STATISTICAL EVIDENCE " + "-" * 47)
    boot = report.bootstrap
    if boot is None or not boot.available:
        out.append("  bootstrap: NOT AVAILABLE (insufficient matched trades or trading days)")
    else:
        out.append(f"  method={boot.method}  resamples={boot.n_resamples}  seed={boot.seed}")
        out.append(f"  blocks(days)={boot.n_blocks}  observations={boot.n_observations}")
        out.append(f"  expectancy point={_num(boot.point_estimate, 4)}"
                   f"  95% CI=[{_num(boot.ci_low, 4)}, {_num(boot.ci_high, 4)}]")
        out.append(f"  excludes zero: {boot.excludes_zero}")
    out.append("  power analysis: NOT PERFORMED (non-stationary variance)")
    out.append("  independence  : NOT ESTABLISHED (concurrent correlated executors)")

    out.append("")
    out.append("--- NOT MEASURABLE WITH CURRENT DATA " + "-" * 35)
    for item in (
        "equity drawdown", "sharpe / sortino", "time-weighted return",
        "true maker/taker split", "regime segmentation", "expected vs realised slippage",
    ):
        out.append(f"  - {item}")

    out.append("")
    out.append(LINE)
    out.append(f"VERDICT: {report.verdict.verdict}")
    out.append(f"GATE   : {report.verdict.gate}  ({report.verdict.reason_code})")
    out.append("REASON :")
    out.append(f"  {report.verdict.reason}")
    out.append("")
    out.append("DO NOT CHANGE:")
    out.append("  - no parameter tuning on the basis of this report")
    out.append("  - no promotion to live")
    out.append(LINE)
    return "\n".join(out)


def render_json(report: EvidenceReport) -> Dict[str, Any]:
    bundle = report.metrics

    def view(name: str) -> Dict[str, Any]:
        metrics = bundle.views[name]
        return {
            "n": metrics.n,
            "net_pnl": str(metrics.net_pnl),
            "fees": str(metrics.fees),
            "gross_pnl": str(metrics.gross_pnl),
            "deployed_capital": str(metrics.deployed_capital),
            "expectancy_per_trade": str(metrics.expectancy_per_trade) if metrics.expectancy_per_trade is not None else None,
            "return_on_deployed": str(metrics.return_on_deployed) if metrics.return_on_deployed is not None else None,
            "win_rate": str(metrics.win_rate) if metrics.win_rate is not None else None,
            "payoff_ratio": str(metrics.payoff_ratio) if metrics.payoff_ratio is not None else None,
            "profit_factor": str(metrics.profit_factor) if metrics.profit_factor is not None else None,
            "worst_trade": str(metrics.worst_trade) if metrics.worst_trade is not None else None,
            "pnl_sequence_drawdown": str(metrics.pnl_sequence_drawdown),
            "max_consecutive_losses": metrics.max_consecutive_losses,
            "trading_days": metrics.trading_days,
            "distinct_pairs": metrics.distinct_pairs,
        }

    return {
        "schema_version": "1.0.0",
        "policy_version": report.policy_version,
        "input_hash": report.input_hash,
        "database": report.database,
        "cohort": {
            "venue": report.cohort.venue,
            "quote": report.cohort.quote,
            "controller_id": report.cohort.controller_id,
            "fingerprint_distinct": report.cohort.fingerprint_distribution.distinct,
            "fingerprint_dominant_share": report.cohort.fingerprint_distribution.dominant_share,
            "fingerprint_health": report.cohort.fingerprint_distribution.health,
        },
        "data_quality": {
            check.name: {
                "passed": check.passed,
                "value": str(check.value) if check.value is not None else None,
                "limit": str(check.limit) if check.limit is not None else None,
            }
            for check in report.reconciliation.checks
        },
        "tradefill_attribution": {
            "attributable": report.attribution.attributable,
            "reason": report.attribution.reason,
            "ratio": (str(report.attribution.attribution_ratio)
                      if report.attribution.attribution_ratio is not None else None),
            "attributed_volume": str(report.attribution.attributed_volume),
            "executor_volume": str(report.attribution.executor_volume),
            "attributed_fees": str(report.attribution.attributed_fees),
            "effective_fee_rate": (str(report.attribution.effective_fee_rate)
                                   if report.attribution.effective_fee_rate is not None else None),
            "n_matched_fills": report.attribution.n_matched_fills,
            "n_total_fills": report.attribution.n_total_fills,
            "n_order_ids": report.attribution.n_order_ids,
            "controller_ids": list(report.attribution.controller_ids),
        },
        "field_volatility": [
            {"key": item.key, "distinct": item.distinct, "total": item.total, "examples": list(item.examples)}
            for item in report.field_volatility
        ],
        "class_distribution": dict(bundle.class_distribution),
        "class_pnl": {cls: str(value) for cls, value in bundle.class_pnl.items()},
        "close_type_distribution": {str(k): v for k, v in bundle.close_type_distribution.items()},
        "views": {name: view(name) for name in ("A", "B", "C")},
        "operational_share_of_total": str(bundle.operational_share_of_total) if bundle.operational_share_of_total is not None else None,
        "unmatched_buy_rate": str(bundle.unmatched_buy_rate) if bundle.unmatched_buy_rate is not None else None,
        "heuristic_share_of_b": str(bundle.heuristic_share_of_b) if bundle.heuristic_share_of_b is not None else None,
        "dust_sensitivity": report.dust_sensitivity,
        "bootstrap": None if report.bootstrap is None else {
            "method": report.bootstrap.method,
            "n_resamples": report.bootstrap.n_resamples,
            "seed": report.bootstrap.seed,
            "n_blocks": report.bootstrap.n_blocks,
            "n_observations": report.bootstrap.n_observations,
            "point_estimate": report.bootstrap.point_estimate,
            "ci_low": report.bootstrap.ci_low,
            "ci_high": report.bootstrap.ci_high,
        },
        "not_measurable": [
            "equity_drawdown", "sharpe", "sortino", "time_weighted_return",
            "maker_taker_true_split", "regime_segmentation", "expected_vs_realised_slippage",
        ],
        **report.verdict.as_dict(),
    }


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Evidence Engine (deterministic foundation)")
    parser.add_argument("--database", required=True, help="path to a bot SQLite database (read-only)")
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--controller-id", default=None)
    parser.add_argument("--quote", default="UNKNOWN")
    parser.add_argument("--period-start", type=int, default=None, help="unix seconds, inclusive")
    parser.add_argument("--period-end", type=int, default=None, help="unix seconds, inclusive")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON instead of text")
    parser.add_argument("--json-out", default=None, help="also write the JSON payload to this path")
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    report = run_evidence(
        args.database,
        policy,
        controller_id=args.controller_id,
        quote=args.quote,
        period_start=args.period_start,
        period_end=args.period_end,
    )

    payload = render_json(report)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
