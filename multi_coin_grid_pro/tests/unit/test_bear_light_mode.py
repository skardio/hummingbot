"""
Unit tests for V2-06: Auto BEAR-light mode

Tests:
- Threshold-based BEAR-light activation
- bear_size_multiplier applied to position sizing
- Divergence filter (coin 24h > BTC 24h)
- All defaults off (safe by default)
- Interaction with bear_allow_meanrev
"""
import unittest
from decimal import Decimal

# ---------------------------------------------------------------------------
# Minimal stubs to test the business logic in isolation
# ---------------------------------------------------------------------------


class _Config:
    """Minimal config stub."""

    def __init__(self, regime_cfg: dict, filters_cfg: dict = None, quote_asset="USD"):
        self.adaptive_regime_detection = regime_cfg
        self.adaptive_filters = filters_cfg or {}
        self.quote_asset = quote_asset


class _Trends:
    """Stub trend object with a 24h trend value."""

    def __init__(self, trend_1440m: float):
        self.trend_1440m = trend_1440m


class BearLightDecider:
    """
    Pure-logic extraction of the V2-06 BEAR kill-switch / BEAR-light logic.
    Mirrors what the controller does in TIER 2.
    """

    def should_block_entry(
        self,
        last_detected_regime: str,
        last_regime_score: float | None,
        config: _Config,
    ) -> tuple[bool, bool]:
        """
        Returns (block, in_bear_light).
        block=True means no new entry.
        in_bear_light=True means shallow BEAR — continue with reduced size.
        """
        if last_detected_regime != "BEAR":
            return False, False

        adaptive_filters_cfg = config.adaptive_filters or {}
        bear_cfg = adaptive_filters_cfg.get('BEAR', {})
        bear_allow_meanrev = bear_cfg.get('bear_allow_meanrev', False)

        regime_cfg = config.adaptive_regime_detection or {}
        bear_auto_light_enabled = regime_cfg.get('bear_auto_light_enabled', False)
        bear_auto_light_threshold = float(regime_cfg.get('bear_auto_light_threshold', -5.0))
        current_score = last_regime_score

        in_bear_light = (
            bear_auto_light_enabled
            and current_score is not None
            and current_score > bear_auto_light_threshold
        )

        if not bear_allow_meanrev and not in_bear_light:
            return True, False

        return False, in_bear_light

    def apply_size_multiplier(
        self,
        per_coin_capital: Decimal,
        last_detected_regime: str,
        config: _Config,
    ) -> Decimal:
        """Apply BEAR-light size multiplier if applicable."""
        regime_cfg = config.adaptive_regime_detection or {}
        if (
            last_detected_regime == "BEAR"
            and regime_cfg.get('bear_auto_light_enabled', False)
        ):
            mult = float(regime_cfg.get('bear_size_multiplier', 0.5))
            return Decimal(str(float(per_coin_capital) * mult))
        return per_coin_capital

    def passes_divergence_filter(
        self,
        coin: str,
        last_detected_regime: str,
        config: _Config,
        trends: dict,
    ) -> bool:
        """
        Returns True if coin passes divergence check (or filter not applicable).
        Divergence: coin 24h > BTC 24h.
        """
        regime_cfg = config.adaptive_regime_detection or {}
        if last_detected_regime != "BEAR" or not regime_cfg.get('bear_auto_light_enabled', False):
            return True  # filter not active

        btc_pair = f"BTC-{config.quote_asset}"
        btc_trend_obj = trends.get(btc_pair)
        coin_trend_obj = trends.get(coin)
        if btc_trend_obj is None or coin_trend_obj is None:
            return True  # no data → don't block

        btc_24h = float(getattr(btc_trend_obj, 'trend_1440m', 0.0) or 0.0)
        coin_24h = float(getattr(coin_trend_obj, 'trend_1440m', 0.0) or 0.0)
        return coin_24h > btc_24h


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBearLightDecider(unittest.TestCase):

    def _cfg(self, bear_auto_light_enabled=False, bear_auto_light_threshold=-5.0,
             bear_size_multiplier=0.5, bear_allow_meanrev=False):
        return _Config(
            regime_cfg={
                'bear_auto_light_enabled': bear_auto_light_enabled,
                'bear_auto_light_threshold': bear_auto_light_threshold,
                'bear_size_multiplier': bear_size_multiplier,
            },
            filters_cfg={'BEAR': {'bear_allow_meanrev': bear_allow_meanrev}},
        )

    # --- should_block_entry ---

    def test_non_bear_regime_never_blocks(self):
        d = BearLightDecider()
        cfg = self._cfg()
        block, light = d.should_block_entry("CHOP", -1.0, cfg)
        self.assertFalse(block)
        self.assertFalse(light)

    def test_bear_blocks_by_default(self):
        """BEAR with bear_auto_light disabled and bear_allow_meanrev false → block."""
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=False)
        block, light = d.should_block_entry("BEAR", -7.0, cfg)
        self.assertTrue(block)
        self.assertFalse(light)

    def test_bear_no_block_if_allow_meanrev(self):
        """bear_allow_meanrev=true bypasses block regardless of bear_auto_light."""
        d = BearLightDecider()
        cfg = self._cfg(bear_allow_meanrev=True, bear_auto_light_enabled=False)
        block, light = d.should_block_entry("BEAR", -7.0, cfg)
        self.assertFalse(block)
        self.assertFalse(light)

    def test_bear_auto_light_enabled_deep_bear_blocks(self):
        """score <= threshold → deep BEAR → block even with bear_auto_light enabled."""
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True, bear_auto_light_threshold=-5.0)
        block, light = d.should_block_entry("BEAR", -6.0, cfg)
        self.assertTrue(block)
        self.assertFalse(light)

    def test_bear_auto_light_enabled_shallow_bear_allows(self):
        """score > threshold → shallow BEAR → allow BEAR-light."""
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True, bear_auto_light_threshold=-5.0)
        block, light = d.should_block_entry("BEAR", -4.0, cfg)
        self.assertFalse(block)
        self.assertTrue(light)

    def test_bear_auto_light_exactly_at_threshold_blocks(self):
        """score == threshold → still deep BEAR (strictly greater required)."""
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True, bear_auto_light_threshold=-5.0)
        block, light = d.should_block_entry("BEAR", -5.0, cfg)
        self.assertTrue(block)
        self.assertFalse(light)

    def test_bear_auto_light_no_score_blocks(self):
        """If no score available yet, treat as deep BEAR (fail-safe)."""
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True, bear_auto_light_threshold=-5.0)
        block, light = d.should_block_entry("BEAR", None, cfg)
        self.assertTrue(block)
        self.assertFalse(light)

    # --- apply_size_multiplier ---

    def test_size_multiplier_applied_in_bear_light(self):
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True, bear_size_multiplier=0.5)
        result = d.apply_size_multiplier(Decimal("100"), "BEAR", cfg)
        self.assertEqual(result, Decimal("50.0"))

    def test_size_multiplier_not_applied_outside_bear(self):
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True, bear_size_multiplier=0.5)
        result = d.apply_size_multiplier(Decimal("100"), "CHOP", cfg)
        self.assertEqual(result, Decimal("100"))

    def test_size_multiplier_not_applied_when_disabled(self):
        """Even in BEAR, no size reduction when bear_auto_light_enabled=False."""
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=False, bear_size_multiplier=0.5)
        result = d.apply_size_multiplier(Decimal("100"), "BEAR", cfg)
        self.assertEqual(result, Decimal("100"))

    def test_custom_size_multiplier(self):
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True, bear_size_multiplier=0.3)
        result = d.apply_size_multiplier(Decimal("200"), "BEAR", cfg)
        self.assertAlmostEqual(float(result), 60.0, places=6)

    # --- passes_divergence_filter ---

    def test_divergence_filter_inactive_outside_bear(self):
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True)
        self.assertTrue(d.passes_divergence_filter("XRP-USD", "CHOP", cfg, {}))

    def test_divergence_filter_inactive_when_disabled(self):
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=False)
        self.assertTrue(d.passes_divergence_filter("XRP-USD", "BEAR", cfg, {}))

    def test_divergence_passes_when_coin_outperforms_btc(self):
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True)
        trends = {
            'BTC-USD': _Trends(-5.0),
            'XRP-USD': _Trends(-2.0),  # coin falls less than BTC → positive divergence
        }
        self.assertTrue(d.passes_divergence_filter("XRP-USD", "BEAR", cfg, trends))

    def test_divergence_fails_when_coin_underperforms_btc(self):
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True)
        trends = {
            'BTC-USD': _Trends(-2.0),
            'XRP-USD': _Trends(-5.0),  # coin falls more than BTC
        }
        self.assertFalse(d.passes_divergence_filter("XRP-USD", "BEAR", cfg, trends))

    def test_divergence_fails_when_coin_equals_btc(self):
        """Equal performance is not positive divergence (strictly greater required)."""
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True)
        trends = {
            'BTC-USD': _Trends(-3.0),
            'XRP-USD': _Trends(-3.0),
        }
        self.assertFalse(d.passes_divergence_filter("XRP-USD", "BEAR", cfg, trends))

    def test_divergence_passes_when_btc_data_missing(self):
        """If BTC data unavailable, don't block (fail open for divergence)."""
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True)
        trends = {
            'XRP-USD': _Trends(-2.0),
            # BTC-USD missing
        }
        self.assertTrue(d.passes_divergence_filter("XRP-USD", "BEAR", cfg, trends))

    def test_divergence_passes_when_coin_data_missing(self):
        """If coin data unavailable, don't block."""
        d = BearLightDecider()
        cfg = self._cfg(bear_auto_light_enabled=True)
        trends = {
            'BTC-USD': _Trends(-3.0),
            # XRP-USD missing
        }
        self.assertTrue(d.passes_divergence_filter("XRP-USD", "BEAR", cfg, trends))


if __name__ == "__main__":
    unittest.main()
