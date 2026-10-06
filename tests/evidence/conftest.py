"""Shared fixtures for the Evidence Engine tests.

Every fixture is synthetic. No test reads a real database or the network.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from tools.evidence.classify import classify, extract_facts
from tools.evidence.fingerprint import fingerprint_config, fingerprint_distribution
from tools.evidence.gate_engine import CohortInfo, GateInput
from tools.evidence.metrics import ExecutorRecord, compute_metrics
from tools.evidence.policy import load_policy
from tools.evidence.reconcile import reconcile

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "config" / "evidence_policy.yaml"

DAY_SECONDS = 86400
BASE_TS = 1_767_225_600  # 2026-01-01T00:00:00Z


@pytest.fixture(scope="session")
def policy():
    return load_policy(POLICY_PATH)


def make_order(
    side: str,
    base: str,
    quote: str,
    order_id: str,
    fee_quote: str = "0",
    order_type: str = "LIMIT",
) -> Dict[str, Any]:
    """Build one entry of ``custom_info.filled_orders``."""
    return {
        "client_order_id": order_id,
        "trade_type": side,
        "executed_amount_base": base,
        "executed_amount_quote": quote,
        "cumulative_fee_paid_quote": fee_quote,
        "order_type": order_type,
    }


def make_custom_info(
    filled_orders: Optional[List[Dict[str, Any]]] = None,
    held_position_orders: Optional[List[Dict[str, Any]]] = None,
    realized_buy_size_quote: Optional[str] = None,
    position_size_quote: str = "0",
    realized_sell_size_quote: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a ``custom_info`` payload.

    ``realized_buy_size_quote`` defaults to the exact sum of the buy legs, i.e.
    no dust correction was applied. Pass a smaller value to simulate the
    executor's own dust correction.
    """
    orders = filled_orders or []
    held = held_position_orders or []
    held_ids = {o["client_order_id"] for o in held}
    regular = [o for o in orders if o["client_order_id"] not in held_ids]

    if realized_buy_size_quote is None:
        total = sum(
            (Decimal(o["executed_amount_quote"]) for o in regular if o["trade_type"] == "BUY"),
            Decimal(0),
        )
        realized_buy_size_quote = format(total, "f")
    if realized_sell_size_quote is None:
        total_sell = sum(
            (Decimal(o["executed_amount_quote"]) for o in regular if o["trade_type"] == "SELL"),
            Decimal(0),
        )
        realized_sell_size_quote = format(total_sell, "f")

    return {
        "filled_orders": orders,
        "held_position_orders": held,
        "realized_buy_size_quote": realized_buy_size_quote,
        "realized_sell_size_quote": realized_sell_size_quote,
        "position_size_quote": position_size_quote,
    }


def base_config(**overrides: Any) -> Dict[str, Any]:
    """A realistic executor config, shaped like the real database payload."""
    config: Dict[str, Any] = {
        "id": "executor-1",
        "timestamp": 1790960906.722423,
        "level_id": None,
        "connector_name": "kraken",
        "controller_id": "multi_coin_grid_usd",
        "trading_pair": "APE-USD",
        "total_amount_quote": "40.91494378125",
        "start_price": "0.16637370",
        "end_price": "0.16922630",
        "limit_price": "0.1580550150",
        "min_order_amount_quote": "15",
        "activation_bounds": "0.075",
        "max_open_orders": 2,
        "order_frequency": 3,
        "side": 1,
        "triple_barrier_config": {
            "stop_loss": "0.02",
            "take_profit": "0.075",
            "trailing_stop": {"activation_price": "0.015", "trailing_delta": "0.01"},
        },
        "custom_info": {
            "bot_instance_id": "usd",
            "atr_pct": "0.19123456",
            "entry_trend_pct": "10.76",
            "entry_grid_score": "0.65",
            "no_fill_timeout_sec": 3600,
            "no_progress_timeout_sec": 5400,
            "max_hold_time_sec": 5400,
        },
    }
    for dotted, value in overrides.items():
        node: Any = config
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return config


def build_record(
    policy,
    *,
    executor_id: str = "e1",
    day_offset: int = 0,
    trading_pair: str = "APE-USD",
    close_type: Optional[int] = 3,
    net_pnl: Optional[str] = None,
    fees: str = "0",
    custom_info: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> ExecutorRecord:
    """Classify and wrap one synthetic executor into an :class:`ExecutorRecord`.

    ``net_pnl`` defaults to ``(sell - buy) - fees`` so fixtures satisfy the leg
    identity by construction. Pass an explicit value only when deliberately
    testing inconsistent data.
    """
    info = custom_info if custom_info is not None else make_custom_info()
    cfg = config if config is not None else base_config()
    facts = extract_facts(info)
    realized_buy = facts.stored_realized_buy_quote
    if realized_buy is None:
        realized_buy = facts.buy_quote
    if net_pnl is None:
        derived = (facts.sell_quote - realized_buy) - Decimal(fees)
        net_pnl = format(derived, "f")
    classification = classify(
        facts,
        dust_abs_quote=policy.decimal("classification.dust_abs_quote"),
        dust_rel_pct=policy.decimal("classification.dust_rel_pct"),
        zero_residual_epsilon_base=policy.decimal("classification.zero_residual_epsilon_base"),
        dust_signature_epsilon_quote=policy.decimal("classification.dust_signature_epsilon_quote"),
    )
    return ExecutorRecord(
        executor_id=executor_id,
        close_timestamp=BASE_TS + day_offset * DAY_SECONDS,
        trading_pair=trading_pair,
        close_type=close_type,
        net_pnl_quote=Decimal(net_pnl),
        cum_fees_quote=Decimal(fees),
        filled_amount_quote=facts.buy_quote + facts.sell_quote,
        realized_buy_size_quote=realized_buy,
        realized_sell_size_quote=facts.sell_quote,
        position_size_quote=Decimal(str(info.get("position_size_quote", "0"))),
        classification=classification,
        fingerprint=fingerprint_config(cfg, policy).full,
    )


def build_gate_input(policy, records: List[ExecutorRecord], **cohort_overrides: Any) -> GateInput:
    """Assemble a :class:`GateInput` with real reconciliation over the records."""
    bundle = compute_metrics(records)
    low, high = policy.get("data_integrity.fee_rate_plausible_range")
    recon = reconcile(
        net_pnl=bundle.totals["net_pnl"],
        buy_quote=bundle.totals["buy_quote"],
        sell_quote=bundle.totals["sell_quote"],
        fees=bundle.totals["fees"],
        pnl_a=bundle.views["A"].net_pnl,
        pnl_b=bundle.views["B"].net_pnl,
        pnl_c=bundle.views["C"].net_pnl,
        traded_notional=bundle.totals["buy_quote"] + bundle.totals["sell_quote"],
        total_executors=len(records),
        classified_executors=sum(bundle.class_distribution.values()),
        residual_rel=policy.decimal("data_integrity.reconciliation_residual_rel"),
        residual_abs=policy.decimal("data_integrity.reconciliation_residual_abs"),
        abc_tolerance=policy.decimal("data_integrity.abc_identity_tolerance_abs"),
        allow_negative_fees=bool(policy.get("data_integrity.allow_negative_fees")),
        fee_rate_range=(Decimal(str(low)), Decimal(str(high))),
    )
    cohort = CohortInfo(
        venue=cohort_overrides.get("venue", "kraken"),
        quote=cohort_overrides.get("quote", "USD"),
        controller_id=cohort_overrides.get("controller_id", "multi_coin_grid_usd"),
        fingerprint_distribution=fingerprint_distribution([r.fingerprint for r in records]),
    )
    return GateInput(
        metrics=bundle,
        reconciliation=recon,
        cohort=cohort,
        dust_sensitivity_stable=cohort_overrides.get("dust_sensitivity_stable"),
        dust_sensitivity_detail=cohort_overrides.get("dust_sensitivity_detail", ""),
        baseline=cohort_overrides.get("baseline"),
        bootstrap_difference=cohort_overrides.get("bootstrap_difference"),
    )
