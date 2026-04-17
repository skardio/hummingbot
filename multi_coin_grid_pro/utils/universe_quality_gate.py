"""
ST-02: Universe Quality Gate — prefilter before ranking.

Removes coins that should never enter the candidate pool:
  - Stablecoins (USDT, USDC, DAI, …)
  - Leveraged / inverse tokens (3L, 3S, BULL, BEAR, UP, DOWN)
  - Wrapped duplicates when the native exists (WBTC when BTC available)
  - Exchange-specific exclusions per config

All checks are O(1) string operations — no network calls.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# ── well-known stablecoins (base asset, uppercase) ──────────────────
_STABLECOINS: FrozenSet[str] = frozenset({
    "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "GUSD",
    "FRAX", "LUSD", "CRVUSD", "USDD", "FDUSD", "PYUSD",
    "EUR", "GBP", "CHF", "JPY", "AUD", "CAD",  # fiat-pegged
    "EURT", "EUROC",
})

# ── leveraged / derivative token patterns ────────────────────────────
_LEVERAGED_RE = re.compile(
    r"("
    r"\d+[LSX]$"          # BTC3L, ETH3S, SOL2X (at end of symbol)
    r"|BULL$|BEAR$"        # BTCBULL, ETHBEAR (at end)
    r"|^BULL|^BEAR"        # BULL*, BEAR* prefix
    r"|UP$|DOWN$"          # Binance UP/DOWN
    r"|HALF$|HEDGE$"       # half / hedge tokens
    r")",
    re.IGNORECASE,
)

# ── wrapped tokens that duplicate natives ────────────────────────────
_WRAPPED_PREFIXES = ("W", "ST", "CB")  # WBTC, stETH, cbETH


@dataclass
class QualityGateConfig:
    """Configuration for the universe quality gate."""
    enabled: bool = True
    exclude_stablecoins: bool = True
    exclude_leveraged: bool = True
    exclude_wrapped_when_native_exists: bool = True
    extra_blacklist: Set[str] = field(default_factory=set)
    min_24h_volume: float = 0.0       # 0 = use existing volume filter
    max_spread_pct: float = 0.0       # 0 = use existing spread filter


@dataclass
class QualityGateResult:
    """Result of quality prefilter on the universe."""
    passed: List[Tuple[str, float, float]]    # (pair, volume, spread)
    rejected: Dict[str, str]                  # pair → reason
    stats: Dict[str, int]                     # reason → count


def apply_quality_gate(
    candidates: List[Tuple[str, float, float]],
    quote_asset: str,
    config: Optional[QualityGateConfig] = None,
    available_base_assets: Optional[Set[str]] = None,
) -> QualityGateResult:
    """
    Filter a list of (pair, volume, spread) candidates through quality checks.

    Args:
        candidates: List of (trading_pair, volume_24h, spread) tuples.
        quote_asset: The quote currency (e.g. "USD", "EUR", "USDT").
        config: Gate configuration. Uses defaults if None.
        available_base_assets: Set of all base assets in the universe
            (used for wrapped-duplicate detection).

    Returns:
        QualityGateResult with passed/rejected lists and stats.
    """
    if config is None:
        config = QualityGateConfig()

    if not config.enabled:
        return QualityGateResult(passed=list(candidates), rejected={}, stats={})

    # Build set of available base assets for wrapped-duplicate check
    if available_base_assets is None:
        available_base_assets = {
            _extract_base(pair, quote_asset) for pair, _, _ in candidates
        }

    passed: List[Tuple[str, float, float]] = []
    rejected: Dict[str, str] = {}
    stats: Dict[str, int] = {}

    for pair, volume, spread in candidates:
        base = _extract_base(pair, quote_asset)
        reason = _check_quality(base, pair, config, available_base_assets)

        if reason:
            rejected[pair] = reason
            stats[reason] = stats.get(reason, 0) + 1
        else:
            passed.append((pair, volume, spread))

    return QualityGateResult(passed=passed, rejected=rejected, stats=stats)


def _extract_base(pair: str, quote_asset: str) -> str:
    """Extract base asset from trading pair: 'BTC-USD' → 'BTC'."""
    return pair.replace(f"-{quote_asset}", "").upper()


def _check_quality(
    base: str,
    pair: str,
    config: QualityGateConfig,
    available_bases: Set[str],
) -> Optional[str]:
    """Return rejection reason or None if the coin passes."""
    # Extra blacklist
    if base in config.extra_blacklist or pair in config.extra_blacklist:
        return "BLACKLISTED"

    # Stablecoin check
    if config.exclude_stablecoins and base in _STABLECOINS:
        return "STABLECOIN"

    # Leveraged / derivative token
    if config.exclude_leveraged and _LEVERAGED_RE.search(base):
        return "LEVERAGED_TOKEN"

    # Wrapped duplicate (WBTC when BTC exists)
    if config.exclude_wrapped_when_native_exists:
        for prefix in _WRAPPED_PREFIXES:
            if base.startswith(prefix) and len(base) > len(prefix):
                native = base[len(prefix):]
                if native in available_bases:
                    return f"WRAPPED_DUPLICATE({native})"

    return None
