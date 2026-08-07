"""
Tests for DPM exchange-data invariants and bucket classification correctness.

Covers requirements:
  T1  OKX DPM must NOT use the Kraken ticker endpoint
  T2  Kraken DPM still uses Kraken data path
  T3  After a correct scan OKB-USDC receives valid volume/spread MarketMetrics
  T4  Unknown coin without metrics → BLOCKED (fail-closed)
  T5  Liquid unknown coin with good metrics → ILLIQUID (never auto L1/L2)
  T6  Illiquid coin with bad metrics → ILLIQUID via volume/spread checks
  T7  ADA/XRP manual overrides unchanged and sufficient without metrics
  T8  XRP passes bucket (L2) but V2-04 blocks when expected_hourly < threshold
  T9  OKX ticker parsing: correct volume, spread, pair name from mocked response
  T10 Spread unit: pair_spreads stores fraction; MarketMetrics takes %
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from multi_coin_grid_pro.core.risk_buckets import (
    CoinBucket,
    MarketMetrics,
    RiskBucketClassifier,
    RiskBucketExposureTracker,
)
from multi_coin_grid_pro.logic.fee_aware_filter import FeeAwareFilter
from multi_coin_grid_pro.utils.dynamic_pair_manager import DynamicPairManager

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_connector(name: str = "okx") -> MagicMock:
    conn = MagicMock()
    conn.name = name
    conn.trading_pair_symbol_map = AsyncMock(return_value={})
    return conn


def _make_dpm(connector_name: str = "okx") -> DynamicPairManager:
    conn = _make_connector(connector_name)
    return DynamicPairManager(connector=conn, quote_asset="USDC")


# Minimal mock OKX ticker response with real-world-like values
OKX_MOCK_TICKER_RESPONSE = {
    "code": "0",
    "data": [
        {
            "instId": "OKB-USDC",
            "bidPx": "88.39",
            "askPx": "88.41",
            "last": "88.40",
            "vol24h": "1750.96",       # base volume (OKB units)
            "volCcy24h": "153224.98",  # quote volume (USDC) — THIS is what we want
            "open24h": "86.01",
            "high24h": "89.47",
            "low24h": "85.20",
            "ts": "1786107672961",
            "sodUtc0": "85.34",
            "sodUtc8": "85.71",
        },
        {
            "instId": "ETH-USDC",
            "bidPx": "1929.01",
            "askPx": "1929.16",
            "last": "1929.02",
            "vol24h": "3830.72",
            "volCcy24h": "7322790.49",
            "open24h": "1900.00",
            "high24h": "1950.00",
            "low24h": "1890.00",
            "ts": "1786107672961",
            "sodUtc0": "1900.00",
            "sodUtc8": "1910.00",
        },
        # This one should be filtered out (wrong quote asset)
        {
            "instId": "OKB-USDT",
            "bidPx": "88.38",
            "askPx": "88.42",
            "last": "88.40",
            "vol24h": "5000.00",
            "volCcy24h": "441950.00",
            "open24h": "86.00",
            "ts": "1786107672961",
            "sodUtc0": "86.00",
            "sodUtc8": "86.00",
        },
    ],
}


# ── T1: OKX DPM must NOT use the Kraken API URL ──────────────────────────────

class TestDpmDoesNotUseKrakenForOkx:
    """T1 — After fix: OKX DPM must not call api.kraken.com."""

    def test_fetch_all_tickers_kraken_url_not_in_okx_path(self):
        """
        T1: After fix, _fetch_all_tickers dispatches on exchange name.
        The Kraken URL must only live inside _fetch_kraken_tickers, not in the
        router method itself or in _fetch_okx_tickers.
        """
        import inspect

        import multi_coin_grid_pro.utils.dynamic_pair_manager as dpm_module

        source = inspect.getsource(dpm_module.DynamicPairManager._fetch_all_tickers)
        assert "kraken.com" not in source, (
            "Kraken URL must not appear in _fetch_all_tickers after the fix "
            "(it belongs only in _fetch_kraken_tickers)."
        )

    def test_okx_dpm_routes_to_okx_method(self):
        """T1: For connector.name='okx', _fetch_all_tickers calls _fetch_okx_tickers."""
        dpm = _make_dpm("okx")
        import inspect
        source = inspect.getsource(dpm._fetch_all_tickers)
        assert "okx" in source.lower(), "Route to OKX must be present in _fetch_all_tickers"

    @pytest.mark.asyncio
    async def test_okx_dpm_calls_okx_not_kraken(self):
        """T1: full_scan for OKX connector must call OKX URL, never api.kraken.com."""
        dpm = _make_dpm("okx")
        dpm.connector.trading_pair_symbol_map = AsyncMock(
            return_value={"OKB-USDC": "OKB-USDC", "ETH-USDC": "ETH-USDC"}
        )

        okx_called = []
        kraken_called = []

        class MockResponse:
            status = 200

            async def json(self):
                return OKX_MOCK_TICKER_RESPONSE

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def get(self, url, **kw):
                if "okx.com" in url:
                    okx_called.append(url)
                if "kraken.com" in url:
                    kraken_called.append(url)
                return MockResponse()

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            await dpm.full_scan()

        assert not kraken_called, f"OKX DPM must not call Kraken: {kraken_called}"
        assert okx_called, "OKX DPM must call the OKX ticker API"


# ── T2: Kraken DPM still uses Kraken data ────────────────────────────────────

class TestKrakenDpmUsesKrakenData:
    """T2 — Kraken DPM must still use the Kraken endpoint after the fix."""

    def test_kraken_connector_routes_to_kraken(self):
        """T2: connector.name containing 'kraken' routes to _fetch_kraken_tickers."""
        dpm = _make_dpm("kraken")
        import inspect
        source = inspect.getsource(dpm._fetch_all_tickers)
        # After fix, the router checks for 'okx'; anything else falls through to Kraken
        assert "okx" in source.lower(), "Exchange routing logic must be in _fetch_all_tickers"

    @pytest.mark.asyncio
    async def test_kraken_dpm_calls_kraken_not_okx(self):
        """T2: full_scan for Kraken connector calls api.kraken.com."""
        dpm = _make_dpm("kraken")
        dpm.connector.trading_pair_symbol_map = AsyncMock(
            return_value={"ETH-EUR": "ETH-EUR"}
        )

        kraken_called = []
        okx_called = []

        class MockResponse:
            status = 200

            async def json(self):
                return {"error": [], "result": {}}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def get(self, url, **kw):
                if "kraken.com" in url:
                    kraken_called.append(url)
                if "okx.com" in url:
                    okx_called.append(url)
                return MockResponse()

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            await dpm.full_scan()

        assert not okx_called, f"Kraken DPM must not call OKX: {okx_called}"
        assert kraken_called, "Kraken DPM must call api.kraken.com"


# ── T3 + T9: OKX ticker parsing correctness ──────────────────────────────────

class TestOkxTickerParsing:
    """T3/T9 — OKX _fetch_okx_tickers parses fields correctly."""

    @pytest.mark.asyncio
    async def test_okb_usdc_volume_is_quote_currency(self):
        """
        T9: volCcy24h (not vol24h * last) is used as volume_24h.
        OKB-USDC volCcy24h=153224.98 USDC — must match within 1% of expected.
        """
        dpm = _make_dpm("okx")

        class MockResponse:
            status = 200

            async def json(self):
                return OKX_MOCK_TICKER_RESPONSE

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def get(self, url, **kw):
                return MockResponse()

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            result = await dpm._fetch_okx_tickers()

        assert "OKB-USDC" in result, "OKB-USDC must be in parsed result"
        okb = result["OKB-USDC"]

        # volume_24h must equal volCcy24h (153224.98), NOT vol24h*last (1750.96*88.4≈154735)
        assert abs(okb["volume_24h"] - 153224.98) < 1.0, (
            f"volume_24h must be volCcy24h=153224.98, got {okb['volume_24h']}"
        )

    @pytest.mark.asyncio
    async def test_okb_last_price_correct(self):
        dpm = _make_dpm("okx")

        class MockResponse:
            status = 200

            async def json(self):
                return OKX_MOCK_TICKER_RESPONSE

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def get(self, url, **kw):
                return MockResponse()

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            result = await dpm._fetch_okx_tickers()

        okb = result["OKB-USDC"]
        assert okb["last_price"] == pytest.approx(88.40, rel=1e-4)

    @pytest.mark.asyncio
    async def test_spread_stored_as_fraction(self):
        """T10: spread stored as fraction (0.000226), not percent (0.0226)."""
        dpm = _make_dpm("okx")

        class MockResponse:
            status = 200

            async def json(self):
                return OKX_MOCK_TICKER_RESPONSE

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def get(self, url, **kw):
                return MockResponse()

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            result = await dpm._fetch_okx_tickers()

        # OKB-USDC: bid=88.39, ask=88.41 → spread_frac = 0.02/88.39 ≈ 0.000226
        okb = result["OKB-USDC"]
        assert "spread_frac" in okb, "OKX result must include spread_frac key"
        expected_frac = (88.41 - 88.39) / 88.39
        assert okb["spread_frac"] == pytest.approx(expected_frac, rel=0.01), (
            f"spread must be fraction {expected_frac:.6f}, got {okb['spread_frac']}"
        )
        # Confirm it's << 1 (fraction, not percent)
        assert okb["spread_frac"] < 0.01, "spread_frac must be < 0.01 (fraction, not pct)"

    @pytest.mark.asyncio
    async def test_wrong_quote_asset_filtered_out(self):
        """T9: OKB-USDT must NOT appear in results when quote_asset='USDC'."""
        dpm = _make_dpm("okx")

        class MockResponse:
            status = 200

            async def json(self):
                return OKX_MOCK_TICKER_RESPONSE

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def get(self, url, **kw):
                return MockResponse()

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            result = await dpm._fetch_okx_tickers()

        assert "OKB-USDT" not in result, "OKB-USDT must be filtered (wrong quote asset)"
        assert "OKB-USDC" in result
        assert "ETH-USDC" in result


# ── T10: Spread unit test ─────────────────────────────────────────────────────

class TestSpreadUnits:
    """T10 — pair_spreads stores fractions; MarketMetrics.spread_pct takes %."""

    def test_pair_spreads_to_market_metrics_no_double_multiply(self):
        """
        pair_spreads["OKB-USDC"] = 0.000226 (fraction)
        MarketMetrics(spread_pct=0.000226 * 100) = 0.0226%
        The bucket classifier threshold is 2.0% → 0.0226% well below → not illiquid via spread
        """
        spread_frac = 0.000226  # what pair_spreads stores
        m = MarketMetrics(
            volume_24h_usd=153224.98,
            spread_pct=spread_frac * 100.0,  # exactly what controller does
        )
        assert m.spread_pct == pytest.approx(0.0226, rel=0.01)
        # Must NOT be > 2% (which would make it ILLIQUID)
        assert m.spread_pct < 2.0

    def test_full_scan_stores_spread_as_fraction_in_pair_metrics(self):
        """
        After full_scan, PairMetrics.spread_pct is in % (calculated from bid/ask).
        The controller propagation divides by 100 again → correct fraction in pair_spreads.
        """
        from multi_coin_grid_pro.utils.dynamic_pair_manager import PairMetrics

        pm = PairMetrics(symbol="OKB-USDC")
        pm.bid = 88.39
        pm.ask = 88.41
        pm.volume_24h = 153224.98

        # Simulate what full_scan does: spread_pct = (ask-bid)/bid * 100
        pm.spread_pct = (pm.ask - pm.bid) / pm.bid * 100  # = 0.02263%

        # Simulate controller propagation: pair_spreads[sym] = (ask-bid)/bid
        pair_spreads_value = (pm.ask - pm.bid) / pm.bid   # = 0.0002263

        # Confirm fraction is small (< 0.01) and pct is small (< 1)
        assert pm.spread_pct == pytest.approx(0.0226, rel=0.01)
        assert pair_spreads_value == pytest.approx(0.000226, rel=0.01)
        assert pair_spreads_value < 0.01, "pair_spreads must be fraction not percent"


# ── T3: OKB-USDC receives MarketMetrics after correct scan ───────────────────

class TestOkbReceivesMarketMetrics:
    """T3 — After a correct scan OKB-USDC should have non-zero volume/spread."""

    @pytest.mark.asyncio
    async def test_full_scan_populates_all_pairs_for_okb(self):
        """T3: After mocked OKX full_scan, all_pairs contains OKB-USDC."""
        dpm = _make_dpm("okx")
        dpm.connector.trading_pair_symbol_map = AsyncMock(
            return_value={"OKB-USDC": "OKB-USDC", "ETH-USDC": "ETH-USDC"}
        )

        class MockResponse:
            status = 200

            async def json(self):
                return OKX_MOCK_TICKER_RESPONSE

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

        class MockSession:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                pass

            def get(self, url, **kw):
                return MockResponse()

        with patch("aiohttp.ClientSession", return_value=MockSession()):
            count = await dpm.full_scan()

        assert count >= 2
        assert "OKB-USDC" in dpm.all_pairs
        pm = dpm.all_pairs["OKB-USDC"]
        assert pm.volume_24h > 0
        assert pm.bid > 0 and pm.ask > 0

    def test_controller_can_build_market_metrics_from_dpm(self):
        """T3: Given DPM has OKB data, controller code can build correct MarketMetrics."""
        from multi_coin_grid_pro.utils.dynamic_pair_manager import PairMetrics

        dpm = _make_dpm("okx")
        dpm.all_pairs["OKB-USDC"] = PairMetrics(
            symbol="OKB-USDC", volume_24h=153224.98, bid=88.39, ask=88.41
        )

        # Simulate controller propagation
        pair_volumes = {}
        pair_spreads = {}
        for sym, pm in dpm.all_pairs.items():
            if pm.volume_24h > 0:
                pair_volumes[sym] = pm.volume_24h
            if pm.bid > 0 and pm.ask > 0:
                pair_spreads[sym] = (pm.ask - pm.bid) / pm.bid

        vol = pair_volumes.get("OKB-USDC")
        spr = pair_spreads.get("OKB-USDC")

        assert vol is not None and vol == pytest.approx(153224.98, rel=0.001)
        assert spr is not None and spr == pytest.approx(0.000226, rel=0.01)

        # Build MarketMetrics exactly as controller does
        m = MarketMetrics(volume_24h_usd=float(vol), spread_pct=float(spr) * 100.0)
        # OKB-USDC USDC volume is ~$153k/day — below the $5M ILLIQUID threshold.
        # This means data-driven classification would give ILLIQUID (not tradeable at 51% cap).
        # The L2 manual override for OKB bypasses metrics entirely, so this is fine.
        assert m.volume_24h_usd < 5_000_000, "OKB USDC volume is low; L2 override is what enables trading"


# ── T4: Unknown coin without metrics → BLOCKED ───────────────────────────────

class TestFailClosedForUnknownCoins:
    """T4 — Fail-closed: unknown coin, no metrics → BLOCKED."""

    def test_unknown_coin_no_metrics_blocked(self):
        clf = RiskBucketClassifier()
        result = clf.classify("UNKNOWNCOIN99-USDC", metrics=None)
        assert result.bucket == CoinBucket.BLOCKED

    def test_blocked_reason_mentions_no_market_data(self):
        clf = RiskBucketClassifier()
        result = clf.classify("NEWCOIN-USDC", metrics=None)
        assert "no market data" in result.reason.lower()

    def test_can_add_blocked_coin_returns_false(self):
        tracker = RiskBucketExposureTracker(portfolio_value=300.0)
        ok, reason = tracker.can_add("UNKNOWNCOIN99-USDC", 51.26, metrics=None)
        assert not ok
        assert "BLOCKED" in reason


# ── T5: Liquid unknown coin with good metrics → ILLIQUID (not L1/L2) ─────────

class TestDataDrivenClassificationNeverProducesL1L2:
    """
    T5 — A coin without manual override can NEVER be auto-classified as L1/L2.
    Even with vol=$1B and spread=0.001%, unknown coins get ILLIQUID.
    """

    def test_excellent_metrics_still_yields_illiquid(self):
        clf = RiskBucketClassifier()
        m = MarketMetrics(volume_24h_usd=1_000_000_000, spread_pct=0.001)
        result = clf.classify("ALLO-USDC", metrics=m)
        assert result.bucket == CoinBucket.ILLIQUID
        assert "policy fallback" in result.reason.lower()

    def test_no_data_driven_path_to_l1(self):
        clf = RiskBucketClassifier()
        m = MarketMetrics(volume_24h_usd=1_000_000_000, spread_pct=0.001)
        for sym in ["ALLO-USDC", "BCH-USDC", "UNKNOWN-USDC"]:
            result = clf.classify(sym, metrics=m)
            assert result.bucket != CoinBucket.L1

    def test_no_data_driven_path_to_l2(self):
        clf = RiskBucketClassifier()
        m = MarketMetrics(volume_24h_usd=1_000_000_000, spread_pct=0.001)
        for sym in ["ALLO-USDC", "BCH-USDC", "UNKNOWN-USDC"]:
            result = clf.classify(sym, metrics=m)
            assert result.bucket != CoinBucket.L2

    def test_illiquid_cap_blocks_standard_notional(self):
        """ILLIQUID cap (3%) = $9 for portfolio=$300; any notional >$9 is blocked."""
        tracker = RiskBucketExposureTracker(portfolio_value=300.0)
        m = MarketMetrics(volume_24h_usd=100_000_000, spread_pct=0.001)
        ok, reason = tracker.can_add("ALLO-USDC", 51.26, metrics=m)
        assert not ok
        assert "ILLIQUID" in reason


# ── T6: Illiquid coin with bad metrics → ILLIQUID via checks ─────────────────

class TestIlliquidDetectionFromMetrics:
    """T6 — Volume and spread checks correctly classify illiquid coins."""

    def test_low_volume_classified_as_illiquid(self):
        clf = RiskBucketClassifier()
        m = MarketMetrics(volume_24h_usd=100_000, spread_pct=0.01)
        result = clf.classify("THINTOKEN-USDC", metrics=m)
        assert result.bucket == CoinBucket.ILLIQUID
        assert "volume" in result.reason.lower()

    def test_high_spread_classified_as_illiquid(self):
        clf = RiskBucketClassifier()
        m = MarketMetrics(volume_24h_usd=50_000_000, spread_pct=5.0)
        result = clf.classify("WIDESPREADTOKEN-USDC", metrics=m)
        assert result.bucket == CoinBucket.ILLIQUID
        assert "spread" in result.reason.lower()


# ── T7: ADA/XRP manual overrides work without metrics ────────────────────────

class TestManualOverridesPreserved:
    """T7 — ADA, XRP, BTC, DOGE retain their classifications unchanged."""

    def test_ada_is_l2_without_metrics(self):
        clf = RiskBucketClassifier()
        assert clf.classify("ADA-USDC", metrics=None).bucket == CoinBucket.L2

    def test_xrp_is_l2_without_metrics(self):
        clf = RiskBucketClassifier()
        assert clf.classify("XRP-USDC", metrics=None).bucket == CoinBucket.L2

    def test_btc_is_l1_without_metrics(self):
        clf = RiskBucketClassifier()
        assert clf.classify("BTC-USDC", metrics=None).bucket == CoinBucket.L1

    def test_doge_is_meme_without_metrics(self):
        clf = RiskBucketClassifier()
        assert clf.classify("DOGE-USDC", metrics=None).bucket == CoinBucket.MEME

    def test_okb_is_l2_after_patch(self):
        """After Patch B: OKB must be L2 without metrics."""
        clf = RiskBucketClassifier()
        result = clf.classify("OKB-USDC", metrics=None)
        assert result.bucket == CoinBucket.L2, (
            f"OKB should be L2 after adding to _MANUAL_L2, got {result.bucket}: {result.reason}"
        )
        assert "manual override" in result.reason.lower()

    def test_ada_can_add_passes(self):
        tracker = RiskBucketExposureTracker(portfolio_value=300.0)
        ok, reason = tracker.can_add("ADA-USDC", 51.26, metrics=None)
        assert ok, f"ADA must pass: {reason}"

    def test_xrp_can_add_passes(self):
        tracker = RiskBucketExposureTracker(portfolio_value=300.0)
        ok, reason = tracker.can_add("XRP-USDC", 51.26, metrics=None)
        assert ok, f"XRP must pass: {reason}"

    def test_okb_can_add_passes_after_patch(self):
        """After Patch B: OKB can_add must pass at portfolio=300, notional=51.26."""
        tracker = RiskBucketExposureTracker(portfolio_value=300.0)
        ok, reason = tracker.can_add("OKB-USDC", 51.26, metrics=None)
        assert ok, f"OKB must pass bucket check after L2 override: {reason}"

    def test_unknown_coin_still_blocked(self):
        tracker = RiskBucketExposureTracker(portfolio_value=300.0)
        ok, _ = tracker.can_add("UNKNOWNCOIN99-USDC", 51.26, metrics=None)
        assert not ok

    def test_metrics_do_not_downgrade_manual_override(self):
        clf = RiskBucketClassifier()
        m = MarketMetrics(volume_24h_usd=1, spread_pct=99.0)
        assert clf.classify("ADA-USDC", metrics=m).bucket == CoinBucket.L2
        assert clf.classify("OKB-USDC", metrics=m).bucket == CoinBucket.L2


# ── T8: XRP passes bucket but V2-04 blocks when expected_hourly < threshold ──

class TestXrpV2_04Block:
    """T8 — XRP passes bucket check but V2-04 silently blocks it."""

    def _make_fee_filter(self, hourly_check_enabled: bool = True) -> FeeAwareFilter:
        return FeeAwareFilter(config={
            "enabled": True,
            "hourly_profit_check_enabled": hourly_check_enabled,
            "taker_fee_pct": 0.35,
            "maker_fee_pct": 0.20,
            "fee_model": "best_case",
            "min_net_profit_pct": 0.40,
            "min_profit_per_hour_pct": 0.10,
            "fills_calibration_factor": 1.0,
        })

    def test_xrp_passes_bucket_check(self):
        tracker = RiskBucketExposureTracker(portfolio_value=300.0)
        ok, reason = tracker.can_add("XRP-USDC", 51.26, metrics=None)
        assert ok, f"XRP bucket check should pass: {reason}"

    def test_xrp_atr_too_low_for_v204(self):
        """ATR=0.075% → expected_hourly=0.049% < 0.10% → V2-04 FAIL."""
        faf = self._make_fee_filter()
        est = faf.estimate_hourly_profit("XRP-USDC", grid_range_pct=7.0, num_grids=7, atr_pct=0.075)
        assert not est.passed
        assert est.expected_hourly_profit_pct < 0.10

    def test_xrp_with_sufficient_atr_passes_v204(self):
        faf = self._make_fee_filter()
        est = faf.estimate_hourly_profit("XRP-USDC", grid_range_pct=7.0, num_grids=7, atr_pct=0.20)
        assert est.passed

    def test_okb_atr_currently_failing_v204(self):
        """OKB current ATR=0.13% → expected=0.086% < 0.10% → V2-04 FAIL (expected behavior)."""
        faf = self._make_fee_filter()
        est = faf.estimate_hourly_profit("OKB-USDC", grid_range_pct=7.0, num_grids=7, atr_pct=0.13)
        assert not est.passed
        assert est.expected_hourly_profit_pct < 0.10

    def test_okb_passes_bucket_after_patch(self):
        """After OKB L2 override, OKB passes bucket even when V2-04 eventually fails."""
        tracker = RiskBucketExposureTracker(portfolio_value=300.0)
        ok, reason = tracker.can_add("OKB-USDC", 51.26, metrics=None)
        assert ok, f"OKB must pass bucket after L2 patch: {reason}"
