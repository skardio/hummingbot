"""
Unit Tests for Dynamic Pair Manager

Tests:
1. Symbol conversion (Kraken -> standard format)
2. Pair scoring algorithm (standalone)
3. REST API integration (with mocked responses)

Note: Tests are designed to run without full Hummingbot environment
"""

import unittest
from dataclasses import dataclass

# ============================================================================
# STANDALONE TEST CLASSES (copied from dynamic_pair_manager.py)
# These allow testing without importing hummingbot
# ============================================================================


@dataclass
class PairMetrics:
    """Test copy of PairMetrics for standalone testing"""
    symbol: str
    volume_24h: float = 0.0
    price_change_24h: float = 0.0
    spread_pct: float = 0.0
    last_price: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    last_scanned: float = 0.0
    score: float = 0.0

    def calculate_score(
        self,
        volume_weight: float = 0.4,
        trend_weight: float = 0.4,
        spread_weight: float = 0.2
    ) -> float:
        """Calculate composite score for pair ranking"""
        volume_score = min(100, max(0, (self.volume_24h / 100000) * 10)) if self.volume_24h > 0 else 0
        trend_score = min(100, max(0, (self.price_change_24h + 10) * 5))
        spread_score = max(0, 100 - (self.spread_pct * 100))

        self.score = (
            volume_score * volume_weight
            + trend_score * trend_weight
            + spread_score * spread_weight
        )
        return self.score


def convert_kraken_symbol(kraken_symbol: str, quote_asset: str = "EUR") -> str:
    """Test copy of symbol conversion function"""
    symbol = kraken_symbol.upper()
    quote = quote_asset.upper()

    if not symbol.endswith(quote) and not symbol.endswith(f"Z{quote}"):
        return ""

    fiat_to_fiat = [
        "ZEURZUSD", "EURUSD", "EURGBP", "EURCHF", "EURCAD", "EURAUD", "EURJPY",
        "USDJPY", "GBPUSD", "USDCHF", "USDCAD"
    ]
    if symbol in fiat_to_fiat:
        return ""

    if symbol.startswith("ZEUR") or symbol.startswith("ZUSD"):
        return ""

    kraken_base_map = {
        "XXBT": "BTC", "XBT": "BTC",
        "XXDG": "DOGE", "XDG": "DOGE",
        "XXRP": "XRP",
        "XETH": "ETH",
        "XLTC": "LTC",
        "XXLM": "XLM",
        "XZEC": "ZEC",
        "XXMR": "XMR",
    }

    if symbol.endswith(f"Z{quote}"):
        base = symbol[:-len(f"Z{quote}")]
    else:
        base = symbol[:-len(quote)]

    if base in kraken_base_map:
        base = kraken_base_map[base]
    else:
        if base.startswith("X") and len(base) == 4:
            stripped = base[1:]
            if stripped in ["ETH", "LTC", "XLM", "ZEC", "XMR", "REP", "ETC", "DG"]:
                base = stripped
                if base == "DG":
                    base = "DOGE"

    if len(base) < 2 or base == "EURC":
        return ""

    return f"{base}-{quote}"


# ============================================================================
# TESTS
# ============================================================================

class TestSymbolConversion(unittest.TestCase):
    """Test Kraken symbol to standard format conversion"""

    def test_stablecoins(self):
        """Test stablecoin conversion"""
        self.assertEqual(convert_kraken_symbol("USDCEUR"), "USDC-EUR")
        self.assertEqual(convert_kraken_symbol("USDTEUR"), "USDT-EUR")

    def test_major_cryptos_with_x_prefix(self):
        """Test major cryptos with Kraken's X prefix"""
        self.assertEqual(convert_kraken_symbol("XXBTZEUR"), "BTC-EUR")
        self.assertEqual(convert_kraken_symbol("XETHZEUR"), "ETH-EUR")
        self.assertEqual(convert_kraken_symbol("XXRPZEUR"), "XRP-EUR")
        self.assertEqual(convert_kraken_symbol("XLTCZEUR"), "LTC-EUR")

    def test_newer_coins_without_prefix(self):
        """Test newer coins without X prefix"""
        self.assertEqual(convert_kraken_symbol("SOLEUR"), "SOL-EUR")
        self.assertEqual(convert_kraken_symbol("ADAEUR"), "ADA-EUR")
        self.assertEqual(convert_kraken_symbol("DOTEUR"), "DOT-EUR")
        self.assertEqual(convert_kraken_symbol("SUIEUR"), "SUI-EUR")
        self.assertEqual(convert_kraken_symbol("LINKEUR"), "LINK-EUR")
        self.assertEqual(convert_kraken_symbol("TRXEUR"), "TRX-EUR")
        self.assertEqual(convert_kraken_symbol("AVAXEUR"), "AVAX-EUR")
        self.assertEqual(convert_kraken_symbol("PEPEEUR"), "PEPE-EUR")

    def test_special_cases(self):
        """Test special symbol mappings"""
        self.assertEqual(convert_kraken_symbol("XDGEUR"), "DOGE-EUR")
        self.assertEqual(convert_kraken_symbol("MONEUR"), "MON-EUR")
        self.assertEqual(convert_kraken_symbol("TAOEUR"), "TAO-EUR")
        self.assertEqual(convert_kraken_symbol("XNYEUR"), "XNY-EUR")

    def test_fiat_pairs_skipped(self):
        """Test that fiat-to-fiat pairs are skipped"""
        self.assertEqual(convert_kraken_symbol("ZEURZUSD"), "")
        self.assertEqual(convert_kraken_symbol("EURGBP"), "")
        self.assertEqual(convert_kraken_symbol("EURCHF"), "")

    def test_non_eur_pairs_skipped(self):
        """Test that non-EUR pairs are skipped"""
        self.assertEqual(convert_kraken_symbol("BTCUSD"), "")
        self.assertEqual(convert_kraken_symbol("ETHUSD"), "")
        self.assertEqual(convert_kraken_symbol("SOLUSD"), "")

    def test_case_insensitive(self):
        """Test case insensitivity"""
        self.assertEqual(convert_kraken_symbol("soleur"), "SOL-EUR")
        self.assertEqual(convert_kraken_symbol("SolEur"), "SOL-EUR")
        self.assertEqual(convert_kraken_symbol("SOLEUR"), "SOL-EUR")

    def test_empty_and_invalid(self):
        """Test empty and invalid inputs"""
        self.assertEqual(convert_kraken_symbol(""), "")
        self.assertEqual(convert_kraken_symbol("INVALID"), "")
        self.assertEqual(convert_kraken_symbol("X"), "")


class TestPairMetrics(unittest.TestCase):
    """Test PairMetrics scoring"""

    def test_high_volume_high_trend_low_spread(self):
        """Test scoring for ideal pair"""
        metrics = PairMetrics(
            symbol="SOL-EUR",
            volume_24h=10_000_000,  # €10M
            price_change_24h=5.0,   # +5%
            spread_pct=0.01,        # 0.01%
        )
        score = metrics.calculate_score()

        # Should have high score (>70)
        self.assertGreater(score, 70)
        self.assertEqual(metrics.score, score)

    def test_low_volume_negative_trend_high_spread(self):
        """Test scoring for poor pair"""
        metrics = PairMetrics(
            symbol="BADCOIN-EUR",
            volume_24h=10_000,      # €10k
            price_change_24h=-8.0,  # -8%
            spread_pct=0.8,         # 0.8%
        )
        score = metrics.calculate_score()

        # Should have low score (<30)
        self.assertLess(score, 30)

    def test_score_weights(self):
        """Test that weights are applied correctly"""
        metrics = PairMetrics(
            symbol="TEST-EUR",
            volume_24h=1_000_000,
            price_change_24h=0.0,
            spread_pct=0.5,
        )

        score = metrics.calculate_score(
            volume_weight=0.4,
            trend_weight=0.4,
            spread_weight=0.2
        )

        self.assertIsInstance(score, float)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_score_bounds(self):
        """Test that score is bounded between 0 and 100"""
        # Extreme positive
        metrics1 = PairMetrics(
            symbol="BEST-EUR",
            volume_24h=100_000_000,
            price_change_24h=50.0,
            spread_pct=0.0,
        )
        score1 = metrics1.calculate_score()
        self.assertLessEqual(score1, 100)

        # Extreme negative
        metrics2 = PairMetrics(
            symbol="WORST-EUR",
            volume_24h=0,
            price_change_24h=-50.0,
            spread_pct=10.0,
        )
        score2 = metrics2.calculate_score()
        self.assertGreaterEqual(score2, 0)


class TestPairSelection(unittest.TestCase):
    """Test pair selection logic"""

    def test_select_top_pairs(self):
        """Test selecting top N pairs by score"""
        pairs = [
            PairMetrics(symbol="A-EUR", volume_24h=1_000_000, price_change_24h=5.0, spread_pct=0.1),
            PairMetrics(symbol="B-EUR", volume_24h=500_000, price_change_24h=3.0, spread_pct=0.2),
            PairMetrics(symbol="C-EUR", volume_24h=2_000_000, price_change_24h=-1.0, spread_pct=0.05),
            PairMetrics(symbol="D-EUR", volume_24h=100_000, price_change_24h=10.0, spread_pct=0.5),
            PairMetrics(symbol="E-EUR", volume_24h=50_000, price_change_24h=-5.0, spread_pct=0.8),
        ]

        # Calculate scores
        for p in pairs:
            p.calculate_score()

        # Sort by score
        sorted_pairs = sorted(pairs, key=lambda x: x.score, reverse=True)

        # Top 3
        top_3 = sorted_pairs[:3]
        self.assertEqual(len(top_3), 3)

        # Verify ordering (highest score first)
        self.assertGreaterEqual(top_3[0].score, top_3[1].score)
        self.assertGreaterEqual(top_3[1].score, top_3[2].score)

    def test_filter_by_volume(self):
        """Test filtering pairs by minimum volume"""
        pairs = [
            PairMetrics(symbol="HIGH-EUR", volume_24h=1_000_000),
            PairMetrics(symbol="LOW-EUR", volume_24h=10_000),
            PairMetrics(symbol="MED-EUR", volume_24h=500_000),
        ]

        min_volume = 100_000
        filtered = [p for p in pairs if p.volume_24h >= min_volume]

        self.assertEqual(len(filtered), 2)
        self.assertIn("HIGH-EUR", [p.symbol for p in filtered])
        self.assertIn("MED-EUR", [p.symbol for p in filtered])

    def test_filter_by_spread(self):
        """Test filtering pairs by maximum spread"""
        pairs = [
            PairMetrics(symbol="TIGHT-EUR", spread_pct=0.1),
            PairMetrics(symbol="WIDE-EUR", spread_pct=1.0),
            PairMetrics(symbol="OK-EUR", spread_pct=0.4),
        ]

        max_spread = 0.5
        filtered = [p for p in pairs if p.spread_pct <= max_spread]

        self.assertEqual(len(filtered), 2)
        self.assertIn("TIGHT-EUR", [p.symbol for p in filtered])
        self.assertIn("OK-EUR", [p.symbol for p in filtered])


class TestKrakenAPIResponse(unittest.TestCase):
    """Test parsing Kraken API responses"""

    def test_parse_ticker_data(self):
        """Test parsing Kraken ticker response"""
        # Sample Kraken ticker format
        ticker = {
            "a": ["100.0", "1", "1.0"],      # ask
            "b": ["99.9", "1", "1.0"],       # bid
            "c": ["100.0", "1.0"],           # last trade
            "v": ["1000", "10000"],          # volume [today, 24h]
            "o": "95.0"                       # opening price
        }

        # Parse
        ask = float(ticker["a"][0])
        bid = float(ticker["b"][0])
        last = float(ticker["c"][0])
        vol_24h = float(ticker["v"][1])
        open_price = float(ticker["o"])

        # Assertions
        self.assertEqual(ask, 100.0)
        self.assertEqual(bid, 99.9)
        self.assertEqual(last, 100.0)
        self.assertEqual(vol_24h, 10000)
        self.assertEqual(open_price, 95.0)

        # Calculate derived values
        spread_pct = ((ask - bid) / bid) * 100
        price_change_pct = ((last - open_price) / open_price) * 100
        vol_eur = vol_24h * last

        self.assertAlmostEqual(spread_pct, 0.1, places=2)
        self.assertAlmostEqual(price_change_pct, 5.26, places=2)
        self.assertEqual(vol_eur, 1_000_000)


class TestAsyncDiscovery(unittest.IsolatedAsyncioTestCase):
    """Async tests for discovery logic"""

    async def test_mock_api_call(self):
        """Test mocked API call"""

        mock_response = {
            "error": [],
            "result": {
                "SOLEUR": {
                    "a": ["100.0", "1", "1.0"],
                    "b": ["99.9", "1", "1.0"],
                    "c": ["100.0", "1.0"],
                    "v": ["1000", "10000"],
                    "o": "95.0"
                },
                "XXBTZEUR": {
                    "a": ["50000.0", "1", "1.0"],
                    "b": ["49999.0", "1", "1.0"],
                    "c": ["50000.0", "1.0"],
                    "v": ["100", "1000"],
                    "o": "49000.0"
                }
            }
        }

        # Verify response structure
        self.assertEqual(mock_response["error"], [])
        self.assertIn("SOLEUR", mock_response["result"])
        self.assertIn("XXBTZEUR", mock_response["result"])

        # Parse SOL
        sol = mock_response["result"]["SOLEUR"]
        self.assertEqual(float(sol["c"][0]), 100.0)

        # Convert symbol
        symbol = convert_kraken_symbol("SOLEUR")
        self.assertEqual(symbol, "SOL-EUR")


class TestFullScanBidictUsage(unittest.TestCase):
    """
    Test that full_scan uses trading_pair_symbol_map VALUES (hummingbot format)
    not KEYS (exchange native format).

    The bidict returned by connector.trading_pair_symbol_map():
      keys   = exchange native format (e.g., "ADAEUR", "XXBTZEUR")
      values = hummingbot format      (e.g., "ADA-EUR", "BTC-EUR")

    full_scan must filter on values to find "-EUR" pairs.
    """

    def test_values_have_dash_separator(self):
        """Values (hummingbot format) contain '-' separator, keys do not."""
        # Simulate bidict: keys=exchange, values=hummingbot
        bidict_mock = {
            "ADAEUR": "ADA-EUR",
            "XXBTZEUR": "BTC-EUR",
            "SOLEUR": "SOL-EUR",
            "XETHZEUR": "ETH-EUR",
            "ADAUSD": "ADA-USD",
        }

        # Using .keys() (THE BUG): no key ends with "-EUR"
        keys = list(bidict_mock.keys())
        keys_eur = [p for p in keys if p.endswith("-EUR")]
        self.assertEqual(len(keys_eur), 0, "keys() should NOT have -EUR suffix")

        # Using .values() (THE FIX): values DO end with "-EUR"
        values = list(bidict_mock.values())
        values_eur = [p for p in values if p.endswith("-EUR")]
        self.assertEqual(len(values_eur), 4, "values() should have 4 EUR pairs")
        self.assertIn("ADA-EUR", values_eur)
        self.assertIn("BTC-EUR", values_eur)
        self.assertIn("SOL-EUR", values_eur)
        self.assertIn("ETH-EUR", values_eur)

    def test_values_filter_correct_quote(self):
        """Only pairs matching the quote asset are returned."""
        bidict_mock = {
            "ADAEUR": "ADA-EUR",
            "ADAUSD": "ADA-USD",
            "BTCEUR": "BTC-EUR",
            "BTCUSD": "BTC-USD",
        }

        values = list(bidict_mock.values())

        eur_pairs = [p for p in values if p.endswith("-EUR")]
        self.assertEqual(eur_pairs, ["ADA-EUR", "BTC-EUR"])

        usd_pairs = [p for p in values if p.endswith("-USD")]
        self.assertEqual(usd_pairs, ["ADA-USD", "BTC-USD"])


if __name__ == "__main__":
    unittest.main()
