from multi_coin_grid_pro.logic.exit_safety import fee_aware_timeout_bypass_allowed


def test_fee_aware_timeout_bypass_allows_stale_no_progress_block():
    assert fee_aware_timeout_bypass_allowed(
        close_reason="NO_PROGRESS_TIMEOUT",
        blocked_for_sec=5400,
        bypass_after_sec=5400,
    )


def test_fee_aware_timeout_bypass_waits_until_threshold():
    assert not fee_aware_timeout_bypass_allowed(
        close_reason="NO_PROGRESS_TIMEOUT",
        blocked_for_sec=5399,
        bypass_after_sec=5400,
    )


def test_fee_aware_timeout_bypass_only_applies_to_no_progress():
    assert not fee_aware_timeout_bypass_allowed(
        close_reason="TIME_LIMIT",
        blocked_for_sec=7200,
        bypass_after_sec=5400,
    )


def test_fee_aware_timeout_bypass_disabled_when_threshold_zero():
    assert not fee_aware_timeout_bypass_allowed(
        close_reason="NO_PROGRESS_TIMEOUT",
        blocked_for_sec=7200,
        bypass_after_sec=0,
    )
