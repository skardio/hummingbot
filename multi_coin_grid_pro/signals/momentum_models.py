"""
Data models for the momentum signal service.

Pure dataclasses — no I/O, no exchange dependencies, no Hummingbot imports.
All fields use stdlib types only.

Schaal-afspraak: score is altijd 0.0–1.0 (niet 0–100).
See docs/MOMENTUM_SIGNAL_SERVICE_PATCHPLAN.md for the full contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Market data snapshots (candles + orderbook)
# ---------------------------------------------------------------------------


@dataclass
class CandleSnapshot:
    """Single OHLCV candle (typically 1-minute interval)."""
    timestamp: float   # Unix epoch of candle open
    open: float
    high: float
    low: float
    close: float
    volume: float      # base-asset volume


@dataclass
class OrderBookSnapshot:
    """Point-in-time orderbook snapshot."""
    fetched_at: float                # Unix epoch when fetched
    bids: List[List[float]]          # [[price, amount], ...] best-bid first
    asks: List[List[float]]          # [[price, amount], ...] best-ask first


# ---------------------------------------------------------------------------
# Stage 1: raw ticker data from exchange REST endpoint
# ---------------------------------------------------------------------------

@dataclass
class RawTicker:
    """Minimale tickerdata zoals opgehaald via publiek REST endpoint."""
    exchange: str
    trading_pair: str
    price: float
    bid: float
    ask: float
    volume_24h: float       # in base asset
    timestamp: float        # Unix epoch wanneer opgehaald

    @property
    def spread_pct(self) -> float:
        if self.bid <= 0:
            return 0.0
        return ((self.ask - self.bid) / self.bid) * 100.0


# ---------------------------------------------------------------------------
# Stage 2: enriched candidate (candles + orderbook + state annotations)
# ---------------------------------------------------------------------------

@dataclass
class EnrichedCandidate:
    """
    Kandidaat na ophalen van candles, orderbook en annotatie van grid-state.
    Alle Optional-velden zijn None als data niet beschikbaar was.
    """
    # Identiteit
    exchange: str
    trading_pair: str

    # Prijs & spread (altijd beschikbaar — uit ticker)
    price: float
    bid: float
    ask: float
    spread_pct: float

    # Momentum (uit 1m-candles; None als < 2 candles beschikbaar)
    price_change_1m_pct: Optional[float] = None
    price_change_3m_pct: Optional[float] = None
    price_change_5m_pct: Optional[float] = None
    price_change_15m_pct: Optional[float] = None

    # Acceleration (afgeleid van 1m/3m/5m deltas; 0.0 als onvoldoende data)
    acceleration_score: Optional[float] = None

    # Volume (uit candles)
    volume_ratio: Optional[float] = None       # volume_now / volume_avg_20_candles

    # Orderbook (uit depth snapshot)
    orderbook_depth_quote: Optional[float] = None   # bid-diepte binnen 1% in quote
    orderbook_imbalance: Optional[float] = None     # (bid_vol - ask_vol) / totaal

    # Slippage schatting (uit orderbook; quote-valuta van het pair)
    slippage_100eur: Optional[float] = None    # slippage % voor marktorder van 100 quote
    slippage_250eur: Optional[float] = None    # slippage % voor marktorder van 250 quote

    # Volatiliteit (std van 1m-returns)
    volatility_pct: Optional[float] = None

    # 24h ticker data (for pre-enrichment ranking; None if not provided)
    quote_volume_24h: Optional[float] = None
    price_change_24h_pct: Optional[float] = None
    high_24h: Optional[float] = None   # 24h high (for range_position_24h)
    low_24h: Optional[float] = None    # 24h low  (for range_position_24h)

    # Preselection annotations (filled by apply_preselection)
    preselection_score: Optional[float] = None
    preselection_rank: Optional[int] = None
    preselection_bucket: Optional[str] = None     # top_score / top_quote_volume / rotating_round_robin
    preselection_breakdown: Optional[dict] = None  # JSON-serializable dict

    # Timestamps voor staleness checks
    ob_fetched_at: float = 0.0
    candles_fetched_at: float = 0.0

    # Grid-state annotaties (gevuld door ReadOnlyStateAnnotator)
    active_grid_position: bool = False
    blacklisted: bool = False
    in_cooldown: bool = False

    # Scorer-inputs (afgeleid uit candles; None als onvoldoende data)
    trend_1h_pct: Optional[float] = None
    trend_4h_pct: Optional[float] = None
    volume_expansion: Optional[float] = None   # volume_ratio vs. baseline
    rsi: Optional[float] = None
    wick_risk: Optional[float] = None          # 0.0–1.0


# ---------------------------------------------------------------------------
# Stage 3: scored signal
# ---------------------------------------------------------------------------

@dataclass
class MomentumSignal:
    """
    Volledig gescoord signaal na de volledige pipeline.
    score is altijd 0.0–1.0.
    rank is None voor verworpen signalen.
    """
    # Identiteit
    scan_id: str
    timestamp: float
    exchange: str
    trading_pair: str

    # Prijs & momentum
    price: float
    spread_pct: float
    price_change_1m_pct: Optional[float] = None
    price_change_3m_pct: Optional[float] = None
    price_change_5m_pct: Optional[float] = None
    price_change_15m_pct: Optional[float] = None

    # Acceleration
    acceleration_score: Optional[float] = None

    # Volume & liquiditeit
    volume_ratio: Optional[float] = None
    orderbook_depth_quote: Optional[float] = None
    orderbook_imbalance: Optional[float] = None

    # Slippage schatting
    slippage_100eur: Optional[float] = None
    slippage_250eur: Optional[float] = None

    # Volatiliteit
    volatility_pct: Optional[float] = None

    # Context
    active_grid_position: bool = False
    blacklisted: bool = False
    in_cooldown: bool = False

    # Scoring (0.0–1.0)
    score: float = 0.0
    accepted: bool = False
    rank: Optional[int] = None              # 1 = beste van de scan

    # Rejection
    rejection_reason: Optional[str] = None  # None als geaccepteerd
    all_reasons: list[str] = field(default_factory=list)

    # Classificatie (US-201: WATCH / BUY_NOW / TOO_LATE; None voor verworpen signalen)
    signal_label: Optional[str] = None

    # Entry zone (US-204)
    entry_min: Optional[float] = None
    entry_max: Optional[float] = None
    max_chase_price: Optional[float] = None

    # Stop + take-profit (US-205)
    invalidation_price: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_2: Optional[float] = None

    # Score breakdown per dimensie (voor debuggen)
    score_breakdown: dict[str, float] = field(default_factory=dict)

    # Preselection context (voor analyse waarom coin in top-100 terechtkwam)
    preselection_score: Optional[float] = None
    preselection_rank: Optional[int] = None
    preselection_bucket: Optional[str] = None
    preselection_breakdown: Optional[dict] = None

    # Config versie (gevuld door service op startup, voor analyse per paramset)
    config_version_id: Optional[int] = None

    # ── Marktcontext (gevuld door service per scan, voor regime-analyse) ──────
    # Gemiddelde Δ15m van alle verrijkte paren in de scan (markttemperatuur proxy).
    market_regime_at_signal: Optional[float] = None
    # % van verrijkte paren met positieve Δ15m (marktbreedte indicator).
    market_breadth_15m: Optional[float] = None
    # BTC Δ15m op het moment van het signaal (NULL als BTC niet in de scan zit).
    btc_15m_change_pct: Optional[float] = None
    # ETH Δ15m op het moment van het signaal (NULL als ETH niet in de scan zit).
    eth_15m_change_pct: Optional[float] = None

    # DB-id (gevuld door SignalStore na schrijven)
    id: Optional[int] = None


# ---------------------------------------------------------------------------
# Pre-enrichment selection report
# ---------------------------------------------------------------------------

@dataclass
class PreselectionCandidate:
    """Snapshot of a candidate chosen during pre-enrichment selection."""
    exchange: str
    trading_pair: str
    spread_pct: float
    quote_volume_24h: Optional[float]
    price_change_24h_pct: Optional[float]
    pre_score: float


@dataclass
class ExchangePreselectionStats:
    """Per-exchange counters from the pre-enrichment selection step."""
    exchange: str
    universe_total: int = 0    # all ticker candidates from this exchange
    eligible: int = 0          # passed pre-filters (spread, volume, change, universe)
    selected: int = 0          # chosen for enrichment (top N by pre_score)
    top_examples: List["PreselectionCandidate"] = field(default_factory=list)
    region: str = "global"
    allowed_quote_assets: List[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class PreselectionReport:
    """Aggregated pre-enrichment selection stats across all exchanges."""
    by_exchange: List[ExchangePreselectionStats] = field(default_factory=list)

    @property
    def total_universe(self) -> int:
        return sum(s.universe_total for s in self.by_exchange)

    @property
    def total_selected(self) -> int:
        return sum(s.selected for s in self.by_exchange)


# ---------------------------------------------------------------------------
# Filter result
# ---------------------------------------------------------------------------

@dataclass
class RejectedCandidate:
    """Wrapper om een verworpen EnrichedCandidate met de eerste afwijzingsreden."""
    candidate: EnrichedCandidate
    rejection_reason: str
    all_reasons: list[str] = field(default_factory=list)


@dataclass
class FilterResult:
    """Uitkomst van HardFilter.apply() op een lijst kandidaten."""
    accepted: list[EnrichedCandidate] = field(default_factory=list)
    rejected: list[RejectedCandidate] = field(default_factory=list)

    @property
    def n_accepted(self) -> int:
        return len(self.accepted)

    @property
    def n_rejected(self) -> int:
        return len(self.rejected)

    @property
    def rejection_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for r in self.rejected:
            counts[r.rejection_reason] = counts.get(r.rejection_reason, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Scan result (output van één volledige scan-cyclus)
# ---------------------------------------------------------------------------

@dataclass
class ScanResult:
    """
    Volledige output van één scan-cyclus over alle exchanges.
    Bevat zowel geaccepteerde als verworpen signalen voor volledige audit.
    """
    scan_id: str
    timestamp: float
    scan_duration_seconds: float

    # Alle signalen (geaccepteerd + verworpen)
    signals: list[MomentumSignal] = field(default_factory=list)

    # Coverage report (aanwezig als output.log_data_coverage=True)
    coverage: Optional["DataCoverageReport"] = None

    # Top-N verworpen enriched candidates op score (aanwezig als log_top_rejected_candidates=True)
    top_rejected: list[MomentumSignal] = field(default_factory=list)

    # Up to 10 rejected candidates with n/a momentum data (for debug)
    missing_data_sample: list[MomentumSignal] = field(default_factory=list)

    # Pre-enrichment selection report (None when preselection disabled)
    preselection_report: Optional["PreselectionReport"] = None

    @property
    def top_signals(self) -> list[MomentumSignal]:
        """Alleen geaccepteerde signalen, gesorteerd op rank."""
        return sorted(
            [s for s in self.signals if s.accepted],
            key=lambda s: s.rank if s.rank is not None else 999,
        )

    @property
    def total_scanned(self) -> int:
        return len(self.signals)

    @property
    def total_accepted(self) -> int:
        return sum(1 for s in self.signals if s.accepted)

    @property
    def total_rejected(self) -> int:
        return sum(1 for s in self.signals if not s.accepted)

    @property
    def rejection_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for s in self.signals:
            if not s.accepted and s.rejection_reason:
                counts[s.rejection_reason] = counts.get(s.rejection_reason, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Data coverage report
# ---------------------------------------------------------------------------

@dataclass
class ExchangeCoverageStats:
    """Per-exchange data quality counters computed from enriched candidates."""
    exchange: str
    pairs_total: int = 0
    tickers_ok: int = 0          # always == pairs_total
    orderbook_ok: int = 0        # orderbook_depth_quote is not None
    candles_1m_ok: int = 0       # price_change_1m_pct is not None
    candles_3m_ok: int = 0       # price_change_3m_pct is not None
    candles_5m_ok: int = 0       # price_change_5m_pct is not None
    candles_15m_ok: int = 0      # price_change_15m_pct is not None
    volume_ratio_ok: int = 0     # volume_ratio is not None
    momentum_data_complete: int = 0   # all three (5m, 15m, vol_ratio) not None
    missing_momentum_data: int = 0    # any of (5m, 15m, vol_ratio) is None
    accepted: int = 0
    rejected: int = 0


@dataclass
class DataCoverageReport:
    """Aggregated data coverage over all exchanges in a scan cycle."""
    by_exchange: List[ExchangeCoverageStats] = field(default_factory=list)
    # Counts per specific missing-data reason, computed from raw candidate fields
    missing_reason_breakdown: Dict[str, int] = field(default_factory=dict)
    # True when > 80% of all pairs are missing momentum data (or >20% of enriched in sample mode)
    blind_warning: bool = False

    # Sample-mode metadata
    sample_mode: bool = False
    enriched_total: int = 0       # candidates with any enrichment (candles or OB)
    enriched_complete: int = 0    # enriched and fully complete
    enriched_incomplete: int = 0  # enriched but missing some metric

    @property
    def total_pairs(self) -> int:
        return sum(s.pairs_total for s in self.by_exchange)

    @property
    def total_missing(self) -> int:
        return sum(s.missing_momentum_data for s in self.by_exchange)
