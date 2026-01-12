"""
CoinSelector v2.0 - Dynamic Pair Discovery

Automatically discovers and filters trading pairs based on:
- 24h volume (liquidity)
- Spread (transaction cost)
- Blacklist (manual exclusions)
- Quote asset (EUR/USDT/etc)

Falls back to core_universe if discovery fails.
"""
import logging
from typing import Dict, List, Optional, Set


class CoinSelector:
    """
    Dynamic coin discovery and filtering

    Usage:
        selector = CoinSelector(config, logger)
        tradable = selector.filter_pairs(
            available_pairs=["BTC-EUR", "ETH-EUR", ...],
            volume_eur={"BTC-EUR": 5000000, ...},
            spreads={"BTC-EUR": 0.001, ...}
        )
    """

    def __init__(
        self,
        cfg: dict,
        logger: Optional[logging.Logger] = None
    ):
        """
        Initialize Coin Selector

        Args:
            cfg: Config dict with blacklist, core_universe, min_24h_volume_eur, etc
            logger: Optional logger instance
        """
        self.cfg = cfg
        self.logger = logger or logging.getLogger(__name__)

        # Configuration
        self.blacklist: Set[str] = set(cfg.get("blacklist", []))
        self.core_universe: List[str] = cfg.get("core_universe", [])
        self.min_volume_eur = cfg.get("min_24h_volume_eur", 300000)
        self.max_spread_pct = cfg.get("max_entry_spread_pct", 0.5)
        self.quote_asset = cfg.get("quote_asset", "EUR")
        self.use_dynamic = cfg.get("use_dynamic_pair_discovery", True)

        self.logger.info("=" * 80)
        self.logger.info("🎯 CoinSelector v2.0 initialized")
        self.logger.info(f"   Mode: {'DYNAMIC' if self.use_dynamic else 'MANUAL'}")
        self.logger.info(f"   Quote asset: {self.quote_asset}")
        self.logger.info(f"   Min volume: €{self.min_volume_eur:,}")
        self.logger.info(f"   Max spread: {self.max_spread_pct}%")
        self.logger.info(f"   Blacklist: {len(self.blacklist)} pairs")
        self.logger.info(f"   Core universe: {len(self.core_universe)} pairs")
        self.logger.info("=" * 80)

    def filter_pairs(
        self,
        available_pairs: List[str],
        volume_eur: Dict[str, float],
        spreads: Optional[Dict[str, float]] = None
    ) -> List[str]:
        """
        Filter trading pairs based on volume, spread, and blacklist

        Args:
            available_pairs: All pairs from exchange
            volume_eur: Dict mapping pair -> 24h volume in EUR
            spreads: Optional dict mapping pair -> bid-ask spread percentage

        Returns:
            List of tradable pairs, sorted by volume descending
        """
        if not self.use_dynamic:
            self.logger.info("Using manual trading pairs from config")
            manual_pairs = self.cfg.get("manual_trading_pairs", self.core_universe)
            return [p for p in manual_pairs if p not in self.blacklist]

        self.logger.info(f"🔍 Filtering {len(available_pairs)} pairs...")

        candidates = []

        for pair in available_pairs:
            # 1) Must end with quote asset
            if not pair.endswith(f"-{self.quote_asset}"):
                continue

            # 2) Check blacklist
            if pair in self.blacklist:
                self.logger.debug(f"   ❌ {pair}: blacklisted")
                continue

            # 3) Check volume
            vol = volume_eur.get(pair, 0.0)
            if vol < self.min_volume_eur:
                self.logger.debug(f"   ❌ {pair}: volume €{vol:,.0f} < €{self.min_volume_eur:,}")
                continue

            # 4) Check spread (if provided)
            if spreads:
                spread_pct = spreads.get(pair, 999.0) * 100
                if spread_pct > self.max_spread_pct:
                    self.logger.debug(f"   ❌ {pair}: spread {spread_pct:.3f}% > {self.max_spread_pct}%")
                    continue

            # Passed all filters
            candidates.append((pair, vol))
            self.logger.debug(f"   ✅ {pair}: €{vol:,.0f} volume")

        if not candidates:
            self.logger.warning("⚠️  No candidates found - falling back to core_universe")
            fallback = [p for p in self.core_universe if p not in self.blacklist]
            self.logger.info(f"   Fallback: {len(fallback)} pairs from core_universe")
            return fallback

        # Sort by volume descending
        candidates.sort(key=lambda x: x[1], reverse=True)
        result = [pair for pair, vol in candidates]

        self.logger.info(f"✅ Selected {len(result)} tradable pairs")
        self.logger.info(f"   Top 10: {result[:10]}")

        return result

    def get_top_n(
        self,
        pairs: List[str],
        volume_eur: Dict[str, float],
        n: int
    ) -> List[str]:
        """
        Get top N pairs by volume

        Args:
            pairs: List of pairs
            volume_eur: Volume dict
            n: Number of pairs to return

        Returns:
            Top N pairs sorted by volume
        """
        sorted_pairs = sorted(
            pairs,
            key=lambda p: volume_eur.get(p, 0.0),
            reverse=True
        )
        return sorted_pairs[:n]
