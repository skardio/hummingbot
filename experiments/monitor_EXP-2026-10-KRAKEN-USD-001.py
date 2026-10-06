#!/usr/bin/env python
"""Daily monitor for EXP-2026-10-KRAKEN-USD-001.

Read-only. Prints only the metrics the contract permits before the sample
gate is met. Profitability figures are deliberately NOT shown: looking at
them mid-run invites stopping at a favourable moment.

    source ~/.venvs/bot/bin/activate
    python experiments/monitor_EXP-2026-10-KRAKEN-USD-001.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tools.evidence.classify import UNMATCHED_BUY  # noqa: E402
from tools.evidence.db import load_closed_executors  # noqa: E402
from tools.evidence.fingerprint import fingerprint_config  # noqa: E402
from tools.evidence.metrics import compute_metrics  # noqa: E402
from tools.evidence.pipeline import build_records  # noqa: E402
from tools.evidence.policy import load_policy  # noqa: E402

# --- contract constants: must match EXP-2026-10-KRAKEN-USD-001.yaml ---
EXPERIMENT_ID = "EXP-2026-10-KRAKEN-USD-001"
PERIOD_START = 1791125758          # 2026-10-04T14:55:58Z
PERIOD_END_LATEST = 1791125758 + 45 * 86400
FROZEN_FINGERPRINT = "49344cef79"
EXPECTED_POLICY = "1.3.0"
DATABASE = REPO / "data" / "multi_coin_grid_v2_usd.sqlite"
CONTROLLER_ID = "multi_coin_grid_usd"

MIN_MATCHED = 100
MIN_DAYS = 20
MIN_PAIRS = 5
MAX_UNMATCHED_BUY_RATE = 0.10
MAX_OPERATIONAL_SHARE = 0.25
MAX_HEURISTIC_SHARE = 0.20


def pct(value) -> str:
    return "n/a" if value is None else f"{float(value) * 100:.1f}%"


def bar(done: int, needed: int, width: int = 24) -> str:
    filled = min(width, int(width * done / needed)) if needed else 0
    return "[" + "#" * filled + "-" * (width - filled) + f"] {done}/{needed}"


def main() -> int:
    policy = load_policy(REPO / "config" / "evidence_policy.yaml")
    now = int(datetime.now(tz=timezone.utc).timestamp())
    alerts: list[str] = []

    print("=" * 68)
    print(f"MONITOR  {EXPERIMENT_ID}")
    print("=" * 68)

    if policy.version != EXPECTED_POLICY:
        alerts.append(f"POLICY DRIFT: {policy.version} != {EXPECTED_POLICY} -> EXPERIMENT INVALID")

    executors = [
        e for e in load_closed_executors(DATABASE, controller_id=CONTROLLER_ID)
        if e.close_timestamp >= PERIOD_START
    ]
    fingerprints = {fingerprint_config(e.config, policy).short for e in executors}
    records = build_records(
        executors,
        policy,
        policy.decimal("classification.dust_abs_quote"),
        policy.decimal("classification.dust_rel_pct"),
    )
    bundle = compute_metrics(records)
    view_b = bundle.views["B"]

    elapsed_days = (now - PERIOD_START) / 86400
    remaining_days = (PERIOD_END_LATEST - now) / 86400

    print(f"elapsed            : {elapsed_days:.1f} days   remaining {remaining_days:.1f}")
    print(f"closed executors   : {len(executors)}")
    print()
    print("SAMPLE GATE")
    print(f"  matched trades   : {bar(view_b.n, MIN_MATCHED)}")
    print(f"  trading days     : {bar(view_b.trading_days, MIN_DAYS)}")
    print(f"  distinct pairs   : {bar(view_b.distinct_pairs, MIN_PAIRS)}")
    gate_met = (view_b.n >= MIN_MATCHED
                and view_b.trading_days >= MIN_DAYS
                and view_b.distinct_pairs >= MIN_PAIRS)
    print(f"  gate met         : {'YES - run the final adjudication' if gate_met else 'not yet'}")

    print()
    print("ABORT WATCH")
    for label, value, limit in (
        ("unmatched_buy_rate", bundle.unmatched_buy_rate, MAX_UNMATCHED_BUY_RATE),
        ("operational_share ", bundle.operational_share_of_total, MAX_OPERATIONAL_SHARE),
        ("heuristic_share_B ", bundle.heuristic_share_of_b, MAX_HEURISTIC_SHARE),
    ):
        breached = value is not None and float(value) > limit
        flag = "  <<< ABORT" if breached else ""
        print(f"  {label}: {pct(value):>8}   limit {limit:.0%}{flag}")
        if breached:
            alerts.append(f"{label.strip()} {pct(value)} exceeds {limit:.0%} -> ABORT")
    n_unmatched = bundle.class_distribution.get(UNMATCHED_BUY, 0)
    if n_unmatched:
        print(f"  UNMATCHED_BUY    : {n_unmatched} executor(s) - the Apr/May failure mode")

    print()
    print("INTEGRITY")
    drift = bool(fingerprints - {FROZEN_FINGERPRINT})
    print(f"  policy_version   : {policy.version}")
    print(f"  fingerprints     : {sorted(fingerprints) if fingerprints else 'none yet'}")
    print(f"  fingerprint drift: {'YES -> EXPERIMENT INVALID' if drift else 'no'}")
    if drift:
        alerts.append(f"FINGERPRINT DRIFT: {sorted(fingerprints - {FROZEN_FINGERPRINT})} -> EXPERIMENT INVALID")
    if now > PERIOD_END_LATEST and not gate_met:
        alerts.append("TIMEOUT reached without the sample gate -> close as INSUFFICIENT_EVIDENCE (SAMPLE)")

    print()
    print("=" * 68)
    if alerts:
        print("ACTION REQUIRED")
        for alert in alerts:
            print(f"  ! {alert}")
        print("  Stop the bot yourself; record the trigger in the contract.")
    else:
        print("OK - no abort condition triggered. Do not inspect PnL before the gate.")
    print("=" * 68)
    return 1 if alerts else 0


if __name__ == "__main__":
    raise SystemExit(main())
