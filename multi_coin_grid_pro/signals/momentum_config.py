# momentum_config.py — ServiceConfig dataclass + YAML loader
# Read-only signal service configuration. mode MUST be "signal_only".
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml

_ALLOWED_MODES = {"signal_only"}

_DEFAULT_SAFETY: Dict[str, Any] = {
    "read_only": True,
    "allow_order_creation": False,
    "allow_executor_actions": False,
    "allow_budget_reservation": False,
    "allow_grid_state_writes": False,
}

# Safety flags that must remain False in signal_only mode
_MUST_BE_FALSE = (
    "allow_order_creation",
    "allow_executor_actions",
    "allow_budget_reservation",
    "allow_grid_state_writes",
)


@dataclass
class ExchangeConfig:
    exchange: str
    api_url: str
    quote_assets: List[str]
    region: str = "global"
    enabled: bool = True
    allowed_quote_assets: List[str] = field(default_factory=list)
    disallowed_quote_assets: List[str] = field(default_factory=list)
    grid_db_path: str = ""
    blacklist_yaml: str = ""
    cooldown_db_path: str = ""

    def effective_quote_assets(self) -> List[str]:
        """Return the allowlist used for ticker filtering.

        Uses ``allowed_quote_assets`` if non-empty; otherwise falls back to
        ``quote_assets`` so that legacy configs without the explicit allowlist
        continue to work unchanged.
        """
        return self.allowed_quote_assets if self.allowed_quote_assets else self.quote_assets


@dataclass
class CandidateFilters:
    min_price_change_5m_pct: float = 2.0
    min_price_change_15m_pct: float = 4.0
    max_price_change_15m_pct: float = 35.0
    min_volume_ratio: float = 3.0
    max_spread_pct: float = 0.35
    min_orderbook_depth_quote: float = 5000.0
    max_orderbook_staleness_seconds: float = 5.0
    exclude_blacklisted: bool = True
    exclude_active_grid_positions: bool = True
    exclude_cooldown_pairs: bool = True
    # US-207: entry-quality filters (0.0 = disabled; backward-compatible)
    min_price_change_1m_pct: float = 0.0        # reject if Δ1m < this (0 = off)
    min_price_change_3m_pct: float = 0.0        # reject if Δ3m < this (0 = off)
    max_price_change_5m_pct: float = 0.0        # SPIKE_NO_CONTINUATION (0 = off)
    max_too_late_price_change_15m_pct: float = 0.0  # TOO_LATE_EXTENDED_MOVE (0 = off)
    max_estimated_slippage_pct: float = 0.0     # ORDERBOOK_TOO_THIN (0 = off)
    # spread_pct is stored/compared in percentage points (e.g. 0.15 = 0.15%, NOT 15%).
    max_spread_pct_entry: float = 0.0           # SPREAD_TOO_HIGH_FOR_ENTRY (0 = off); unit: % points
    require_acceleration: bool = False          # NO_SHORT_TERM_ACCELERATION
    # max_volume_ratio: reject BUY_NOW if volume spike is extreme (thin-market artefact).
    # 0.0 = disabled. Unit: ratio (e.g. 1000 = 1000x normal volume).
    max_volume_ratio: float = 0.0               # VOLUME_SPIKE_TOO_EXTREME (0 = off)


@dataclass
class ScoringConfig:
    # 0.0–1.0 schaal; wrapper normaliseert legacy 0–100 scorer
    min_score: float = 0.70


@dataclass
class UniverseConfig:
    """Defines which asset types are eligible for momentum scanning.

    All flags default to False so existing tests are unaffected unless
    explicitly overridden.  The YAML config sets them to True in production.
    """
    exclude_forex_pairs: bool = False
    exclude_stablecoins: bool = False
    exclude_tokenized_metals: bool = False
    # exclude_major_assets uses `excluded_base_assets` as the reference list.
    exclude_major_assets: bool = False
    excluded_base_assets: List[str] = field(default_factory=list)


@dataclass
class OutputConfig:
    """Controls diagnostic output produced by the signal service."""
    log_data_coverage: bool = True
    log_top_rejected_candidates: bool = True
    top_rejected_n: int = 20


@dataclass
class RateLimitConfig:
    """Per-exchange rate-limit parameters for the enrichment engine."""
    max_requests_per_minute_per_exchange: int = 60
    min_seconds_between_orderbook_calls: float = 2.0


@dataclass
class MarketDataConfig:
    """Controls candle/orderbook enrichment behaviour.

    mode="sample"  — enrich only the top ``max_enriched_pairs_per_exchange``
                     candidates per exchange (sorted by spread, most liquid
                     first).  Use during development / rate-limit testing.
    mode="full"    — enrich all candidates (subject to rate limits).
    """
    mode: str = "sample"
    max_enriched_pairs_per_exchange: int = 25
    rate_limits: RateLimitConfig = field(default_factory=RateLimitConfig)


@dataclass
class TelegramConfig:
    """Telegram notification settings for accepted momentum signals."""
    enabled: bool = False
    bot_token: Optional[str] = None   # falls back to env TELEGRAM_BOT_TOKEN
    chat_id: Optional[str] = None     # falls back to env TELEGRAM_CHAT_ID
    cooldown_seconds: int = 1200      # dedup window: min seconden tussen berichten per pair
    dedup_min_price_drop_pct: float = 1.5  # stuur opnieuw als prijs >= x% gedaald
    heartbeat_interval_seconds: int = 3600  # 0 = heartbeat uitgeschakeld


@dataclass
class NotificationsConfig:
    """Container voor alle notificatie-kanalen."""
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


@dataclass
class ClassificationConfig:
    """Thresholds for WATCH / BUY_NOW / TOO_LATE signal classification (US-201)."""
    watch_min_score: float = 0.55
    buy_now_min_score: float = 0.80
    # TOO_LATE conditions (any one triggers TOO_LATE label):
    too_late_delta_15m_pct: float = 6.0       # absolute 15m move too large
    too_late_delta_5m_pct: float = 3.5        # single-candle spike
    too_late_delta_15m_soft: float = 5.0      # soft 15m threshold (combined with accel)
    too_late_acceleration_threshold: float = 0.4  # below this + soft → TOO_LATE
    # BUY_NOW downgrade: if Δ15m >= this, downgrade BUY_NOW → WATCH (not TOO_LATE)
    buy_now_delta_15m_max_pct: float = 5.5    # 5.5% ≤ Δ15m < 6.0% → WATCH not BUY_NOW
    # Conservative paper-test controls (signal_only only; never place orders).
    paper_test_enabled: bool = False
    # Optional stricter gate for paper analysis (e.g. 0.80). 0.0 = disabled.
    paper_watch_min_score_override: float = 0.0
    # Block BUY_NOW in strong bullish regime (Q4 proxy). 0.0 = disabled.
    paper_block_buy_now_when_market_regime_ge_pct: float = 0.0
    # Optional exchange preference in ranking (paper only).
    paper_prefer_exchange_enabled: bool = False
    paper_preferred_exchange: str = "bitget"
    paper_preferred_exchange_rank_bonus: float = 0.0
    # Analysis-only variant: optional max-score cap to test overfitting hypotheses.
    analysis_max_score_filter_enabled: bool = False
    analysis_max_score: float = 1.0
    # Evaluation target for post-change comparisons.
    evaluation_target_buy_now_count: int = 200


@dataclass
class EntryConfig:
    """Entry zone, stop and take-profit percentages for BUY_NOW signals (US-204, US-205)."""
    entry_below_bid_pct: float = 0.3            # entry_min = bid * (1 - 0.003)
    entry_above_ask_pct: float = 0.2            # entry_max = ask * (1 + 0.002)
    max_chase_above_entry_max_pct: float = 0.8  # max_chase = entry_max * 1.008
    stop_below_entry_min_pct: float = 1.5       # invalidation = entry_min * 0.985
    tp1_above_entry_max_pct: float = 1.2        # take_profit_1 = entry_max * 1.012
    tp2_above_entry_max_pct: float = 2.5        # take_profit_2 = entry_max * 1.025


@dataclass
class Change24hContextConfig:
    """Piecewise penalty curve for 24h price change in preselection scoring."""
    ideal_min_pct: float = -2.0           # below this: light penalty starts
    ideal_max_pct: float = 8.0            # above this: light penalty starts
    soft_penalty_below_pct: float = -8.0  # below this: heavy penalty
    heavy_penalty_below_pct: float = -15.0  # below this: very heavy penalty
    soft_penalty_above_pct: float = 15.0  # above this: heavy penalty
    extreme_penalty_above_pct: float = 25.0  # above this: very heavy penalty
    hard_reject_enabled: bool = False     # never hard-reject on 24h change


@dataclass
class PreselectionBucketsConfig:
    """Bucket sizes for the top-100 preselection split."""
    top_score: int = 70       # best coins by composite pre_score
    top_quote_volume: int = 20  # most liquid coins not in top_score
    rotating_round_robin: int = 10  # rotating coverage to avoid blind spots


@dataclass
class PreselectionConfig:
    """Pre-enrichment filtering and ranking.

    Applied before candle/orderbook enrichment to select the most promising
    momentum candidates from the full ticker universe.
    """
    enabled: bool = True
    min_quote_volume_24h: float = 100_000.0
    max_spread_pct: float = 0.35
    min_abs_24h_change_pct: float = 1.0
    exclude_negative_24h_change_below_pct: float = -20.0  # kept for backward compat
    prefer_positive_24h_change: bool = True  # kept for backward compat
    # New ranking weights (should sum to 1.0)
    quote_volume_24h_weight: float = 0.40
    spread_quality_weight: float = 0.30
    range_position_24h_weight: float = 0.20
    change_24h_context_weight: float = 0.10
    # Legacy weights (used if new weights are all zero — backward compat)
    abs_24h_change_weight: float = 0.0
    quote_volume_weight: float = 0.0
    positive_change_weight: float = 0.0
    # Sub-configs
    change_24h_context: Change24hContextConfig = field(
        default_factory=Change24hContextConfig
    )
    buckets: PreselectionBucketsConfig = field(
        default_factory=PreselectionBucketsConfig
    )


@dataclass
class ServiceConfig:
    mode: str = "signal_only"
    enabled: bool = True
    scan_interval_seconds: int = 60
    top_n: int = 10
    exchanges: List[ExchangeConfig] = field(default_factory=list)
    safety: Dict[str, Any] = field(default_factory=dict)
    candidate_filters: CandidateFilters = field(default_factory=CandidateFilters)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    market_data: MarketDataConfig = field(default_factory=MarketDataConfig)
    preselection: PreselectionConfig = field(default_factory=PreselectionConfig)
    notifications: NotificationsConfig = field(default_factory=NotificationsConfig)
    classification: ClassificationConfig = field(default_factory=ClassificationConfig)
    entry: EntryConfig = field(default_factory=EntryConfig)
    # Eigen blacklist van de scanner — onafhankelijk van de grid-bot configs
    scanner_blacklist: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.mode not in _ALLOWED_MODES:
            raise ValueError(
                f"mode must be 'signal_only', got {self.mode!r}. "
                "Automatic and paper trading are disabled in this service."
            )
        # Merge caller-supplied safety dict with defaults
        merged: Dict[str, Any] = {**_DEFAULT_SAFETY, **self.safety}
        for flag in _MUST_BE_FALSE:
            if merged.get(flag, False):
                raise ValueError(
                    f"safety.{flag} must be False — "
                    "this is a read-only signal-only service."
                )
        if not merged.get("read_only", True):
            raise ValueError("safety.read_only must be True in signal_only mode.")
        self.safety = merged

    @classmethod
    def from_yaml(cls, path: Union[str, Path]) -> "ServiceConfig":
        """Load ServiceConfig from a YAML file using yaml.safe_load."""
        with open(path) as fh:
            raw = yaml.safe_load(fh)
        section = raw.get("momentum_signal_service", raw) if isinstance(raw, dict) else raw
        return cls._from_dict(section)

    @classmethod
    def _from_dict(cls, d: Dict[str, Any]) -> "ServiceConfig":
        exchanges = [ExchangeConfig(**ex) for ex in d.get("exchanges", [])]
        cf_raw = d.get("candidate_filters", {})
        cf = CandidateFilters(**cf_raw) if cf_raw else CandidateFilters()
        sc_raw = d.get("scoring", {})
        sc = ScoringConfig(**sc_raw) if sc_raw else ScoringConfig()
        uc_raw = d.get("universe", {})
        uc = UniverseConfig(**uc_raw) if uc_raw else UniverseConfig()
        oc_raw = d.get("output", {})
        oc = OutputConfig(**oc_raw) if oc_raw else OutputConfig()
        md_raw = d.get("market_data", {})
        if md_raw:
            rl_raw = md_raw.pop("rate_limits", {})
            rl = RateLimitConfig(**rl_raw) if rl_raw else RateLimitConfig()
            md = MarketDataConfig(rate_limits=rl, **md_raw)
        else:
            md = MarketDataConfig()
        ps_raw = d.get("preselection", {})
        if ps_raw:
            ctx_raw = ps_raw.pop("change_24h_context", {})
            ctx = Change24hContextConfig(**ctx_raw) if ctx_raw else Change24hContextConfig()
            bkt_raw = ps_raw.pop("buckets", {})
            bkt = PreselectionBucketsConfig(**bkt_raw) if bkt_raw else PreselectionBucketsConfig()
            ps = PreselectionConfig(change_24h_context=ctx, buckets=bkt, **ps_raw)
        else:
            ps = PreselectionConfig()
        notif_raw = d.get("notifications", {})
        tg_raw = notif_raw.get("telegram", {}) if notif_raw else {}
        tg = TelegramConfig(**tg_raw) if tg_raw else TelegramConfig()
        notif = NotificationsConfig(telegram=tg)
        cls_raw = d.get("classification", {})
        cls_cfg = ClassificationConfig(**cls_raw) if cls_raw else ClassificationConfig()
        entry_raw = d.get("entry", {})
        entry_cfg = EntryConfig(**entry_raw) if entry_raw else EntryConfig()
        return cls(
            mode=d.get("mode", "signal_only"),
            enabled=d.get("enabled", True),
            scan_interval_seconds=d.get("scan_interval_seconds", 60),
            top_n=d.get("top_n", 10),
            exchanges=exchanges,
            safety=d.get("safety", {}),
            candidate_filters=cf,
            scoring=sc,
            universe=uc,
            output=oc,
            market_data=md,
            preselection=ps,
            notifications=notif,
            classification=cls_cfg,
            entry=entry_cfg,
            scanner_blacklist=d.get("scanner_blacklist", []),
        )
