"""Fingerprint tests: denylist behaviour, canonicalisation and health."""
from __future__ import annotations

from tools.evidence.fingerprint import (
    canonical_value,
    diff_fingerprints,
    fingerprint_config,
    fingerprint_distribution,
    flatten,
    is_denied,
)

from .conftest import base_config


def test_identical_configs_share_a_fingerprint(policy):
    assert fingerprint_config(base_config(), policy).full == fingerprint_config(base_config(), policy).full


def test_unknown_new_parameter_changes_the_fingerprint(policy):
    """The core guarantee of the denylist approach.

    A parameter nobody anticipated must still split the cohort rather than be
    silently merged into it.
    """
    before = fingerprint_config(base_config(), policy)
    config = base_config()
    config["brand_new_strategy_parameter"] = 42
    after = fingerprint_config(config, policy)
    assert before.full != after.full
    assert after.field_count == before.field_count + 1


def test_unknown_nested_parameter_changes_the_fingerprint(policy):
    before = fingerprint_config(base_config(), policy)
    config = base_config()
    config["custom_info"]["brand_new_nested_param"] = "on"
    assert fingerprint_config(config, policy).full != before.full


def test_volatile_denylisted_field_does_not_change_the_fingerprint(policy):
    """Market-derived and per-trade fields must not fragment the cohort."""
    before = fingerprint_config(base_config(), policy)
    config = base_config(
        **{
            "id": "completely-different-id",
            "timestamp": 1234567890.123,
            "start_price": "9.99999",
            "end_price": "8.88888",
            "limit_price": "7.77777",
            "total_amount_quote": "999.123456",
            "trading_pair": "BTC-USD",
            "custom_info.atr_pct": "0.98765",
            "custom_info.entry_trend_pct": "99.9",
            "custom_info.entry_grid_score": "0.01",
            "custom_info.bot_instance_id": "other-bot",
        }
    )
    assert fingerprint_config(config, policy).full == before.full


def test_float_artefact_yields_identical_fingerprint(policy):
    """0.075 and 0.07500000000000001 are the same parameter."""
    clean = base_config(**{"triple_barrier_config.take_profit": "0.075"})
    noisy = base_config(**{"triple_barrier_config.take_profit": "0.07500000000000001"})
    assert fingerprint_config(clean, policy).full == fingerprint_config(noisy, policy).full


def test_float_artefact_in_native_float_form(policy):
    clean = base_config(**{"activation_bounds": 0.075})
    noisy = base_config(**{"activation_bounds": 0.07500000000000001})
    assert fingerprint_config(clean, policy).full == fingerprint_config(noisy, policy).full


def test_genuinely_different_values_still_differ(policy):
    a = base_config(**{"custom_info.max_hold_time_sec": 5400})
    b = base_config(**{"custom_info.max_hold_time_sec": 7200})
    assert fingerprint_config(a, policy).full != fingerprint_config(b, policy).full


def test_runtime_output_fields_are_denylisted(policy):
    """Policy 1.2.0: fields proven to be computed per executor must not split a cohort."""
    runtime_outputs = {
        "triple_barrier_config.stop_loss": "0.0342587902338",
        "triple_barrier_config.take_profit": "0.0625",
        "activation_bounds": "0.0625",
        "max_open_orders": 11,
        "min_spread_between_orders": "0.001",
        "custom_info.no_fill_timeout_sec": 1680,
        "custom_info.no_progress_max_extension_sec": 10800,
    }
    baseline = fingerprint_config(base_config(), policy)
    for key, value in runtime_outputs.items():
        changed = fingerprint_config(base_config(**{key: value}), policy)
        assert changed.full == baseline.full, f"{key} still splits the cohort"


def test_settings_driving_runtime_outputs_remain_in_fingerprint(policy):
    """The knobs stay; only their computed results are removed."""
    baseline = fingerprint_config(base_config(), policy)
    for key, value in {
        "custom_info.dynamic_tp_min_pct": "0.03",
        "custom_info.dynamic_tp_max_pct": "0.06",
        "triple_barrier_config.trailing_stop": {"activation_price": "0.02", "trailing_delta": "0.01"},
        "order_frequency": 5,
        "min_order_amount_quote": "20",
    }.items():
        assert fingerprint_config(base_config(**{key: value}), policy).full != baseline.full, key


def test_trailing_stop_parameters_are_included(policy):
    """These were missed entirely by the rejected whitelist approach."""
    before = fingerprint_config(base_config(), policy)
    changed = base_config(**{"triple_barrier_config.trailing_stop": {"activation_price": "0.02", "trailing_delta": "0.01"}})
    assert fingerprint_config(changed, policy).full != before.full


def test_string_and_numeric_representations_match(policy):
    assert fingerprint_config(base_config(**{"order_frequency": 3}), policy).full == \
        fingerprint_config(base_config(**{"order_frequency": "3"}), policy).full


def test_canonical_value_cases():
    assert canonical_value(None, 12) == "null"
    assert canonical_value(True, 12) == "true"
    assert canonical_value(False, 12) == "false"
    assert canonical_value(0, 12) == "0"
    assert canonical_value("0.000", 12) == "0"
    assert canonical_value("abc", 12) == "abc"
    assert canonical_value("1E+2", 12) == canonical_value("100", 12)


def test_is_denied_prefix_and_exact():
    patterns = ["id", "custom_info.entry_*"]
    assert is_denied("id", patterns)
    assert is_denied("custom_info.entry_trend_pct", patterns)
    assert not is_denied("identifier", patterns)
    assert not is_denied("custom_info.atr_pct", patterns)


def test_flatten_collapses_lists():
    flat = flatten({"a": {"b": 1}, "c": [1, 2, 3]})
    assert flat == {"a.b": 1, "c": "<list:3>"}


def test_distribution_health_and_dominance(policy):
    uniform = fingerprint_distribution(["x"] * 10)
    assert uniform.dominant_share == 1.0
    assert uniform.health == 0.1

    fragmented = fingerprint_distribution([f"f{i}" for i in range(10)])
    assert fragmented.health == 1.0
    assert fragmented.distinct == 10

    mixed = fingerprint_distribution(["a"] * 9 + ["b"])
    assert mixed.dominant == "a"
    assert mixed.dominant_share == 0.9


def test_empty_distribution_is_safe():
    empty = fingerprint_distribution([])
    assert empty.total == 0
    assert empty.dominant_share == 0.0
    assert empty.health == 0.0


def test_diff_reports_changed_fields(policy):
    a = fingerprint_config(base_config(**{"order_frequency": 3}), policy)
    b = fingerprint_config(base_config(**{"order_frequency": 5}), policy)
    differences = diff_fingerprints(a, b)
    assert [key for key, _, _ in differences] == ["order_frequency"]


def test_field_volatility_identifies_fragmenting_fields(policy):
    """A semi-volatile field must be named, because aggregate health misses it.

    Mirrors the real Bitget finding: triple_barrier_config.stop_loss carries
    ATR-derived values that shatter cohorts without tripping the stale-denylist
    ratio.
    """
    from tools.evidence.fingerprint import field_volatility

    configs = [
        base_config(**{"custom_info.max_hold_time_sec": 5400 + i}) for i in range(20)
    ]
    ranked = field_volatility(configs, policy)
    assert ranked
    assert ranked[0].key == "custom_info.max_hold_time_sec"
    assert ranked[0].distinct == 20
    assert ranked[0].total == 20
    assert ranked[0].volatility == 1.0


def test_field_volatility_ignores_constant_fields(policy):
    from tools.evidence.fingerprint import field_volatility

    ranked = field_volatility([base_config() for _ in range(10)], policy)
    assert ranked == []
