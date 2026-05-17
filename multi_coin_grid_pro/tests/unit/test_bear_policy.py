from multi_coin_grid_pro.logic.bear_policy import bear_light_divergence_passes, decide_bear_policy


def test_conditional_bear_policy_blocks_deep_bear():
    decision = decide_bear_policy(
        regime="BEAR",
        score=-5.0,
        regime_cfg={
            "bear_meanrev_policy": "conditional",
            "bear_auto_light_enabled": True,
            "bear_auto_light_threshold": -5.0,
        },
        adaptive_filters_cfg={"BEAR": {"bear_allow_meanrev": False}},
    )

    assert decision.block_new_entries
    assert not decision.in_bear_light


def test_conditional_bear_policy_allows_shallow_bear_light():
    decision = decide_bear_policy(
        regime="BEAR",
        score=-4.9,
        regime_cfg={
            "bear_meanrev_policy": "conditional",
            "bear_auto_light_enabled": True,
            "bear_auto_light_threshold": -5.0,
            "bear_size_multiplier": 0.5,
        },
        adaptive_filters_cfg={"BEAR": {"bear_allow_meanrev": False}},
    )

    assert not decision.block_new_entries
    assert decision.in_bear_light
    assert decision.size_multiplier == 0.5


def test_explicit_conditional_policy_ignores_legacy_allow_flag():
    decision = decide_bear_policy(
        regime="BEAR",
        score=-7.0,
        regime_cfg={
            "bear_meanrev_policy": "conditional",
            "bear_auto_light_enabled": True,
            "bear_auto_light_threshold": -5.0,
        },
        adaptive_filters_cfg={"BEAR": {"bear_allow_meanrev": True}},
    )

    assert decision.block_new_entries
    assert decision.policy == "conditional"


def test_legacy_allow_still_supported_without_explicit_policy():
    decision = decide_bear_policy(
        regime="BEAR",
        score=-7.0,
        regime_cfg={"bear_auto_light_enabled": False},
        adaptive_filters_cfg={"BEAR": {"bear_allow_meanrev": True}},
    )

    assert not decision.block_new_entries
    assert decision.policy == "allow"


def test_bear_light_divergence_requires_coin_to_beat_btc():
    assert bear_light_divergence_passes(True, coin_trend_24h=-2.0, btc_trend_24h=-4.0)
    assert not bear_light_divergence_passes(True, coin_trend_24h=-5.0, btc_trend_24h=-4.0)


def test_divergence_filter_is_noop_outside_bear_light():
    assert bear_light_divergence_passes(False, coin_trend_24h=-5.0, btc_trend_24h=-4.0)
