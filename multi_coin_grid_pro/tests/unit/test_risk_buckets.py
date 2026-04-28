"""
Unit tests for the Risk Bucket module.

Acceptance criteria:
  AC1  Manual overrides
  AC2  Fail-closed default (BLOCKED when no market data)
  AC3  Illiquid detection via market metrics
  AC4  Exposure check includes pending orders
  AC5  Bucket breach blocks order
  AC6  Coin-level state is source of truth
  AC7  Clear diagnostics in rejection reason
  AC8  Config-driven limits
  AC9  Symbol normalisation
"""
import pytest

from multi_coin_grid_pro.core.risk_buckets import (
    BUCKET_MAX_PCT,
    BucketExposureTracker,
    CoinBucket,
    MarketMetrics,
    RiskBucketClassifier,
    RiskBucketConfig,
    RiskBucketExposureTracker,
    _normalize_base,
    get_bucket,
    get_max_pct,
)

# ── AC9: Symbol normalisation ─────────────────────────────────────────────────


class TestNormalizeBase:
    def test_dash_separated(self):
        assert _normalize_base("BTC-USDT") == "BTC"

    def test_slash_separated(self):
        assert _normalize_base("BTC/USDT") == "BTC"

    def test_bare_base(self):
        assert _normalize_base("ETH") == "ETH"

    def test_xbt_alias(self):
        assert _normalize_base("XBT-USD") == "BTC"

    def test_lowercase_normalised(self):
        assert _normalize_base("sol-usd") == "SOL"

    def test_eur_suffix_stripped(self):
        assert _normalize_base("PEPE-EUR") == "PEPE"


# ── AC1: Manual overrides ─────────────────────────────────────────────────────

class TestManualOverrides:
    def setup_method(self):
        self.clf = RiskBucketClassifier()

    def test_btc_is_l1(self):
        assert self.clf.classify("BTC-EUR").bucket == CoinBucket.L1

    def test_eth_is_l1(self):
        assert self.clf.classify("ETH").bucket == CoinBucket.L1

    def test_xbt_resolves_to_l1(self):
        # Kraken uses XBT instead of BTC
        assert self.clf.classify("XBT-USD").bucket == CoinBucket.L1

    def test_sol_is_l2(self):
        assert self.clf.classify("SOL-USD").bucket == CoinBucket.L2

    def test_doge_is_meme(self):
        assert self.clf.classify("DOGE").bucket == CoinBucket.MEME

    def test_pepe_is_meme(self):
        assert self.clf.classify("PEPE-EUR").bucket == CoinBucket.MEME

    def test_pengu_is_meme(self):
        assert self.clf.classify("PENGU-USD").bucket == CoinBucket.MEME

    def test_reason_mentions_manual_override(self):
        profile = self.clf.classify("BTC-USD")
        assert "manual override" in profile.reason

    def test_runtime_override_respected(self):
        clf = RiskBucketClassifier(overrides={"NEWCOIN": CoinBucket.L2})
        assert clf.classify("NEWCOIN-USD").bucket == CoinBucket.L2

    def test_case_insensitive_override(self):
        clf = RiskBucketClassifier(overrides={"newcoin": CoinBucket.MEME})
        assert clf.classify("NEWCOIN").bucket == CoinBucket.MEME


# ── AC2: Fail-closed default ──────────────────────────────────────────────────

class TestFailClosedDefault:
    def setup_method(self):
        self.clf = RiskBucketClassifier()

    def test_unknown_coin_without_metrics_is_blocked(self):
        profile = self.clf.classify("FOOBAR-EUR")
        assert profile.bucket == CoinBucket.BLOCKED

    def test_blocked_profile_is_blocked(self):
        profile = self.clf.classify("UNKNOWNCOIN")
        assert profile.is_blocked is True

    def test_reason_mentions_no_market_data(self):
        profile = self.clf.classify("MYSTERY-USD")
        assert "no market data" in profile.reason.lower()

    def test_blocked_bucket_max_is_zero(self):
        assert RiskBucketConfig().limits[CoinBucket.BLOCKED] == 0.0


# ── AC3: Illiquid detection ───────────────────────────────────────────────────

class TestIlliquidDetection:
    def setup_method(self):
        self.clf = RiskBucketClassifier()

    def test_low_volume_is_illiquid(self):
        metrics = MarketMetrics(volume_24h_usd=1_000_000, spread_pct=0.1)
        profile = self.clf.classify("NEWTOKEN-USD", metrics)
        assert profile.bucket == CoinBucket.ILLIQUID

    def test_high_spread_is_illiquid(self):
        metrics = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=3.0)
        profile = self.clf.classify("NEWTOKEN-USD", metrics)
        assert profile.bucket == CoinBucket.ILLIQUID

    def test_sufficient_quality_is_illiquid_conservative(self):
        # Good volume + tight spread but unknown coin → ILLIQUID (conservative)
        metrics = MarketMetrics(volume_24h_usd=100_000_000, spread_pct=0.05)
        profile = self.clf.classify("NEWTOKEN-USD", metrics)
        assert profile.bucket == CoinBucket.ILLIQUID

    def test_reason_mentions_volume(self):
        metrics = MarketMetrics(volume_24h_usd=500_000, spread_pct=0.1)
        profile = self.clf.classify("NEWTOKEN-USD", metrics)
        assert "volume" in profile.reason.lower()

    def test_reason_mentions_spread(self):
        metrics = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=5.0)
        profile = self.clf.classify("NEWTOKEN-USD", metrics)
        assert "spread" in profile.reason.lower()

    def test_manual_override_beats_metrics(self):
        # PEPE has a manual override → metrics are ignored
        bad_metrics = MarketMetrics(volume_24h_usd=0, spread_pct=99.0)
        profile = self.clf.classify("PEPE-USD", bad_metrics)
        assert profile.bucket == CoinBucket.MEME

    def test_custom_thresholds_respected(self):
        cfg = RiskBucketConfig(illiquid_min_volume_usd=1_000_000)
        clf = RiskBucketClassifier(config=cfg)
        # 2M > threshold of 1M → not blocked by volume
        metrics = MarketMetrics(volume_24h_usd=2_000_000, spread_pct=0.1)
        profile = clf.classify("NEWTOKEN-USD", metrics)
        assert profile.bucket == CoinBucket.ILLIQUID
        assert "volume" not in profile.reason.lower()


# ── Config validation ─────────────────────────────────────────────────────────

class TestRiskBucketConfig:
    def test_valid_config_accepted(self):
        cfg = RiskBucketConfig()
        assert cfg.limits[CoinBucket.L1] == 40.0

    def test_missing_bucket_raises(self):
        with pytest.raises(ValueError, match="missing bucket"):
            RiskBucketConfig(limits={
                CoinBucket.L1: 40.0,
                CoinBucket.L2: 25.0,
                CoinBucket.MEME: 15.0,
                # ILLIQUID and BLOCKED intentionally missing
            })

    def test_limit_over_100_raises(self):
        limits = {b: 20.0 for b in CoinBucket}
        limits[CoinBucket.L1] = 110.0
        with pytest.raises(ValueError, match="must be in"):
            RiskBucketConfig(limits=limits)

    def test_negative_limit_raises(self):
        limits = {b: 10.0 for b in CoinBucket}
        limits[CoinBucket.MEME] = -5.0
        with pytest.raises(ValueError, match="must be in"):
            RiskBucketConfig(limits=limits)

    def test_negative_volume_threshold_raises(self):
        with pytest.raises(ValueError, match="illiquid_min_volume_usd"):
            RiskBucketConfig(illiquid_min_volume_usd=-1.0)

    def test_negative_spread_threshold_raises(self):
        with pytest.raises(ValueError, match="illiquid_max_spread_pct"):
            RiskBucketConfig(illiquid_max_spread_pct=-0.1)


# ── MarketMetrics validation ──────────────────────────────────────────────────

class TestMarketMetrics:
    def test_valid_metrics_accepted(self):
        m = MarketMetrics(volume_24h_usd=1_000_000, spread_pct=0.5)
        assert m.volume_24h_usd == 1_000_000

    def test_negative_volume_raises(self):
        with pytest.raises(ValueError, match="volume_24h_usd"):
            MarketMetrics(volume_24h_usd=-1.0, spread_pct=0.1)

    def test_negative_spread_raises(self):
        with pytest.raises(ValueError, match="spread_pct"):
            MarketMetrics(volume_24h_usd=1_000_000, spread_pct=-0.1)

    def test_zero_volume_allowed(self):
        m = MarketMetrics(volume_24h_usd=0.0, spread_pct=0.5)
        assert m.volume_24h_usd == 0.0

    def test_zero_spread_allowed(self):
        m = MarketMetrics(volume_24h_usd=1_000_000, spread_pct=0.0)
        assert m.spread_pct == 0.0


# ── Exposure tracker ──────────────────────────────────────────────────────────

class TestRiskBucketExposureTracker:

    def test_initial_bucket_pct_is_zero(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        assert tracker.get_bucket_pct(CoinBucket.MEME) == pytest.approx(0.0)

    # AC6: coin-level state as source of truth
    def test_bucket_total_derived_from_coin_state(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("PEPE-EUR", 50.0)
        tracker.set_filled("DOGE-EUR", 30.0)
        assert tracker.get_bucket_total(CoinBucket.MEME) == pytest.approx(80.0)

    def test_clear_coin_removes_from_bucket_total(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("PEPE-EUR", 100.0)
        tracker.clear_coin("PEPE-EUR")
        assert tracker.get_bucket_total(CoinBucket.MEME) == pytest.approx(0.0)

    # AC4: pending orders count toward bucket cap
    def test_pending_orders_counted_in_bucket_total(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("PEPE-EUR", 50.0)
        tracker.set_pending("DOGE-EUR", 40.0)
        assert tracker.get_bucket_total(CoinBucket.MEME) == pytest.approx(90.0)

    def test_set_filled_replaces_not_adds(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("PEPE-EUR", 100.0)
        tracker.set_filled("PEPE-EUR", 50.0)  # replace
        assert tracker.get_coin_total("PEPE-EUR") == pytest.approx(50.0)

    def test_update_portfolio_affects_pct(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("BTC-EUR", 200.0)
        tracker.update_portfolio(2000.0)
        assert tracker.get_bucket_pct(CoinBucket.L1) == pytest.approx(10.0)

    # AC5: bucket breach blocks order
    def test_can_add_within_limits(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        allowed, reason = tracker.can_add("DOGE-EUR", 50.0)  # 5% < 15% cap
        assert allowed is True

    def test_can_add_rejected_over_meme_cap(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("PEPE-EUR", 120.0)  # 12% already in MEME
        allowed, reason = tracker.can_add("DOGE-EUR", 50.0)  # would push to 17%
        assert allowed is False
        assert "MEME" in reason

    def test_can_add_at_exact_cap_is_rejected(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("BTC-EUR", 400.0)  # exactly 40% = L1 cap
        allowed, _ = tracker.can_add("ETH-EUR", 1.0)
        assert allowed is False

    # AC4 + AC5: pending orders block further entry
    def test_pending_blocks_new_entry(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_pending("PEPE-EUR", 130.0)  # 13% pending in MEME
        allowed, reason = tracker.can_add("DOGE-EUR", 30.0)  # would be 16% > 15%
        assert allowed is False
        assert "MEME" in reason

    # AC7: diagnostics
    def test_rejection_reason_contains_diagnostics(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("PEPE-EUR", 120.0)
        _, reason = tracker.can_add("DOGE-EUR", 50.0)
        assert "current=" in reason
        assert "requested=" in reason
        assert "projected=" in reason
        assert "max=" in reason

    def test_blocked_coin_is_rejected(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        allowed, reason = tracker.can_add("UNKNOWNCOIN-USD", 10.0)
        assert allowed is False
        assert "BLOCKED" in reason

    # AC8: config-driven limits
    def test_custom_config_limits_respected(self):
        cfg = RiskBucketConfig(limits={
            CoinBucket.L1: 40.0,
            CoinBucket.L2: 25.0,
            CoinBucket.MEME: 5.0,   # tighter than default
            CoinBucket.ILLIQUID: 3.0,
            CoinBucket.BLOCKED: 0.0,
        })
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0, config=cfg)
        tracker.set_filled("PEPE-EUR", 30.0)  # 3% — under 5%
        allowed, _ = tracker.can_add("DOGE-EUR", 30.0)  # would be 6% > 5%
        assert allowed is False

    def test_xbt_usd_resolves_correctly(self):
        # Kraken XBT-USD should resolve as BTC (L1)
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        allowed, _ = tracker.can_add("XBT-USD", 100.0)  # 10% < 40% L1 cap
        assert allowed is True

    def test_clear_coin_removes_pending_too(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("DOGE-EUR", 50.0)
        tracker.set_pending("DOGE-EUR", 30.0)
        tracker.clear_coin("DOGE-EUR")
        assert tracker.get_coin_total("DOGE-EUR") == pytest.approx(0.0)

    def test_clear_coin_removes_stored_profile(self):
        # After clear, profile should be gone so the coin re-classifies fresh
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        metrics = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=0.1)
        tracker.set_pending("NEWTOKEN-USD", 10.0, metrics)
        tracker.clear_coin("NEWTOKEN-USD")
        assert "NEWTOKEN" not in tracker._profiles

    # Reviewer: additional_notional must be > 0
    def test_zero_notional_rejected(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        allowed, reason = tracker.can_add("BTC-USD", 0.0)
        assert allowed is False
        assert "invalid" in reason.lower()

    def test_negative_notional_rejected(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        allowed, reason = tracker.can_add("BTC-USD", -10.0)
        assert allowed is False
        assert "invalid" in reason.lower()

    # Reviewer: profile stored at can_add must be reused in get_bucket_total
    def test_bucket_consistency_across_lifecycle(self):
        """
        A coin classified as ILLIQUID via set_pending(metrics=...)
        must remain ILLIQUID in get_bucket_total(), not re-classify to BLOCKED.
        """
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        metrics = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=0.1)
        tracker.set_pending("NEWTOKEN-USD", 30.0, metrics)

        # Bucket total must use stored ILLIQUID profile, not reclassify to BLOCKED
        total = tracker.get_bucket_total(CoinBucket.ILLIQUID)
        assert total == pytest.approx(30.0)

    def test_set_filled_with_metrics_stores_profile(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        metrics = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=0.1)
        tracker.set_filled("NEWTOKEN-USD", 20.0, metrics)
        assert "NEWTOKEN" in tracker._profiles
        assert tracker._profiles["NEWTOKEN"].bucket == CoinBucket.ILLIQUID

    # Reviewer: can_add() must be read-only (no side effects)
    def test_can_add_does_not_store_profile_on_new_coin(self):
        """can_add() on a new coin (no exposure) must NOT store the profile."""
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        metrics = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=0.1)
        tracker.can_add("NEWTOKEN-USD", 10.0, metrics)
        assert "NEWTOKEN" not in tracker._profiles

    def test_rejected_can_add_leaves_state_unchanged(self):
        """A rejected can_add() must leave all state exactly as before."""
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("PEPE-EUR", 140.0)  # 14% in MEME, cap is 15%

        profiles_before = dict(tracker._profiles)
        filled_before = dict(tracker._filled)
        pending_before = dict(tracker._pending)

        allowed, _ = tracker.can_add("DOGE-EUR", 20.0)  # would push to 16% — rejected

        assert allowed is False
        assert tracker._profiles == profiles_before
        assert tracker._filled == filled_before
        assert tracker._pending == pending_before

    def test_repeated_can_add_with_different_metrics_uses_locked_profile(self):
        """
        Once a coin has exposure, can_add() must reuse the stored profile,
        ignoring new metrics that would classify it differently.
        """
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)

        # First: classify as ILLIQUID via low volume
        low_vol = MarketMetrics(volume_24h_usd=1_000_000, spread_pct=0.1)
        tracker.set_pending("NEWTOKEN-USD", 10.0, low_vol)
        assert tracker._profiles["NEWTOKEN"].bucket == CoinBucket.ILLIQUID

        # Now try to add more — even with "good" metrics, profile stays locked
        high_vol = MarketMetrics(volume_24h_usd=100_000_000, spread_pct=0.05)
        allowed, reason = tracker.can_add("NEWTOKEN-USD", 5.0, high_vol)
        # Still uses ILLIQUID bucket (not reclassified)
        assert "ILLIQUID" in reason

    def test_clear_and_reclassify_lifecycle(self):
        """After clear_coin(), the next add may classify the coin differently."""
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)

        low_vol = MarketMetrics(volume_24h_usd=1_000_000, spread_pct=0.1)
        tracker.set_pending("NEWTOKEN-USD", 10.0, low_vol)
        assert tracker._profiles["NEWTOKEN"].bucket == CoinBucket.ILLIQUID

        tracker.clear_coin("NEWTOKEN-USD")
        assert "NEWTOKEN" not in tracker._profiles

        # Re-add: this time classify fresh (profile was cleared)
        tracker.set_pending("NEWTOKEN-USD", 10.0, low_vol)
        assert tracker._profiles["NEWTOKEN"].bucket == CoinBucket.ILLIQUID

    # Hard validation: invalid portfolio
    def test_invalid_portfolio_zero_raises(self):
        with pytest.raises(ValueError, match="portfolio_value"):
            RiskBucketExposureTracker(portfolio_value=0.0)

    def test_invalid_portfolio_negative_raises(self):
        with pytest.raises(ValueError, match="portfolio_value"):
            RiskBucketExposureTracker(portfolio_value=-100.0)

    def test_update_portfolio_zero_raises(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        with pytest.raises(ValueError, match="portfolio_value"):
            tracker.update_portfolio(0.0)

    def test_update_portfolio_negative_raises(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        with pytest.raises(ValueError, match="portfolio_value"):
            tracker.update_portfolio(-500.0)

    # Hard validation: negative notional
    def test_set_filled_negative_notional_raises(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        with pytest.raises(ValueError, match="notional"):
            tracker.set_filled("BTC-USD", -10.0)

    def test_set_pending_negative_notional_raises(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        with pytest.raises(ValueError, match="notional"):
            tracker.set_pending("BTC-USD", -10.0)

    def test_set_filled_zero_notional_allowed(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("BTC-USD", 0.0)
        assert tracker.get_coin_total("BTC-USD") == pytest.approx(0.0)

    # Hard validation: metrics required for new non-manual assets
    def test_set_filled_new_nonmanual_without_metrics_raises(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        with pytest.raises(ValueError, match="metrics required"):
            tracker.set_filled("NEWTOKEN-USD", 10.0)

    def test_set_pending_new_nonmanual_without_metrics_raises(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        with pytest.raises(ValueError, match="metrics required"):
            tracker.set_pending("NEWTOKEN-USD", 10.0)

    def test_set_filled_manual_coin_without_metrics_works(self):
        # Manual override coins never need metrics
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("PENGU-USD", 20.0)
        assert tracker.get_coin_total("PENGU-USD") == pytest.approx(20.0)

    def test_set_pending_manual_coin_without_metrics_works(self):
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_pending("DOGE-EUR", 15.0)
        assert tracker.get_coin_total("DOGE-EUR") == pytest.approx(15.0)

    def test_second_set_filled_without_metrics_works_if_profile_stored(self):
        """Once a profile is stored (first set_pending/set_filled), metrics not needed."""
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        metrics = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=0.1)
        tracker.set_pending("NEWTOKEN-USD", 10.0, metrics)  # stores profile
        tracker.set_filled("NEWTOKEN-USD", 10.0)            # reuses profile, no metrics
        assert tracker.get_coin_total("NEWTOKEN-USD") == pytest.approx(20.0)

    # Restart / restore scenarios
    def test_restore_manual_coins_without_metrics(self):
        """Restart: restoring positions for manual-override coins works without metrics."""
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("BTC-USD", 200.0)
        tracker.set_filled("DOGE-USD", 50.0)
        assert tracker.get_bucket_total(CoinBucket.L1) == pytest.approx(200.0)
        assert tracker.get_bucket_total(CoinBucket.MEME) == pytest.approx(50.0)

    def test_restore_nonmanual_coin_requires_metrics(self):
        """Restart: restoring a non-manual position without metrics must raise."""
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        with pytest.raises(ValueError, match="metrics required"):
            tracker.set_filled("NEWTOKEN-USD", 20.0)

    def test_restore_nonmanual_coin_with_metrics_works(self):
        """Restart: restoring a non-manual position with metrics works correctly."""
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        metrics = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=0.1)
        tracker.set_filled("NEWTOKEN-USD", 20.0, metrics)
        assert tracker.get_bucket_total(CoinBucket.ILLIQUID) == pytest.approx(20.0)

    # Bucket breach with combined filled + pending
    def test_bucket_breach_combined_filled_and_pending(self):
        """Filled + pending from different coins in same bucket must sum toward cap."""
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        tracker.set_filled("PEPE-EUR", 80.0)   # 8% in MEME
        tracker.set_pending("DOGE-EUR", 50.0)  # 5% in MEME -- total 13%
        allowed, reason = tracker.can_add("BONK-USD", 30.0)  # +3% = 16% > 15% cap
        assert allowed is False
        assert "MEME" in reason

    # Lifecycle: full fill
    def test_full_fill_clears_pending_sets_filled(self):
        """
        Order lifecycle: pending=100 -> order fills fully -> pending=0, filled=100.
        Bucket total stays at 100 throughout (no double counting at any point).
        """
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        # Order placed: record as pending
        tracker.set_pending("PEPE-USD", 100.0)
        assert tracker.get_coin_total("PEPE-USD") == pytest.approx(100.0)
        assert tracker.get_bucket_total(CoinBucket.MEME) == pytest.approx(100.0)

        # Order fills fully: pending -> 0, filled -> 100
        tracker.set_pending("PEPE-USD", 0.0)
        tracker.set_filled("PEPE-USD", 100.0)

        assert tracker._pending.get("PEPE", 0.0) == pytest.approx(0.0)
        assert tracker._filled.get("PEPE", 0.0) == pytest.approx(100.0)
        assert tracker.get_coin_total("PEPE-USD") == pytest.approx(100.0)
        assert tracker.get_bucket_total(CoinBucket.MEME) == pytest.approx(100.0)

    # Lifecycle: partial fill
    def test_partial_fill_reduces_pending_raises_filled(self):
        """
        Partial fill: pending drops by filled amount, filled rises.
        Total must stay constant (no double counting, no loss).
        """
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        # Order placed at 100
        tracker.set_pending("PEPE-USD", 100.0)

        # Partial fill of 60: pending -> 40, filled -> 60
        tracker.set_pending("PEPE-USD", 40.0)
        tracker.set_filled("PEPE-USD", 60.0)

        assert tracker._pending.get("PEPE", 0.0) == pytest.approx(40.0)
        assert tracker._filled.get("PEPE", 0.0) == pytest.approx(60.0)
        assert tracker.get_coin_total("PEPE-USD") == pytest.approx(100.0)
        assert tracker.get_bucket_total(CoinBucket.MEME) == pytest.approx(100.0)

        # Second partial fill: pending -> 0, filled -> 100
        tracker.set_pending("PEPE-USD", 0.0)
        tracker.set_filled("PEPE-USD", 100.0)

        assert tracker.get_coin_total("PEPE-USD") == pytest.approx(100.0)

    # Lifecycle: restore non-manual coin with metrics
    def test_restore_nonmanual_coin_lifecycle(self):
        """
        Restart scenario: bot comes back up, restores a non-manual coin position
        using metrics (the required path for unknown coins).
        After restore the coin must trade in the correct bucket and obey the cap.
        """
        tracker = RiskBucketExposureTracker(portfolio_value=1000.0)
        metrics = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=0.1)

        # Restore from DB: filled position that existed before restart
        tracker.set_filled("NEWTOKEN-USD", 20.0, metrics)

        # Profile must be stored (ILLIQUID, not BLOCKED)
        assert "NEWTOKEN" in tracker._profiles
        assert tracker._profiles["NEWTOKEN"].bucket == CoinBucket.ILLIQUID

        # Bucket total reflects restored position
        assert tracker.get_bucket_total(CoinBucket.ILLIQUID) == pytest.approx(20.0)

        # can_add still works and reuses stored profile (no metrics needed)
        # ILLIQUID cap = 3% of 1000 = 30. Currently 20 filled (2%).
        # Adding 11 -> projected 31/1000 = 3.1% > 3% cap -> rejected
        allowed, reason = tracker.can_add("NEWTOKEN-USD", 11.0)
        assert "ILLIQUID" in reason
        assert allowed is False

        # Adding 10 -> projected 30/1000 = 3.0%, not strictly > 3% -> allowed
        allowed, _ = tracker.can_add("NEWTOKEN-USD", 10.0)
        assert allowed is True


# ── Backward-compatible shims ─────────────────────────────────────────────────

class TestBackwardCompatShims:
    def test_get_bucket_btc_is_l1(self):
        assert get_bucket("BTC-EUR") == CoinBucket.L1

    def test_get_bucket_doge_is_meme(self):
        assert get_bucket("DOGE") == CoinBucket.MEME

    def test_get_bucket_unknown_is_blocked(self):
        assert get_bucket("FOOBAR-EUR") == CoinBucket.BLOCKED

    def test_get_max_pct_l1(self):
        assert get_max_pct("BTC") == 40.0

    def test_get_max_pct_meme(self):
        assert get_max_pct("DOGE") == 15.0

    def test_get_max_pct_unknown_is_zero(self):
        # Unknown coin -> BLOCKED -> 0% limit, not 10%
        assert get_max_pct("FOOBAR") == 0.0

    def test_bucket_max_pct_has_all_buckets(self):
        for bucket in CoinBucket:
            assert bucket in BUCKET_MAX_PCT

    def test_bucket_exposure_tracker_alias(self):
        # BucketExposureTracker must still work (used by controller)
        tracker = BucketExposureTracker(portfolio_value=500.0)
        allowed, _ = tracker.can_add("PENGU-USD", 50.0)  # 10% < 15% MEME cap
        assert allowed is True
