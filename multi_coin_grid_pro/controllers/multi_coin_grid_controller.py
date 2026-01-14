"""
Multi-Coin Grid Trading Controller

Main controller that implements the multi-coin grid trading strategy using
Hummingbot's Strategy V2 architecture.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.data_type.common import OrderType
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.data_feed.market_data_provider import MarketDataProvider
from hummingbot.strategy_v2.controllers.controller_base import ControllerBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig, TripleBarrierConfig
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, ExecutorAction, StopExecutorAction
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo
from multi_coin_grid_pro.alerts.telegram_alerter import TelegramAlerter

# Config parsers
from multi_coin_grid_pro.core.config_loader import (
    MarketRegimeConfig,
    parse_market_regime_config,
    parse_performance_config,
    parse_time_based_config,
)

# Import from multi_coin_grid_pro package (actual implementation)
from multi_coin_grid_pro.core.drawdown_tracker import DrawdownTracker
from multi_coin_grid_pro.core.global_risk_manager import GlobalRiskManager

# Feature 1.1: Market Regime Filter
from multi_coin_grid_pro.core.market_regime_integration import MarketRegimeIntegration

# Feature 1.3: Performance Tracking
from multi_coin_grid_pro.core.performance_tracker import PerformanceTracker

# Phase 1B: Observability
from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage

# Feature 1.2: Time-Based Trading Rules
from multi_coin_grid_pro.core.time_based_integration import TimeBasedIntegration

# Task 3.1: Dynamic Slot Manager
from multi_coin_grid_pro.execution.dynamic_slot_manager import DynamicSlotManager
from multi_coin_grid_pro.filters import CandleIndicators, SmartEntryConfig, SmartEntryFilter

# Story 6 Part 2: Momentum Indicators
from multi_coin_grid_pro.indicators.momentum_indicators import MomentumIndicatorService
from multi_coin_grid_pro.logic.coin_selector import CoinSelector
from multi_coin_grid_pro.logic.grid_sizer import DynamicGridSizer as DynamicGridSizerV2

# Hybrid Grid Bot v2.0 - New modular components
from multi_coin_grid_pro.logic.liquidity_aware_sizer import LiquidityAwareSizing
from multi_coin_grid_pro.logic.smart_entry import SmartEntryBaseConfig, SmartEntryFilter as SmartEntryFilterV2

# Story B2: Execution Audit Records
from multi_coin_grid_pro.models.execution_audit import AuditWriter, create_audit_from_executor
from multi_coin_grid_pro.observability.event_logger import EventLogger

# Story 10: Cooldown Persistence
from multi_coin_grid_pro.persistence.cooldown_store import CooldownStore
from multi_coin_grid_pro.risk.pnl_tracker import RealtimePnLTracker
from multi_coin_grid_pro.risk.risk_guard import RiskGuardV2

# Story D1: Adaptive Timeout based on volatility
from multi_coin_grid_pro.utils.adaptive_timeout import AdaptiveTimeout, get_recommended_timeout
from multi_coin_grid_pro.utils.candle_indicators import CandleIndicatorsCalculator
from multi_coin_grid_pro.utils.coin_discovery import CoinDiscovery
from multi_coin_grid_pro.utils.decision_trace import PairDecisionTrace
from multi_coin_grid_pro.utils.dynamic_grid_sizer import DynamicGridSizer

# Story C1: Log Throttling + Structured Logging
from multi_coin_grid_pro.utils.log_throttle import StructuredLogger, should_log
from multi_coin_grid_pro.utils.trend_calculator import TrendCalculator, TrendStatus

from .multi_coin_grid_config import MultiCoinGridConfig

logger = logging.getLogger(__name__)


class MultiCoinGridController(ControllerBase):
    """
    Multi-Coin Grid Trading Controller

    This controller:
    1. Monitors multiple coins for trend opportunities
    2. Selects the best trending coin
    3. Creates a GridExecutor to trade that coin
    4. Switches to a different coin when trends change

    Uses Hummingbot's GridExecutor for order management, stop-loss, and tracking.
    """

    def __init__(self, config: MultiCoinGridConfig,
                 market_data_provider: MarketDataProvider,
                 actions_queue,
                 connectors: Dict[str, ConnectorBase] = None,
                 update_interval: float = 10.0):
        """
        Initialize the Multi-Coin Grid controller

        Args:
            config: Strategy configuration
            market_data_provider: Market data provider
            actions_queue: Queue for executor actions
            connectors: Dict of exchange connectors
            update_interval: How often to update (seconds)
        """
        try:
            print("\n🎯 CONTROLLER __INIT__ START\n")
            self.logger().info(f"🎯 CONTROLLER __INIT__ START - update_interval={update_interval}s")

            super().__init__(
                config=config,
                market_data_provider=market_data_provider,
                actions_queue=actions_queue,
                update_interval=update_interval
            )

            print("\n✅ super().__init__() completed\n")
            self.logger().info("✅ super().__init__() completed")

            self.config: MultiCoinGridConfig = config
            self.connectors = connectors or {}  # Store connectors dict
            self.logger().info(f"🔌 Available connectors: {list(self.connectors.keys())}")

            print(f"\n🎯 CONTROLLER __INIT__ CALLED - update_interval={update_interval}s\n")
            self.logger().info(f"🎯 MultiCoinGridController INIT - update_interval={update_interval}s")
        except Exception as e:
            print(f"\n❌ CONTROLLER __INIT__ FAILED: {e}\n")
            import traceback
            traceback.print_exc()
            self.logger().error(f"❌ CONTROLLER __INIT__ FAILED: {e}")
            self.logger().error(traceback.format_exc())
            raise

        # Get connector
        self.connector: Optional[ConnectorBase] = None
        self.base_connector: Optional[ConnectorBase] = None  # Base connector for price fetching in paper trading

        # Coin discovery and trend tracking
        self.coin_discovery: Optional[CoinDiscovery] = None
        self.trend_calculator: Optional[TrendCalculator] = None
        self._lookback_fix_applied = False  # Flag to ensure lookback fix is applied once
        self.monitored_coins: List[str] = []
        self.all_available_pairs: List[str] = []  # All EUR pairs from exchange
        self.pair_volumes: Dict[str, float] = {}  # Store volume data for rotation: {pair: volume_eur}
        self.pair_spreads: Dict[str, float] = {}  # Store spread data: {pair: spread}
        self.coin_performance: Dict[str, int] = {}  # Track updates without trades per coin
        # Get rotation threshold from config, default to 90 if not set
        # Replace coin after X updates without trades
        self.rotation_threshold: int = getattr(config, 'coin_rotation_threshold', 90)

        # Periodic coin discovery (auto-refresh pool)
        self.coin_discovery_refresh_interval: int = getattr(config, 'coin_discovery_refresh_interval_seconds', 3600)
        self._last_coin_discovery: float = 0.0  # Timestamp of last discovery scan

        # State tracking - MULTI-COIN SUPPORT
        # Legacy single-coin (for backwards compatibility when max_simultaneous_coins=1)
        self.active_coin: Optional[str] = None
        self.active_executor_id: Optional[str] = None
        # Multi-coin tracking: {coin: executor_id}
        self.active_coins: Dict[str, str] = {}
        self.last_switch_time: float = 0
        self.bot_start_time: float = time.time()  # Track when bot started (for startup delay)
        # Max simultaneous coins from config (default 1 for backwards compatibility)
        self.max_simultaneous_coins: int = getattr(config, 'max_simultaneous_coins', 1)

        # NEW: Tracking voor coin rotation bij monitoring (without execution)
        self.monitoring_coin: Optional[str] = None  # Coin being monitored (maar niet geëxecuteerd)
        self.monitoring_start_time: float = 0  # When monitoring of this coin started
        self.session_blacklist: Dict[str, float] = {}  # {coin: timestamp_when_blacklisted}

        # ==============================================================================
        # STORY A2: SESSION BLACKLIST & ANTI-FLIPFLOP
        # ==============================================================================
        # Track which executors we've already processed for blacklisting (idempotency)
        self._processed_timeout_executors: set = set()  # Set of executor IDs we've already blacklisted

        # Phase 1.1: Stop-Loss tracking
        self.entry_prices: Dict[str, Decimal] = {}  # Track entry price per coin: {coin: entry_price}
        self.stop_loss_triggered: Dict[str, float] = {}  # Track stop-loss events: {coin: timestamp}

        # Phase 1.2: Circuit Breaker state
        self.circuit_breaker_active: bool = False
        self.circuit_breaker_triggered_at: Optional[float] = None
        self.price_history_for_volatility: Dict[str, List[Dict]] = {}  # {coin: [{price, timestamp}]}
        self.circuit_breaker_threshold_pct: float = 5.0  # 5% move in 1 minute = circuit breaker
        self.circuit_breaker_window_seconds: int = 60  # 1 minute window

        # Phase 1.3: API Error Handling state (with circuit breaker pattern)
        self.consecutive_api_errors: int = 0
        self.total_api_errors: int = 0  # Track total errors for permanent failure detection
        self.api_error_threshold: int = 10  # Pause after 10 consecutive errors
        self.max_total_errors: int = 100  # Permanent circuit breaker after 100 total errors
        self.api_error_paused: bool = False
        self.api_error_paused_at: Optional[float] = None
        self.last_api_error_time: float = 0
        self.api_error_backoff_seconds: float = 5.0  # Start with 5 second backoff
        self.max_backoff_seconds: float = 300.0  # Max 5 minutes backoff
        self.last_successful_api_call: float = time.time()
        self.permanent_api_failure: bool = False  # Circuit breaker open permanently
        self._last_pnl_reset_day = None
        self._last_pnl_reset_week = None
        self._last_pnl_reset_month = None

        self._last_logged_regime = None
        self._last_detected_regime = None  # Story 6 Part 2: Cache detected regime for momentum guards

        # Phase 1.4: Position Size Limits state
        self.current_exposure_per_coin: Dict[str, Decimal] = {}  # {coin: exposure_amount}
        self.total_exposure: Decimal = Decimal("0")

        # Global risk supervision
        self.risk_manager = GlobalRiskManager(
            reference_balance_quote=self.config.risk_reference_balance,
            limits=self.config.risk_limits,
        )
        self._active_executor_notional: Decimal = Decimal("0")
        self._realised_executors_tracked: Dict[str, Decimal] = {}
        self._next_allocation_quote: Optional[Decimal] = None

        # Memory cleanup tracking (TTL-based)
        self._executor_creation_timestamps: Dict[str, float] = {}  # {executor_id: creation_time}
        self._trend_last_seen: Dict[str, float] = {}  # {coin: last_access_time}
        self._last_memory_cleanup_log: float = 0  # Hourly summary

        # Task 3.1: Dynamic Slot Manager
        dynamic_slots_cfg = getattr(config, 'dynamic_slots', {})
        self.dynamic_slot_manager = DynamicSlotManager(
            config=dynamic_slots_cfg,
            logger=self.logger()
        )
        if self.dynamic_slot_manager.enabled:
            self.logger().info(
                f"✅ Dynamic Slot Manager enabled "
                f"(min={self.dynamic_slot_manager.min_slots}, "
                f"max={self.dynamic_slot_manager.max_slots})"
            )
        else:
            self.logger().info(f"ℹ️  Dynamic Slot Manager disabled (using static max_simultaneous_coins={self.max_simultaneous_coins})")

        # Phase 1C: Observability - EventLogger
        observability_cfg = getattr(config, 'observability', {})

        # Robust config reading: support both dict and object/dataclass
        if isinstance(observability_cfg, dict):
            structured_events_enabled = observability_cfg.get('structured_events_enabled', False)
        else:
            structured_events_enabled = getattr(observability_cfg, 'structured_events_enabled', False)

        self.event_logger: Optional[EventLogger] = None

        # Phase 4: Scheduled Reporting - define interval FIRST before using it
        self._last_report_time: float = 0.0  # Track last time we generated report
        self._report_interval_minutes: int = getattr(
            getattr(config, 'observability', {}),
            'report_interval_minutes',
            60  # Default: hourly
        )
        self._console_reporter = None  # Will be initialized below if observability enabled

        if structured_events_enabled:
            try:
                from multi_coin_grid_pro.observability.event_logger import compute_config_hash

                # Robust config reading for nested values
                if isinstance(observability_cfg, dict):
                    events_output_dir = observability_cfg.get('events_output_dir', 'logs/events')
                    buffer_size = observability_cfg.get('buffer_size', 100)
                else:
                    events_output_dir = getattr(observability_cfg, 'events_output_dir', 'logs/events')
                    buffer_size = getattr(observability_cfg, 'buffer_size', 100)

                self.event_logger = EventLogger(
                    enabled=True,
                    output_dir=events_output_dir,
                    buffer_size=buffer_size
                )

                # Initialize ConsoleReporter for scheduled reports (Phase 4)
                try:
                    from pathlib import Path

                    from multi_coin_grid_pro.observability.console_reporter import ConsoleReporter
                    bot_name = f"{self.config.connector_name}_multi_coin_grid"
                    self._console_reporter = ConsoleReporter(
                        Path(events_output_dir),
                        logger=self.logger(),
                        bot_name=bot_name,
                        config=self.config  # Pass full config for threshold analysis in US-E3.x v2 reports
                    )
                    self.logger().info(f"✅ ConsoleReporter initialized for {bot_name} (interval={self._report_interval_minutes}m)")
                except Exception as e:
                    self.logger().warning(f"ConsoleReporter initialization failed: {e}")

                # Emit config_loaded event with hash
                config_hash = compute_config_hash(config, logger=self.logger())
                self.event_logger.emit_config_loaded(
                    config_hash=config_hash,
                    config_keys={
                        "connector": config.connector_name,
                        "quote_asset": config.quote_asset,
                        "max_simultaneous_coins": getattr(config, 'max_simultaneous_coins', 1),
                        "use_smart_entry_filter": getattr(config, 'use_smart_entry_filter', False),
                        "use_multi_timeframe": getattr(config, 'use_multi_timeframe', False),
                    }
                )

                self.logger().info(f"✅ EventLogger initialized (buffer={buffer_size}, dir={events_output_dir})")
            except Exception as e:
                self.logger().error(f"Failed to initialize EventLogger: {e}")
                self.event_logger = None
        else:
            self.logger().info("ℹ️  Structured events disabled (observability.structured_events_enabled=false)")

        # Phase 1C: Correlation tracking (for observability)
        self._last_smart_entry_trace = None  # Stores last trace for correlation_id propagation

        # PHASE 1 FIX #2 & #3: Drawdown tracking
        max_daily_loss_eur = getattr(config, 'max_daily_loss_eur', None)
        if max_daily_loss_eur:
            max_daily_loss_eur = Decimal(str(max_daily_loss_eur))

        self.drawdown_tracker = DrawdownTracker(
            max_daily_loss_pct=Decimal(str(getattr(config, 'max_daily_loss_pct', 5.0))),
            max_weekly_loss_pct=Decimal(str(getattr(config, 'max_weekly_loss_pct', 10.0))),
            max_monthly_loss_pct=Decimal(str(getattr(config, 'max_monthly_loss_pct', 15.0))),
            max_daily_loss_eur=max_daily_loss_eur,
            quote_asset=config.quote_asset,
            portfolio_value_calculator=self._calculate_portfolio_value
        )

        # Phase 3: Switch Logic Improvements state
        self.last_grid_creation_time: float = 0  # Track when grid was created (Phase 4.4)
        self.last_grid_price: Dict[str, Decimal] = {}  # Track price when grid was created: {coin: price} (Phase 4.4)
        self.switch_costs: Dict[str, float] = {}  # Track calculated switch costs: {coin: cost} (Phase 3.2)

        # Insufficient balance cooldown tracking
        # Track when executor failed due to insufficient balance: {coin: timestamp}
        self.last_insufficient_balance_time: Dict[str, float] = {}
        # 30 minutes cooldown before retry (aligned with switch cooldown)
        self.insufficient_balance_cooldown_seconds: int = 1800

        # Automatic blacklist tracking (prevent loops)
        self.coin_error_count: Dict[str, int] = {}  # Track errors per coin: {coin: error_count}
        self.max_errors_per_coin: int = 5  # Auto-blacklist after 5 errors
        self.auto_blacklisted_coins: set = set()  # Coins automatically blacklisted

        # Trend update scheduling
        self._last_trend_update: float = 0.0  # Track last time we fetched ticker data

        # ===== HYBRID GRID: SmartEntry Filter + Dynamic Grid Sizer =====
        # SmartEntry Filter (ML-lite entry decision system)
        self.smart_entry_filter: Optional[SmartEntryFilter] = None
        if getattr(config, 'use_smart_entry_filter', False):
            smart_config_dict = getattr(config, 'smart_entry_filter', {})
            smart_config = SmartEntryConfig(**smart_config_dict) if smart_config_dict else SmartEntryConfig()
            # Pass market_data_provider and connector_name for order book queries
            self.smart_entry_filter = SmartEntryFilter(
                smart_config,
                exchange=self.market_data_provider,
                connector_name=self.config.connector_name
            )
            self.logger().info("🧠 SmartEntryFilter enabled (with slippage + depth protection)")

        # Dynamic Grid Sizer (ATR-based 3-7 grids)
        self.dynamic_grid_sizer: Optional[DynamicGridSizer] = None
        if getattr(config, 'use_dynamic_grid_sizer', False):
            grid_config_dict = getattr(config, 'dynamic_grid_sizer', {})
            self.dynamic_grid_sizer = DynamicGridSizer(**grid_config_dict) if grid_config_dict else DynamicGridSizer()
            self.logger().info("📊 DynamicGridSizer enabled (3-7 grids based on ATR)")

        # Candle Indicators Calculator (for SmartEntry)
        self.candle_calc = CandleIndicatorsCalculator()

        # Story D1: Adaptive Timeout Calculator
        self.adaptive_timeout = AdaptiveTimeout(
            base_timeout_sec=self.config.no_fill_timeout_sec,
            atr_period=14
        )

        # Story 6 Part 2: Momentum Indicator Service
        self.momentum_service = MomentumIndicatorService(connector_name=config.connector_name)

        # Story 10: Cooldown Persistence (restart-safe parabolic cooldowns)
        self.cooldown_store: Optional[CooldownStore] = None
        self.parabolic_blacklist: Dict[str, float] = {}  # In-memory cache: {symbol: expiry_timestamp}
        self._last_cooldown_cleanup: float = time.time()
        self._cooldown_cleanup_interval: int = 300  # Cleanup expired cooldowns every 5 minutes

        # Initialize CooldownStore if parabolic persistence enabled
        smart_cfg = getattr(config, 'smart_entry_filter', {})
        if smart_cfg.get('parabolic_cooldown_persist', False):
            try:
                self.cooldown_store = CooldownStore("data/cooldowns.db")
                self.logger().info("✅ Story 10: CooldownStore initialized (data/cooldowns.db)")
            except Exception as e:
                self.logger().error(f"❌ Story 10: CooldownStore init failed: {e}")
                self.cooldown_store = None

        # ===== HYBRID GRID BOT V2.0 - New Modular Components =====
        # Telegram Alerter
        telegram_cfg = getattr(config, 'telegram', {})
        self.telegram_alerter = TelegramAlerter(
            bot_token=telegram_cfg.get('bot_token', '') if isinstance(telegram_cfg, dict) else '',
            chat_id=telegram_cfg.get('chat_id', '') if isinstance(telegram_cfg, dict) else '',
            logger=self.logger()
        )

        # Real-time P&L Tracker
        self.pnl_tracker_v2 = RealtimePnLTracker(
            starting_balance=Decimal(str(config.risk_reference_balance)),
            logger=self.logger()
        )

        # Risk Guard v2.0 (Kill Switch)
        self.risk_guard_v2 = RiskGuardV2(
            cfg={
                'max_daily_loss_pct': float(getattr(config, 'max_daily_loss_pct', 3.0)),
                'max_weekly_loss_pct': float(getattr(config, 'max_weekly_loss_pct', 8.0)),
                'max_monthly_loss_pct': float(getattr(config, 'max_monthly_loss_pct', 12.0)),
                'max_daily_loss_eur': float(getattr(config, 'max_daily_loss_eur', 0)) if getattr(config,
                                                                                                 'max_daily_loss_eur', None) else None,  # noqa: E501
                # Convert fractional percentages (0.15 = 15%) to integer form (15) for RiskGuard
                'max_exposure_per_coin_pct': float(getattr(config, 'max_exposure_per_coin_pct', 0.40)) * 100,
                'max_total_exposure_pct': float(getattr(config, 'max_total_exposure_pct', 0.80)) * 100,
            },
            pnl_tracker=self.pnl_tracker_v2,
            alerter=self.telegram_alerter,
            logger=self.logger(),
            event_logger=self.event_logger  # Pass EventLogger for Phase 2 observability
        )

        # SmartEntry Filter v2.0 (with coin profiles)
        self.smart_entry_v2: Optional[SmartEntryFilterV2] = None
        if getattr(config, 'use_smart_entry_filter', False):
            smart_filter_cfg = getattr(config, 'smart_entry_filter', {})
            if smart_filter_cfg:
                base_cfg = SmartEntryBaseConfig(**smart_filter_cfg)
                coin_profiles = getattr(config, 'coin_profiles', {})
                self.smart_entry_v2 = SmartEntryFilterV2(
                    base_cfg,
                    coin_profiles,
                    self.logger(),
                    exchange_connector=self.market_data_provider,
                    event_logger=self.event_logger
                )
                self.logger().info("🧠 SmartEntry v2.0: ENABLED (with coin profiles)")

        # Dynamic Grid Sizer v2.0 (ATR-based)
        self.grid_sizer_v2: Optional[DynamicGridSizerV2] = None
        if getattr(config, 'use_dynamic_grid_sizer', False):
            grid_sizer_cfg = getattr(config, 'dynamic_grid_sizer', {})
            if grid_sizer_cfg:
                self.grid_sizer_v2 = DynamicGridSizerV2(grid_sizer_cfg, self.logger())
                self.logger().info("📊 DynamicGridSizer v2.0: ENABLED (3-7 ATR-based grids)")

        # Coin Selector v2.0 (Dynamic Discovery)
        core_universe = getattr(config, 'core_universe', None)
        manual_pairs = getattr(config, 'manual_trading_pairs', None)
        blacklist = getattr(config, 'blacklist', None)

        self.coin_selector_v2 = CoinSelector(
            cfg={
                'blacklist': list(blacklist) if blacklist else [],
                'core_universe': list(core_universe) if core_universe else [],
                'min_24h_volume_eur': int(getattr(config, 'min_24h_volume_usdt', getattr(config, 'min_24h_volume_eur', 300000))),
                'max_entry_spread_pct': float(getattr(config, 'max_entry_spread_pct', 0.5)),
                'quote_asset': config.quote_asset,
                'use_dynamic_pair_discovery': getattr(config, 'use_dynamic_pair_discovery', True),
                'manual_trading_pairs': list(manual_pairs) if manual_pairs else [],
            },
            logger=self.logger()
        )

        # ===== FEATURE 1.1: MARKET REGIME FILTER =====
        # Store config for lazy initialization (needs trend_calculator which is created later)
        self.market_regime_filter: Optional[MarketRegimeIntegration] = None
        self._market_regime_config: Optional[MarketRegimeConfig] = None
        self._market_regime_enabled: bool = False  # Store enabled flag separately
        regime_dict = getattr(config, 'market_regime', None)
        if regime_dict:
            try:
                # Extract 'enabled' from config dict BEFORE parsing (MarketRegimeConfig doesn't have this field)
                self._market_regime_enabled = regime_dict.get('enabled', False)
                self._market_regime_config = parse_market_regime_config({"market_regime": regime_dict})
                status = "WILL ENABLE" if self._market_regime_enabled else "DISABLED"
                self.logger().info(f"⚪ Feature 1.1: Market Regime config loaded ({status})")
            except Exception as e:
                self.logger().warning(f"⚠️  Feature 1.1 config parse failed: {e}")

        # ===== FEATURE 1.2: TIME-BASED TRADING RULES =====
        self.time_based_filter: Optional[TimeBasedIntegration] = None
        time_dict = getattr(config, 'time_based_rules', None)
        if time_dict:
            try:
                time_config = parse_time_based_config({"time_based_rules": time_dict})
                self.time_based_filter = TimeBasedIntegration(time_config)
                self.logger().info("✅ Feature 1.2: Time-Based Filter initialized")
            except Exception as e:
                self.logger().warning(f"⚠️  Feature 1.2 disabled: {e}")

        # ===== FEATURE 1.2b: LIQUIDITY-AWARE SMART SIZING =====
        self.liquidity_aware_sizer: Optional[LiquidityAwareSizing] = None
        liquidity_dict = getattr(config, 'liquidity_aware_sizing', None)
        if liquidity_dict:
            try:
                self.liquidity_aware_sizer = LiquidityAwareSizing(liquidity_dict, self.logger())
                if liquidity_dict.get('enabled', False):
                    self.logger().info("✅ Feature 1.2b: Liquidity-Aware Sizing initialized")
            except Exception as e:
                self.logger().warning(f"⚠️  Feature 1.2b disabled: {e}")

        # ===== FEATURE 1.3: PERFORMANCE TRACKING =====
        self.performance_tracker: Optional[PerformanceTracker] = None
        self._last_performance_report_time: float = time.time()
        perf_dict = getattr(config, 'performance_tracking', None)
        if perf_dict:
            try:
                perf_config = parse_performance_config({"performance_tracking": perf_dict})
                self.performance_tracker = PerformanceTracker(perf_config)
                self.logger().info("✅ Feature 1.3: Performance Tracker initialized")
            except Exception as e:
                self.logger().warning(f"⚠️  Feature 1.3 disabled: {e}")

        # ===== DECISION TRACE SYSTEM =====
        self.debug_trace_enabled = getattr(config, 'debug_trace_enabled', False)
        self.debug_trace_format = getattr(config, 'debug_trace_format', 'compact')
        self.debug_trace_log_accepted = getattr(config, 'debug_trace_log_accepted', False)
        self.debug_trace_log_rejected = getattr(config, 'debug_trace_log_rejected', True)
        if self.debug_trace_enabled:
            self.logger().info(f"🔍 Decision Trace: ENABLED (format={self.debug_trace_format})")

        # ===== ADAPTIVE REGIME DETECTION (Phase 1: Logging Only) =====
        self.regime_detector = None

        # ===== ORDERBOOK PREFETCH (Phase 1: Shadow Mode) =====
        from collections import deque
        self.prefetch_timestamps: deque = deque(maxlen=100)  # Track prefetch attempts for rate limiting
        self.filter_resolver = None
        regime_detection_cfg = getattr(config, 'adaptive_regime_detection', None)
        if regime_detection_cfg and regime_detection_cfg.get('enabled', False):
            try:
                self.logger().info("🌡️  Loading Adaptive Regime Detection modules...")
                from multi_coin_grid_pro.utils.adaptive_filter_resolver import AdaptiveFilterResolver
                from multi_coin_grid_pro.utils.regime_detector import RegimeDetector

                self.logger().info("   ✅ Modules imported successfully")
                self.regime_detector = RegimeDetector(regime_detection_cfg, self.logger())
                self.logger().info("   ✅ RegimeDetector initialized")

                adaptive_filters_cfg = getattr(config, 'adaptive_filters', {})
                self.filter_resolver = AdaptiveFilterResolver(adaptive_filters_cfg, self.logger())
                self.logger().info("   ✅ AdaptiveFilterResolver initialized")

                logging_only = regime_detection_cfg.get('logging_only', True)
                mode_str = "LOGGING ONLY" if logging_only else "ACTIVE"
                self.logger().info(f"🌡️  Adaptive Regime Detection: ENABLED ({mode_str})")
                self.logger().info(f"   Bull threshold: >={regime_detection_cfg.get('bull_score_min', 5.0)}")
                self.logger().info(f"   Chop range: [{regime_detection_cfg.get('chop_score_min', -3.0)}, {regime_detection_cfg.get('bull_score_min', 5.0)})")
                self.logger().info(f"   Bear threshold: <{regime_detection_cfg.get('bear_score_max', -3.0)}")
            except Exception as e:
                import traceback
                self.logger().error(f"❌ Adaptive Regime Detection failed to initialize: {e}")
                self.logger().error(f"   Full traceback:\n{traceback.format_exc()}")
                self.regime_detector = None
                self.filter_resolver = None

        self.logger().info("=" * 80)
        self.logger().info("🚀 MULTI-COIN GRID CONTROLLER INITIALIZED (v3.3)")
        self.logger().info("=" * 80)
        self.logger().info(f"Exchange: {config.connector_name}")
        self.logger().info(f"Quote Asset: {config.quote_asset}")
        self.logger().info(f"Max Coins: {config.max_coins_to_monitor}")
        self.logger().info(f"Trend Lookback: {config.trend_lookback_minutes} min")
        self.logger().info(f"Min Trend: {config.trend_min_change_pct}%")
        self.logger().info(f"Switch Cooldown: {config.min_switch_interval_seconds / 60:.0f} min")
        self.logger().info(f"Grid Capital: €{config.total_amount_quote}")
        self.logger().info(f"Stop Loss: -{config.stop_loss_pct * 100}%")
        if self.smart_entry_filter:
            self.logger().info("🧠 SmartEntry (legacy): ENABLED")
        if self.smart_entry_v2:
            self.logger().info("🧠 SmartEntry v2.0: ENABLED")
        if self.dynamic_grid_sizer:
            self.logger().info("📊 Dynamic Grids (legacy): ENABLED (3-7)")
        if self.grid_sizer_v2:
            self.logger().info("📊 DynamicGridSizer v2.0: ENABLED")
        self.logger().info("🛡️  RiskGuard v2.0: ENABLED")
        self.logger().info("💰 P&L Tracker v2.0: ENABLED")
        if self.telegram_alerter.enabled:
            self.logger().info("📱 Telegram Alerts: ENABLED")
        if self.market_regime_filter:
            self.logger().info("🌍 Feature 1.1: Market Regime Filter ENABLED")
        if self.time_based_filter:
            self.logger().info("⏰ Feature 1.2: Time-Based Filter ENABLED")
        if self.performance_tracker:
            self.logger().info("📊 Feature 1.3: Performance Tracker ENABLED")
        self.logger().info("=" * 80)

    def stop(self):
        """
        Explicit cleanup on controller shutdown.

        Phase 1C: Flush EventLogger if present to ensure all events are written.
        Call this from strategy stop() or cleanup path.
        """
        try:
            if hasattr(self, 'event_logger') and self.event_logger:
                self.event_logger.close()
                self.logger().info("✅ EventLogger flushed and closed")
        except Exception as e:
            self.logger().error(f"Error closing EventLogger: {e}")

    def _log_decision_trace(self, trace: PairDecisionTrace):
        """
        Log decision trace based on config settings.

        Phase 1C: Also emit structured events if EventLogger is enabled.

        Correlation ID Pattern:
            - Generated per candidate evaluation (e.g., UUID at start of determine_executor_actions)
            - Stored in trace.correlation_id (single source of truth)
            - Passed via trace through all stages (SmartEntry, MTF, Risk, Execution)
            - No global state (_current_correlation_id) - explicit parameter passing only
            - Links all rejection/acceptance events for same trading decision

        Args:
            trace: PairDecisionTrace instance with stage, reason_code, correlation_id populated
        """
        if not trace.enabled:
            return

        # Phase 1C: Emit structured event if configured
        # Fix: Only require trace.stage (success has no reason_code)
        if self.event_logger and trace.stage:
            try:
                if trace.accepted:
                    self.event_logger.emit_gate_passed(
                        correlation_id=trace.correlation_id or "unknown",
                        symbol=trace.trading_pair,
                        stage=trace.stage,
                        metadata={
                            "exchange": trace.exchange,
                            "strategy": trace.strategy,
                            "final_reason": trace.final_reason or "all checks passed"
                        }
                    )
                else:
                    # Denied events MUST have reason_code
                    if trace.reason_code:
                        self.event_logger.emit_gate_denied(
                            correlation_id=trace.correlation_id or "unknown",
                            symbol=trace.trading_pair,
                            stage=trace.stage,
                            reason_code=trace.reason_code,
                            reason_msg=trace.final_reason or "rejected",
                            metadata={
                                "exchange": trace.exchange,
                                "strategy": trace.strategy,
                                "rejected_by": trace.rejected_by
                            }
                        )
                    else:
                        self.logger().warning(f"Denied event missing reason_code: {trace.trading_pair}")
            except Exception as e:
                # Event emission errors should never break trading
                self.logger().error(f"Error emitting structured event: {e}")

        # Original logging behavior
        should_log = (
            (trace.accepted and self.debug_trace_log_accepted)
            or (not trace.accepted and self.debug_trace_log_rejected)
        )

        if not should_log:
            return

        # Choose format based on config
        try:
            if self.debug_trace_format == "detailed":
                self.logger().info(trace.to_detailed_log())
            elif self.debug_trace_format == "json":
                self.logger().info(f"DECISION_TRACE: {trace.to_json()}")
            else:  # compact (default)
                self.logger().info(trace.to_compact_log())
        except Exception as e:
            # Trace errors should never break trading
            self.logger().error(f"Error logging decision trace: {e}")

    def _handle_parabolic_cooldown(self, symbol: str, reason: str):
        """
        Story 10: Handle parabolic detection cooldown persistence

        Args:
            symbol: Trading pair symbol
            reason: Rejection reason containing parabolic trigger info
        """
        try:
            # Get cooldown duration from config
            smart_cfg = getattr(self.config, 'smart_entry_filter', {})
            cooldown_minutes = smart_cfg.get('parabolic_cooldown_minutes', 30)
            cooldown_sec = cooldown_minutes * 60
            shadow_mode = smart_cfg.get('parabolic_detector_shadow_mode', True)

            # Update in-memory cache
            expiry_ts = time.time() + cooldown_sec
            self.parabolic_blacklist[symbol] = expiry_ts

            # Persist to database if enabled (and NOT in shadow mode)
            if self.cooldown_store and not shadow_mode:
                self.cooldown_store.set_cooldown(
                    connector=self.config.connector_name,
                    symbol=symbol,
                    reason="PARABOLIC",
                    cooldown_sec=cooldown_sec
                )
                self.logger().info(
                    f"✅ Story 10: Parabolic cooldown persisted for {symbol} ({cooldown_minutes}min)"
                )
            elif shadow_mode:
                self.logger().info(
                    f"[SHADOW] Story 10: Would persist cooldown for {symbol} ({cooldown_minutes}min)"
                )

        except Exception as e:
            self.logger().error(f"❌ Story 10: Failed to handle cooldown for {symbol}: {e}")

    def _calculate_portfolio_value(self) -> Decimal:
        """
        Calculate total portfolio value in quote asset (EUR/USDT/etc.)

        This includes:
        - Quote asset balance (e.g., EUR)
        - Market value of all held coins

        Used by DrawdownTracker to calculate real drawdown based on
        total portfolio value, not just available quote balance.

        Returns:
            Total portfolio value in quote asset
        """
        try:
            quote_asset = self.config.quote_asset
            total_value = Decimal("0")

            # 1. Get quote asset balance
            quote_balance = self.connector.get_balance(quote_asset)
            total_value += quote_balance

            # 2. Get all non-zero balances and calculate their value
            if hasattr(self.connector, '_account_balances'):
                balances = self.connector._account_balances
                for asset, amount in balances.items():
                    if asset == quote_asset or amount <= Decimal("0.00001"):
                        continue

                    # Skip dust amounts
                    if amount < Decimal("0.0001"):
                        continue

                    # Get trading pair for this asset
                    trading_pair = f"{asset}-{quote_asset}"

                    try:
                        # Get mid price for this pair
                        mid_price = self.connector.get_mid_price(trading_pair)
                        if mid_price and mid_price > Decimal("0"):
                            asset_value = amount * mid_price
                            total_value += asset_value
                    except Exception:
                        # If we can't get price, skip this asset
                        # This can happen for staked assets or unsupported pairs
                        pass

            return total_value

        except Exception as e:
            self.logger().error(f"Error calculating portfolio value: {e}")
            # Fallback to quote balance only
            return self.connector.get_balance(self.config.quote_asset)

    def _get_current_max_slots(self) -> int:
        """
        Task 3.1: Get current max slots based on dynamic slot manager or static config.

        Returns dynamic slots if enabled, otherwise falls back to static max_simultaneous_coins.

        Returns:
            int: Current maximum simultaneous trading slots
        """
        if not self.dynamic_slot_manager.enabled:
            return self.max_simultaneous_coins

        # Get current portfolio value
        try:
            account_balance = self._calculate_portfolio_value()
        except Exception as e:
            self.logger().warning(f"Failed to calculate portfolio value for dynamic slots: {e}, using static fallback")
            return self.max_simultaneous_coins

        # Get current regime
        try:
            if self.market_regime_filter:
                regime_state = self.market_regime_filter.get_market_regime_state()
                current_regime = regime_state.regime if regime_state else "baseline"
            else:
                current_regime = "baseline"
        except Exception as e:
            self.logger().warning(f"Failed to get regime for dynamic slots: {e}, using baseline")
            current_regime = "baseline"

        # Calculate dynamic slots
        dynamic_slots = self.dynamic_slot_manager.get_dynamic_slots(
            account_balance_eur=account_balance,
            current_regime=current_regime,
            static_fallback=self.max_simultaneous_coins
        )

        return dynamic_slots

    async def _handle_api_error(self, error: Exception, operation: str) -> None:
        """
        Phase 1.3: Handle API errors with consecutive counting, exponential backoff,
        and circuit breaker pattern (max retries before permanent failure)

        Args:
            error: The exception that occurred
            operation: Description of the operation that failed
        """
        current_time = time.time()
        self.last_api_error_time = current_time
        self.consecutive_api_errors += 1
        self.total_api_errors += 1

        # Circuit breaker: Check for permanent failure
        if self.total_api_errors >= self.max_total_errors:
            if not self.permanent_api_failure:
                self.permanent_api_failure = True
                self.logger().critical(
                    f"🔴 CIRCUIT BREAKER OPEN - PERMANENT FAILURE!\n"
                    f"   Total API errors: {self.total_api_errors}\n"
                    f"   Bot will stop trading permanently\n"
                    f"   Manual intervention required - check API keys, network, exchange status"
                )
            return

        # Detect specific error types
        error_msg = str(error).lower()
        is_rate_limit = any(term in error_msg for term in ['rate limit', '429', 'too many requests'])
        is_maintenance = any(term in error_msg for term in ['maintenance', '503', 'service unavailable'])
        is_timeout = any(term in error_msg for term in ['timeout', 'timed out', 'connection'])

        # Exponential backoff for rate limits
        if is_rate_limit:
            self.api_error_backoff_seconds = min(
                self.api_error_backoff_seconds * 2,
                self.max_backoff_seconds
            )
            self.logger().warning(
                f"⚠️  Rate limit hit - backing off for {self.api_error_backoff_seconds:.1f}s"
            )

        # Log error details
        error_type = (
            "RATE_LIMIT" if is_rate_limit else
            "MAINTENANCE" if is_maintenance else
            "TIMEOUT" if is_timeout else
            "API_ERROR"
        )

        self.logger().warning(
            f"⚠️  API Error ({error_type}) in {operation}: {error}\n"
            f"   Consecutive errors: {self.consecutive_api_errors}/{self.api_error_threshold}"
        )

        # Check if we should pause
        if self.consecutive_api_errors >= self.api_error_threshold:
            if not self.api_error_paused:
                self.api_error_paused = True
                self.api_error_paused_at = current_time
                self.logger().critical(
                    "🛑 API ERROR THRESHOLD REACHED!\n"
                    f"   {self.consecutive_api_errors} consecutive errors\n"
                    "   Trading PAUSED - Manual resume required\n"
                    f"   Last error: {error_type} in {operation}"
                )

                # Stop active executor if exists
                if self.active_coin and self.active_executor_id and self._is_executor_actually_active():
                    self.logger().critical("🛑 Stopping active executor due to API errors")
                    stop_action = self._create_stop_action()
                    if stop_action:
                        # Note: We can't append to actions here, but we log it
                        self.logger().warning("⚠️  Stop action should be created in determine_executor_actions")

    async def _api_call_with_error_handling(self, func, *args, **kwargs) -> Optional[any]:
        """
        Phase 1.3: Wrapper for API calls with circuit breaker and error handling

        Args:
            func: Async function to call
            *args, **kwargs: Arguments to pass to function

        Returns:
            Result of function call, or None if error occurred or circuit breaker open
        """
        # Circuit breaker: Immediately return if permanently failed
        if self.permanent_api_failure:
            return None

        # Check if we're paused due to API errors
        if self.api_error_paused:
            # Check if enough time has passed to retry (exponential backoff)
            time_since_pause = time.time() - (self.api_error_paused_at or 0)
            if time_since_pause < self.api_error_backoff_seconds:
                return None
            # Try to resume if backoff period passed
            # (For now, manual resume only - can add auto-resume later)

        try:
            # Apply exponential backoff if we have recent errors
            if self.consecutive_api_errors > 0:
                time_since_last_error = time.time() - self.last_api_error_time
                if time_since_last_error < self.api_error_backoff_seconds:
                    await asyncio.sleep(self.api_error_backoff_seconds - time_since_last_error)

            # Make the API call
            result = await func(*args, **kwargs)

            # Success - reset error counters
            if self.consecutive_api_errors > 0:
                self.logger().info(
                    f"✅ API call successful - resetting error counter "
                    f"(was {self.consecutive_api_errors} errors)"
                )
            self.consecutive_api_errors = 0
            self.api_error_backoff_seconds = 1.0  # Reset backoff
            self.last_successful_api_call = time.time()

            return result

        except NotImplementedError as e:
            # Special handling for NotImplementedError (paper trading connector)
            # If this is get_last_traded_prices, try fallback to base connector first, then get_mid_price
            func_name = func.__name__ if hasattr(func, '__name__') else str(func)
            if 'get_last_traded_prices' in func_name:
                trading_pairs = args[0] if args else []
                if isinstance(trading_pairs, list) and len(trading_pairs) > 0:
                    # FIRST: Try base connector (has access to all coins via live exchange)
                    if self.base_connector:
                        try:
                            prices_dict = await self.base_connector.get_last_traded_prices(trading_pairs)
                            if prices_dict:
                                self.logger().debug(
                                    f"✅ Using base connector for price fetching: {
                                        len(prices_dict)} prices")
                                return prices_dict
                        except Exception as base_error:
                            self.logger().debug(f"Base connector price fetch failed: {base_error}")

                    # SECOND: Try get_mid_price from paper connector (only works if order book exists)
                    if self.connector:
                        try:
                            prices_dict = {}
                            for pair in trading_pairs:
                                try:
                                    mid_price = self.connector.get_mid_price(pair)
                                    prices_dict[pair] = float(mid_price) if mid_price else None
                                except Exception:
                                    # Order book doesn't exist for this coin - skip
                                    continue
                            if prices_dict:
                                self.logger().debug(f"✅ Using get_mid_price fallback: {len(prices_dict)} prices")
                                return prices_dict
                        except Exception as fallback_error:
                            self.logger().debug(f"Fallback to get_mid_price failed: {fallback_error}")

            # If fallback didn't work, treat as normal error
            await self._handle_api_error(e, func_name)
            return None

        except Exception as e:
            await self._handle_api_error(e, func.__name__ if hasattr(func, '__name__') else str(func))
            return None

    async def _get_ticker_data_safe(self) -> Dict[str, Any]:
        """
        Safely get ticker data from connector.

        This method attempts to use the connector's ticker data method if available.
        For Kraken specifically, this provides volume and spread data needed for
        coin selection. Falls back to empty dict if method doesn't exist.

        IMPORTANT: This method makes a single API call to get ALL tickers (rate limit: 1 call/second).
        Only call this method when necessary (e.g., during coin discovery at startup).

        Returns:
            Dict of ticker data keyed by exchange symbol, or empty dict if unavailable
        """
        if not self.connector:
            self.logger().warning("⚠️  Connector not initialized, cannot fetch ticker data")
            return {}

        # Rate limiting: Ensure we don't call this too frequently (Kraken: 1 call/second)
        # This method should only be called during coin discovery (once at startup)
        current_time = time.time()
        if hasattr(self, '_last_ticker_call_time'):
            time_since_last_call = current_time - self._last_ticker_call_time
            if time_since_last_call < 1.5:  # Wait at least 1.5 seconds between calls
                wait_time = 1.5 - time_since_last_call
                self.logger().debug(f"⏳ Rate limiting ticker call - waiting {wait_time:.2f}s...")
                await asyncio.sleep(wait_time)

        # Check if connector has the ticker data method (Kraken-specific)
        if hasattr(self.connector, '_get_ticker_data'):
            # Phase 1.3: Use error handling wrapper
            if asyncio.iscoroutinefunction(self.connector._get_ticker_data):
                ticker_data = await self._api_call_with_error_handling(
                    self.connector._get_ticker_data
                )
            else:
                # Sync method - wrap in async
                try:
                    ticker_data = self.connector._get_ticker_data()
                    self.consecutive_api_errors = 0  # Reset on success
                    self.last_successful_api_call = time.time()
                except Exception as e:
                    await self._handle_api_error(e, "_get_ticker_data")
                    ticker_data = None

            # Update last call time
            self._last_ticker_call_time = time.time()

            return ticker_data if ticker_data is not None else {}
        else:
            # Connector doesn't support ticker data - use fallback approach
            self.logger().warning(
                f"⚠️  Connector {type(self.connector).__name__} doesn't support ticker data. "
                "Volume-based selection will be limited."
            )
            return {}

    def _initialize_components(self):
        """Initialize coin discovery and trend calculator"""
        if not self.connector:
            # Get connector from connectors dict
            # Note: connectors dict is passed from the strategy which has access to all exchange connectors
            connectors = getattr(self, 'connectors', {})

            # Enhanced logging for debugging
            self.logger().info(f"🔍 Looking for connector: '{self.config.connector_name}'")
            self.logger().info(f"🔍 Available connectors: {list(connectors.keys()) if connectors else 'NONE'}")
            self.logger().info(f"🔍 Connectors dict type: {type(connectors)}, empty: {not connectors}")

            if not connectors:
                self.logger().error("❌ No connectors available! Make sure connectors are passed to controller.")
                self.logger().error(f"❌ Expected connector name: '{self.config.connector_name}'")
                self.logger().error("❌ To fix this:")
                self.logger().error(f"   1. In Hummingbot CLI, run: connect {self.config.connector_name}")
                self.logger().error("   2. Enter your API keys when prompted")
                self.logger().error("   3. Verify with: list connectors")
                self.logger().error("   4. Then run: start --script futures_grid_bitget.py")
                return

            # Auto-adjust connector name if paper trading is enabled
            paper_trading_config = getattr(self.config, 'paper_trading', False)
            if paper_trading_config and not self.config.connector_name.endswith('_paper_trade'):
                original_connector_name = self.config.connector_name
                self.config.connector_name = f"{original_connector_name}_paper_trade"
                self.logger().info(
                    f"🔧 Paper trading enabled: Auto-adjusting connector name "
                    f"'{original_connector_name}' → '{self.config.connector_name}'"
                )

            self.connector = connectors.get(self.config.connector_name)

            if not self.connector:
                self.logger().error(f"❌ Connector '{self.config.connector_name}' not found in connectors dict!")
                self.logger().error(f"❌ Available connectors: {list(connectors.keys())}")
                self.logger().error(f"❌ Expected connector name: '{self.config.connector_name}'")
                self.logger().error("❌ To fix this:")
                self.logger().error(f"   1. In Hummingbot CLI, run: connect {self.config.connector_name}")
                self.logger().error("   2. Enter your API keys when prompted")
                self.logger().error("   3. Verify with: list connectors")
                self.logger().error("   4. Then run: start --script futures_grid_bitget.py")

            # If paper trading connector exists, also store base connector for price fetching
            if self.connector and self.config.connector_name.endswith('_paper_trade'):
                base_connector_name = self.config.connector_name.replace('_paper_trade', '')
                self.base_connector = connectors.get(base_connector_name)
                if self.base_connector:
                    self.logger().info(f"✅ Base connector '{base_connector_name}' stored for price fetching")

            # CRITICAL: If paper trading connector not found, try to create it manually
            # This is a workaround for Hummingbot not creating paper trading connectors correctly
            if not self.connector and self.config.connector_name.endswith('_paper_trade'):
                base_connector_name = self.config.connector_name.replace('_paper_trade', '')
                paper_trading_config = getattr(self.config, 'paper_trading', False)

                # Try to create paper trading connector manually
                try:
                    from hummingbot.connector.exchange.paper_trade import create_paper_trade_market

                    # Get trading pairs from base connector if available
                    base_connector = connectors.get(base_connector_name)
                    # Store base connector for price fetching (paper trading connector doesn't
                    # have order books for all coins)
                    self.base_connector = base_connector
                    if base_connector:
                        trading_pairs = list(base_connector.trading_pairs)
                    else:
                        # Fallback: use EUR pairs
                        trading_pairs = [f"{coin}-{self.config.quote_asset}" for coin in ["BTC", "ETH", "EUR"]]

                    self.logger().info(
                        f"🔧 Paper trading connector '{self.config.connector_name}' not found in connectors dict. "
                        "Attempting to create it manually..."
                    )

                    # Create paper trading connector
                    paper_connector = create_paper_trade_market(
                        exchange_name=base_connector_name,
                        trading_pairs=trading_pairs
                    )

                    # Set paper trade balances from config
                    # Try to get balances from HummingbotApplication singleton
                    try:
                        from hummingbot.client.hummingbot_application import HummingbotApplication
                        app = HummingbotApplication.main_application()
                        if app and hasattr(app, 'client_config_map'):
                            paper_trade_balance = app.client_config_map.paper_trade.paper_trade_account_balance
                            if paper_trade_balance:
                                for asset, balance in paper_trade_balance.items():
                                    paper_connector.set_balance(asset, float(balance))
                                self.logger().info(
                                    f"✅ Set paper trading balances: {paper_trade_balance}"
                                )
                            else:
                                # Fallback: set EUR balance from config file (150 EUR)
                                paper_connector.set_balance("EUR", 150.0)
                                self.logger().info("✅ Set default paper trading balance: EUR=150.0")
                        else:
                            # Fallback: set EUR balance from config file (150 EUR)
                            paper_connector.set_balance("EUR", 150.0)
                            self.logger().info("✅ Set default paper trading balance: EUR=150.0")
                    except Exception as e:
                        # Fallback: set EUR balance from config file (150 EUR)
                        paper_connector.set_balance("EUR", 150.0)
                        self.logger().warning(f"⚠️  Could not set paper trading balances from config: {e}")
                        self.logger().info("✅ Set default paper trading balance: EUR=150.0")

                    # Add to connectors dict
                    connectors[self.config.connector_name] = paper_connector
                    self.connector = paper_connector
                    # Store base connector for price fetching (paper trading connector doesn't
                    # have order books for all coins)
                    self.base_connector = base_connector

                    self.logger().info(
                        f"✅ Successfully created paper trading connector '{self.config.connector_name}' manually!"
                    )
                    if self.base_connector:
                        self.logger().info(
                            f"✅ Base connector '{base_connector_name}' stored for price fetching"
                        )

                except Exception as e:
                    # Manual creation failed - stop bot if paper trading is enabled
                    self.logger().error("=" * 80)
                    self.logger().error("🚨🚨🚨 CRITICAL SAFETY ERROR 🚨🚨🚨")
                    self.logger().error(
                        f"❌ Paper trading connector '{self.config.connector_name}' not found and could not be created!"
                    )
                    self.logger().error(f"   Error: {e}")
                    self.logger().error("=" * 80)

                    # Check if paper trading is enabled in config
                    if paper_trading_config:
                        # Paper trading is enabled but connector not found - STOP THE BOT
                        self.logger().error(
                            f"🛑 STOPPING BOT: Paper trading is enabled but connector not available!\n"
                            f"   This prevents accidental live trading with real money.\n"
                            f"   Available connectors: {list(connectors.keys())}\n"
                            f"\n"
                            f"   TO FIX:\n"
                            f"   1. In Hummingbot CLI, type: config paper_trade_exchanges\n"
                            f"   2. Add '{base_connector_name}' to the list\n"
                            f"   3. Restart the bot\n"
                            f"\n"
                            f"   DO NOT USE LIVE TRADING WHEN PAPER TRADING IS ENABLED!"
                        )
                        self.logger().error("=" * 80)
                        # Don't set connector - bot will fail safely
                        return
                else:
                    # Paper trading not enabled in config, but connector name suggests it should be
                    # This is a configuration mismatch - warn but allow fallback
                    self.logger().warning(
                        f"⚠️  WARNING: Connector name suggests paper trading but config says paper_trading=False\n"
                        f"   Falling back to '{base_connector_name}' (LIVE TRADING)"
                    )
                    self.connector = connectors.get(base_connector_name)
                    if self.connector:
                        self.config.connector_name = base_connector_name

            if not self.connector:
                available = list(connectors.keys())
                self.logger().error(f"❌ Connector '{self.config.connector_name}' not found! Available: {available}")
                return

        # Initialize coin discovery
        if not self.coin_discovery:
            self.coin_discovery = CoinDiscovery(
                connector=self.connector,
                quote_asset=self.config.quote_asset,
                min_24h_volume=self.config.min_24h_volume_eur,
                max_coins=self.config.max_coins_to_monitor,
                exclude_expensive=self.config.exclude_expensive_coins
            )

        # Initialize trend calculator
        if not self.trend_calculator:
            # Phase 2.5: Pass bot start time for warm-up mode
            bot_start_time = getattr(self, '_bot_start_time', None)
            if bot_start_time is None:
                bot_start_time = self.market_data_provider.time()
                self._bot_start_time = bot_start_time

            self.trend_calculator = TrendCalculator(
                connector=self.connector,
                lookback_minutes=self.config.trend_lookback_minutes,
                bot_start_time=bot_start_time,
                base_connector=self.base_connector  # Pass base connector for price fetching in paper trading
            )

        # Ensure correct lookback_seconds for 60h of historical 5m candles
        if self.trend_calculator and not self._lookback_fix_applied:
            _correct_lookback_hours = 65  # 65 hours to preserve 60h of historical 5m candles
            _correct_lookback_seconds = _correct_lookback_hours * 3600
            self.trend_calculator.lookback_seconds = _correct_lookback_seconds
            self._lookback_fix_applied = True
            self.logger().info(f"Lookback configured: {_correct_lookback_hours}h ({_correct_lookback_seconds}s)")

            # Phase 2.5: Set multi-timeframe lookback periods if configured
            if hasattr(self.config, 'trend_lookback_short_minutes'):
                self.trend_calculator.trend_lookback_short_minutes = self.config.trend_lookback_short_minutes
            if hasattr(self.config, 'trend_lookback_mid_minutes'):
                self.trend_calculator.trend_lookback_mid_minutes = self.config.trend_lookback_mid_minutes
            if hasattr(self.config, 'trend_lookback_long_minutes'):
                self.trend_calculator.trend_lookback_long_minutes = self.config.trend_lookback_long_minutes

            # ===== FEATURE 1.1: LAZY INITIALIZATION (needs trend_calculator) =====
            if self._market_regime_config and not self.market_regime_filter:
                try:
                    # Use stored enabled flag (MarketRegimeConfig dataclass doesn't have 'enabled' field)
                    self.market_regime_filter = MarketRegimeIntegration(
                        trend_calculator=self.trend_calculator,
                        regime_config=self._market_regime_config,
                        enabled=self._market_regime_enabled
                    )
                    if self._market_regime_enabled:
                        self.logger().info("✅ Feature 1.1: Market Regime Filter initialized (ACTIVE)")
                    else:
                        self.logger().info("⚪ Feature 1.1: Market Regime Filter initialized (DISABLED)")
                except Exception as e:
                    self.logger().warning(f"⚠️  Feature 1.1 initialization failed: {e}")

    async def on_start(self):
        """Override to log when control_loop starts"""
        self.logger().info("🚀 Controller.on_start() called - control_loop is starting!")

        # Story 10: Load active cooldowns from database on startup
        if self.cooldown_store:
            try:
                active_cooldowns = self.cooldown_store.load_active()
                self.parabolic_blacklist.update(active_cooldowns)
                if active_cooldowns:
                    self.logger().info(f"✅ Story 10: Loaded {len(active_cooldowns)} active cooldowns from database")
                    for symbol, expiry_ts in active_cooldowns.items():
                        remaining = int(expiry_ts - time.time())
                        self.logger().info(f"   - {symbol}: {remaining}s remaining")
                else:
                    self.logger().info("ℹ️  Story 10: No active cooldowns to restore")
            except Exception as e:
                self.logger().error(f"❌ Story 10: Failed to load cooldowns: {e}")

        await super().on_start()

    async def control_task(self):
        """Override to always update trends and determine actions, even if market_data_provider isn't ready"""
        mdp_ready = self.market_data_provider.ready if self.market_data_provider else False

        # HYBRID GRID v2.0: Check RiskGuard before any trading operations
        if not self.risk_guard_v2.check_limits():
            self.logger().critical("🚨 RiskGuard v2.0: Kill switch activated - trading disabled")
            return  # Stop all trading activity

        # PnL tracker resets (UTC-based)
        now_utc = datetime.utcnow()
        current_day = now_utc.date()
        current_week = now_utc.isocalendar().week
        current_month = (now_utc.year, now_utc.month)

        if self._last_pnl_reset_day != current_day:
            self.pnl_tracker_v2.on_new_day()
            self._last_pnl_reset_day = current_day

        if self._last_pnl_reset_week != current_week:
            self.pnl_tracker_v2.on_new_week()
            self._last_pnl_reset_week = current_week

        if self._last_pnl_reset_month != current_month:
            self.pnl_tracker_v2.on_new_month()
            self._last_pnl_reset_month = current_month

        # Story 10: Periodic cooldown cleanup (every 5 minutes)
        current_time = time.time()
        if self.cooldown_store and (current_time - self._last_cooldown_cleanup) >= self._cooldown_cleanup_interval:
            try:
                deleted = self.cooldown_store.cleanup_expired()
                if deleted > 0:
                    self.logger().debug(f"🧹 Story 10: Cleaned up {deleted} expired cooldowns")
                # Also cleanup in-memory cache
                expired_symbols = [sym for sym, expiry in self.parabolic_blacklist.items() if expiry <= current_time]
                for sym in expired_symbols:
                    del self.parabolic_blacklist[sym]
                self._last_cooldown_cleanup = current_time
            except Exception as e:
                self.logger().error(f"❌ Story 10: Cooldown cleanup failed: {e}")

        # Phase 6: Periodic memory cleanup (every 5 minutes) - PRODUCTION-GRADE MEMORY LEAK FIX
        if (current_time - getattr(self, '_last_memory_cleanup', 0)) >= 300:  # 5 minutes
            try:
                import os

                import psutil

                cleanup_stats = {}
                process = psutil.Process(os.getpid())
                rss_before_mb = process.memory_info().rss / 1024 / 1024

                # Hard caps
                MAX_REALISED_TRACKED = 300
                MAX_TIMEOUT_TRACKED = 200
                MAX_EXECUTOR_TIMES = 500
                MAX_TREND_DATA = 50  # Keep max 50 trends (more than monitored_coins)

                # Get current state (safe iteration with list())
                active_coins_set = set(self.active_coins.keys())
                monitored_set = set(self.monitored_coins) if hasattr(self, 'monitored_coins') else set()
                current_executor_ids = {e.id for e in self.executors_info}
                cooldown_pairs = set(self.session_blacklist.keys()) if hasattr(self, 'session_blacklist') else set()
                important_coins = active_coins_set | monitored_set | cooldown_pairs

                # 1. Clean up price histories (keep only important coins + TTL grace)
                stale_price_histories = [
                    coin for coin in list(self.price_history_for_volatility.keys())
                    if coin not in important_coins
                ]

                for coin in stale_price_histories:
                    del self.price_history_for_volatility[coin]

                if stale_price_histories:
                    cleanup_stats['price_histories'] = len(stale_price_histories)

                # 2. Clean up _executor_creation_times for terminated executors
                if hasattr(self, '_executor_creation_times'):
                    stale_exec_times = [
                        exec_id for exec_id in list(self._executor_creation_times.keys())
                        if exec_id not in current_executor_ids
                    ]

                    for exec_id in stale_exec_times:
                        del self._executor_creation_times[exec_id]
                        if hasattr(self, '_executor_creation_timestamps') and exec_id in self._executor_creation_timestamps:
                            del self._executor_creation_timestamps[exec_id]

                    # Hard cap enforcement (FIFO - oldest first)
                    if len(self._executor_creation_times) > MAX_EXECUTOR_TIMES:
                        excess = len(self._executor_creation_times) - MAX_EXECUTOR_TIMES
                        oldest_ids = list(self._executor_creation_times.keys())[:excess]
                        for exec_id in oldest_ids:
                            del self._executor_creation_times[exec_id]
                            if hasattr(self, '_executor_creation_timestamps') and exec_id in self._executor_creation_timestamps:
                                del self._executor_creation_timestamps[exec_id]
                        stale_exec_times.extend(oldest_ids)

                    if stale_exec_times:
                        cleanup_stats['executor_times'] = len(stale_exec_times)

                # 3. Clean up trend_calculator.trends (keep only monitored + hard cap)
                if hasattr(self, 'trend_calculator') and self.trend_calculator and hasattr(self.trend_calculator, 'trends'):
                    # Remove coins not in monitored set
                    stale_trends = [
                        coin for coin in list(self.trend_calculator.trends.keys())
                        if coin not in monitored_set
                    ]

                    for coin in stale_trends:
                        del self.trend_calculator.trends[coin]

                    # Enforce hard cap even for monitored coins (keep most recent)
                    if len(self.trend_calculator.trends) > MAX_TREND_DATA:
                        excess = len(self.trend_calculator.trends) - MAX_TREND_DATA
                        # Remove oldest (assuming dict insertion order)
                        oldest_trend_coins = list(self.trend_calculator.trends.keys())[:excess]
                        for coin in oldest_trend_coins:
                            del self.trend_calculator.trends[coin]
                        stale_trends.extend(oldest_trend_coins)

                    if stale_trends:
                        cleanup_stats['trend_data'] = len(stale_trends)

                # 4. Clean up _realised_executors_tracked with hard cap
                if len(self._realised_executors_tracked) > MAX_REALISED_TRACKED:
                    stale_tracked = [
                        exec_id for exec_id in list(self._realised_executors_tracked.keys())
                        if exec_id not in current_executor_ids
                    ]
                    # Remove all stale
                    for exec_id in stale_tracked:
                        del self._realised_executors_tracked[exec_id]

                    # If still over cap, remove oldest (FIFO)
                    if len(self._realised_executors_tracked) > MAX_REALISED_TRACKED:
                        excess = len(self._realised_executors_tracked) - MAX_REALISED_TRACKED
                        oldest_ids = list(self._realised_executors_tracked.keys())[:excess]
                        for exec_id in oldest_ids:
                            del self._realised_executors_tracked[exec_id]
                        stale_tracked.extend(oldest_ids)

                    if stale_tracked:
                        cleanup_stats['realised_tracked'] = len(stale_tracked)

                # 5. Clean up _processed_timeout_executors with hard cap
                if len(self._processed_timeout_executors) > MAX_TIMEOUT_TRACKED:
                    stale_timeout = [
                        exec_id for exec_id in list(self._processed_timeout_executors)
                        if exec_id not in current_executor_ids
                    ]
                    for exec_id in stale_timeout:
                        self._processed_timeout_executors.discard(exec_id)

                    # Enforce hard cap (convert to list, remove oldest)
                    if len(self._processed_timeout_executors) > MAX_TIMEOUT_TRACKED:
                        excess = len(self._processed_timeout_executors) - MAX_TIMEOUT_TRACKED
                        oldest_ids = list(self._processed_timeout_executors)[:excess]
                        for exec_id in oldest_ids:
                            self._processed_timeout_executors.discard(exec_id)
                        stale_timeout.extend(oldest_ids)

                    if stale_timeout:
                        cleanup_stats['timeout_executors'] = len(stale_timeout)

                # Measure RSS after cleanup
                rss_after_mb = process.memory_info().rss / 1024 / 1024
                rss_delta = rss_after_mb - rss_before_mb

                # Log only if something was cleaned OR hourly summary
                should_log = bool(cleanup_stats) or (current_time - getattr(self, '_last_memory_cleanup_log', 0)) >= 3600

                if should_log:
                    trend_count = len(self.trend_calculator.trends) if hasattr(self, 'trend_calculator') and self.trend_calculator and hasattr(self.trend_calculator, 'trends') else 0
                    exec_times_count = len(self._executor_creation_times) if hasattr(self, '_executor_creation_times') else 0

                    if cleanup_stats:
                        stats_str = ', '.join(f"{v} {k}" for k, v in cleanup_stats.items())
                        self.logger().info(
                            f"🧹 Memory cleanup: Removed {stats_str} | "
                            f"RSS: {rss_after_mb:.1f}MB ({rss_delta:+.1f}MB) | "
                            f"Tracking: {len(self._realised_executors_tracked)} executors, "
                            f"{len(self.price_history_for_volatility)} prices, "
                            f"{trend_count} trends, {exec_times_count} exec_times"
                        )
                    else:
                        # Hourly summary even if nothing cleaned
                        self.logger().info(
                            f"🧠 Memory status: RSS: {rss_after_mb:.1f}MB | "
                            f"Tracking: {len(self._realised_executors_tracked)} executors, "
                            f"{len(self.price_history_for_volatility)} prices, "
                            f"{trend_count} trends, {exec_times_count} exec_times"
                        )

                    if not hasattr(self, '_last_memory_cleanup_log'):
                        self._last_memory_cleanup_log = 0
                    self._last_memory_cleanup_log = current_time

                self._last_memory_cleanup = current_time
            except Exception as e:
                self.logger().error(f"❌ Memory cleanup failed: {e}")

        # ===== ADAPTIVE REGIME DETECTION (Phase 1: Logging Only) =====
        if hasattr(self, 'regime_detector') and self.regime_detector:
            try:
                # Detect regime periodically (once per control cycle)
                regime_state = await self._detect_current_regime()
                if regime_state:
                    # Story 6 Part 2: Cache regime for momentum guards
                    self._last_detected_regime = regime_state.regime

                    regime_changed = regime_state.regime != self._last_logged_regime
                    if regime_changed:
                        self.logger().info(
                            f"🌡️  REGIME: {regime_state.regime} "
                            f"(score: {regime_state.score:.1f}, "
                            f"confidence: {regime_state.confidence:.2f}, "
                            f"duration: {regime_state.duration_minutes}m)\n"
                            f"   {regime_state.reason}"
                        )
                        self._last_logged_regime = regime_state.regime

                    # Resolve filters based on regime
                    if hasattr(self, 'filter_resolver') and self.filter_resolver:
                        active_filters = self.filter_resolver.resolve_filters(regime_state)
                        if regime_changed:
                            self.logger().info(self.filter_resolver.explain_active_filters())

                        # Apply filters if not in logging-only mode
                        logging_only = True
                        if hasattr(self.config, 'adaptive_regime_detection'):
                            # FIX: adaptive_regime_detection is a dict, not an object
                            regime_cfg = self.config.adaptive_regime_detection
                            if isinstance(regime_cfg, dict):
                                logging_only = regime_cfg.get('logging_only', True)
                            else:
                                logging_only = getattr(regime_cfg, 'logging_only', True)

                        if not logging_only:
                            # Phase 2: Apply adaptive filters to SmartEntry
                            self._apply_adaptive_filters(active_filters)
                            if regime_changed:
                                self.logger().info("✅ Adaptive filters applied to SmartEntry")
            except Exception as e:
                self.logger().error(f"❌ Regime detection error: {e}")

        # ===== FEATURE 1.3: PERIODIC PERFORMANCE REPORTING =====
        if self.performance_tracker:
            current_time = time.time()
            time_since_last_report = current_time - self._last_performance_report_time
            report_interval = self.performance_tracker.config.report_interval_hours * 3600

            if time_since_last_report >= report_interval:
                try:
                    report = self.performance_tracker.generate_report()
                    self.logger().info(
                        f"\n{
                            '='
                            * 80}\n📊 PERFORMANCE REPORT (Feature 1.3)\n{
                            '='
                            * 80}\n{report}\n{
                            '='
                            * 80}")

                    # Check performance thresholds
                    acceptable, issues = self.performance_tracker.is_performance_acceptable()
                    if not acceptable:
                        self.logger().warning(
                            "⚠️  Performance issues detected:\n"
                            + "\n".join(f"   - {issue}" for issue in issues)
                        )

                    self._last_performance_report_time = current_time
                except Exception as e:
                    self.logger().error(f"❌ Feature 1.3: Failed to generate performance report: {e}")

        # ===== PHASE 4 (US-E3): SCHEDULED "WHY NO TRADE?" REPORTING =====
        if self._console_reporter and self._report_interval_minutes > 0:
            current_time = time.time()
            time_since_last_report = current_time - self._last_report_time
            report_interval = self._report_interval_minutes * 60  # Convert to seconds

            if time_since_last_report >= report_interval:
                try:
                    self.logger().info("\n" + "=" * 80)
                    self.logger().info(f"📊 WHY NO TRADE REPORT (every {self._report_interval_minutes}m)")
                    self.logger().info("=" * 80)
                    self._console_reporter.report_summary(hours=1)
                    self._last_report_time = current_time
                except Exception as e:
                    self.logger().error(f"❌ US-E3: Failed to generate scheduled report: {e}")

        # CRITICAL FIX: Always update trends and determine actions, even if mdp_ready is False
        # Market data provider might not be ready if no candle feeds are configured,
        # but we still need to update price data for trend calculation and coin selection
        if not mdp_ready:
            # If market data provider isn't ready, update trends and determine actions anyway
            # This is needed because we don't use candle feeds, we fetch prices directly
            try:
                await self.update_processed_data()
                # Also determine executor actions after updating trends
                executor_actions = self.determine_executor_actions()
                if len(executor_actions) > 0:
                    self.logger().debug(f"Sending actions: {executor_actions}")
                    await self.send_actions(executor_actions)
            except Exception as e:
                self.logger().error(f"❌ Error updating trends/actions (mdp_ready=False): {e}")
                import traceback
                self.logger().error(traceback.format_exc())

        self.logger().info(f"🔍 control_task: mdp_ready={mdp_ready}")
        await super().control_task()

    async def update_processed_data(self):
        """
        Update market data and trends

        This method is called periodically by the controller base.
        """
        self.logger().info("🔄 Controller update started")

        # Initialize components if needed
        if not self.connector:
            self.logger().info("🔧 Initializing connector...")
            self._initialize_components()
            if not self.connector:
                self.logger().error("❌ Failed to initialize connector")
                return
            self.logger().info(f"✅ Connector initialized: {self.config.connector_name}")

        # Debug: Check monitored_coins state BEFORE reset
        # Discover coins ONLY ONCE at startup - keep them persistent for trend tracking
        # Don't reset every cycle! Trend data needs to accumulate over 30 minutes
        if not self.monitored_coins:
            # BUGFIX: Check use_dynamic_pair_discovery FIRST before checking manual_trading_pairs
            use_dynamic = getattr(self.config, 'use_dynamic_pair_discovery', True)
            manual_pairs = getattr(self.config, 'manual_trading_pairs', None)

            if not use_dynamic and manual_pairs and isinstance(manual_pairs, list) and len(manual_pairs) > 0:
                # Use manual trading pairs - validate and set them
                self.logger().info("=" * 80)
                self.logger().info("🎯 Using MANUAL trading pairs from config (use_dynamic_pair_discovery=False)...")
                self.logger().info("=" * 80)

                # Validate manual pairs format and filter blacklist
                validated_pairs = []
                blacklist = set(self.config.blacklist or [])

                for pair in manual_pairs:
                    pair = pair.strip().upper()
                    # Convert / to - (some users might use XRP/EUR format)
                    if "/" in pair:
                        pair = pair.replace("/", "-")
                    # Ensure format is correct (BASE-QUOTE)
                    if "-" not in pair:
                        # Try to add quote asset if missing
                        if not pair.endswith(f"-{self.config.quote_asset}"):
                            pair = f"{pair}-{self.config.quote_asset}"

                    # Check blacklist
                    if pair in blacklist:
                        self.logger().warning(f"⚠️  Skipping blacklisted pair: {pair}")
                        continue

                    validated_pairs.append(pair)

                if not validated_pairs:
                    self.logger().error("❌ No valid manual trading pairs after validation!")
                    return

                self.monitored_coins = validated_pairs
                self.logger().info(f"✅ Using {len(self.monitored_coins)} manual trading pairs:")
                for i, pair in enumerate(self.monitored_coins, 1):
                    self.logger().info(f"   {i}. {pair}")
                self.logger().info("=" * 80)

                # Still populate all_available_pairs for potential future rotation (if enabled)
                # But for now, manual pairs means no rotation
                self.all_available_pairs = self.monitored_coins.copy()

                # PHASE 2.6: Load historical data from Kraken for manual pairs
                # This allows us to calculate accurate 24h trends from minute 1!
                if self.monitored_coins and hasattr(self, 'trend_calculator'):
                    if not self.trend_calculator._historical_data_loaded:
                        self.logger().info("=" * 80)
                        self.logger().info("📥 LOADING HISTORICAL DATA FROM KRAKEN...")
                        self.logger().info("=" * 80)
                        try:
                            await self.trend_calculator.load_historical_data(self.monitored_coins)
                            self.logger().info("=" * 80)
                            self.logger().info("✅ Historical data loaded - ready for accurate 24h trends!")
                            self.logger().info("=" * 80)

                            # DEBUG: Verify loaded data
                            for symbol in self.monitored_coins[:3]:  # First 3 for debugging
                                if symbol in self.trend_calculator.trends:
                                    trend = self.trend_calculator.trends[symbol]
                                    if len(trend.price_history) > 1:
                                        first = float(trend.price_history[0]['price'])
                                        last = float(trend.price_history[-1]['price'])
                                        change = ((last - first) / first) * 100 if first > 0 else 0
                                        self.logger().info(
                                            f"  🔍 DEBUG {symbol}: {len(trend.price_history)} points, "
                                            f"first=€{first:.4f}, last=€{last:.4f}, Δ{change:+.2f}%"
                                        )
                                    else:
                                        self.logger().warning(f"  ⚠️ {symbol}: Only {len(trend.price_history)} points!")
                                else:
                                    self.logger().warning(f"  ⚠️ {symbol}: No trend data!")

                            # CRITICAL: Update with real-time prices RIGHT AFTER loading historical data!
                            self.logger().info("🔄 Adding real-time prices to complete the dataset...")
                            try:
                                # Build orderbook config for early filtering (if enabled)
                                orderbook_config = self._build_orderbook_config()
                                await self.trend_calculator.update_all_trends_v2(
                                    self.monitored_coins,
                                    orderbook_config=orderbook_config
                                )
                                self.logger().info("✅ Real-time prices added - dataset is now complete!")
                            except Exception as update_error:
                                self.logger().warning(f"⚠️  Failed to add real-time prices: {update_error}")

                            # Manually force trend calculation from historical data
                            self.logger().info("=" * 80)
                            self.logger().info("🔧 FORCING MANUAL TREND CALCULATION from historical data")
                            self.logger().info("=" * 80)
                            for symbol in self.monitored_coins:
                                if symbol in self.trend_calculator.trends:
                                    trend = self.trend_calculator.trends[symbol]
                                    if len(trend.price_history) >= 2:
                                        # Manual: compare current price to oldest price for 24h trend
                                        current_price = float(trend.current_price) if trend.current_price else float(
                                            trend.price_history[-1]['price'])
                                        oldest_price = float(trend.price_history[0]['price'])
                                        manual_24h = (
                                            (current_price - oldest_price) / oldest_price * 100) if oldest_price > 0 else 0.0  # noqa: E501

                                        # Calculate 4h and 1h from subset of data
                                        now_ts = time.time()
                                        # 4h trend: last 4 hours of data
                                        prices_4h = [
                                            p for p in trend.price_history if (
                                                now_ts
                                                - p['timestamp']) <= (
                                                4
                                                * 3600)]
                                        if len(prices_4h) >= 2:
                                            manual_4h = (
                                                (float(prices_4h[-1]['price']) - float(prices_4h[0]['price'])) / float(prices_4h[0]['price']) * 100)  # noqa: E501
                                        else:
                                            manual_4h = manual_24h * 0.4

                                        # 1h trend: last 1 hour of data
                                        prices_1h = [
                                            p for p in trend.price_history if (
                                                now_ts - p['timestamp']) <= 3600]
                                        if len(prices_1h) >= 2:
                                            manual_1h = (
                                                (float(prices_1h[-1]['price']) - float(prices_1h[0]['price'])) / float(prices_1h[0]['price']) * 100)  # noqa: E501
                                        else:
                                            manual_1h = manual_24h * 0.2

                                        # FORCE the trend attributes
                                        trend.trend_1440m = manual_24h
                                        trend.trend_240m = manual_4h
                                        trend.trend_60m = manual_1h
                                        trend.trend_score = 0.2 * manual_1h + 0.4 * manual_4h + 0.4 * manual_24h
                                        trend.trend_pct = trend.trend_score
                                        trend.consensus_trend_pct = trend.trend_score

                                        self.logger().info(
                                            f"✅ {symbol}: trends = "
                                            f"1h:{manual_1h:+.2f}%, 4h:{manual_4h:+.2f}%, 24h:{manual_24h:+.2f}%, score:{trend.trend_score:+.2f}% "  # noqa: E501
                                            f"({len(trend.price_history)} pts)"
                                        )
                            self.logger().info("=" * 80)

                            # ===== FEATURE 1.1: INITIALIZE MARKET REGIME FILTER =====
                            if self.market_regime_filter:
                                try:
                                    self.logger().info("🌍 Initializing Market Regime Filter...")
                                    await self.market_regime_filter.initialize()
                                except Exception as regime_error:
                                    self.logger().warning(
                                        f"⚠️  Failed to initialize Market Regime Filter: {regime_error}")

                        except Exception as e:
                            self.logger().error(f"❌ Failed to load historical data: {e}")
                            import traceback
                            self.logger().error(traceback.format_exc())

            else:
                # Auto-discovery mode
                self.logger().info("💫 First run - discovering coins automatically...")
                self.logger().info("DEBUG: INSIDE if not self.monitored_coins block!")
                try:
                    # 🔧 FIX: Don't wait for ALL order books to be ready (connector.ready)
                    # Only check if trading_pair_symbol_map is available (essential for coin discovery)
                    # This fixes the "kraken is not ready" spam (was waiting for 40 order books)
                    if not self.connector.trading_pair_symbol_map_ready():
                        self.logger().warning(
                            f"⏳ Connector {
                                self.config.connector_name} symbol map not ready yet, waiting...")
                        return

                    self.logger().info("=" * 80)
                    self.logger().info("🚀 Discovering coins dynamically from exchange...")
                    self.logger().info("=" * 80)

                    # Get trading pairs DIRECTLY from connector
                    # trading_pair_symbol_map returns bidict: {exchange_symbol: hb_symbol}
                    # e.g. {"XRPEUR": "XRP-EUR"}
                    # Phase 1.3: Use error handling wrapper
                    trading_pair_map = await self._api_call_with_error_handling(
                        self.connector.trading_pair_symbol_map
                    )
                    if trading_pair_map is None:
                        self.logger().error("❌ Failed to get trading pair map - API error")
                        return

                    # Filter for EUR pairs using Hummingbot format (with dash)
                    quote = self.config.quote_asset
                    eur_pairs = [hb_pair for kraken_pair, hb_pair in trading_pair_map.items()
                                 if hb_pair.endswith(f"-{quote}")]

                    self.logger().info(
                        f"📊 Found {
                            len(eur_pairs)} {quote} pairs from {
                            len(trading_pair_map)} total pairs")

                    # Store ALL available pairs for rotation later
                    self.all_available_pairs = eur_pairs

                    # Fetch 24h volumes for all EUR pairs to sort by liquidity
                    self.logger().info("📊 Fetching 24h volumes for all pairs...")

                    # Get ticker data using public API where possible
                    # Note: For Kraken, we need ticker data with volume/spread which isn't available
                    # via public connector API, so we use a helper method that safely accesses it
                    ticker_data = await self._get_ticker_data_safe()

                    # Build volume map: {hb_symbol: volume_24h_in_quote}
                    pair_volumes = {}
                    pair_spreads = {}
                    for kraken_symbol, hb_symbol in trading_pair_map.items():
                        if hb_symbol in eur_pairs and kraken_symbol in ticker_data:
                            ticker = ticker_data[kraken_symbol]
                            # Volume data: ticker["v"] = [volume_today, volume_24h]
                            volume_24h = float(ticker["v"][1]) if "v" in ticker else 0
                            # Get last price to calculate EUR volume
                            last_price = float(ticker["c"][0]) if "c" in ticker else 0
                            volume_eur = volume_24h * last_price
                            pair_volumes[hb_symbol] = volume_eur

                            # Calculate spread
                            try:
                                best_ask = float(ticker["a"][0]) if "a" in ticker and ticker["a"] else None
                                best_bid = float(ticker["b"][0]) if "b" in ticker and ticker["b"] else None
                                if best_bid and best_ask and best_ask > 0:
                                    spread = (best_ask - best_bid) / best_ask
                                    pair_spreads[hb_symbol] = spread
                            except Exception:
                                pass

                    # Store volume and spread data for rotation
                    self.pair_volumes = pair_volumes
                    self.pair_spreads = pair_spreads

                    # Sort pairs by 24h EUR volume (descending)
                    # If no volume data available (empty pair_volumes), use all pairs sorted alphabetically
                    if pair_volumes:
                        sorted_pairs = sorted(pair_volumes.items(), key=lambda x: x[1], reverse=True)
                    else:
                        # No volume data - use all pairs with volume=0
                        sorted_pairs = [(pair, 0) for pair in eur_pairs]
                        self.logger().warning("⚠️  No volume data available - using all pairs")

                    # Take top N by volume that meet minimum threshold and not blacklisted
                    min_volume = getattr(self.config, 'min_24h_volume_usdt', self.config.min_24h_volume_eur) if pair_volumes else 0  # Skip volume filter if no data
                    blacklist = set(getattr(self.config, 'blacklist', []) or [])
                    filtered_pairs = [(pair, vol) for pair, vol in sorted_pairs if vol
                                      >= min_volume and pair not in blacklist]

                    # Spread check: only include coins with spread < 0.5% using ticker bid/ask
                    spread_limit = 0.005  # 0.5%
                    spread_checked_pairs = []

                    # If no ticker data available, skip spread check and use all filtered pairs
                    if not ticker_data:
                        self.logger().info("📊 No ticker data - using all pairs without spread check")
                        for pair, vol in filtered_pairs[:100]:
                            spread_checked_pairs.append((pair, vol, 0.0))  # spread=0 indicates no data
                    else:
                        for pair, vol in filtered_pairs[:100]:
                            # Find kraken_symbol for this pair
                            kraken_symbol = None
                            for k, v in trading_pair_map.items():
                                if v == pair:
                                    kraken_symbol = k
                                    break
                            if kraken_symbol and kraken_symbol in ticker_data:
                                ticker = ticker_data[kraken_symbol]
                                # Kraken ticker: 'a' = ask [price, whole lot volume, lot volume], 'b' = bid [...]
                                try:
                                    best_ask = float(ticker["a"][0]) if "a" in ticker and ticker["a"] else None
                                    best_bid = float(ticker["b"][0]) if "b" in ticker and ticker["b"] else None
                                    if best_bid and best_ask and best_ask > 0:
                                        spread = (best_ask - best_bid) / best_ask
                                        if spread <= spread_limit:
                                            spread_checked_pairs.append((pair, vol, spread))
                                except Exception as e:
                                    self.logger().warning(f"Spread calc failed for {pair}: {e}")

                    # Sort by volume again, just in case
                    spread_checked_pairs.sort(key=lambda x: x[1], reverse=True)  # Sort by volume descending

                    # Log ALL selected coins with full details
                    max_coins = self.config.max_coins_to_monitor
                    self.logger().info("=" * 80)
                    self.logger().info(f"📊 COIN DISCOVERY - VOLLEDIGE LIJST VAN {max_coins} COINS")
                    self.logger().info("=" * 80)
                    for i, (pair, vol, spread) in enumerate(spread_checked_pairs[:max_coins], 1):
                        self.logger().info(
                            f"  {i:2}. {pair:15} | Volume: €{vol:>12,.0f} | Spread: {spread * 100:>5.3f}%"
                        )
                    self.logger().info("=" * 80)
                    self.monitored_coins = [pair for pair, vol, spread in spread_checked_pairs[:max_coins]]

                    self.logger().info(
                        f"✅ All {len(self.monitored_coins)} selected coins by 24h volume and spread < 0.5%:")
                    for i, (pair, vol, spread) in enumerate(spread_checked_pairs[:max_coins], 1):
                        self.logger().info(f"   {i}. {pair}: €{vol:,.0f} (spread: {spread:.3%})")

                    self.logger().info(
                        f"🎯 Selected {len(self.monitored_coins)} pairs (min €{min_volume:,} volume, spread < 0.5%, not blacklisted)")  # noqa: E501
                    self.logger().info(f"💡 Pool size: {len(self.all_available_pairs)} pairs available for rotation")

                    if not self.monitored_coins:
                        self.logger().error("❌ No coins discovered!")
                        return

                    self.logger().info("=" * 80)
                    self.logger().info(f"✅ Discovery complete: Monitoring {len(self.monitored_coins)} coins")
                    self.logger().info(f"✅ Top 20: {', '.join(self.monitored_coins[:20])}")
                    self.logger().info("=" * 80)

                    # Mark initial discovery timestamp for periodic refresh
                    self._last_coin_discovery = time.time()

                except Exception as e:
                    self.logger().error(f"❌ EXCEPTION during DIRECT discovery: {e}")
                    import traceback
                    self.logger().error(traceback.format_exc())
                    # Use fallback list on error (use - format, not / format)
                    self.monitored_coins = [
                        f"XRP-{self.config.quote_asset}",
                        f"ADA-{self.config.quote_asset}",
                        f"DOT-{self.config.quote_asset}",
                        f"SOL-{self.config.quote_asset}",
                        f"LINK-{self.config.quote_asset}",
                    ]
                    self.logger().warning(f"⚠️  Using emergency fallback: {self.monitored_coins}")

                # PHASE 2.6: Load historical data from Kraken after coin discovery
                # This allows us to calculate accurate 24h trends from minute 1!
                # CRITICAL FIX: Move OUTSIDE except block so it runs after SUCCESSFUL discovery too!
                if self.monitored_coins and hasattr(self, 'trend_calculator'):
                    if not self.trend_calculator._historical_data_loaded:
                        self.logger().info("=" * 80)
                        self.logger().info("📥 LOADING HISTORICAL DATA FROM KRAKEN...")
                        self.logger().info("=" * 80)
                        try:
                            await self.trend_calculator.load_historical_data(self.monitored_coins)
                            self.logger().info("=" * 80)
                            self.logger().info("✅ Historical data loaded - ready for accurate 24h trends!")
                            self.logger().info("=" * 80)

                            # DEBUG: Verify loaded data
                            for symbol in self.monitored_coins[:3]:  # First 3 for debugging
                                if symbol in self.trend_calculator.trends:
                                    trend = self.trend_calculator.trends[symbol]
                                    if len(trend.price_history) > 1:
                                        first = float(trend.price_history[0]['price'])
                                        last = float(trend.price_history[-1]['price'])
                                        change = ((last - first) / first) * 100 if first > 0 else 0
                                        self.logger().info(
                                            f"  🔍 DEBUG {symbol}: {len(trend.price_history)} points, "
                                            f"first=€{first:.4f}, last=€{last:.4f}, Δ{change:+.2f}%"
                                        )
                                    else:
                                        self.logger().warning(f"  ⚠️ {symbol}: Only {len(trend.price_history)} points!")
                                else:
                                    self.logger().warning(f"  ⚠️ {symbol}: No trend data!")

                            # CRITICAL: Update with real-time prices RIGHT AFTER loading historical data!
                            # This ensures we have data points up to NOW, not just up to 20 seconds ago
                            self.logger().info("🔄 Adding real-time prices to complete the dataset...")
                            try:
                                # Build orderbook config for early filtering (if enabled)
                                orderbook_config = self._build_orderbook_config()
                                await self.trend_calculator.update_all_trends_v2(
                                    self.monitored_coins,
                                    orderbook_config=orderbook_config
                                )
                                self.logger().info("✅ Real-time prices added - dataset is now complete!")
                            except Exception as update_error:
                                self.logger().warning(f"⚠️  Failed to add real-time prices: {update_error}")

                            # Manually force trend calculation (bypass cached update_all_trends_v2)
                            # Historical data has trends, but update_all_trends_v2 uses old cached code → 0%
                            self.logger().info("=" * 80)
                            self.logger().info("🔧 FORCING MANUAL TREND CALCULATION from historical data")
                            self.logger().info("=" * 80)
                            for symbol in self.monitored_coins:  # ALL monitored coins (was [:10] - BUG!)
                                if symbol in self.trend_calculator.trends:
                                    trend = self.trend_calculator.trends[symbol]
                                    if len(trend.price_history) >= 2:
                                        # Manual: compare current price to oldest price for 24h trend
                                        current_price = float(trend.current_price) if trend.current_price else float(
                                            trend.price_history[-1]['price'])
                                        oldest_price = float(trend.price_history[0]['price'])
                                        manual_24h = (
                                            (current_price - oldest_price) / oldest_price * 100) if oldest_price > 0 else 0.0  # noqa: E501

                                        # Calculate 4h and 1h from subset of data
                                        now_ts = time.time()
                                        # 4h trend: last 4 hours of data
                                        prices_4h = [
                                            p for p in trend.price_history if (
                                                now_ts
                                                - p['timestamp']) <= (
                                                4
                                                * 3600)]
                                        if len(prices_4h) >= 2:
                                            manual_4h = (
                                                (float(prices_4h[-1]['price']) - float(prices_4h[0]['price'])) / float(prices_4h[0]['price']) * 100)  # noqa: E501
                                        else:
                                            manual_4h = manual_24h * 0.4

                                        # 1h trend: last 1 hour of data
                                        prices_1h = [
                                            p for p in trend.price_history if (
                                                now_ts - p['timestamp']) <= 3600]
                                        if len(prices_1h) >= 2:
                                            manual_1h = (
                                                (float(prices_1h[-1]['price']) - float(prices_1h[0]['price'])) / float(prices_1h[0]['price']) * 100)  # noqa: E501
                                        else:
                                            manual_1h = manual_24h * 0.2

                                        # FORCE the trend attributes
                                        trend.trend_1440m = manual_24h
                                        trend.trend_240m = manual_4h
                                        trend.trend_60m = manual_1h
                                        trend.trend_score = 0.2 * manual_1h + 0.4 * manual_4h + 0.4 * manual_24h
                                        trend.trend_pct = trend.trend_score
                                        trend.consensus_trend_pct = trend.trend_score
                                        # Note: has_sufficient_data is a computed property, no need to set it

                                        self.logger().info(
                                            f"✅ {symbol}: trends = "
                                            f"1h:{manual_1h:+.2f}%, 4h:{manual_4h:+.2f}%, 24h:{manual_24h:+.2f}%, score:{trend.trend_score:+.2f}% "  # noqa: E501
                                            f"({len(trend.price_history)} pts)"
                                        )
                            self.logger().info("=" * 80)

                            # ===== FEATURE 1.1: INITIALIZE MARKET REGIME FILTER =====
                            if self.market_regime_filter:
                                try:
                                    self.logger().info("🌍 Initializing Market Regime Filter...")
                                    await self.market_regime_filter.initialize()
                                except Exception as regime_error:
                                    self.logger().warning(
                                        f"⚠️  Failed to initialize Market Regime Filter: {regime_error}")

                        except Exception as e:
                            self.logger().error(f"❌ Failed to load historical data: {e}")
                            import traceback
                            self.logger().error(traceback.format_exc())
                            self.logger().warning("⚠️  Continuing with warm-up mode...")

        # Rotate underperforming coins if we have a pool to rotate from
        # BUT: Skip rotation if manual trading pairs are configured (user wants specific coins)
        manual_pairs = getattr(self.config, 'manual_trading_pairs', None)
        if not manual_pairs or len(manual_pairs) == 0:
            # Only rotate in auto-discovery mode
            if len(self.all_available_pairs) > len(self.monitored_coins):
                self._rotate_underperforming_coins()
        else:
            self.logger().debug("⏭️  Skipping coin rotation (manual trading pairs mode)")

        # PERIODIC COIN DISCOVERY: Refresh the coin pool if interval has passed
        if self.coin_discovery_refresh_interval > 0:  # 0 = disabled
            time_since_last_discovery = time.time() - self._last_coin_discovery
            if time_since_last_discovery >= self.coin_discovery_refresh_interval:
                self.logger().info("=" * 80)
                self.logger().info(f"🔄 PERIODIC COIN DISCOVERY: Refreshing pool after {time_since_last_discovery / 60:.0f} min")
                self.logger().info("=" * 80)
                try:
                    await self._refresh_coin_pool()
                    self._last_coin_discovery = time.time()
                    self.logger().info("✅ Coin pool refreshed successfully")
                except Exception as e:
                    self.logger().error(f"❌ Error refreshing coin pool: {e}")
                    import traceback
                    self.logger().error(traceback.format_exc())

        # Update trends for all monitored coins (respect configured refresh interval)
        min_update_interval = max(1.0, float(getattr(self.config, "price_update_interval", 30)))
        time_since_last_update = time.time() - getattr(self, "_last_trend_update", 0.0)

        if time_since_last_update < min_update_interval:
            self.logger().debug(
                f"⏳ Skipping trend update ({time_since_last_update:.1f}s since last fetch, "
                f"min interval {min_update_interval:.1f}s)"
            )
        else:
            self.logger().info(
                f"📊 Updating trends for {len(self.monitored_coins)} coins "
                f"(last refresh {time_since_last_update:.1f}s ago)"
            )
            try:
                # Build orderbook config for early filtering (if enabled)
                orderbook_config = self._build_orderbook_config()
                await self.trend_calculator.update_all_trends_v2(
                    self.monitored_coins,
                    orderbook_config=orderbook_config
                )
                self._last_trend_update = time.time()
            except Exception as e:
                self.logger().error(f"❌ Error updating trends: {e}")
                import traceback
                self.logger().error(traceback.format_exc())
                # Don't update _last_trend_update on error, so we retry sooner
                # This ensures we don't skip updates when API is having issues

    async def _refresh_coin_pool(self):
        """
        Refresh the coin pool by rescanning ALL available pairs from the exchange.
        This updates self.all_available_pairs, self.pair_volumes, and self.pair_spreads.
        Called periodically based on coin_discovery_refresh_interval_seconds.
        """
        try:
            # Phase 1.3: Use error handling wrapper
            trading_pair_map = await self._api_call_with_error_handling(
                self.connector.trading_pair_symbol_map
            )
            if trading_pair_map is None:
                self.logger().error("❌ Failed to get trading pair map during refresh")
                return

            # Filter for quote pairs
            quote = self.config.quote_asset
            quote_pairs = [hb_pair for kraken_pair, hb_pair in trading_pair_map.items()
                           if hb_pair.endswith(f"-{quote}")]

            old_pool_size = len(self.all_available_pairs)
            self.all_available_pairs = quote_pairs

            # Fetch fresh ticker data
            ticker_data = await self._get_ticker_data_safe()

            # Build volume and spread maps
            pair_volumes = {}
            pair_spreads = {}
            for exchange_symbol, hb_symbol in trading_pair_map.items():
                if hb_symbol in quote_pairs and exchange_symbol in ticker_data:
                    ticker = ticker_data[exchange_symbol]
                    # Volume data
                    volume_24h = float(ticker["v"][1]) if "v" in ticker else 0
                    last_price = float(ticker["c"][0]) if "c" in ticker else 0
                    volume_quote = volume_24h * last_price
                    pair_volumes[hb_symbol] = volume_quote

                    # Spread data
                    try:
                        best_ask = float(ticker["a"][0]) if "a" in ticker and ticker["a"] else None
                        best_bid = float(ticker["b"][0]) if "b" in ticker and ticker["b"] else None
                        if best_bid and best_ask and best_ask > 0:
                            spread = (best_ask - best_bid) / best_ask
                            pair_spreads[hb_symbol] = spread
                    except Exception:
                        pass

            # Update stored data
            self.pair_volumes = pair_volumes
            self.pair_spreads = pair_spreads

            # Log changes
            new_pairs = set(quote_pairs) - set([p for p in self.all_available_pairs if p in quote_pairs[:old_pool_size]])
            if new_pairs:
                self.logger().info(f"🆕 Found {len(new_pairs)} NEW pairs since last scan: {sorted(new_pairs)[:10]}...")

            self.logger().info(
                f"✅ Pool refreshed: {len(self.all_available_pairs)} total pairs, "
                f"{len(pair_volumes)} with volume data"
            )

        except Exception as e:
            self.logger().error(f"❌ Error refreshing coin pool: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

    def _rotate_underperforming_coins(self):
        """
        Replace coins that haven't had trades in X updates with new coins from the pool.
        Uses volume-based selection and respects blacklist.
        """
        # Track updates for each coin (increment counter)
        for coin in self.monitored_coins:
            if coin not in self.coin_performance:
                self.coin_performance[coin] = 0
            self.coin_performance[coin] += 1

        # Find coins to replace (no trades for rotation_threshold updates)
        coins_to_replace = [
            coin for coin in self.monitored_coins
            if self.coin_performance.get(coin, 0) >= self.rotation_threshold
        ]

        if not coins_to_replace:
            return

        # Get blacklist
        blacklist = set(getattr(self.config, 'blacklist', []) or [])
        min_volume = float(getattr(self.config, 'min_24h_volume_usdt', self.config.min_24h_volume_eur))
        spread_limit = 0.005  # 0.5%

        # Find new coins not yet monitored, sorted by volume (highest first)
        # Filter by: not monitored, not blacklisted (config + runtime), meets volume threshold, meets spread threshold
        candidate_pairs = []
        for pair in self.all_available_pairs:
            if pair in self.monitored_coins:
                continue  # Already monitored
            if pair in blacklist:
                continue  # Blacklisted in config
            if pair in self.auto_blacklisted_coins:
                continue  # Auto-blacklisted at runtime (NL-restrictions, error loops, etc.)
            if pair not in self.pair_volumes:
                continue  # No volume data
            if self.pair_volumes[pair] < min_volume:
                continue  # Below volume threshold
            if pair in self.pair_spreads and self.pair_spreads[pair] > spread_limit:
                continue  # Spread too high

            candidate_pairs.append((pair, self.pair_volumes[pair]))

        # Sort by volume (descending) - highest volume first
        candidate_pairs.sort(key=lambda x: x[1], reverse=True)

        if not candidate_pairs:
            self.logger().info("💡 No suitable replacement coins found (all blacklisted or below volume threshold)")
            # Reset counters for coins that can't be replaced
            for coin in coins_to_replace:
                self.coin_performance[coin] = 0
            return

        # Replace underperforming coins with top volume candidates
        replacements = []
        num_replacements = min(len(coins_to_replace), len(candidate_pairs))

        for i in range(num_replacements):
            old_coin = coins_to_replace[i]
            new_coin, new_volume = candidate_pairs[i]

            # Replace in list
            idx = self.monitored_coins.index(old_coin)
            self.monitored_coins[idx] = new_coin

            # Reset performance counters
            self.coin_performance[new_coin] = 0
            del self.coin_performance[old_coin]

            replacements.append((old_coin, new_coin, new_volume))

        if replacements:
            self.logger().info(f"🔄 Rotated {len(replacements)} underperforming coins (volume-based selection):")
            for old, new, vol in replacements:
                self.logger().info(f"   {old} → {new} (€{vol:,.0f} volume)")

    def determine_executor_actions(self) -> List[ExecutorAction]:
        """
        Main decision logic

        Determines whether to:
        - Create a new grid on the best coin
        - Switch to a different coin
        - Stop trading (no coin meets criteria)

        Returns:
            List of executor actions (create/stop)
        """
        actions = []
        self._sync_risk_state()

        # ===== FEATURE 1.2: TIME-BASED FILTER CHECK =====
        if self.time_based_filter:
            time_decision = self.time_based_filter.check_trading_permission()
            if not time_decision.can_enter_trades():
                self.logger().info(f"⏸️  Feature 1.2: {time_decision.reason}")
                # Allow exits but block new entries
                if not (self.active_coin and self.active_executor_id):
                    return actions
                # Continue to allow monitoring of active positions

        now_ts = self.market_data_provider.time()
        risk_block_new_entries = False
        daily_loss_pct = self.risk_manager.daily_loss_pct
        if daily_loss_pct >= self.config.risk_limits.max_daily_loss_pct:
            risk_block_new_entries = True
            self.logger().critical(
                f"🛑 Daily loss limit reached ({daily_loss_pct:.2f}% ≥ "
                f"{self.config.risk_limits.max_daily_loss_pct}%) - blocking new entries"
            )
        switch_remaining = self.risk_manager.switch_cooldown_remaining(now_ts)
        if switch_remaining > 0 and not self.active_coin:
            risk_block_new_entries = True
            self.logger().info(
                f"⏳ Global switch cooldown active - {switch_remaining / 60:.1f} min remaining"
            )
        self._risk_block_new_entries = risk_block_new_entries

        # Check if we have data
        if not self.trend_calculator or not self.monitored_coins:
            self.logger().debug("⚠️  No trend data available yet")
            return actions

        # Phase 1.2: Check circuit breaker - if active, pause trading
        if self.circuit_breaker_active:
            if self.active_coin and self.active_executor_id:
                # Cancel all orders and stop executor
                if self._is_executor_actually_active():
                    self.logger().critical(
                        f"🛑 CIRCUIT BREAKER ACTIVE - Stopping executor for {self.active_coin}"
                    )
                    stop_action = self._create_stop_action()
                    if stop_action:
                        actions.append(stop_action)
            # Don't create new executors while circuit breaker is active
            self.logger().warning("🛑 Circuit breaker active - trading paused")
            return actions

        # Phase 1.3: Check API error pause - if active, pause trading
        if self.api_error_paused:
            if self.active_coin and self.active_executor_id:
                # Stop executor if exists
                if self._is_executor_actually_active():
                    self.logger().critical(
                        f"🛑 API ERROR PAUSE ACTIVE - Stopping executor for {self.active_coin}"
                    )
                    stop_action = self._create_stop_action()
                    if stop_action:
                        actions.append(stop_action)
            # Don't create new executors while API errors are paused
            time_since_pause = self.market_data_provider.time() - (self.api_error_paused_at or 0)
            self.logger().warning(
                f"🛑 API errors paused - trading paused "
                f"({time_since_pause / 60:.1f} min since pause, "
                f"{self.consecutive_api_errors} consecutive errors)"
            )
            return actions

        # Phase 1.1 & 1.2: Monitor stop-loss and volatility for active executor
        if self.active_coin and self.active_executor_id and self._is_executor_actually_active():
            self._monitor_stop_loss_and_volatility()

        # Find best coin
        self.logger().info("🔎 Analyzing coins for best trading opportunity...")
        self.logger().info(f"🎯 Looking for trend >= {self.config.trend_min_change_pct}%")
        self.logger().info(f"🔧 DEBUG: trend_calculator exists = {self.trend_calculator is not None}")
        self.logger().info(
            f"🔧 DEBUG: trend_calculator.trends has {len(self.trend_calculator.trends) if self.trend_calculator else 0} coins")  # noqa: E501

        # ===== FEATURE 1.1: MARKET REGIME FILTER CHECK =====
        if self.market_regime_filter and self.market_regime_filter.enabled:
            regime_state = self.market_regime_filter.get_market_regime_state()
            if regime_state and not regime_state.is_favorable:
                self.logger().info(f"🌍 Feature 1.1: {regime_state.reason}")
                # Block new entries but allow exits
                if not (self.active_coin and self.active_executor_id):
                    return actions
                # Continue to monitor active positions but don't create new ones

        # Filter out coins that are in cooldown due to insufficient balance
        coins_in_cooldown = []
        current_time = self.market_data_provider.time()
        for coin, failure_time in list(self.last_insufficient_balance_time.items()):
            time_since_failure = current_time - failure_time
            if time_since_failure < self.insufficient_balance_cooldown_seconds:
                coins_in_cooldown.append(coin)
                remaining_cooldown = self.insufficient_balance_cooldown_seconds - time_since_failure
                self.logger().debug(
                    f"⏳ {coin} in cooldown: {remaining_cooldown / 60:.1f} min remaining"
                )
            else:
                # Cooldown expired - remove from tracking
                del self.last_insufficient_balance_time[coin]
                self.logger().info(f"✅ Cooldown expired for {coin} - can retry")

        # CRITICAL: Check if active coin is in blacklist - force stop if so
        config_blacklist = set(getattr(self.config, 'blacklist', []) or [])
        if self.active_coin and self.active_coin in config_blacklist:
            self.logger().critical(
                f"🚨 BLACKLIST VIOLATION: Active coin {self.active_coin} is in blacklist! "
                f"Force stopping executor immediately."
            )
            if self.active_executor_id and self._is_executor_actually_active():
                try:
                    stop_action = self._create_stop_action()
                    if stop_action:
                        actions.append(stop_action)
                        return actions
                except Exception as e:
                    self.logger().error(f"❌ Error creating stop action for blacklisted coin: {e}")

        try:
            # Phase 2.5: Check if multi-timeframe is enabled
            use_multi_timeframe = getattr(self.config, 'use_multi_timeframe', True)

            # Get config blacklist
            config_blacklist = set(getattr(self.config, 'blacklist', []) or [])

            # ==============================================================================
            # STORY A2: PURGE EXPIRED BLACKLIST & ADD TO EXCLUSIONS
            # ==============================================================================
            # First, purge any expired blacklist entries
            self._purge_expired_blacklist(current_time)

            # Add currently blacklisted coins to exclusions
            blacklisted_coins = set(self.session_blacklist.keys())

            # Log blacklisted coins if any (max once per coin per cycle)
            if blacklisted_coins:
                for coin in blacklisted_coins:
                    blacklist_info = self._get_blacklist_info(coin, current_time)
                    if blacklist_info:
                        self.logger().debug(f"🚫 BLACKLIST_SKIP | Story A2: {coin} ({blacklist_info})")

            # Exit cooldown enforced by risk manager
            exit_cooldown_map = self.risk_manager.coins_in_exit_cooldown(current_time)
            if exit_cooldown_map:
                for coin, remaining_seconds in exit_cooldown_map.items():
                    self.logger().debug(
                        f"⏳ {coin} exit cooldown: {remaining_seconds / 60:.1f} min remaining"
                    )

            # Combine cooldown coins, auto-blacklisted coins, config blacklist, and Story A2 blacklist
            excluded_coins = (
                set(coins_in_cooldown)
                | self.auto_blacklisted_coins
                | config_blacklist
                | set(exit_cooldown_map.keys())
                | blacklisted_coins  # Story A2: Add session blacklist
            )
            if excluded_coins:
                self.logger().debug(f"🚫 Excluding coins: {excluded_coins}")
                if config_blacklist:
                    self.logger().debug(f"   Config blacklist: {config_blacklist}")
                if self.auto_blacklisted_coins:
                    self.logger().debug(f"   Auto-blacklisted: {self.auto_blacklisted_coins}")
                if coins_in_cooldown:
                    self.logger().debug(f"   In cooldown: {coins_in_cooldown}")
                if blacklisted_coins:
                    self.logger().debug(f"   Story A2 session blacklist: {blacklisted_coins}")

            # MULTI-COIN: Get top N coins (where N = available slots)
            # Task 3.1: Calculate dynamic slots if enabled
            max_slots = self._get_current_max_slots()

            # Calculate how many slots are available
            available_slots = max_slots - len(self.active_coins)

            # Add currently active coins to exclusion list (avoid selecting coins we're already trading)
            excluded_coins_with_active = excluded_coins | set(self.active_coins.keys())

            if available_slots <= 0:
                # ENHANCED: Get top candidate BEFORE rejecting, so we can see what we missed
                orderbook_config = self._build_orderbook_config()

                # Get top 3 candidates even though we have no slots (for observability)
                missed_candidates = self.trend_calculator.get_top_n_coins(
                    n=3,
                    min_trend_pct=float(self.config.trend_min_change_pct),
                    exclude_coins=list(excluded_coins_with_active) if excluded_coins_with_active else None,
                    orderbook_config=orderbook_config,
                )

                self.logger().info(
                    f"📊 Multi-coin mode: All {max_slots} slots filled "
                    f"({list(self.active_coins.keys())}) - no room for new coins"
                )

                if missed_candidates:
                    self.logger().info(f"   📉 Missed opportunities: {missed_candidates}")

                # Phase 3: Emit SLOT_FULL event for observability
                # This helps identify capacity constraints in production
                correlation_id = str(uuid.uuid4())

                # Use first missed candidate as symbol (if any), otherwise N/A
                missed_symbol = missed_candidates[0] if missed_candidates else "N/A"

                self._emit_execution_denial(
                    symbol=missed_symbol,
                    reason_code=ReasonCode.SLOT_FULL,
                    reason_msg=f"All {max_slots} slots filled",
                    correlation_id=correlation_id,
                    metadata={
                        "max_slots": max_slots,
                        "active_coins": list(self.active_coins.keys()),
                        "missed_candidates": missed_candidates[:3],  # Top 3 missed opportunities
                        "timestamp": self.market_data_provider.time()
                    }
                )

                top_coins = []  # No slots available
            else:

                # NEW: Clean up expired session blacklist entries en add to exclusion
                current_time = self.market_data_provider.time()
                blacklist_duration = getattr(self.config, 'session_blacklist_duration_seconds', 7200)  # Default 2 uur
                expired_coins = []

                for coin, blacklisted_at in list(self.session_blacklist.items()):
                    time_in_blacklist = current_time - blacklisted_at
                    if time_in_blacklist >= blacklist_duration:
                        expired_coins.append(coin)

                # Remove expired entries
                for coin in expired_coins:
                    del self.session_blacklist[coin]
                    self.logger().info(
                        f"✅ {coin} verwijderd uit session blacklist (timeout na "
                        f"{blacklist_duration / 3600:.1f} uur) - mag weer geprobeerd worden"
                    )

                # Add remaining blacklisted coins to exclusion
                if self.session_blacklist:
                    excluded_coins_with_active = excluded_coins_with_active | set(self.session_blacklist.keys())
                    remaining_times = []
                    for coin, blacklisted_at in self.session_blacklist.items():
                        time_remaining = blacklist_duration - (current_time - blacklisted_at)
                        remaining_times.append(f"{coin}({time_remaining / 60:.0f}m)")
                    self.logger().debug(f"🚫 Session blacklist (tijdelijk): {', '.join(remaining_times)}")

                # Request TOP N coins where N = available slots
                # With depth filtering enabled from orderbook_liquidity config
                orderbook_config = self._build_orderbook_config()
                top_coins = self.trend_calculator.get_top_n_coins(
                    n=available_slots,
                    min_trend_pct=float(self.config.trend_min_change_pct),
                    exclude_coins=list(excluded_coins_with_active) if excluded_coins_with_active else None,
                    orderbook_config=orderbook_config,
                )

                max_slots = self._get_current_max_slots()
                self.logger().info(
                    f"📊 Multi-coin mode: {len(self.active_coins)}/{max_slots} slots used, "
                    f"{len(top_coins)} qualifying coins found for available slots"
                )

            # ===== ORDERBOOK PREFETCH (Shadow Mode) =====
            # Observe orderbook cache status for top candidates BEFORE SmartEntry validation
            self.logger().debug(f"[PREFETCH] Hook triggered - top_coins length: {len(top_coins) if top_coins else 0}")
            if top_coins:
                self._prefetch_orderbooks_shadow(top_coins)
            else:
                self.logger().debug("[PREFETCH] No top_coins to prefetch")

            # For compatibility with existing single-coin logic, set best_coin to first coin
            # (We'll process all coins in the loop below)
            # 🔧 FIX: Use helper to skip coins with active grids
            best_coin = self.pick_first_inactive(top_coins) if top_coins else None

            # Double-check: reject if somehow a blacklisted coin was selected (config or runtime)
            if best_coin and (best_coin in config_blacklist or best_coin in self.auto_blacklisted_coins):
                blacklist_type = "config" if best_coin in config_blacklist else "runtime (NL-restriction/error-loop)"
                self.logger().warning(
                    f"🚨 CRITICAL: {best_coin} is in blacklist ({blacklist_type}) but was selected! Rejecting..."
                )

                # Phase 3: Emit BLACKLIST denial event
                correlation_id = str(uuid.uuid4())
                self._emit_execution_denial(
                    symbol=best_coin,
                    reason_code=ReasonCode.BLACKLIST,
                    reason_msg=f"{best_coin} is in {blacklist_type} blacklist",
                    correlation_id=correlation_id,
                    metadata={
                        "blacklist_type": blacklist_type,
                        "blacklist_size": len(config_blacklist),
                        "timestamp": self.market_data_provider.time()
                    }
                )

                best_coin = None

            # SMART SELECTION: Check SmartEntry BEFORE finalizing coin selection
            # This prevents selecting coins that will be rejected anyway
            rejection_reason = None
            if best_coin and not self._check_smart_entry_filter(best_coin):
                self.logger().warning(
                    f"⚠️  {best_coin} rejected by SmartEntry - checking fallbacks..."
                )

                # Try next best coins from top 10
                fallback_found = False
                if hasattr(self.trend_calculator, '_debug_info'):
                    top_10 = self.trend_calculator._debug_info.get('top_10', [])
                    for i, (fallback_coin, fallback_trend) in enumerate(top_10[1:], start=2):
                        # 🔧 FIX: Skip if coin already has active grid
                        if fallback_coin in self.active_coins:
                            self.logger().debug(f"   {i}. {fallback_coin}: SKIPPED (already active)")
                            continue

                        if fallback_coin in excluded_coins or fallback_coin in config_blacklist:
                            self.logger().debug(f"   {i}. {fallback_coin}: SKIPPED (blacklist)")
                            continue

                        # Check SmartEntry for fallback
                        if self._check_smart_entry_filter(fallback_coin):
                            # Multi-timeframe buy protection check
                            if not self._check_multi_timeframe_buy(fallback_coin):
                                self.logger().warning(f"⏱️  {fallback_coin}: Blocked by multi-timeframe protection")
                                continue

                            # Also check multi-timeframe if enabled
                            if not use_multi_timeframe or self._check_multi_timeframe_buy_conditions(fallback_coin):
                                self.logger().info(
                                    f"✅ Fallback: {fallback_coin} (#{i}) passes ALL filters! "
                                    f"Trend: {fallback_trend:+.2f}%"
                                )
                                best_coin = fallback_coin
                                fallback_found = True
                                break
                            else:
                                self.logger().debug(f"   {i}. {fallback_coin}: REJECTED (multi-timeframe)")
                        else:
                            self.logger().debug(f"   {i}. {fallback_coin}: REJECTED (SmartEntry)")

                if not fallback_found:
                    self.logger().warning("⚠️  No valid coin found in top 10 after SmartEntry filtering")
                    best_coin = None
                    rejection_reason = "All top coins rejected by SmartEntry filters"

            elif best_coin and not self._check_multi_timeframe_buy(best_coin):
                self.logger().warning(
                    f"⏱️  {best_coin} rejected by multi-timeframe protection - checking fallbacks..."
                )

                # Try next best coins from top 10
                fallback_found = False
                if hasattr(self.trend_calculator, '_debug_info'):
                    top_10 = self.trend_calculator._debug_info.get('top_10', [])
                    for i, (fallback_coin, fallback_trend) in enumerate(top_10[1:], start=2):
                        # 🔧 FIX: Skip if coin already has active grid
                        if fallback_coin in self.active_coins:
                            self.logger().debug(f"   {i}. {fallback_coin}: SKIPPED (already active)")
                            continue

                        if fallback_coin in excluded_coins or fallback_coin in config_blacklist:
                            self.logger().debug(f"   {i}. {fallback_coin}: SKIPPED (blacklist)")
                            continue

                        # Check SmartEntry for fallback
                        if self._check_smart_entry_filter(fallback_coin):
                            # Multi-timeframe buy protection check
                            if not self._check_multi_timeframe_buy(fallback_coin):
                                self.logger().warning(f"⏱️  {fallback_coin}: Blocked by multi-timeframe protection")
                                continue

                            # Also check multi-timeframe if enabled
                            if not use_multi_timeframe or self._check_multi_timeframe_buy_conditions(fallback_coin):
                                self.logger().info(
                                    f"✅ Fallback: {fallback_coin} (#{i}) passes ALL filters! "
                                    f"Trend: {fallback_trend:+.2f}%"
                                )
                                best_coin = fallback_coin
                                fallback_found = True
                                break
                            else:
                                self.logger().debug(f"   {i}. {fallback_coin}: REJECTED (multi-timeframe)")
                        else:
                            self.logger().debug(f"   {i}. {fallback_coin}: REJECTED (SmartEntry)")

                if not fallback_found:
                    self.logger().warning("⚠️  No valid coin found in top 10 after SmartEntry filtering")
                    best_coin = None
                    rejection_reason = "All top coins rejected by SmartEntry filters"

            # Phase 2.5: Apply multi-timeframe buy conditions if enabled (only if not already checked above)
            if best_coin and use_multi_timeframe and rejection_reason is None:
                if not self._check_multi_timeframe_buy_conditions(best_coin):
                    # Phase 1C: Instrument MTF rejection inline (no helper method)
                    # Get rejection reason from trend data
                    trend_obj = self.trend_calculator.get_trend(best_coin)
                    reason_code = ReasonCode.MTF_INSUFFICIENT  # Default

                    if trend_obj and hasattr(trend_obj, 'trend_240m') and hasattr(trend_obj, 'trend_60m'):
                        if hasattr(trend_obj, 'long_trend_warmup') and trend_obj.long_trend_warmup:
                            if trend_obj.trend_240m <= 0.75:
                                rejection_reason = f"4h trend ({
                                    trend_obj.trend_240m:+.2f}%) <= +0.75% (warm-up requires > +0.75%)"
                                reason_code = ReasonCode.MTF_INSUFFICIENT
                            elif trend_obj.trend_60m < 0.15:
                                # Fix #4: < 0.15 is insufficient, not crash
                                rejection_reason = f"1h trend ({
                                    trend_obj.trend_60m:+.2f}%) < +0.15% (warm-up requires >= +0.15%)"
                                reason_code = ReasonCode.MTF_INSUFFICIENT
                            else:
                                rejection_reason = "Warm-up mode: trends niet sterk genoeg"
                                reason_code = ReasonCode.MTF_INSUFFICIENT
                        else:
                            if trend_obj.trend_1440m <= 1.0:
                                rejection_reason = f"24h trend ({trend_obj.trend_1440m:+.2f}%) <= +1%"
                                reason_code = ReasonCode.MTF_INSUFFICIENT
                            elif trend_obj.trend_240m <= 1.0:
                                rejection_reason = f"4h trend ({trend_obj.trend_240m:+.2f}%) <= +1%"
                                reason_code = ReasonCode.MTF_INSUFFICIENT
                            elif trend_obj.trend_60m < 0.0:
                                # Fix #4: Only negative trends are crashes
                                rejection_reason = f"1h trend ({trend_obj.trend_60m:+.2f}%) < 0% (crash detected)"
                                reason_code = ReasonCode.MTF_CRASH_DETECTED
                            else:
                                rejection_reason = "Multi-timeframe buy conditions niet voldaan"
                                reason_code = ReasonCode.MTF_INSUFFICIENT
                    else:
                        rejection_reason = "Multi-timeframe data niet beschikbaar"
                        reason_code = ReasonCode.MTF_INSUFFICIENT

                    # Phase 1C: Create trace inline and populate stage + reason_code
                    # Fix #1: Reuse correlation_id from SmartEntry trace (single source of truth)
                    last_trace = getattr(self, '_last_smart_entry_trace', None)
                    correlation_id = last_trace.correlation_id if last_trace and last_trace.correlation_id else str(__import__('uuid').uuid4())

                    mtf_trace = PairDecisionTrace(
                        trading_pair=best_coin,
                        exchange=self.config.connector_name,
                        enabled=True,
                        strategy="spot_grid"
                    )
                    mtf_trace.finalize(accepted=False, rejected_by="mtf", final_reason=rejection_reason)
                    mtf_trace.reason_code = reason_code.value
                    mtf_trace.stage = Stage.MTF.value
                    mtf_trace.correlation_id = correlation_id  # Fix #1: Reuse correlation_id

                    # Event emission happens centrally in _log_decision_trace()
                    self._log_decision_trace(mtf_trace)

                    self.logger().warning(
                        f"❌ {best_coin} does not meet multi-timeframe buy conditions - will retry next cycle"
                    )
                    best_coin = None
                else:
                    # Fix #2: MTF passed - emit gate_passed event
                    last_trace = getattr(self, '_last_smart_entry_trace', None)
                    if last_trace and last_trace.correlation_id:
                        mtf_pass_trace = PairDecisionTrace(
                            trading_pair=best_coin,
                            exchange=self.config.connector_name,
                            enabled=True,
                            strategy="spot_grid"
                        )
                        mtf_pass_trace.finalize(accepted=True, final_reason="MTF buy conditions passed")
                        mtf_pass_trace.stage = Stage.MTF.value
                        mtf_pass_trace.correlation_id = last_trace.correlation_id
                        self._log_decision_trace(mtf_pass_trace)

            # Log debug info from trend_calculator
            if hasattr(self.trend_calculator, '_debug_info'):
                info = self.trend_calculator._debug_info
                self.logger().info(f"🔍 Analysis: {info['sufficient']}/{info['total']} coins with sufficient data")

                # DEBUG: Show first 5 coins with their data points
                for i, (symbol, trend) in enumerate(list(self.trend_calculator.trends.items())[:5]):
                    self.logger().info(
                        f"  Sample {i + 1}: {symbol} has {len(trend.price_history)} points, "
                        f"sufficient={trend.has_sufficient_data}"
                    )

                self.logger().info(f"🔍 Found {info['all_count']} coins meeting criteria (min {info['min_trend']}%)")

                if info.get('top_10'):
                    self.logger().info("🔝 Top 10 trends:")
                    for i, (sym, tr) in enumerate(info['top_10'], 1):
                        # Get detailed trend info for top coins
                        trend_obj = self.trend_calculator.trends.get(sym)
                        if trend_obj:
                            trend_24h = getattr(trend_obj, 'trend_1440m', 0.0)
                            trend_4h = getattr(trend_obj, 'trend_240m', 0.0)
                            trend_1h = getattr(trend_obj, 'trend_60m', 0.0)
                            points = len(trend_obj.price_history)
                            self.logger().info(
                                f"  {i}. {sym}: {tr:+.3f}% "
                                f"(24h: {trend_24h:+.2f}%, 4h: {trend_4h:+.2f}%, 1h: {trend_1h:+.2f}%, "
                                f"{points} points)"
                            )
                        else:
                            self.logger().info(f"  {i}. {sym}: {tr:+.3f}%")

                if info.get('best'):
                    sym, tr = info['best']
                    self.logger().info(f"🏆 BEST: {sym} with {tr:+.2f}% trend")
                else:
                    self.logger().info(f"❌ No coin >= {info['min_trend']}% threshold")

                # MONITORING: Show validation summary for top coins
                try:
                    top_symbols = [sym for sym, _ in info.get('top_10', [])[:5]]  # Top 5 only
                    if top_symbols:
                        self.logger().info("📊 VALIDATION STATUS (Top 5):")
                        for sym in top_symbols:
                            validation = self.trend_calculator.validate_trend(sym)
                            if validation:
                                status_icon = "✅" if validation.passes else "❌"
                                self.logger().info(
                                    f"   {status_icon} {sym:12s} | {validation.status.value:8s} | "
                                    f"Score: {validation.trend_score_pct:+6.2f}% | Candles: {validation.candle_count:3d}"  # noqa: E501
                                )
                except Exception as e:
                    self.logger().debug(f"Could not generate validation summary: {e}")

            # Only log selected coin if one was found
            if best_coin:
                # MONITORING: Log trend validation status using new validate_trend() framework
                try:
                    validation = self.trend_calculator.validate_trend(best_coin)
                    if validation:
                        status_emoji = {
                            TrendStatus.BULLISH: "📈",
                            TrendStatus.SIDEWAYS: "➡️",
                            TrendStatus.BEARISH: "📉",
                            TrendStatus.WARMUP: "⏳"
                        }.get(validation.status, "❓")

                        self.logger().info(
                            f"📊 TREND VALIDATION: {best_coin} | "
                            f"Status: {status_emoji} {validation.status.value} | "
                            f"Score: {validation.trend_score_pct:+.2f}% | "
                            f"Passes: {'✅' if validation.passes else '❌'} | "
                            f"Candles: {validation.candle_count} | "
                            f"Timeframes (1h/4h/24h): {validation.trend_1h:+.2f}% / {validation.trend_4h:+.2f}% / {validation.trend_24h:+.2f}%"  # noqa: E501
                        )

                        # Optional: Log warning if passes=False but coin was still selected
                        if not validation.passes:
                            if validation.status == TrendStatus.WARMUP:
                                self.logger().debug(
                                    f"ℹ️  Note: {best_coin} in WARMUP mode (only {
                                        validation.candle_count} candles, need 360+)")
                            elif validation.status == TrendStatus.SIDEWAYS:
                                self.logger().debug(
                                    f"ℹ️  Note: {best_coin} in SIDEWAYS trend ({
                                        validation.trend_score_pct:+.2f}% < +0.5% threshold)")
                            elif validation.status == TrendStatus.BEARISH:
                                self.logger().warning(
                                    f"⚠️  Warning: {best_coin} has BEARISH trend ({
                                        validation.trend_score_pct:+.2f}% < -0.5%)")
                except Exception as e:
                    self.logger().debug(f"Could not validate trend for {best_coin}: {e}")

                # NEW: Check if we've been monitoring this coin too long without execution
                current_time = self.market_data_provider.time()
                max_monitoring_seconds = getattr(
                    self.config,
                    'max_coin_monitoring_seconds',
                    60)  # Default 60s (was 300s)

                if best_coin == self.monitoring_coin and self.monitoring_start_time > 0:
                    # Same coin being monitored - check timeout
                    time_monitoring = current_time - self.monitoring_start_time
                    if time_monitoring > max_monitoring_seconds:
                        self.logger().warning(
                            f"⏰ MONITORING TIMEOUT: {best_coin} heeft {time_monitoring / 60:.1f} minuten "
                            f"gemonitord zonder trade (max: {max_monitoring_seconds / 60:.1f} min). "
                            f"Forceer rotatie naar volgende coin..."
                        )
                        # Voeg toe aan session blacklist met timestamp
                        self.session_blacklist[best_coin] = current_time
                        blacklist_duration = getattr(
                            self.config, 'session_blacklist_duration_seconds', 7200)  # Default 2 uur
                        self.logger().info(
                            f"🚫 {best_coin} toegevoegd aan session blacklist voor "
                            f"{blacklist_duration / 3600:.1f} uur"
                        )
                        # Reset monitoring en zoek opnieuw
                        self.monitoring_coin = None
                        self.monitoring_start_time = 0
                        return actions  # Return nu, next cycle selecteert andere coin
                elif best_coin != self.monitoring_coin:
                    # Nieuwe coin - start monitoring tracking
                    self.monitoring_coin = best_coin
                    self.monitoring_start_time = current_time
                    self.logger().info(f"🔍 Start monitoring: {best_coin}")

                self.logger().info(f"🔍 Selected coin: {best_coin}")
                # MONITORING FIX: Also log in format collector can easily find
                self.logger().info(f"📊 MONITORING: Active Coin: {best_coin}")
            else:
                # Reset monitoring als geen coin gevonden
                self.monitoring_coin = None
                self.monitoring_start_time = 0
                self.logger().info("🔍 Selected coin: None (no coin meets criteria)")
                # MONITORING FIX: Log None explicitly
                self.logger().info("📊 MONITORING: Active Coin: None")

                # Log WHY no coin was selected (helpful debugging)
                if hasattr(self.trend_calculator, '_debug_info'):
                    info = self.trend_calculator._debug_info
                    if info.get('best'):
                        sym, tr = info['best']
                        trend_obj = self.trend_calculator.trends.get(sym)
                        if trend_obj:
                            trend_24h = getattr(trend_obj, 'trend_1440m', 0.0)
                            trend_4h = getattr(trend_obj, 'trend_240m', 0.0)
                            trend_1h = getattr(trend_obj, 'trend_60m', 0.0)
                            use_multi_timeframe = getattr(self.config, 'use_multi_timeframe', True)
                            warmup_mode = hasattr(trend_obj, 'long_trend_warmup') and trend_obj.long_trend_warmup

                            # Build rejection reason message
                            reason_msg = ""
                            if rejection_reason:
                                reason_msg = f"\n   - REDEN: {rejection_reason}"

                            self.logger().warning(
                                f"⚠️  Best coin {sym} (consensus: {tr:+.2f}%) werd afgewezen:\n"
                                f"   - Consensus trend: {tr:+.2f}% (overall score)\n"
                                f"   - 24h trend: {trend_24h:+.2f}%\n"
                                f"   - 4h trend: {trend_4h:+.2f}%\n"
                                f"   - 1h trend: {trend_1h:+.2f}%\n"
                                f"   - Multi-timeframe: {'AAN' if use_multi_timeframe else 'UIT'}\n"
                                f"   - Warm-up mode: {'AAN' if warmup_mode else 'UIT'}"
                                f"{reason_msg}"
                            )
        except Exception as e:
            self.logger().error(f"💥 CRASH in get_best_coin(): {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            return actions

        # PRO EXIT SYSTEM: Check exit conditions for active coin (5-layer stack)
        use_multi_timeframe = getattr(self.config, 'use_multi_timeframe', True)
        if self.active_coin and self.active_executor_id and use_multi_timeframe:
            exit_reason = self.should_exit_position(self.active_coin)
            if exit_reason:
                # Exit conditions met - force stop
                self.logger().critical(
                    f"🚨 PRO EXIT SYSTEM: {self.active_coin} exit triggered - reason: {exit_reason}"
                )
                if self._is_executor_actually_active():
                    try:
                        stop_action = self._create_stop_action()
                        if stop_action:
                            actions.append(stop_action)
                            if self.active_coin:
                                self.risk_manager.note_exit(self.active_coin, now_ts)
                            return actions
                    except Exception as e:
                        self.logger().error(f"❌ Error creating stop action for exit: {e}")

        # No coin meets criteria - check if we should stop active executor
        if not best_coin:
            self.logger().info(f"❌ No coin found with trend >= {self.config.trend_min_change_pct}%")

            # PHASE 2 FIX: "No better coin" does NOT force close!
            # Risk management (stop loss, P&L targets) controls exits, NOT coin selection
            # Coin selection only decides what NEW positions to open

            if self.active_coin:
                self.logger().info(
                    f"✅ No better coin found, but keeping {self.active_coin} running. "
                    f"Risk management will handle exit if needed."
                )

            # Just pause new entries - don't touch active positions!
            return actions

        # Check if risk controls allow new entries
        if risk_block_new_entries:
            self.logger().info("🛑 Risk controls blocking new executor creation this cycle")
            return actions

        # PHASE 1 FIX #2 & #3: Check drawdown limits
        try:
            current_balance = self.connector.get_balance(self.config.quote_asset)
            allowed, reason = self.drawdown_tracker.check_drawdown_limits(current_balance)
            if not allowed:
                self.logger().critical(f"🛑 DRAWDOWN LIMIT: {reason}")
                return actions  # No new trades allowed
        except Exception as e:
            self.logger().error(f"Error checking drawdown limits: {e}")
            # Continue on error (don't block trading due to check failure)

        # Check if we should create/switch grid
        # Note: best_coin is already filtered to exclude coins in cooldown
        if self._should_create_new_grid(best_coin):
            # PHASE 1 FIX #1: Check slippage/spread before entry (skip for paper trading)
            paper_trading = getattr(self.config, 'paper_trading', False)

            if not paper_trading:
                # Live trading: Check spread + depth before creating executor
                spread_acceptable = self._check_spread_acceptable(best_coin)

                # PHASE 2: Check order book depth (calculate order size first)
                total_capital = self._next_allocation_quote if self._next_allocation_quote else Decimal(
                    str(self.config.total_amount_quote))
                per_coin_capital = total_capital / Decimal(str(self.max_simultaneous_coins))
                order_size_eur = float(per_coin_capital)

                depth_acceptable = self._check_order_book_depth(best_coin, order_size_eur)

                if not spread_acceptable or not depth_acceptable:
                    rejection_reason = []
                    if not spread_acceptable:
                        rejection_reason.append("spread too wide")
                    if not depth_acceptable:
                        rejection_reason.append("insufficient depth")

                    self.logger().warning(
                        f"🚫 Rejecting {best_coin}: {' + '.join(rejection_reason)}"
                    )

                    # 🔧 FALLBACK: Try next coins in top 10 when spread check fails
                    self.logger().info("🔄 Trying fallback coins (top 10)...")
                    if hasattr(self.trend_calculator, '_debug_info'):
                        top_10 = self.trend_calculator._debug_info.get('top_10', [])
                        # Build exclusion set inline (same logic as in determine_executor_actions)
                        config_blacklist = set(getattr(self.config, 'blacklist', []) or [])
                        excluded_coins = config_blacklist | self.auto_blacklisted_coins

                        for i, (fallback_coin, fallback_trend) in enumerate(
                                top_10[1:], start=2):  # Skip #1 (already rejected)
                            if fallback_coin in excluded_coins:
                                self.logger().debug(f"   {i}. {fallback_coin}: SKIPPED (excluded)")
                                continue

                            # Check spread + depth for fallback coin
                            fallback_spread_ok = self._check_spread_acceptable(fallback_coin)
                            fallback_depth_ok = self._check_order_book_depth(fallback_coin, order_size_eur)

                            if fallback_spread_ok and fallback_depth_ok:
                                # Also check trend conditions
                                if self._check_multi_timeframe_buy_conditions(fallback_coin):
                                    self.logger().info(
                                        f"✅ FALLBACK: {fallback_coin} (#{i}) passes spread + depth + trend checks! "
                                        f"Trend: {fallback_trend:+.2f}%"
                                    )
                                    best_coin = fallback_coin
                                    break
                                else:
                                    self.logger().debug(f"   {i}. {fallback_coin}: spread+depth OK but trend rejected")
                            else:
                                rejection = []
                                if not fallback_spread_ok:
                                    rejection.append("spread")
                                if not fallback_depth_ok:
                                    rejection.append("depth")
                                self.logger().debug(f"   {i}. {fallback_coin}: {'+'.join(rejection)} check failed")
                        else:
                            # No fallback coin found
                            self.logger().warning("⚠️  No fallback coin with valid order book - waiting for better conditions")  # noqa: E501
                            return actions
                    else:
                        return actions

            # For paper trading, we can skip order book check if we have price from trend data
            # The GridExecutor will use fallback logic to get price from base connector if needed
            order_book_ready = False

            if paper_trading:
                # Paper trading: Check if we have price from trend data (sufficient for grid creation)
                trend = self.trend_calculator.get_trend(best_coin)
                if trend and trend.current_price and trend.current_price > 0:
                    # We have price from trend data - order book not strictly required
                    # GridExecutor will use base connector fallback if order book doesn't exist
                    self.logger().info(
                        f"📊 Paper trading: Using price from trend data for {best_coin} "
                        f"(€{trend.current_price:.4f}) - order book check skipped"
                    )
                    order_book_ready = True  # Allow executor creation
                else:
                    self.logger().warning(
                        f"⚠️  Paper trading: No trend price available for {best_coin} - "
                        f"cannot create executor without price data"
                    )
                    return actions
            else:
                # Live trading: Order book is required
                # FIRST: Check if pair is actually in connector's trading pairs
                if not self._is_trading_pair_tradeable(best_coin):
                    self.logger().warning(
                        f"⚠️ {best_coin} is NOT tradeable - trying fallback coins..."
                    )
                    # Try fallback coins
                    if hasattr(self.trend_calculator, '_debug_info'):
                        top_10 = self.trend_calculator._debug_info.get('top_10', [])
                        config_blacklist = set(getattr(self.config, 'blacklist', []) or [])
                        excluded_coins = config_blacklist | self.auto_blacklisted_coins

                        for i, (fallback_coin, fallback_trend) in enumerate(top_10[1:], start=2):
                            if fallback_coin in excluded_coins:
                                continue
                            if self._is_trading_pair_tradeable(fallback_coin):
                                if self._check_multi_timeframe_buy_conditions(fallback_coin):
                                    self.logger().info(
                                        f"✅ FALLBACK: {fallback_coin} (#{i}) is tradeable! "
                                        f"Trend: {fallback_trend:+.2f}%"
                                    )
                                    best_coin = fallback_coin
                                    order_book_ready = True
                                    break
                        else:
                            self.logger().warning("⚠️ No tradeable fallback coin found - waiting")
                            return actions
                    else:
                        return actions
                else:
                    # Pair is tradeable, verify order book
                    try:
                        order_book = self.connector.get_order_book(best_coin)
                        if order_book is not None:
                            order_book_ready = True
                            self.logger().debug(f"✅ Order book exists for {best_coin}")
                        else:
                            self.logger().warning(f"⚠️ Order book is None for {best_coin}")
                    except (ValueError, KeyError) as e:
                        self.logger().warning(f"⚠️ Order book not found for {best_coin}: {e}")
                        # Order book doesn't exist - try to initialize
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            try:
                                safe_ensure_future(self._ensure_order_book_exists(best_coin))
                                self.logger().info(
                                    f"⏳ Order book initialization scheduled for {best_coin} - will retry next cycle")
                                return actions
                            except Exception as init_error:
                                self.logger().error(f"❌ Failed to schedule order book initialization: {init_error}")
                                return actions
                        else:
                            order_book_ready = loop.run_until_complete(self._ensure_order_book_exists(best_coin))
                            if not order_book_ready:
                                self.logger().error(
                                    f"❌ Cannot create executor for {best_coin} - order book initialization failed")
                                return actions
                    except Exception as e:
                        self.logger().error(f"❌ Error checking order book for {best_coin}: {e}")
                        return actions

                # Final check - don't create executor if order book is not ready
                if not order_book_ready:
                    self.logger().warning(f"⚠️ Order book not ready for {best_coin} - skipping executor creation")
                    return actions

            # 🔧 MULTI-COIN FIX: Only "switch" if all slots are full
            # If we have free slots, we ADD coins, not SWITCH them
            max_slots = self._get_current_max_slots()
            slots_available = len(self.active_coins) < max_slots

            # Stop old executor if exists and is actually active (ONLY in single-coin mode or when slots full)
            if not slots_available and self.active_coin and self.active_executor_id and self._is_executor_actually_active():
                # 🛡️ GRACE PERIOD: Professional traders give positions time to develop
                # Check executor age - only allow switching after grace period
                executor_info = self._get_executor_info(self.active_executor_id)
                if executor_info:
                    current_time = self.market_data_provider.time()
                    grid_age_seconds = current_time - executor_info.timestamp
                    grace_period = getattr(self.config, 'switch_grace_period_seconds', 600)  # Default 10 min

                    if grid_age_seconds < grace_period:
                        # Task 2.2: Check if grace period should be bypassed
                        should_bypass, bypass_reason = self._should_bypass_grace_period(executor_info, self.active_coin)

                        if should_bypass:
                            self.logger().info(
                                f"✅ GRACE BYPASS: {self.active_coin} rotation allowed - {bypass_reason} "
                                f"(age: {grid_age_seconds / 60:.1f} min, grace: {grace_period / 60:.1f} min)"
                            )
                            # Continue to rotation logic below
                        else:
                            remaining = grace_period - grid_age_seconds
                            self.logger().info(
                                f"🛡️  GRACE PERIOD: {self.active_coin} is only {grid_age_seconds / 60:.1f} min old - "
                                f"wait {remaining / 60:.1f} more minutes before switching (professional practice: "
                                f"give trades room to breathe)"
                            )
                            # Grace period active - only emergency exits allowed (stop-loss will override this)
                            # Don't create new executor, don't switch
                            return actions

                self.logger().info(
                    f"🔄 SWITCHING: {self.active_coin} → {best_coin} (all {max_slots} slots full)"
                )

                # CRITICAL: Check if executor has open position before switching
                executor_info = self._get_executor_info(self.active_executor_id)
                has_open_position = False
                if executor_info:
                    custom_info = executor_info.custom_info
                    position_size_quote = custom_info.get("position_size_quote", Decimal("0"))
                    if isinstance(position_size_quote, (int, float)):
                        position_size_quote = Decimal(str(position_size_quote))

                    if position_size_quote == Decimal("0"):
                        filled_amount = executor_info.filled_amount_quote
                        if filled_amount and filled_amount > Decimal("0"):
                            has_open_position = True
                    elif position_size_quote > Decimal("0"):
                        has_open_position = True

                if has_open_position:
                    self.logger().warning(
                        f"⚠️  Executor {self.active_executor_id[:8]}... has open position - "
                        f"will stop and close position before switching to {best_coin}"
                    )
                    # Don't create new executor in same cycle - wait for position to close
                    # The stop_action will trigger early_stop() which closes the position
                    # Next cycle, if executor is stopped, we can create new one
                    try:
                        stop_action = self._create_stop_action()
                        if stop_action:
                            actions.append(stop_action)
                            # Don't create new executor yet - return and wait for position to close
                            self.logger().info(
                                f"⏳ Waiting for {self.active_coin} position to close before switching to {best_coin}"
                            )
                            if self.active_coin:
                                self.risk_manager.note_exit(self.active_coin, now_ts)
                            return actions
                        else:
                            self.logger().warning(f"⚠️  Failed to create stop action for {self.active_coin}")
                    except Exception as e:
                        self.logger().error(f"❌ Error creating stop action: {e}")
                        import traceback
                        self.logger().error(traceback.format_exc())
                        return actions
                else:
                    # No open position - safe to switch immediately
                    try:
                        stop_action = self._create_stop_action()
                        if stop_action:
                            actions.append(stop_action)
                            if self.active_coin:
                                self.risk_manager.note_exit(self.active_coin, now_ts)
                        else:
                            self.logger().warning(f"⚠️  Failed to create stop action for {self.active_coin}")
                            return actions
                    except Exception as e:
                        self.logger().error(f"❌ Error creating stop action: {e}")
                        import traceback
                        self.logger().error(traceback.format_exc())
                        return actions
            else:
                self.logger().info(f"✨ STARTING new grid on {best_coin}")

            # Phase 1.4: Check position limits before creating executor
            if not self._check_position_limits(best_coin):
                self.logger().warning(
                    f"⚠️  Position limits exceeded for {best_coin} - skipping grid creation"
                )
                return actions

            # Create new grid executor
            try:
                # PHASE 1 FIX #4: Calculate volatility-adjusted position size
                # MULTI-COIN: Divide capital by number of simultaneous coins
                total_capital = self._next_allocation_quote if self._next_allocation_quote else Decimal(
                    str(self.config.total_amount_quote))
                per_coin_capital = total_capital / Decimal(str(self.max_simultaneous_coins))

                # ===== FEATURE 1.2: APPLY TIME-BASED POSITION SIZE ADJUSTMENT =====
                if self.time_based_filter:
                    time_decision = self.time_based_filter.check_trading_permission()
                    per_coin_capital = self.time_based_filter.get_position_size_adjustment(float(per_coin_capital))
                    per_coin_capital = Decimal(str(per_coin_capital))
                    if time_decision.risk_multiplier != 1.0:
                        self.logger().info(
                            f"⏰ Feature 1.2: Position size adjusted by {time_decision.risk_multiplier}x "
                            f"(€{total_capital / Decimal(str(self.max_simultaneous_coins)):.2f} → €{per_coin_capital:.2f})"  # noqa: E501
                        )

                adjusted_size = self._calculate_volatility_adjusted_position_size(best_coin, per_coin_capital)

                # Feature 1.2b: Apply liquidity-aware sizing cap
                if self.liquidity_aware_sizer:
                    # Calculate actual multiplier applied
                    if per_coin_capital > 0:
                        actual_multiplier = float(adjusted_size / per_coin_capital)
                        adjusted_size = self.liquidity_aware_sizer.apply_sizing_cap(
                            base_size=per_coin_capital,
                            calculated_multiplier=actual_multiplier,
                            coin_symbol=best_coin
                        )

                # CRITICAL SAFETY CHECK: Ensure adjusted_size never exceeds available capital
                # This prevents budget check failures when volatility sizing increases position size
                if adjusted_size > per_coin_capital:
                    self.logger().warning(
                        f"⚠️  Adjusted size (€{adjusted_size:.2f}) exceeds available capital (€{per_coin_capital:.2f}) - capping to available"
                    )
                    adjusted_size = per_coin_capital

                self.logger().info(
                    f"💰 Capital allocation: €{total_capital} / {
                        self.max_simultaneous_coins} coins = €{
                        per_coin_capital:.2f} per coin")

                # 🔧 RACE CONDITION GUARD: Final check before creating grid
                # Even with filtering, coin could become active between selection and creation
                if best_coin in self.active_coins:
                    self.logger().warning(
                        f"⏭️  {best_coin} became active just now (race condition) - skipping create"
                    )
                    return actions

                grid_action = self._create_grid_action(best_coin, adjusted_size)
                if grid_action:
                    actions.append(grid_action)
                    applied_notional = Decimal(str(grid_action.executor_config.total_amount_quote))
                    # Phase 1.4: Track exposure when creating executor
                    self._update_exposure_tracking(best_coin, applied_notional)
                    self._active_executor_notional = applied_notional
                    self.risk_manager.register_open_trade(
                        symbol=best_coin,
                        notional=applied_notional,
                        now=now_ts,
                    )
                    self._next_allocation_quote = None

                    # MULTI-COIN: Track in active_coins dictionary
                    if grid_action.executor_config and grid_action.executor_config.id:
                        self.active_coins[best_coin] = grid_action.executor_config.id
                        self.logger().info(
                            f"📊 Active coins: {list(self.active_coins.keys())} ({len(self.active_coins)}/{self._get_current_max_slots()})")  # noqa: E501
                else:
                    self.logger().error(f"❌ Failed to create grid action for {best_coin}")
            except Exception as e:
                self.logger().error(f"❌ Error creating grid action for {best_coin}: {e}")
                import traceback
                self.logger().error(traceback.format_exc())

            # Reset performance counter for this coin (it's performing!)
            if best_coin in self.coin_performance:
                self.coin_performance[best_coin] = 0

            # Update state (legacy single-coin tracking + new multi-coin)
            self.active_coin = best_coin
            self.last_switch_time = self.market_data_provider.time()

        # MULTI-COIN: Process remaining coins from top_coins (if any slots still available)
        max_slots_for_loop = self._get_current_max_slots()
        if len(top_coins) > 1 and len(self.active_coins) < max_slots_for_loop:
            self.logger().info(
                f"\n🔄 MULTI-COIN: Processing remaining {len(top_coins) - 1} qualifying coins..."
            )

            for coin_index, candidate_coin in enumerate(top_coins[1:], start=2):  # Skip first coin (already processed)
                # Check if we've filled all slots
                if len(self.active_coins) >= max_slots_for_loop:
                    self.logger().info(
                        f"📊 All {max_slots_for_loop} slots filled - stopping coin processing"
                    )
                    break

                # Skip if coin is already active (shouldn't happen due to exclusion, but safety check)
                if candidate_coin in self.active_coins:
                    self.logger().debug(f"   {coin_index}. {candidate_coin}: SKIP (already active)")
                    continue

                self.logger().info(f"\n   {coin_index}. Evaluating {candidate_coin}...")

                # Apply all the same checks as for best_coin
                # 1. Multi-timeframe buy conditions
                if use_multi_timeframe and not self._check_multi_timeframe_buy_conditions(candidate_coin):
                    self.logger().debug("      ❌ Multi-timeframe buy conditions not met")
                    continue

                # 2. SmartEntry filter
                if not self._check_smart_entry_filter(candidate_coin):
                    self.logger().debug("      ❌ SmartEntry filter rejected")
                    continue

                # 2b. Multi-timeframe buy protection
                if not self._check_multi_timeframe_buy(candidate_coin):
                    self.logger().debug("      ❌ Multi-timeframe protection rejected")
                    continue

                # 3. Check if should create new grid
                if not self._should_create_new_grid(candidate_coin):
                    self.logger().debug("      ❌ _should_create_new_grid returned False")
                    continue

                # 4. Spread check (for live trading)
                paper_trading = getattr(self.config, 'paper_trading', False)
                if not paper_trading:
                    if not self._check_spread_acceptable(candidate_coin):
                        self.logger().debug("      ❌ Spread check failed")
                        continue

                    if not self._is_trading_pair_tradeable(candidate_coin):
                        self.logger().debug("      ❌ Trading pair not tradeable")
                        continue

                    # Order book check
                    try:
                        order_book = self.connector.get_order_book(candidate_coin)
                        if order_book is None:
                            self.logger().debug("      ❌ Order book is None")
                            continue
                    except Exception as e:
                        self.logger().debug(f"      ❌ Order book error: {e}")
                        continue

                # 5. Position limits
                if not self._check_position_limits(candidate_coin):
                    self.logger().debug("      ❌ Position limits exceeded")
                    continue

                # All checks passed - create executor for this coin
                self.logger().info(f"      ✅ All checks passed - creating executor for {candidate_coin}")

                try:
                    # Calculate per-coin capital (same as for first coin)
                    total_capital = Decimal(str(self.config.total_amount_quote))
                    per_coin_capital = total_capital / Decimal(str(self.max_simultaneous_coins))
                    adjusted_size = self._calculate_volatility_adjusted_position_size(candidate_coin, per_coin_capital)

                    # Feature 1.2b: Apply liquidity-aware sizing cap (fallback path)
                    if self.liquidity_aware_sizer:
                        if per_coin_capital > 0:
                            actual_multiplier = float(adjusted_size / per_coin_capital)
                            adjusted_size = self.liquidity_aware_sizer.apply_sizing_cap(
                                base_size=per_coin_capital,
                                calculated_multiplier=actual_multiplier,
                                coin_symbol=candidate_coin
                            )

                    # CRITICAL SAFETY CHECK: Cap adjusted_size at available capital
                    if adjusted_size > per_coin_capital:
                        self.logger().warning(
                            f"⚠️  Adjusted size (€{adjusted_size:.2f}) exceeds available capital (€{per_coin_capital:.2f}) - capping to available"
                        )
                        adjusted_size = per_coin_capital

                    self.logger().info(
                        f"      💰 Allocating €{per_coin_capital:.2f} (adjusted: €{adjusted_size:.2f})"
                    )

                    grid_action = self._create_grid_action(candidate_coin, adjusted_size)
                    if grid_action:
                        actions.append(grid_action)
                        applied_notional = Decimal(str(grid_action.executor_config.total_amount_quote))

                        # Track exposure
                        self._update_exposure_tracking(candidate_coin, applied_notional)
                        self.risk_manager.register_open_trade(
                            symbol=candidate_coin,
                            notional=applied_notional,
                            now=now_ts,
                        )

                        # Track in active_coins
                        if grid_action.executor_config and grid_action.executor_config.id:
                            self.active_coins[candidate_coin] = grid_action.executor_config.id
                            self.logger().info(
                                f"      📊 Added {candidate_coin} to active coins: "
                                f"{list(self.active_coins.keys())} ({len(self.active_coins)}/{max_slots_for_loop})"  # noqa: E501
                            )

                        # Reset performance counter
                        if candidate_coin in self.coin_performance:
                            self.coin_performance[candidate_coin] = 0

                        self.logger().info(f"      ✨ Successfully started grid on {candidate_coin}")
                    else:
                        self.logger().warning(f"      ⚠️  Failed to create grid action for {candidate_coin}")

                except Exception as e:
                    self.logger().error(f"      ❌ Error creating executor for {candidate_coin}: {e}")
                    import traceback
                    self.logger().error(traceback.format_exc())

        return actions

    def _get_executor_info(self, executor_id: str) -> Optional[ExecutorInfo]:
        """
        Get executor info by ID

        Args:
            executor_id: Executor ID to look up

        Returns:
            ExecutorInfo if found, None otherwise
        """
        if not executor_id:
            return None
        return next(
            (e for e in self.executors_info if e.id == executor_id),
            None
        )

    def _is_executor_actually_active(self) -> bool:
        """
        Check if the tracked executor is actually active

        Returns:
            True if executor exists and is active
        """
        if not self.active_executor_id:
            return False

        # Check if executor exists in executors_info
        active_executor = next(
            (e for e in self.executors_info
             if e.id == self.active_executor_id and e.is_active),
            None
        )

        if not active_executor:
            # BUG FIX: Add grace period - newly created executors need time to appear in executors_info
            # Check if this executor was just created (within last 30 seconds)
            if not hasattr(self, '_executor_creation_times'):
                self._executor_creation_times = {}

            current_time = self.market_data_provider.time()
            creation_time = self._executor_creation_times.get(self.active_executor_id)

            if creation_time:
                time_since_creation = current_time - creation_time
                if time_since_creation < 30:  # 30 second grace period
                    self.logger().debug(
                        f"⏳ Executor {self.active_executor_id[:8]}... created {time_since_creation:.1f}s ago - "
                        f"waiting for orchestrator sync (grace period: 30s)"
                    )
                    return True  # Assume it's still active during grace period
            # Executor doesn't exist or is not active - check why it failed
            failed_executor = self._get_executor_info(self.active_executor_id)

            # CRITICAL: Check for NL-restriction errors FIRST (immediate blacklist, no retry)
            # Note: Check custom_info for nl_restricted flag set by executor
            if failed_executor and failed_executor.custom_info.get('nl_restricted'):
                restricted_coin = failed_executor.custom_info.get('nl_restricted_coin') or self.active_coin
                if restricted_coin:
                    self.logger().warning(
                        f"\ud83d\udeab NL-RESTRICTION DETECTED: {restricted_coin} is restricted for NL accounts\\n"
                        f"   \u2192 AUTO-BLACKLISTING immediately to prevent retries"
                    )
                    # Add to auto-blacklist (runtime)
                    self.auto_blacklisted_coins.add(restricted_coin)
                    # Add to persistent config blacklist
                    if hasattr(self.config, 'blacklist'):
                        if self.config.blacklist is None:
                            self.config.blacklist = []
                        if restricted_coin not in self.config.blacklist:
                            self.config.blacklist.append(restricted_coin)
                            self.logger().info(f"\u2705 Added {restricted_coin} to persistent config blacklist")
                        # Reset error counter (not needed for NL-restrictions, but clean up)
                        if restricted_coin in self.coin_error_count:
                            del self.coin_error_count[restricted_coin]
                        # Clear state and continue to next coin
                        self.active_coin = None
                        self.active_executor_id = None
                        self.global_risk_manager.reset_exposure()
                        return

            # Track errors for this coin (for automatic blacklisting)
            if self.active_coin:
                if self.active_coin not in self.coin_error_count:
                    self.coin_error_count[self.active_coin] = 0
                self.coin_error_count[self.active_coin] += 1

                # Auto-blacklist if too many errors
                if self.coin_error_count[self.active_coin] >= self.max_errors_per_coin:
                    if self.active_coin not in self.auto_blacklisted_coins:
                        self.auto_blacklisted_coins.add(self.active_coin)
                        self.logger().critical(
                            f"🚨 AUTO-BLACKLIST: {self.active_coin} has {self.coin_error_count[self.active_coin]} errors "  # noqa: E501
                            f"(threshold: {self.max_errors_per_coin}) - adding to blacklist to prevent loops"
                        )
                        # Also add to config blacklist if possible (persistent)
                        if hasattr(self.config, 'blacklist'):
                            if self.config.blacklist is None:
                                self.config.blacklist = []
                            if self.active_coin not in self.config.blacklist:
                                self.config.blacklist.append(self.active_coin)
                                self.logger().info(f"✅ Added {self.active_coin} to persistent blacklist")

            # Check if executor failed due to insufficient balance OR stop-loss
            if failed_executor and not failed_executor.is_active:
                close_type = str(failed_executor.close_type) if failed_executor.close_type else ""
                close_type_str = close_type.upper()

                # Check for insufficient balance indicators
                is_insufficient_balance = (
                    'INSUFFICIENT_BALANCE' in close_type_str
                    or 'INSUFFICIENT' in close_type_str
                    or ('BALANCE' in close_type_str and 'NOT ENOUGH' in close_type_str)
                    or 'budget' in close_type.lower()
                    or 'Not enough budget' in close_type
                )

                # Check for stop-loss trigger
                is_stop_loss = 'STOP_LOSS' in close_type_str

                if is_insufficient_balance:
                    # Executor failed due to insufficient balance - set cooldown
                    if self.active_coin:
                        self.logger().warning(
                            f"⚠️  Executor {self.active_executor_id[:8]}... failed due to insufficient balance "
                            f"(close_type: {close_type}). Setting 5-minute cooldown for {self.active_coin} before retry."  # noqa: E501
                        )
                        # Set cooldown: don't retry this coin for 5 minutes
                        self.last_insufficient_balance_time[self.active_coin] = self.market_data_provider.time()
                elif is_stop_loss:
                    # 🔧 CRITICAL FIX: Stop-loss triggered - set switch cooldown to prevent immediate re-entry
                    current_time = self.market_data_provider.time()
                    self.last_switch_time = current_time
                    if self.active_coin:
                        self.logger().critical(
                            f"🛑 STOP-LOSS EXIT: {self.active_coin} executor stopped due to stop-loss. "
                            f"Setting switch cooldown ({self.config.min_switch_interval_seconds}s) to prevent immediate re-entry."
                        )
                else:
                    # Log other failure reasons for debugging
                    self.logger().debug(
                        f"Executor {self.active_executor_id[:8]}... failed with close_type: {close_type}"
                    )

            # Clear tracking and reset exposure
            self.logger().warning(
                f"⚠️  Tracked executor {self.active_executor_id[:8]}... "
                f"not found or inactive - clearing state and resetting exposure"
            )
            # Reset exposure for the active coin if it exists
            if self.active_coin and self.active_coin in self.current_exposure_per_coin:
                old_exposure = self.current_exposure_per_coin[self.active_coin]
                self.total_exposure -= old_exposure
                del self.current_exposure_per_coin[self.active_coin]
                self.logger().info(
                    f"📊 Reset exposure: {self.active_coin} (was €{old_exposure:.2f}), "
                    f"Total now €{self.total_exposure:.2f}"
                )
            # MULTI-COIN: Also remove from active_coins
            if self.active_coin and self.active_coin in self.active_coins:
                del self.active_coins[self.active_coin]
                self.logger().info(f"📊 Removed {self.active_coin} from active_coins: {list(self.active_coins.keys())}")

            # BUG FIX: Clean up executor creation time tracking
            if hasattr(self, '_executor_creation_times') and self.active_executor_id in self._executor_creation_times:
                del self._executor_creation_times[self.active_executor_id]

            # MEMORY LEAK FIX: Clean up price history for this coin
            if self.active_coin and self.active_coin in self.price_history_for_volatility:
                del self.price_history_for_volatility[self.active_coin]
                self.logger().debug(f"🧹 Cleaned up price history for {self.active_coin}")

            self.active_executor_id = None
            self.active_coin = None
            return False

        return True

    def _should_bypass_grace_period(self, executor_info: ExecutorInfo, trading_pair: str) -> tuple[bool, str]:
        """
        Task 2.2: Check if grace period should be bypassed for immediate rotation/exit

        Args:
            executor_info: Executor to check
            trading_pair: Trading pair (e.g., "BTC-EUR")

        Returns:
            (should_bypass, reason) tuple
        """
        # Check 1: Executor in error state
        if getattr(self.config, 'grace_bypass_on_executor_error', True):
            if executor_info and not executor_info.is_active:
                close_type = str(executor_info.close_type) if executor_info.close_type else ""
                if 'FAILED' in close_type or 'ERROR' in close_type or 'INSUFFICIENT_BALANCE' in close_type:
                    return True, f"executor error: {close_type}"

        # Check 2: Stop-loss hit
        if getattr(self.config, 'grace_bypass_on_sl_hit', True):
            if executor_info and executor_info.custom_info:
                sl_hit = executor_info.custom_info.get('stop_loss_hit', False)
                if sl_hit:
                    return True, "stop-loss triggered"

        # Check 3: Regime flip (BULL→BEAR or vice versa)
        if getattr(self.config, 'grace_bypass_on_regime_flip', True):
            if hasattr(self, 'market_regime_filter') and self.market_regime_filter:
                entry_regime = executor_info.custom_info.get('entry_regime') if executor_info and executor_info.custom_info else None
                current_regime = self.market_regime_filter.get_current_regime()

                # Extreme flip: BULL→BEAR or BEAR→BULL
                if entry_regime and current_regime:
                    if (entry_regime == 'BULL' and current_regime == 'BEAR') or \
                       (entry_regime == 'BEAR' and current_regime == 'BULL'):
                        return True, f"regime flip: {entry_regime}→{current_regime}"

        # Check 4: Slot pressure (all slots full + better opportunity)
        if getattr(self.config, 'grace_bypass_on_slot_pressure', True):
            # Check if all slots are full
            active_count = len([e for e in self.executors_info if e.is_active])
            max_grids = getattr(self.config, 'max_simultaneous_coins', 2)
            if active_count >= max_grids:
                return True, f"slot pressure ({active_count}/{max_grids} full)"

        # Check 5: Stale/unavailable market data
        if getattr(self.config, 'grace_bypass_on_stale_data', True):
            # Check if market data provider marks this symbol as stale
            if hasattr(self.market_data_provider, '_stale_symbols'):
                if trading_pair in self.market_data_provider._stale_symbols:
                    return True, "stale market data"

            # Also check if we can't get current price
            try:
                current_price = self.connector.get_mid_price(trading_pair)
                if current_price is None or current_price <= 0:
                    return True, "no price data available"
            except Exception:
                return True, "market data error"

        return False, ""

    def _can_safely_close_position(self, trading_pair: str, executor_info: ExecutorInfo) -> tuple[bool, str]:
        """
        Task 2.3: Pre-close validation to prevent FAILED closes and dust issues

        Args:
            trading_pair: Trading pair (e.g., "BTC-EUR")
            executor_info: Executor information

        Returns:
            (can_close, reason) tuple
        """
        try:
            # Extract base asset from trading pair (e.g., "BTC" from "BTC-EUR")
            base_asset = trading_pair.split("-")[0]

            # Get actual exchange balance (NOT bot's tracked balance)
            try:
                actual_balance = self.connector.get_balance(base_asset)
            except Exception as e:
                return False, f"Can't query balance: {e}"

            # Get exchange trading rules (min order size varies per pair!)
            try:
                trading_rule = self.connector.trading_rules.get(trading_pair)
                if not trading_rule:
                    return False, f"No trading rules found for {trading_pair}"

                min_order_size = trading_rule.min_order_size
                min_notional = trading_rule.min_notional
            except Exception as e:
                return False, f"Can't get trading rules: {e}"

            # Check 1: Do we have enough tokens to place close order?
            if actual_balance < min_order_size:
                value_eur = actual_balance * self.connector.get_mid_price(trading_pair) if self.connector.get_mid_price(trading_pair) else Decimal("0")
                return False, f"Dust: {actual_balance:.8f} {base_asset} < min {min_order_size:.8f} (€{value_eur:.2f})"

            # Check 2: Is value > min notional?
            mid_price = self.connector.get_mid_price(trading_pair)
            if mid_price is None or mid_price <= 0:
                return False, "No price data available"

            order_value = actual_balance * mid_price
            if order_value < min_notional:
                return False, f"Below min notional: €{order_value:.2f} < €{min_notional:.2f}"

            # Check 3: Verify position size matches executor tracking
            if executor_info and executor_info.custom_info:
                tracked_position = executor_info.custom_info.get('position_size_base', Decimal("0"))
                if tracked_position > 0:
                    # Allow 1% tolerance for rounding
                    diff_pct = abs(actual_balance - tracked_position) / tracked_position
                    if diff_pct > Decimal("0.01"):
                        self.logger().warning(
                            f"⚠️ Position mismatch for {trading_pair}: "
                            f"exchange={actual_balance:.8f}, tracked={tracked_position:.8f} "
                            f"(diff={diff_pct * 100:.2f}%)"
                        )

            return True, "OK"

        except Exception as e:
            self.logger().error(f"Error in pre-close validation for {trading_pair}: {e}")
            return False, f"Validation error: {e}"

    def _monitor_stop_loss_and_volatility(self) -> None:
        """
        Phase 1.1 & 1.2: Monitor stop-loss and volatility for active executor

        - Checks if stop-loss was triggered (via executor status)
        - Monitors volatility for circuit breaker
        - Logs stop-loss events
        """
        if not self.active_coin:
            return

        try:
            # Get current price for active coin
            trend = self.trend_calculator.get_trend(self.active_coin)
            if not trend:
                return

            current_price = Decimal(str(trend.current_price))
            current_time = self.market_data_provider.time()

            # Phase 1.1: Check stop-loss status
            entry_price = self.entry_prices.get(self.active_coin)
            if entry_price:
                # Calculate current loss percentage
                loss_pct = float((current_price - entry_price) / entry_price * 100)
                stop_loss_price = entry_price * (Decimal('1') - self.config.stop_loss_pct)

                # Check if executor was stopped due to stop-loss
                executor = next(
                    (e for e in self.executors_info if e.id == self.active_executor_id),
                    None
                )

                if executor and not executor.is_active:
                    # Executor stopped - check if it was due to stop-loss
                    if executor.close_type and 'STOP_LOSS' in str(executor.close_type):
                        if self.active_coin not in self.stop_loss_triggered:
                            self.stop_loss_triggered[self.active_coin] = current_time
                            self.logger().critical(
                                f"🛑 STOP-LOSS TRIGGERED for {self.active_coin}!\n"
                                f"   Entry Price: €{entry_price:.4f}\n"
                                f"   Stop Price: €{stop_loss_price:.4f}\n"
                                f"   Current Price: €{current_price:.4f}\n"
                                f"   Loss: {loss_pct:.2f}%\n"
                                f"   Executor stopped - clearing position"
                            )
                            # Clear entry price tracking
                            if self.active_coin in self.entry_prices:
                                del self.entry_prices[self.active_coin]

                # Log stop-loss proximity warning
                if loss_pct <= -float(self.config.stop_loss_pct) * 50:  # 50% of stop-loss threshold
                    self.logger().warning(
                        f"⚠️  Stop-loss proximity: {self.active_coin} at {loss_pct:.2f}% "
                        f"(stop-loss: {float(self.config.stop_loss_pct) * 100:.1f}%)"
                    )

            # Phase 1.2: Monitor volatility for circuit breaker
            # Track price history for volatility calculation
            if self.active_coin not in self.price_history_for_volatility:
                self.price_history_for_volatility[self.active_coin] = []

            # Add current price to history
            self.price_history_for_volatility[self.active_coin].append({
                'price': float(current_price),
                'timestamp': current_time
            })

            # Remove old data points (keep only last 60 seconds)
            cutoff_time = current_time - self.circuit_breaker_window_seconds
            self.price_history_for_volatility[self.active_coin] = [
                p for p in self.price_history_for_volatility[self.active_coin]
                if p['timestamp'] > cutoff_time
            ]

            # Calculate volatility if we have enough data points
            price_history = self.price_history_for_volatility[self.active_coin]
            if len(price_history) >= 2:
                prices = [p['price'] for p in price_history]
                min_price = min(prices)
                max_price = max(prices)

                # Calculate percentage change
                if min_price > 0:
                    volatility_pct = ((max_price - min_price) / min_price) * 100

                    # Check if volatility exceeds threshold
                    if volatility_pct >= self.circuit_breaker_threshold_pct:
                        if not self.circuit_breaker_active:
                            self.circuit_breaker_active = True
                            self.circuit_breaker_triggered_at = current_time
                            self.logger().critical(
                                f"🛑 CIRCUIT BREAKER TRIGGERED!\n"
                                f"   Coin: {self.active_coin}\n"
                                f"   Volatility: {volatility_pct:.2f}% in {self.circuit_breaker_window_seconds}s\n"
                                f"   Threshold: {self.circuit_breaker_threshold_pct}%\n"
                                f"   Price Range: €{min_price:.4f} - €{max_price:.4f}\n"
                                f"   Trading PAUSED - Manual resume required"
                            )
                    else:
                        # Volatility normalized - check if we should auto-resume
                        # (For now, manual resume only - can add auto-resume later)
                        pass

        except Exception as e:
            self.logger().error(f"❌ Error in stop-loss/volatility monitoring: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

    def reset_circuit_breaker(self) -> None:
        """
        Phase 1.2: Manually reset circuit breaker to resume trading

        Call this method to resume trading after circuit breaker was triggered.
        """
        if self.circuit_breaker_active:
            self.circuit_breaker_active = False
            self.circuit_breaker_triggered_at = None
            # Clear volatility history
            self.price_history_for_volatility.clear()
            self.logger().info("✅ Circuit breaker RESET - Trading resumed")
        else:
            self.logger().info("ℹ️  Circuit breaker not active - no reset needed")

    def reset_api_errors(self) -> None:
        """
        Phase 1.3: Manually reset API error pause to resume trading

        Call this method to resume trading after API errors were paused.
        """
        if self.api_error_paused:
            self.api_error_paused = False
            self.api_error_paused_at = None
            self.consecutive_api_errors = 0
            self.api_error_backoff_seconds = 1.0
            self.logger().info("✅ API error pause RESET - Trading resumed")
        else:
            self.logger().info("ℹ️  API errors not paused - no reset needed")

    # ==============================================================================
    # STORY A2: SESSION BLACKLIST & ANTI-FLIPFLOP
    # ==============================================================================

    def _is_blacklisted(self, symbol: str, now: float) -> bool:
        """
        Check if symbol is currently blacklisted (Story A2)

        Args:
            symbol: Trading pair (e.g., 'BTC-EUR')
            now: Current timestamp

        Returns:
            True if blacklisted and not expired, False otherwise
        """
        if symbol not in self.session_blacklist:
            return False

        expiry_time = self.session_blacklist[symbol]
        return now < expiry_time

    def _add_to_blacklist(self, symbol: str, reason: str, now: float) -> None:
        """
        Add symbol to session blacklist (Story A2)

        Args:
            symbol: Trading pair to blacklist
            reason: Reason for blacklisting (e.g., 'NO_FILL_TIMEOUT')
            now: Current timestamp
        """
        # Get blacklist duration from config (default 30 min = 1800 sec)
        blacklist_duration = getattr(self.config, 'blacklist_after_timeout_sec', 1800)

        # If duration is 0, blacklisting is disabled
        if blacklist_duration <= 0:
            self.logger().debug(f"Story A2: Blacklisting disabled (duration=0), skipping {symbol}")
            return

        expiry_time = now + blacklist_duration
        self.session_blacklist[symbol] = expiry_time

        expiry_datetime = datetime.fromtimestamp(expiry_time).strftime('%H:%M:%S')
        self.logger().info(
            f"🚫 BLACKLIST_ADD | Story A2: {symbol} blacklisted until {expiry_datetime} "
            f"({blacklist_duration / 60:.0f}m) | Reason: {reason}"
        )

    def _purge_expired_blacklist(self, now: float) -> None:
        """
        Remove expired entries from session blacklist (Story A2)

        Args:
            now: Current timestamp
        """
        expired = [sym for sym, expiry in self.session_blacklist.items() if now >= expiry]

        for symbol in expired:
            del self.session_blacklist[symbol]
            self.logger().info(f"✅ BLACKLIST_EXPIRE | Story A2: {symbol} blacklist expired - now selectable")

    def _get_blacklist_info(self, symbol: str, now: float) -> Optional[str]:
        """
        Get blacklist expiry info for a symbol (for logging)

        Args:
            symbol: Trading pair
            now: Current timestamp

        Returns:
            Formatted string with expiry info, or None if not blacklisted
        """
        if symbol not in self.session_blacklist:
            return None

        expiry_time = self.session_blacklist[symbol]
        if now >= expiry_time:
            return None

        remaining_sec = int(expiry_time - now)
        expiry_datetime = datetime.fromtimestamp(expiry_time).strftime('%H:%M:%S')
        return f"expires in {remaining_sec // 60}m at {expiry_datetime}"

    def _sync_risk_state(self) -> None:
        """
        Synchronize realised PnL and cooldown information with the global risk manager.

        Memory cleanup moved to control_loop() for better frequency and comprehensive coverage.
        """
        now = self.market_data_provider.time()

        # 🔧 CLEANUP: Remove terminated/failed executors from active_coins
        # This prevents "ghost actives" where bot thinks coin is active but it's not
        for executor in self.executors_info:
            if not executor.is_active and executor.status == RunnableStatus.TERMINATED:
                trading_pair = getattr(getattr(executor, "config", None), "trading_pair", None)
                if trading_pair and trading_pair in self.active_coins:
                    if self.active_coins[trading_pair] == executor.id:
                        del self.active_coins[trading_pair]
                        self.logger().info(
                            f"🧹 Cleanup: Removed {trading_pair} from active_coins (executor terminated)"
                        )
                        # MEMORY LEAK FIX: Clean up price history for this coin
                        if trading_pair in self.price_history_for_volatility:
                            del self.price_history_for_volatility[trading_pair]
                            self.logger().debug(f"🧹 Cleaned up price history for {trading_pair}")

        # Track realised PnL for terminated executors exactly once
        for executor in self.executors_info:
            if executor.status == RunnableStatus.TERMINATED:
                if executor.id not in self._realised_executors_tracked:
                    realised_pnl = Decimal(str(executor.net_pnl_quote))
                    trading_pair = getattr(getattr(executor, "config", None), "trading_pair", self.active_coin)
                    if trading_pair:
                        # ==============================================================================
                        # STORY B2: WRITE EXECUTION AUDIT RECORD
                        # ==============================================================================
                        # Write audit trail for this completed execution
                        try:
                            # Determine close reason from close_type
                            from hummingbot.strategy_v2.models.executors import CloseType
                            close_type = executor.close_type

                            if close_type == CloseType.STOP_LOSS:
                                close_reason = "stop_loss"
                            elif close_type == CloseType.TAKE_PROFIT:
                                close_reason = "take_profit"
                            elif close_type == CloseType.NO_FILL_TIMEOUT:
                                close_reason = "no_fill_timeout"
                            elif close_type == CloseType.NO_PROGRESS_TIMEOUT:
                                close_reason = "no_progress_timeout"
                            elif close_type == CloseType.TIME_LIMIT:
                                close_reason = "time_limit"
                            elif hasattr(CloseType, 'HARD_CAP_TIME_LIMIT') and close_type == CloseType.HARD_CAP_TIME_LIMIT:
                                close_reason = "hard_cap_time_limit"
                            elif hasattr(CloseType, 'SWITCH') and close_type == CloseType.SWITCH:
                                close_reason = "switch"
                            else:
                                close_reason = str(close_type) if close_type else "manual"

                            # Create audit record from executor
                            audit = create_audit_from_executor(executor, close_reason)

                            # Write to JSONL file (audits/YYYY-MM-DD.jsonl)
                            writer = AuditWriter()
                            writer.write(audit)

                            # Throttled log to avoid spam (max 1 per 30s for "audit_written")
                            if should_log("audit_written", interval_sec=30):
                                slog = StructuredLogger(self.logger())
                                slog.info(
                                    "AUDIT_WRITTEN",
                                    symbol=audit.symbol,
                                    close_reason=close_reason,
                                    pnl_net=float(audit.net_pnl_quote),
                                    duration_sec=audit.duration_sec
                                )
                        except Exception as e:
                            self.logger().error(f"Story B2: Failed to write audit record for {trading_pair}: {e}")
                        # ==============================================================================

                        self.risk_manager.register_close_trade(
                            symbol=trading_pair,
                            realised_pnl_quote=realised_pnl,
                            now=now,
                        )

                        # ===== FEATURE 1.3: RECORD TRADE FOR PERFORMANCE TRACKING =====
                        if self.performance_tracker:
                            try:
                                # Extract trade data from executor
                                executor_config = getattr(executor, "config", None)
                                custom_info = getattr(executor, "custom_info", {}) or {}

                                entry_price = custom_info.get("entry_price", Decimal("0"))
                                entry_time_ts = custom_info.get("entry_time", now - 3600)  # Fallback: 1h ago
                                position_size = Decimal(str(getattr(executor_config, "total_amount_quote", 50.0)))

                                # Calculate exit price from PnL (rough estimate)
                                # PnL = (exit_price - entry_price) * position_size / entry_price
                                # exit_price ≈ entry_price * (1 + PnL / position_size)
                                exit_price = entry_price
                                if entry_price > 0 and position_size > 0:
                                    pnl_pct = realised_pnl / position_size
                                    exit_price = entry_price * (Decimal("1") + pnl_pct)

                                # Estimate fees (Kraken: 0.16% maker, 0.26% taker - use 0.21% avg)
                                fees = position_size * Decimal("0.0021")

                                # Determine exit reason from close_type
                                close_type = str(executor.close_type) if executor.close_type else "unknown"
                                if "STOP_LOSS" in close_type:
                                    exit_reason = "stop_loss"
                                elif "TAKE_PROFIT" in close_type:
                                    exit_reason = "profit_target"
                                elif "SWITCH" in close_type:
                                    exit_reason = "switch"
                                else:
                                    exit_reason = "manual" if realised_pnl >= 0 else "stop_loss"

                                # Convert timestamps to datetime objects
                                from datetime import datetime
                                entry_dt = datetime.fromtimestamp(entry_time_ts)
                                exit_dt = datetime.fromtimestamp(now)

                                self.performance_tracker.record_trade(
                                    symbol=trading_pair,
                                    entry_time=entry_dt,
                                    exit_time=exit_dt,
                                    entry_price=float(entry_price),
                                    exit_price=float(exit_price),
                                    position_size_eur=float(position_size),
                                    realized_pnl_eur=float(realised_pnl),
                                    fees_eur=float(fees),
                                    exit_reason=exit_reason
                                )

                                self.logger().info(
                                    f"📊 Feature 1.3: Trade recorded - {trading_pair} "
                                    f"PnL: €{float(realised_pnl):.2f}, Reason: {exit_reason}"
                                )
                            except Exception as e:
                                self.logger().error(f"❌ Feature 1.3: Failed to record trade: {e}")

                        # ==============================================================================
                        # STORY A2: SESSION BLACKLIST ON TIMEOUT (Anti-Flipflop)
                        # ==============================================================================
                        # Check if this executor closed due to timeout - if so, blacklist the symbol
                        # Only process each executor once (idempotency)
                        if executor.id not in self._processed_timeout_executors:
                            self._processed_timeout_executors.add(executor.id)

                            # Import CloseType enum
                            from hummingbot.strategy_v2.models.executors import CloseType

                            # Check if close_type is a timeout-related reason
                            timeout_close_types = {
                                CloseType.NO_FILL_TIMEOUT,
                                CloseType.NO_PROGRESS_TIMEOUT,
                                CloseType.TIME_LIMIT,
                                CloseType.HARD_CAP_TIME_LIMIT,
                            }

                            if executor.close_type in timeout_close_types:
                                # Timeout close - add to blacklist
                                reason = executor.close_type.name if executor.close_type else "TIMEOUT"
                                self._add_to_blacklist(trading_pair, reason, now)
                            else:
                                # Non-timeout close (e.g., TAKE_PROFIT, normal completion) - no blacklist
                                close_type_name = executor.close_type.name if executor.close_type else "UNKNOWN"
                                self.logger().debug(
                                    f"Story A2: {trading_pair} closed with {close_type_name} - no blacklist (normal exit)"
                                )

                    self._realised_executors_tracked[executor.id] = realised_pnl

        # Update unrealised PnL snapshot for the active position (if any)
        if self.active_coin and self.active_executor_id:
            executor_info = next(
                (e for e in self.executors_info if e.id == self.active_executor_id),
                None
            )
            if executor_info:
                self.risk_manager.update_unrealised(
                    symbol=self.active_coin,
                    unrealised_quote=Decimal(str(executor_info.net_pnl_quote)),
                )

    @staticmethod
    def _compute_trend_strength(trend) -> float:
        """
        Normalize composite trend metrics into a bounded strength value.

        Returns trend percentage as decimal (e.g., 2.5% → 0.025)
        Uses consensus_trend_pct (preferred) as it's the most reliable metric.
        """
        if not trend:
            return 0.0

        # ALWAYS use consensus_trend_pct if available (most reliable metric)
        consensus = getattr(trend, "consensus_trend_pct", None)

        # Fallback order: consensus → trend_pct → trend_score
        if consensus is None or (isinstance(consensus, (int, float, Decimal)) and float(consensus) == 0.0):
            consensus = getattr(trend, "trend_pct", None)
            if consensus is None or (isinstance(consensus, (int, float, Decimal)) and float(consensus) == 0.0):
                consensus = getattr(trend, "trend_score", 0)

        # Convert to float if Decimal
        if isinstance(consensus, Decimal):
            consensus = float(consensus)

        # Convert percentage to decimal (2.5% → 0.025)
        normalized = consensus / 100.0

        # Clamp to reasonable range [-1, 1] (equivalent to -100% to +100%)
        if normalized > 1.0:
            return 1.0
        if normalized < -1.0:
            return -1.0
        return normalized

    def _check_position_limits(self, symbol: str) -> bool:
        """
        Phase 1.4: Check if position limits allow creating executor for this coin

        Phase 2: Integrated with RiskGuard v2.0 + EventLogger for observability.
        Emits gate_denied events with stage=RISK when limits exceeded.

        Note: Since we only have 1 active executor at a time, we mainly check:
        - Max exposure per coin (if switching to same coin)
        - Max total exposure (should always be <= 1 executor worth)

        Args:
            symbol: Trading pair symbol

        Returns:
            True if position limits allow, False otherwise
        """
        try:
            import uuid

            # Generate correlation ID for this Risk stage check
            correlation_id = str(uuid.uuid4())

            # Calculate new exposure
            requested_allocation = self._next_allocation_quote if self._next_allocation_quote else Decimal(
                str(self.config.total_amount_quote))
            new_exposure = requested_allocation
            current_coin_exposure = self.current_exposure_per_coin.get(symbol, Decimal("0"))

            # For now, use grid amount as capital reference
            # In future, could get actual account balance
            total_capital = self.config.risk_reference_balance

            # Phase 2: Use RiskGuard v2.0 for exposure checks + event emission
            allowed, reason = self.risk_guard_v2.can_open_position(
                symbol=symbol,
                size_eur=new_exposure,
                correlation_id=correlation_id
            )

            if not allowed:
                self.logger().warning(f"⚠️  RiskGuard denied position: {reason}")
                return False

            # Emit gate_passed event for successful risk check
            if self.event_logger and self.event_logger.enabled:
                self.event_logger.emit_gate_passed(
                    correlation_id=correlation_id,
                    symbol=symbol,
                    stage=Stage.RISK,
                    metadata={
                        "exchange": self.config.connector_name,
                        "strategy": "spot_grid",
                        "final_reason": "risk limits passed",
                        "position_size_eur": float(new_exposure),
                        "current_coin_exposure": float(current_coin_exposure),
                        "total_capital": float(total_capital)
                    }
                )

            # Legacy code below (kept for backward compatibility, but RiskGuard already checked this)

            # Since we only have 1 executor at a time, check:
            # 1. If switching to same coin, check max per coin limit
            if symbol == self.active_coin and current_coin_exposure > Decimal("0"):
                max_per_coin = total_capital * self.config.max_exposure_per_coin_pct
                if current_coin_exposure + new_exposure > max_per_coin:
                    self.logger().warning(
                        f"⚠️  Max exposure per coin exceeded for {symbol}:\n"
                        f"   Current: €{current_coin_exposure:.2f}\n"
                        f"   New: €{new_exposure:.2f}\n"
                        f"   Limit: €{max_per_coin:.2f} ({self.config.max_exposure_per_coin_pct * 100}%)"
                    )
                    return False

            # 2. Check max total exposure
            # Since we only have 1 active executor at a time, when switching coins:
            # - We subtract old exposure and add new exposure
            # - The new total should be <= max_total_exposure_pct of capital
            # - But since we only have 1 executor, we allow up to 1 executor worth
            new_total_exposure = self.total_exposure - current_coin_exposure + new_exposure
            max_total = total_capital * self.config.max_total_exposure_pct

            # Special case: If we have no active executor, allow creating one even if it exceeds the percentage
            # This handles the case where total_amount_quote (€100) > max_total_exposure_pct (90% = €90)
            # For single-executor strategy, we need at least 1 executor worth of capital
            if self.total_exposure == Decimal("0") and new_exposure <= total_capital:
                # No current exposure, and new exposure is within total capital - allow it
                # This handles the initial case where we're creating the first executor
                return True

            if new_total_exposure > max_total:
                self.logger().warning(
                    f"⚠️  Max total exposure exceeded:\n"
                    f"   Current total: €{self.total_exposure:.2f}\n"
                    f"   New total: €{new_total_exposure:.2f}\n"
                    f"   Limit: €{max_total:.2f} ({self.config.max_total_exposure_pct * 100}%)"
                )
                return False

            return True

        except Exception as e:
            self.logger().error(f"❌ Error checking position limits: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            # On error, allow (fail open) - but log it
            return True

    def _emit_execution_denial(
        self,
        symbol: str,
        reason_code: ReasonCode,
        reason_msg: str,
        correlation_id: str,
        metadata: Dict[str, Any]
    ) -> None:
        """
        Phase 3: Emit execution stage denial event.

        Args:
            symbol: Trading pair symbol
            reason_code: Execution denial reason code
            reason_msg: Human-readable reason
            correlation_id: UUID for event correlation
            metadata: Additional context
        """
        if not hasattr(self, 'event_logger') or not self.event_logger or not self.event_logger.enabled:
            return

        self.event_logger.emit_gate_denied(
            correlation_id=correlation_id,
            symbol=symbol,
            stage=Stage.EXECUTION,
            reason_code=reason_code,
            reason_msg=reason_msg,
            metadata=metadata
        )

    def _emit_regime_denial(
        self,
        symbol: str,
        reason_code: ReasonCode,
        reason_msg: str,
        correlation_id: str,
        metadata: Dict[str, Any]
    ) -> None:
        """
        Phase 3: Emit regime stage denial event.

        Args:
            symbol: Trading pair symbol
            reason_code: Regime denial reason code
            reason_msg: Human-readable reason
            correlation_id: UUID for event correlation
            metadata: Additional context
        """
        if not hasattr(self, 'event_logger') or not self.event_logger or not self.event_logger.enabled:
            return

        self.event_logger.emit_gate_denied(
            correlation_id=correlation_id,
            symbol=symbol,
            stage=Stage.REGIME,
            reason_code=reason_code,
            reason_msg=reason_msg,
            metadata=metadata
        )

    def _update_exposure_tracking(self, symbol: str, amount: Decimal) -> None:
        """
        Phase 1.4: Update exposure tracking when executor is created/stopped

        Args:
            symbol: Trading pair symbol
            amount: Amount to add (positive) or remove (negative)
        """
        try:
            current = self.current_exposure_per_coin.get(symbol, Decimal("0"))
            new_exposure = current + amount

            if new_exposure <= 0:
                # Remove from tracking
                if symbol in self.current_exposure_per_coin:
                    del self.current_exposure_per_coin[symbol]
                self.total_exposure -= current
            else:
                # Update tracking
                self.total_exposure = self.total_exposure - current + new_exposure
                self.current_exposure_per_coin[symbol] = new_exposure

            self.logger().debug(
                f"📊 Exposure updated: {symbol} = €{new_exposure:.2f}, "
                f"Total = €{self.total_exposure:.2f}"
            )
        except Exception as e:
            self.logger().error(f"❌ Error updating exposure tracking: {e}")

    def _should_create_new_grid(self, best_coin: str) -> bool:
        """
        Determine if we should create a new grid

        Phase 3: Enhanced switch logic with smart thresholds and cost calculation

        MULTI-COIN SUPPORT:
        - When max_simultaneous_coins > 1, allows multiple active coins
        - Creates new executor if room available (len(active_coins) < max)
        - Only switches if all slots are full

        Args:
            best_coin: Symbol of best trending coin

        Returns:
            True if should create new grid
        """
        self._next_allocation_quote = None
        now_val = self.market_data_provider.time()

        # MULTI-COIN: Check if best_coin is already trading
        if best_coin in self.active_coins:
            self.logger().info(f"✅ {best_coin} already has active executor - keep running")

            # Phase 3: Emit ALREADY_TRADING event
            correlation_id = str(uuid.uuid4())
            self._emit_execution_denial(
                symbol=best_coin,
                reason_code=ReasonCode.ALREADY_TRADING,
                reason_msg=f"{best_coin} already has active executor",
                correlation_id=correlation_id,
                metadata={
                    "active_coins": list(self.active_coins.keys()),
                    "slot_count": len(self.active_coins),
                    "max_slots": self.max_simultaneous_coins,
                    "timestamp": self.market_data_provider.time()
                }
            )

            return False

        # MULTI-COIN: Check if we have room for more coins
        max_slots_for_capital = self._get_current_max_slots()
        if max_slots_for_capital > 1:
            current_count = len(self.active_coins)
            if current_count < max_slots_for_capital:
                # Room available - create executor for best_coin (if meets other criteria)
                self.logger().info(
                    f"📊 Multi-coin mode: {current_count}/{self.max_simultaneous_coins} slots used - "
                    f"adding {best_coin}"
                )
                # 🔧 FIX: In multi-coin ADD mode, skip hold time check (only applies to SWITCHING)
                # Check risk manager and return True immediately to add the coin
                # Calculate per-coin capital allocation
                per_coin_capital = Decimal(str(self.config.total_amount_quote)) / \
                    Decimal(str(max(1, self.max_simultaneous_coins)))
                requested_notional = per_coin_capital
                allowed = self.risk_manager.can_open_trade(
                    symbol=best_coin,
                    requested_notional=requested_notional,
                    now=now_val,
                    logger=self.logger()
                )
                if allowed is None:
                    self.logger().warning(
                        f"🛑 Risk manager blocked adding {best_coin} (see details above)"
                    )
                    return False
                self._next_allocation_quote = allowed
                return True  # ✅ ADD new coin - no hold time required
            else:
                # All slots full - but don't block here!
                # The multi-coin loop in determine_executor_actions() will handle this
                # by NOT creating an action for this coin (first coin in top_coins is handled separately)
                # Just log that we're at capacity
                self.logger().debug(
                    f"📊 Multi-coin mode: All {self.max_simultaneous_coins} slots filled "
                    f"({list(self.active_coins.keys())})"
                )
                # 🔧 FIX: Don't return False - let startup delay check below proceed
                # This allows the multi-coin loop to evaluate other coins properly

        # No active coin - check startup delay first
        if not self.active_coin and len(self.active_coins) == 0:
            # Check if minimum startup wait time has passed
            min_startup_wait = getattr(self.config, 'min_startup_wait_seconds', 3600)
            time_since_start = time.time() - self.bot_start_time

            if time_since_start < min_startup_wait:
                remaining = min_startup_wait - time_since_start
                self.logger().info(
                    f"⏰ Startup delay active - waiting {remaining / 60:.1f} more minutes "
                    f"({remaining:.0f} seconds) before first trade"
                )

                # Phase 3: Emit STARTUP_DELAY event
                correlation_id = str(uuid.uuid4())
                self._emit_execution_denial(
                    symbol=best_coin,
                    reason_code=ReasonCode.STARTUP_DELAY,
                    reason_msg=f"Startup delay active - {remaining / 60:.1f} min remaining",
                    correlation_id=correlation_id,
                    metadata={
                        "time_since_start_sec": time_since_start,
                        "min_startup_wait_sec": min_startup_wait,
                        "remaining_sec": remaining,
                        "timestamp": time.time()
                    }
                )

                return False

            # Startup delay passed - allow first trade
            self.logger().info(
                f"✅ Startup delay passed ({time_since_start / 60:.1f} minutes) - "
                f"ready to create first grid for {best_coin}"
            )

            # 🧠 SmartEntry Filter Check (if enabled)
            if not self._check_smart_entry_filter(best_coin):
                return False

            # Calculate per-coin capital for multi-coin mode
            per_coin_capital = Decimal(str(self.config.total_amount_quote)) / \
                Decimal(str(max(1, self.max_simultaneous_coins)))
            requested_notional = per_coin_capital
            allowed = self.risk_manager.can_open_trade(
                symbol=best_coin,
                requested_notional=requested_notional,
                now=now_val,
                logger=self.logger()
            )
            if allowed is None:
                self.logger().warning(
                    f"🛑 Risk manager blocked initial entry for {best_coin} (see details above)"
                )
                return False
            self._next_allocation_quote = allowed
            return True

        # Validate executor is actually active
        if not self._is_executor_actually_active():
            # Executor doesn't exist - create new one
            self.logger().info(f"🔄 No active executor found - creating new grid for {best_coin}")

            # 🧠 SmartEntry Filter Check (if enabled)
            if not self._check_smart_entry_filter(best_coin):
                return False

            # ⏱️  Multi-timeframe buy protection check
            if not self._check_multi_timeframe_buy(best_coin):
                return False

            # Calculate per-coin capital for multi-coin mode
            per_coin_capital = Decimal(str(self.config.total_amount_quote)) / \
                Decimal(str(max(1, self.max_simultaneous_coins)))
            requested_notional = per_coin_capital
            allowed = self.risk_manager.can_open_trade(
                symbol=best_coin,
                requested_notional=requested_notional,
                now=now_val,
            )
            if allowed is None:
                self.logger().warning(
                    f"🛑 Risk manager prevented re-creating grid for {best_coin}"
                )
                return False
            self._next_allocation_quote = allowed
            return True

        # Same coin - don't switch
        if best_coin == self.active_coin:
            self.logger().info(f"✅ {best_coin} still best - keep current grid")
            return False

        # Get trend data first (needed for hold time exception check)
        active_trend = self.trend_calculator.get_trend(self.active_coin)
        best_trend = self.trend_calculator.get_trend(best_coin)

        if not active_trend or not best_trend:
            self.logger().warning("⚠️  Missing trend data - cannot evaluate switch")
            return False

        # Phase 3.3: Minimum Hold Time - Never switch <15 minutes (anti-whipsaw)
        # Exception: stop-loss breach (handled elsewhere)
        # Exception: Active coin has negative trend - allow early exit
        # Exception: Best coin is MUCH better (opportunity cost protection)
        time_since_switch = now_val - self.last_switch_time
        min_hold_time = float(self.risk_manager.min_hold_seconds)

        # Get trend values
        active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct  # noqa: E501
        best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct  # noqa: E501
        trend_difference = best_trend_value - active_trend_value

        active_strength = self._compute_trend_strength(active_trend)
        best_strength = self._compute_trend_strength(best_trend)

        # CRITICAL: If active coin is losing significantly, FORCE switch (panic protection)
        negative_trend_threshold = float(self.config.trend_min_exit_strength)
        is_panic_switch = active_strength < negative_trend_threshold

        if is_panic_switch:
            # Active coin is losing badly - FORCE switch regardless of other checks
            self.logger().warning(
                f"🚨 PANIC SWITCH: Active coin {self.active_coin} has negative trend ({active_trend_value:+.2f}%) "
                f"< {negative_trend_threshold}% - FORCING switch to {best_coin} ({best_trend_value:+.2f}%)"
            )
            # Only check liquidity - bypass switch threshold and cost checks
            if not self._check_liquidity_requirements(best_coin):
                self.logger().warning(
                    f"⚠️  {best_coin} doesn't meet liquidity requirements - but panic switch, allowing anyway"
                )
            # Force switch - return True immediately
            return True

        # NEW: If best coin is MUCH better (opportunity cost protection)
        # Allow switch if: best_trend > 2% AND difference > 2% AND best is at least 2x better
        opportunity_threshold = self.config.trend_min_entry_strength
        opportunity_difference = 0.5
        opportunity_multiplier = 1.5

        is_opportunity_switch = (
            best_strength > opportunity_threshold
            and (best_strength - active_strength) > opportunity_difference
            and best_strength >= active_strength * opportunity_multiplier
        )

        if is_opportunity_switch and time_since_switch < min_hold_time:
            # Best coin is MUCH better - allow switch even before hold time expires
            self.logger().warning(
                f"💎 OPPORTUNITY SWITCH: Best coin {best_coin} ({best_trend_value:+.2f}%) is MUCH better "
                f"than active {self.active_coin} ({active_trend_value:+.2f}%) - "
                f"difference: {trend_difference:+.2f}% - "
                f"allowing early switch (hold time: {time_since_switch / 60:.1f}/{min_hold_time / 60:.1f} min)"
            )
            # Continue to other checks but be more lenient
        elif active_trend_value < 0 and time_since_switch < min_hold_time:
            # Active coin is losing slightly - allow switch even before hold time expires
            self.logger().warning(
                f"⚠️  Active coin {self.active_coin} has negative trend ({active_trend_value:+.2f}%) - "
                f"allowing early exit to {best_coin} (hold time: {time_since_switch / 60:.1f}/{min_hold_time / 60:.1f} min)"  # noqa: E501
            )
            # Continue to other checks but be more lenient
        elif time_since_switch < min_hold_time:
            remaining = min_hold_time - time_since_switch
            self.logger().warning(
                f"⏰ Minimum hold time active - "
                f"wait {remaining / 60:.1f} more minutes (anti-whipsaw protection)"
            )
            return False

        # Phase 3.4: Volume/Liquidity Filter - Check volume and spread
        if not self._check_liquidity_requirements(best_coin):
            self.logger().warning(
                f"⚠️  {best_coin} doesn't meet liquidity requirements - skipping switch"
            )
            return False

        # Phase 3.1: Smart Switch Threshold - volatility-based threshold
        # IMPORTANT: For coins with strong long-term trends (>2%), be less sensitive to short-term volatility
        # This prevents switching away from coins with good 24h trends due to small temporary dips
        # 🔧 FIX: Use config threshold instead of hardcoded 2.0%
        strong_trend_threshold = float(getattr(self.config, 'switch_threshold_percent', 3.0))  # Default 3%
        active_has_strong_trend = active_trend_value > strong_trend_threshold
        best_has_strong_trend = best_trend_value > strong_trend_threshold

        # If active coin has strong trend, require larger difference to switch (prevent premature exits)
        if active_has_strong_trend and not best_has_strong_trend:
            # Active coin has strong trend, best coin doesn't - require even larger difference
            trend_difference = best_trend_value - active_trend_value
            # 🔧 FIX: Make hysteresis configurable instead of hardcoded 1.5%
            switch_hysteresis = float(getattr(self.config, 'switch_hysteresis_pct', 1.5))  # Default 1.5%
            if trend_difference < switch_hysteresis:
                self.logger().info(
                    f"📊 Active coin {self.active_coin} has strong trend ({active_trend_value:+.2f}%) - "
                    f"requiring larger difference ({trend_difference:+.2f}% < {switch_hysteresis}%) to switch"
                )
                return False

        # If active coin is negative, be more lenient with threshold
        if active_trend_value < 0:
            # Active coin is losing - use relaxed threshold (50% of normal)
            if not self._check_smart_switch_threshold_relaxed(active_trend, best_trend):
                return False
        else:
            # Normal threshold check
            if not self._check_smart_switch_threshold(active_trend, best_trend):
                return False

        # Phase 3.2: Switch Cost Calculator - only switch if profitable
        # If active coin is negative, be more lenient with cost check
        if active_trend_value < 0:
            # Active coin is losing - use relaxed cost check (only need to cover costs, not 2x)
            if not self._check_switch_cost_relaxed(best_coin, active_trend, best_trend):
                return False
        else:
            # Normal cost check
            if not self._check_switch_cost(best_coin, active_trend, best_trend):
                return False

        # NEW: Minimum Profit Check - don't switch if active coin is profitable and hasn't realized profit yet
        # This prevents switching away from profitable positions before they're closed
        executor_info = self._get_executor_info(self.active_executor_id)
        if executor_info and executor_info.is_active:
            custom_info = executor_info.custom_info
            # Check realized PnL from grid executor
            realized_pnl_quote = custom_info.get("realized_pnl_quote", Decimal("0"))
            if isinstance(realized_pnl_quote, (int, float)):
                realized_pnl_quote = Decimal(str(realized_pnl_quote))

            # If we have positive realized profit, allow switch (position is being closed profitably)
            # If we have negative realized profit but positive trend, wait a bit longer
            min_profit_threshold = Decimal("0.50")  # Minimum €0.50 profit before switching away
            if realized_pnl_quote < min_profit_threshold and active_trend_value > 0:
                # Active coin is profitable but hasn't realized enough profit yet
                # Only allow switch if best coin is MUCH better (opportunity cost)
                if not is_opportunity_switch:
                    self.logger().info(
                        f"💰 Active coin {self.active_coin} has unrealized profit (€{realized_pnl_quote:.2f}) "
                        f"< €{min_profit_threshold:.2f} - waiting to realize profit before switching"
                    )
                    return False

        # All checks passed - obtain risk allocation approval
        # Calculate per-coin capital for multi-coin mode
        per_coin_capital = Decimal(str(self.config.total_amount_quote)) / \
            Decimal(str(max(1, self.max_simultaneous_coins)))
        requested_notional = per_coin_capital
        allowed_notional = self.risk_manager.can_open_trade(
            symbol=best_coin,
            requested_notional=requested_notional,
            now=now_val,
        )
        if allowed_notional is None:
            self.logger().warning(
                f"🛑 Risk manager prevented switching into {best_coin} (limits exceeded)"
            )
            return False
        self._next_allocation_quote = allowed_notional

        # All checks passed - switch to new coin
        self.logger().info(
            f"🔄 SWITCH APPROVED: "
            f"{self.active_coin} ({active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct:+.2f}%) → "  # noqa: E501
            f"{best_coin} ({best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct:+.2f}%)"  # noqa: E501
        )
        return True

    # Phase 3.1: Smart Switch Threshold (relaxed for negative trends)
    def _check_smart_switch_threshold_relaxed(self, active_trend, best_trend) -> bool:
        """
        Relaxed version of smart switch threshold for when active coin is losing

        Uses 50% of normal K multiplier to allow switching more easily
        """
        try:
            active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct  # noqa: E501
            best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct  # noqa: E501

            # Convert to float if Decimal
            if isinstance(active_trend_value, Decimal):
                active_trend_value = float(active_trend_value)
            if isinstance(best_trend_value, Decimal):
                best_trend_value = float(best_trend_value)

            volatility = active_trend.volatility if active_trend.volatility > 0 else 1.0
            if isinstance(volatility, Decimal):
                volatility = float(volatility)
            k_multiplier = getattr(self.config, 'smart_switch_k', 1.75) * 0.5  # 50% of normal

            threshold = active_trend_value + (k_multiplier * volatility)

            if best_trend_value <= threshold:
                self.logger().info(
                    f"📊 Relaxed switch threshold not met:\n"
                    f"   Current trend: {active_trend_value:+.2f}%\n"
                    f"   Best trend: {best_trend_value:+.2f}%\n"
                    f"   Relaxed threshold: {threshold:+.2f}% (50% of normal)\n"
                    f"   Need: {threshold - best_trend_value:+.2f}% more to switch"
                )
                return False

            self.logger().info(
                f"✅ Relaxed switch threshold met: "
                f"{best_trend_value:+.2f}% > {threshold:+.2f}% "
                f"(relaxed for negative trend)"
            )
            return True
        except Exception as e:
            self.logger().error(f"❌ Error checking relaxed switch threshold: {e}")
            return best_trend.trend_pct > active_trend.trend_pct

    # Phase 3.1: Smart Switch Threshold
    def _check_smart_switch_threshold(self, active_trend, best_trend) -> bool:
        """
        Phase 3.1: Check if switch meets volatility-based threshold

        Logic: new_trend > current_trend + (K * volatility)
        This creates a Sharpe-like ratio that prevents switching on noise.

        Args:
            active_trend: Current coin's trend data
            best_trend: Best coin's trend data

        Returns:
            True if switch threshold is met
        """
        try:
            # Use consensus trend if available, otherwise raw trend
            active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct  # noqa: E501
            best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct  # noqa: E501

            # Convert to float if Decimal
            if isinstance(active_trend_value, Decimal):
                active_trend_value = float(active_trend_value)
            if isinstance(best_trend_value, Decimal):
                best_trend_value = float(best_trend_value)

            # Get volatility (use active coin's volatility as baseline)
            volatility = active_trend.volatility if active_trend.volatility > 0 else 1.0
            if isinstance(volatility, Decimal):
                volatility = float(volatility)

            # Get K multiplier from config
            k_multiplier = getattr(self.config, 'smart_switch_k', 1.75)

            # Calculate threshold: current_trend + (K * volatility)
            threshold = active_trend_value + (k_multiplier * volatility)

            # Check if new trend exceeds threshold
            if best_trend_value <= threshold:
                self.logger().info(
                    f"📊 Smart switch threshold not met:\n"
                    f"   Current trend: {active_trend_value:+.2f}%\n"
                    f"   Best trend: {best_trend_value:+.2f}%\n"
                    f"   Threshold: {threshold:+.2f}% (current + {k_multiplier} * {volatility:.3f}% vol)\n"
                    f"   Need: {threshold - best_trend_value:+.2f}% more to switch"
                )
                return False

            self.logger().info(
                f"✅ Smart switch threshold met: "
                f"{best_trend_value:+.2f}% > {threshold:+.2f}% "
                f"(volatility-adjusted)"
            )
            return True
        except Exception as e:
            self.logger().error(f"❌ Error checking smart switch threshold: {e}")
            # Fallback: allow switch if basic trend check passes
            return best_trend.trend_pct > active_trend.trend_pct

    # Phase 3.2: Switch Cost Calculator (relaxed for negative trends)
    def _check_switch_cost_relaxed(self, best_coin: str, active_trend, best_trend) -> bool:
        """
        Relaxed version of switch cost check for when active coin is losing

        Only requires profit to cover costs (1x multiplier instead of 2x)
        """
        try:
            # Same cost calculation as normal
            try:
                from decimal import Decimal

                from hummingbot.core.data_type.common import OrderType, TradeType
                from hummingbot.core.utils.estimate_fee import build_trade_fee

                sample_fee = build_trade_fee(
                    exchange=self.connector.name,
                    is_maker=True,
                    order_type=OrderType.LIMIT_MAKER,
                    order_side=TradeType.BUY,
                    amount=Decimal("1"),
                    price=Decimal("1"),
                    base_currency=best_coin.split("-")[0],
                    quote_currency=best_coin.split("-")[1]
                )
                if hasattr(sample_fee, 'percent') and sample_fee.percent:
                    maker_fee_pct = float(sample_fee.percent)
                else:
                    maker_fee_pct = 0.0025
            except Exception:
                maker_fee_pct = 0.0025

            fee_cost = maker_fee_pct * 2
            spread_cost = 0.001
            slippage_cost = 0.0005
            total_switch_cost_pct = fee_cost + spread_cost + slippage_cost

            active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct  # noqa: E501
            best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct  # noqa: E501

            # Convert to float if Decimal
            if isinstance(active_trend_value, Decimal):
                active_trend_value = float(active_trend_value)
            if isinstance(best_trend_value, Decimal):
                best_trend_value = float(best_trend_value)

            expected_profit_pct = best_trend_value - active_trend_value

            # Relaxed: only need to cover costs (1x instead of 2x)
            required_profit = total_switch_cost_pct * 1.0  # 1x multiplier instead of 2x

            if expected_profit_pct <= required_profit:
                self.logger().info(
                    f"💰 Relaxed switch cost analysis:\n"
                    f"   Expected profit: {expected_profit_pct:+.3f}%\n"
                    f"   Switch cost: {total_switch_cost_pct:.3f}%\n"
                    f"   Required profit: {required_profit:.3f}% (cost * 1.0, relaxed)\n"
                    f"   ❌ Not profitable even with relaxed check"
                )
                return False

            self.logger().info(
                f"✅ Relaxed switch cost analysis passed:\n"
                f"   Expected profit: {expected_profit_pct:+.3f}%\n"
                f"   Switch cost: {total_switch_cost_pct:.3f}%\n"
                f"   Net profit: {expected_profit_pct - total_switch_cost_pct:+.3f}% (relaxed)"
            )
            return True
        except Exception as e:
            self.logger().error(f"❌ Error checking relaxed switch cost: {e}")
            return True

    # Phase 3.2: Switch Cost Calculator
    def _check_switch_cost(self, best_coin: str, active_trend, best_trend) -> bool:
        """
        Phase 3.2: Calculate switch cost and only switch if profitable

        Estimates: fees + spread + slippage
        Only switch if: expected_profit > switch_cost * multiplier

        Args:
            best_coin: Coin to switch to
            active_trend: Current coin's trend data
            best_trend: Best coin's trend data

        Returns:
            True if switch is profitable after costs
        """
        try:
            # Estimate switch costs
            # 1. Fees: Get actual maker fee from connector (or use default)
            try:
                # Try to get actual fee from connector
                from decimal import Decimal

                from hummingbot.core.data_type.common import OrderType, TradeType
                from hummingbot.core.utils.estimate_fee import build_trade_fee

                # Get fee for a sample order to determine maker fee rate
                sample_fee = build_trade_fee(
                    exchange=self.connector.name,
                    is_maker=True,
                    order_type=OrderType.LIMIT_MAKER,
                    order_side=TradeType.BUY,
                    amount=Decimal("1"),
                    price=Decimal("1"),
                    base_currency=best_coin.split("-")[0],
                    quote_currency=best_coin.split("-")[1]
                )
                # Extract fee percentage
                if hasattr(sample_fee, 'percent') and sample_fee.percent:
                    maker_fee_pct = float(sample_fee.percent)
                else:
                    # Fallback to Kraken default: 0.25% maker, but user might have volume discount
                    maker_fee_pct = 0.0025  # 0.25% default Kraken maker fee
                    self.logger().debug(f"Using default maker fee: {maker_fee_pct * 100:.2f}%")
            except Exception as fee_error:
                # Fallback to default if fee lookup fails
                self.logger().debug(f"Could not get fee from connector: {fee_error}, using default")
                maker_fee_pct = 0.0025  # 0.25% default Kraken maker fee

            # Switch requires: close current position (maker) + open new position (maker)
            fee_cost = maker_fee_pct * 2  # Total fees for switch

            # 2. Spread: estimate 0.1% average spread
            spread_cost = 0.001  # 0.1%

            # 3. Slippage: estimate 0.05% for small orders
            slippage_cost = 0.0005  # 0.05%

            # Total switch cost as percentage
            total_switch_cost_pct = fee_cost + spread_cost + slippage_cost

            # Calculate expected profit improvement
            active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct  # noqa: E501
            best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct  # noqa: E501

            # Convert to float if Decimal
            if isinstance(active_trend_value, Decimal):
                active_trend_value = float(active_trend_value)
            if isinstance(best_trend_value, Decimal):
                best_trend_value = float(best_trend_value)

            expected_profit_pct = best_trend_value - active_trend_value

            # Get multiplier from config
            cost_multiplier = getattr(self.config, 'switch_cost_multiplier', 2.0)
            required_profit = total_switch_cost_pct * cost_multiplier

            # Store switch cost for logging
            self.switch_costs[best_coin] = total_switch_cost_pct

            if expected_profit_pct <= required_profit:
                self.logger().info(
                    f"💰 Switch cost analysis:\n" f"   Expected profit: {
                        expected_profit_pct:+.3f}%\n" f"   Switch cost: {
                        total_switch_cost_pct:.3f}% (fees: {
                        fee_cost:.3f}%, spread: {
                        spread_cost:.3f}%, slippage: {
                        slippage_cost:.3f}%)\n" f"   Required profit: {
                            required_profit:.3f}% (cost * {cost_multiplier})\n" f"   ❌ Not profitable - skipping switch")  # noqa: E501
                return False

            self.logger().info(
                f"✅ Switch cost analysis passed:\n"
                f"   Expected profit: {expected_profit_pct:+.3f}%\n"
                f"   Switch cost: {total_switch_cost_pct:.3f}%\n"
                f"   Net profit: {expected_profit_pct - total_switch_cost_pct:+.3f}%"
            )
            return True
        except Exception as e:
            self.logger().error(f"❌ Error checking switch cost: {e}")
            # Fallback: allow switch
            return True

    # Phase 3.4: Volume/Liquidity Filter (enhanced)
    def _check_liquidity_requirements(self, coin: str) -> bool:
        """
        Phase 3.4: Check if coin meets volume and spread requirements

        Args:
            coin: Coin symbol to check

        Returns:
            True if coin meets liquidity requirements
        """
        try:
            # Check volume requirement (€100k minimum)
            min_volume = float(getattr(self.config, 'min_24h_volume_usdt', self.config.min_24h_volume_eur))
            coin_volume = self.pair_volumes.get(coin, 0)

            if coin_volume < min_volume:
                self.logger().debug(
                    f"⚠️  {coin} volume too low: €{coin_volume:,.0f} < €{min_volume:,.0f}"
                )
                return False

            # Check spread requirement (<0.5%)
            max_spread = 0.005  # 0.5%
            coin_spread = self.pair_spreads.get(coin, 1.0)  # Default to high if unknown

            if coin_spread > max_spread:
                self.logger().debug(
                    f"⚠️  {coin} spread too high: {coin_spread * 100:.2f}% > {max_spread * 100:.2f}%"
                )
                return False

            return True
        except Exception as e:
            self.logger().error(f"❌ Error checking liquidity requirements: {e}")
            # Fallback: allow switch
            return True

    # Phase 4.1: ATR Calculation
    def _calculate_atr(self, symbol: str, trend) -> Optional[float]:
        """
        Phase 4.1: Calculate Average True Range (ATR) for a coin

        ATR measures volatility by calculating the average of true ranges over a period.
        True Range = max(high - low, abs(high - prev_close), abs(low - prev_close))

        Args:
            symbol: Trading pair symbol
            trend: CoinTrend object with price history

        Returns:
            ATR value as float, or None if insufficient data
        """
        try:
            if not trend or len(trend.price_history) < 14:  # Need at least 14 periods for ATR(14)
                return None

            # Calculate True Ranges
            true_ranges = []
            price_history = trend.price_history

            for i in range(1, len(price_history)):
                current = price_history[i]
                previous = price_history[i - 1]

                high = float(current.get('high', current.get('price', 0)))
                low = float(current.get('low', current.get('price', 0)))
                prev_close = float(previous.get('price', 0))

                if high > 0 and low > 0 and prev_close > 0:
                    tr1 = high - low
                    tr2 = abs(high - prev_close)
                    tr3 = abs(low - prev_close)
                    true_range = max(tr1, tr2, tr3)
                    true_ranges.append(true_range)

            if len(true_ranges) < 14:
                return None

            # Calculate ATR(14) - simple moving average of true ranges
            # Use last 14 true ranges (or all if less than 14)
            atr_period = min(14, len(true_ranges))
            atr = sum(true_ranges[-atr_period:]) / atr_period

            return atr
        except Exception as e:
            self.logger().debug(f"⚠️  Error calculating ATR for {symbol}: {e}")
            return None

    # ===== MULTI-COIN: Duplicate Grid Prevention =====
    def pick_first_inactive(self, coins: List[str]) -> Optional[str]:
        """
        Select first coin from list that doesn't have an active grid and isn't blacklisted.

        Args:
            coins: List of candidate coins (ordered by preference)

        Returns:
            First coin without active grid and not blacklisted, or None if all are active/blacklisted
        """
        for coin in coins:
            # Skip if already has active grid
            if coin in self.active_coins:
                self.logger().debug(f"⏭️  {coin} already has active grid (executor_id={self.active_coins[coin][:8]}...) - skipping")
                continue
            # Skip if auto-blacklisted (NL-restrictions, error loops, etc.)
            if coin in self.auto_blacklisted_coins:
                self.logger().debug(f"🚫 {coin} is auto-blacklisted (NL-restriction/error-loop) - skipping")
                continue
            return coin
        return None

    # ===== HYBRID GRID: SmartEntry Filter Integration =====
    def _check_smart_entry_filter(self, symbol: str) -> bool:
        """
        Check if SmartEntry filter allows entry for this symbol.

        Returns:
            True if entry allowed (or filter disabled), False if blocked
        """
        # HYBRID GRID v2.0: Use SmartEntry v2 if available, fallback to legacy
        if self.smart_entry_v2:
            return self._check_smart_entry_v2(symbol)
        elif self.smart_entry_filter:
            return self._check_smart_entry_legacy(symbol)
        else:
            return True  # Both filters disabled - allow entry

    def _build_orderbook_config(self) -> Optional[dict]:
        """
        Build orderbook depth config for TrendCalculator filtering.

        Phase 4: Regime-aware depth multipliers:
        - BULL market: 8.0x (looser - allows larger orders)
        - CHOP/Neutral: 5.0x (default moderate threshold)
        - BEAR market: 10.0x (strictest - safety first)

        Returns orderbook_liquidity config dict or None if disabled.
        """
        self.logger().debug("🔧 DEBUG: _build_orderbook_config() called")
        orderbook_config_dict = getattr(self.config, 'orderbook_liquidity', None)

        self.logger().debug(f"🔧 DEBUG: orderbook_config_dict = {orderbook_config_dict}")

        if not orderbook_config_dict or not orderbook_config_dict.get('enabled', False):
            self.logger().debug("🔧 DEBUG: Orderbook config disabled or missing, returning None")
            return None

        base_multiplier = orderbook_config_dict.get('min_depth_multiplier', 5.0)

        # Phase 4: Adjust multiplier based on market regime
        regime_aware = orderbook_config_dict.get('regime_aware', False)
        if regime_aware and self.market_regime_filter:
            regime_state = self.market_regime_filter.get_market_regime_state()
            if regime_state:
                # Determine regime type from BTC trends
                btc_4h = regime_state.btc_trend_4h
                btc_24h = regime_state.btc_trend_24h

                if btc_4h > 2.0 and btc_24h > 3.0:
                    # BULL: Strong uptrend - loosen requirements
                    multiplier = 8.0
                    regime_type = "BULL"
                elif btc_4h < -1.0 or btc_24h < -3.0:
                    # BEAR: Downtrend - tighten requirements (safety)
                    multiplier = 10.0
                    regime_type = "BEAR"
                else:
                    # CHOP: Sideways/mixed - default
                    multiplier = base_multiplier
                    regime_type = "CHOP"

                self.logger().debug(
                    f"🎯 Phase 4 Regime-Aware: {regime_type} → {multiplier}x depth "
                    f"(BTC 4h: {btc_4h:+.1f}%, 24h: {btc_24h:+.1f}%)"
                )
            else:
                multiplier = base_multiplier
        else:
            multiplier = base_multiplier

        # Build config with calculated multiplier
        config = {
            'enabled': True,
            'mode': orderbook_config_dict.get('mode', 'ranking'),  # 'shadow', 'ranking', or 'early'
            'depth_pct_range': orderbook_config_dict.get('depth_pct_range', 0.5),
            'depth_levels': orderbook_config_dict.get('depth_levels', 10),
            'min_depth_multiplier': multiplier,  # Phase 4: Regime-adjusted
            'order_size': self.config.total_amount_quote,  # Use position size as order size
        }

        self.logger().info(f"🔧 DEBUG: Built orderbook config: mode={config['mode']}, order_size={config['order_size']}, multiplier={config['min_depth_multiplier']}")
        return config

    def _check_smart_entry_v2(self, symbol: str) -> bool:
        """
        Check entry permission using SmartEntry v2.0 (with coin profiles)

        Returns:
            True if entry allowed, False if blocked
        """
        # Get trend data
        trend = self.trend_calculator.get_trend(symbol)
        if not trend or not trend.candles or len(trend.candles) < 14:
            self.logger().warning(
                f"🧠 {symbol}: Insufficient candle data for SmartEntry v2 ({len(trend.candles) if trend and trend.candles else 0} candles)")  # noqa: E501
            return False

        try:
            # Calculate indicators for v2.0 (uses core.models.CandleIndicators)
            from multi_coin_grid_pro.core.models import CandleIndicators as CandleIndicatorsV2

            indicators_legacy = self._calculate_smart_entry_indicators(symbol, trend)
            if not indicators_legacy:
                return False

            # Convert to v2.0 format
            indicators_v2 = CandleIndicatorsV2(
                price=Decimal(str(indicators_legacy.price)),
                rsi_14=indicators_legacy.rsi_14,
                vwap=Decimal(str(indicators_legacy.vwap)),
                atr_pct=indicators_legacy.atr_pct,
                wick_ratio=indicators_legacy.wick_ratio,
                trend_1h_pct=indicators_legacy.trend_1h_pct,
                trend_4h_pct=indicators_legacy.trend_4h_pct,
                trend_24h_pct=indicators_legacy.trend_24h_pct,
                change_5m_pct=indicators_legacy.change_5m_pct,
            )

            # Story 6 Part 2: Calculate momentum metrics
            momentum_metrics = self.momentum_service.calculate_metrics(
                symbol=symbol,
                current_price=float(indicators_v2.price),
                current_vwap=float(indicators_v2.vwap) if indicators_v2.vwap else None,
                candles=trend.candles
            )

            # Extract momentum parameters
            vwap_slope_15m_pct = momentum_metrics.vwap_slope_15m_pct if momentum_metrics.vwap_slope_15m_pct is not None else 0.0
            accel_5m_pct = momentum_metrics.accel_5m_pct if momentum_metrics.accel_5m_pct is not None else 0.0
            accel_15m_pct = momentum_metrics.accel_15m_pct if momentum_metrics.accel_15m_pct is not None else 0.0

            # Determine regime from cached value or default to CHOP
            regime = self._last_detected_regime if self._last_detected_regime else 'CHOP'

            # Check with v2.0 filter (with trace)
            order_size_eur = None
            total_amount_quote = getattr(self.config, 'total_amount_quote', None)
            if total_amount_quote:
                try:
                    per_coin_capital = Decimal(str(total_amount_quote)) / \
                        Decimal(str(max(1, self.max_simultaneous_coins)))
                    # Calculate actual order size per grid level
                    num_grids = self._calculate_volatility_based_grid_count(symbol, trend)
                    order_size_eur = float(per_coin_capital / Decimal(str(num_grids)))
                except Exception as e:
                    self.logger().debug(f"Failed to calculate order_size_eur for {symbol}: {e}")
                    order_size_eur = None

            # Story 6 Part 2: Pass momentum parameters to allows_entry
            allowed, reason, trace = self.smart_entry_v2.allows_entry(
                symbol, indicators_v2,
                exchange=self.config.connector_name,
                trace_enabled=self.debug_trace_enabled,
                order_size_eur=order_size_eur,
                vwap_slope_15m_pct=vwap_slope_15m_pct,
                accel_5m_pct=accel_5m_pct,
                accel_15m_pct=accel_15m_pct,
                regime=regime,
            )

            # Story 10: Check parabolic cooldown AFTER smart_entry (parabolic check happens inside)
            # If parabolic was detected, smart_entry will have added to session blacklist
            # We need to persist it if cooldown_persist is enabled
            if not allowed and "PARABOLIC" in reason and self.cooldown_store:
                self._handle_parabolic_cooldown(symbol, reason)

            # Fix #1: Store trace for correlation_id propagation to MTF
            self._last_smart_entry_trace = trace

            # Log decision trace
            self._log_decision_trace(trace)

            if allowed:
                self.logger().info(reason)
            else:
                self.logger().warning(reason)

            return allowed

        except Exception as e:
            self.logger().error(f"🧠 Error in SmartEntry v2 for {symbol}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            return False

    def _check_smart_entry_legacy(self, symbol: str) -> bool:
        """
        Check entry permission using legacy SmartEntry filter

        Returns:
            True if entry allowed, False if blocked
        """
        # Get trend data
        trend = self.trend_calculator.get_trend(symbol)
        if not trend or not trend.candles or len(trend.candles) < 14:
            self.logger().warning(
                f"🧠 {symbol}: Insufficient candle data for SmartEntry ({len(trend.candles) if trend and trend.candles else 0} candles)")  # noqa: E501
            return False  # No data - block entry

        # Calculate indicators from candles
        try:
            indicators = self._calculate_smart_entry_indicators(symbol, trend)
            if not indicators:
                return False

            # Check entry permission (with trace)
            allowed, reason, trace = self.smart_entry_filter.allows_entry(
                symbol, indicators,
                exchange=self.config.connector_name,
                trace_enabled=self.debug_trace_enabled
            )

            # Fix #1: Store trace for correlation_id propagation to MTF
            self._last_smart_entry_trace = trace

            # Log decision trace
            self._log_decision_trace(trace)

            if allowed:
                self.logger().info(f"🧠 {reason}")
            else:
                self.logger().warning(f"🧠 {reason}")

            return allowed

        except Exception as e:
            self.logger().error(f"🧠 Error in SmartEntry filter for {symbol}: {e}")
            return False  # Error - block entry for safety

    def _calculate_smart_entry_indicators(self, symbol: str, trend) -> Optional[CandleIndicators]:
        """
        Calculate all indicators needed for SmartEntry filter.

        Returns:
            CandleIndicators object, or None if calculation fails
        """
        try:
            candles = trend.candles
            if len(candles) < 14:
                return None

            # Extract OHLCV data
            closes = [c.close for c in candles]
            highs = [c.high for c in candles]
            lows = [c.low for c in candles]
            opens = [c.open for c in candles]
            volumes = [c.volume for c in candles]

            # Calculate indicators
            rsi = self.candle_calc.calculate_rsi(closes, period=14)
            vwap = self.candle_calc.calculate_vwap(highs, lows, closes, volumes)
            atr_pct = self.candle_calc.calculate_atr_pct(highs, lows, closes, period=14)
            wick_ratio = self.candle_calc.calculate_wick_ratio(highs[-1], lows[-1], opens[-1], closes[-1])

            # Trend calculations (from 5m candles)
            # 1h = 12 candles, 4h = 48 candles, 24h = 288 candles
            trend_1h = self.candle_calc.calculate_trend_pct(closes, lookback_candles=12)
            trend_4h = self.candle_calc.calculate_trend_pct(closes, lookback_candles=48)
            trend_24h = self.candle_calc.calculate_trend_pct(closes, lookback_candles=288)

            # 5m change
            change_5m = self.candle_calc.calculate_change_5m_pct(opens[-1], closes[-1])

            return CandleIndicators(
                price=closes[-1],
                rsi_14=rsi,
                vwap=vwap,
                atr_pct=atr_pct,
                wick_ratio=wick_ratio,
                trend_1h_pct=trend_1h,
                trend_4h_pct=trend_4h,
                trend_24h_pct=trend_24h,
                change_5m_pct=change_5m
            )

        except Exception as e:
            self.logger().error(f"Error calculating SmartEntry indicators for {symbol}: {e}")
            return None

    def _check_multi_timeframe_buy(self, symbol: str) -> bool:
        """
        Check if coin passes multi-timeframe buy protection.

        Requires positive momentum on multiple timeframes to prevent buying
        crashing or illiquid coins (prevents KAS-EUR disaster scenarios).

        Returns:
            True if entry allowed (or feature disabled), False if blocked
        """
        # Check if feature is enabled
        if not getattr(self.config, 'use_multi_timeframe_buy', False):
            return True  # Feature disabled - allow entry

        # Get trend data with indicators
        trend = self.trend_calculator.get_trend(symbol)
        if not trend or not trend.candles or len(trend.candles) < 288:  # Need 24h of 5m candles
            self.logger().warning(f"⏱️  {symbol}: Insufficient candle data for multi-timeframe check")
            return False  # No data - block entry for safety

        try:
            # Calculate indicators to get trend percentages
            indicators = self._calculate_smart_entry_indicators(symbol, trend)
            if not indicators:
                return False

            trend_1h = indicators.trend_1h_pct
            trend_4h = indicators.trend_4h_pct
            trend_24h = indicators.trend_24h_pct

            # Get thresholds from config
            mtf_1h_min = self.config.mtf_1h_min_pct
            mtf_4h_min = self.config.mtf_4h_min_pct
            mtf_24h_min = self.config.mtf_24h_min_pct
            mtf_declining_1h_max = self.config.mtf_declining_1h_max
            mtf_declining_4h_max = self.config.mtf_declining_4h_max

            # Check 1: Minimum trend requirements
            if trend_1h < mtf_1h_min:
                self.logger().warning(
                    f"⏱️  {symbol}: 1h trend too weak ({trend_1h:.2f}% < {mtf_1h_min:.2f}%)"
                )
                return False

            if trend_4h < mtf_4h_min:
                self.logger().warning(
                    f"⏱️  {symbol}: 4h momentum missing ({trend_4h:.2f}% < {mtf_4h_min:.2f}%)"
                )
                return False

            if trend_24h < mtf_24h_min:
                self.logger().warning(
                    f"⏱️  {symbol}: 24h uptrend required ({trend_24h:.2f}% < {mtf_24h_min:.2f}%)"
                )
                return False

            # Check 2: Declining trend protection (crash detection)
            if trend_1h < mtf_declining_1h_max and trend_4h < mtf_declining_4h_max:
                self.logger().warning(
                    f"⏱️  {symbol}: Declining trend detected (crash protection) "
                    f"[1h: {trend_1h:.2f}% < {mtf_declining_1h_max:.2f}%, "
                    f"4h: {trend_4h:.2f}% < {mtf_declining_4h_max:.2f}%]"
                )
                return False

            # All checks passed
            self.logger().info(
                f"⏱️  {symbol}: Multi-timeframe check PASSED "
                f"[1h: {trend_1h:.2f}%, 4h: {trend_4h:.2f}%, 24h: {trend_24h:.2f}%]"
            )
            return True

        except Exception as e:
            self.logger().error(f"⏱️  Error in multi-timeframe check for {symbol}: {e}")
            return False  # Error - block entry for safety

    def _prefetch_orderbooks_shadow(self, top_candidates: List[str]) -> None:
        """
        Phase 1: Shadow mode - Observe orderbook cache status for top candidates.

        This is a LOG-ONLY implementation that observes which coins have cached
        orderbook data WITHOUT making any subscriptions. Used to analyze whether
        prefetch is actually needed before implementing live mode.

        Args:
            top_candidates: List of top-N candidate coins from ranking
        """
        try:
            # Read config - must handle both dict and None cases
            prefetch_config = getattr(self.config, 'orderbook_prefetch', None)

            # If config is None or empty, skip
            if not prefetch_config:
                self.logger().debug("[PREFETCH][SHADOW] Config not found or disabled")
                return

            # Check if enabled
            if not prefetch_config.get('enabled', False):
                self.logger().debug("[PREFETCH] Feature disabled in config")
                return

            # Get mode and top_n from config
            mode = prefetch_config.get('mode', 'shadow')
            top_n = prefetch_config.get('top_n', 3)

            # Log differently based on mode
            if mode == 'shadow':
                self.logger().info(f"[PREFETCH][SHADOW] Checking top {top_n} candidates (log-only)...")
            else:
                self.logger().info(f"[PREFETCH][LIVE] Prefetching top {top_n} candidates...")

            # Log cache status for top candidates
            for i, symbol in enumerate(top_candidates[:top_n], 1):
                # Check if orderbook is cached for this symbol
                cached = self._is_orderbook_cached(symbol)

                if mode == 'shadow':
                    # Shadow mode: only log
                    self.logger().info(
                        f"[PREFETCH][SHADOW] #{i} {symbol} orderbook_cached={cached}"
                    )
                else:
                    # Live mode: actually prefetch if not cached
                    if not cached:
                        self.logger().info(f"[PREFETCH][LIVE] #{i} {symbol} - prefetching orderbook...")
                        # Actually subscribe to orderbook
                        self._subscribe_to_orderbook(symbol)
                    else:
                        self.logger().debug(f"[PREFETCH][LIVE] #{i} {symbol} - already cached")

        except Exception as e:
            self.logger().error(f"[PREFETCH][SHADOW] Error: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

    def _is_orderbook_cached(self, symbol: str) -> bool:
        """
        Check if orderbook data is available in cache for symbol.

        Args:
            symbol: Trading pair symbol

        Returns:
            True if orderbook cached, False otherwise
        """
        try:
            if not self.connector:
                return False

            # Get orderbook from connector cache
            order_book = self.connector.get_order_book(trading_pair=symbol)

            # Check if we got valid data
            if order_book and order_book.snapshot and len(order_book.snapshot[0]) > 0 and len(order_book.snapshot[1]) > 0:
                return True

            return False

        except Exception as e:
            self.logger().debug(f"[PREFETCH] Orderbook check failed for {symbol}: {e}")
            return False

    def _subscribe_to_orderbook(self, symbol: str) -> None:
        """
        Subscribe to orderbook updates for a trading pair.

        This ensures orderbook data is available for depth checks and spread validation.

        Args:
            symbol: Trading pair to subscribe to (e.g., 'HIPPO-USDT')
        """
        try:
            if not self.connector:
                self.logger().warning(f"[ORDERBOOK] Cannot subscribe to {symbol}: connector not available")
                return

            # Check if connector has order book tracker
            if not hasattr(self.connector, '_order_book_tracker'):
                self.logger().debug(f"[ORDERBOOK] Connector has no order book tracker for {symbol}")
                return

            tracker = self.connector._order_book_tracker

            # Check if already subscribed (already in trading_pairs)
            if symbol in tracker._trading_pairs:
                self.logger().debug(f"[ORDERBOOK] Already subscribed to {symbol}")
                return

            # Add to trading pairs list
            tracker._trading_pairs.append(symbol)
            self.logger().info(f"[ORDERBOOK] ✅ Subscribed to {symbol} orderbook")

            # Trigger immediate snapshot fetch (don't wait for next cycle)
            if hasattr(tracker, '_order_books') and symbol not in tracker._order_books:
                # Initialize order book for this pair
                safe_ensure_future(self._initialize_orderbook(symbol, tracker))

        except Exception as e:
            self.logger().error(f"[ORDERBOOK] Failed to subscribe to {symbol}: {e}")
            import traceback
            self.logger().debug(traceback.format_exc())

    async def _initialize_orderbook(self, symbol: str, tracker) -> None:
        """
        Initialize orderbook for a trading pair.

        Args:
            symbol: Trading pair
            tracker: Order book tracker instance
        """
        try:
            self.logger().debug(f"[ORDERBOOK] Initializing orderbook for {symbol}...")

            # Request initial snapshot
            order_book = await tracker._initial_order_book_for_trading_pair(symbol)

            if order_book:
                tracker._order_books[symbol] = order_book
                self.logger().info(f"[ORDERBOOK] ✅ Initialized orderbook for {symbol}")
            else:
                self.logger().warning(f"[ORDERBOOK] Failed to get initial snapshot for {symbol}")

        except Exception as e:
            self.logger().error(f"[ORDERBOOK] Error initializing {symbol}: {e}")
            import traceback
            self.logger().debug(traceback.format_exc())

    # Phase 4.2: Volatility-Based Grid Count
    def _calculate_volatility_based_grid_count(self, symbol: str, trend) -> int:
        """
        Phase 4.2: Calculate optimal grid count based on volatility

        High volatility → more grids (4-6)
        Low volatility → fewer grids (2-3)
        Formula: num_grids = min(6, max(2, int(volatility * 100)))

        Args:
            symbol: Trading pair symbol
            trend: CoinTrend object with volatility data

        Returns:
            Optimal number of grid levels
        """
        try:
            base_grids = self.config.num_grids

            # HYBRID GRID v2.0: Use DynamicGridSizer v2 if available
            if self.grid_sizer_v2 and trend.candles and len(trend.candles) >= 20:
                try:
                    # Calculate indicators to get ATR%
                    indicators = self._calculate_smart_entry_indicators(symbol, trend)
                    if indicators:
                        optimal_grids = self.grid_sizer_v2.grid_count_for(indicators.atr_pct)
                        if optimal_grids != base_grids:
                            self.logger().info(
                                f"📊 DynamicGridSizer v2.0: {base_grids} → {optimal_grids} "
                                f"(ATR: {indicators.atr_pct:.2f}%)"
                            )
                        return optimal_grids
                except Exception as e:
                    self.logger().warning(f"⚠️  DynamicGridSizer v2 failed for {symbol}: {e}, using fallback")
            # Use legacy DynamicGridSizer if enabled
            elif self.dynamic_grid_sizer and trend.candles and len(trend.candles) >= 20:
                try:
                    # Calculate indicators to get ATR%
                    indicators = self._calculate_smart_entry_indicators(symbol, trend)
                    if indicators:
                        optimal_grids = self.dynamic_grid_sizer.grid_count_for(indicators.atr_pct, symbol)
                        if optimal_grids != base_grids:
                            self.logger().info(
                                f"📊 DynamicGrid (legacy): {base_grids} → {optimal_grids} "
                                f"(ATR: {indicators.atr_pct:.2f}%)"
                            )
                        return optimal_grids
                except Exception as e:
                    self.logger().warning(f"⚠️  DynamicGridSizer (legacy) failed for {symbol}: {e}, using fallback")

            # Fallback to legacy volatility-based calculation
            volatility = trend.volatility if trend.volatility > 0 else 0.01  # Default 1% if unknown

            # Calculate volatility-based grid count
            # Higher volatility = more grids
            volatility_multiplier = min(2.0, max(0.67, volatility * 100))  # Scale between 0.67x and 2.0x
            calculated_grids = int(base_grids * volatility_multiplier)

            # Clamp between 2 and 6 grids
            optimal_grids = min(6, max(2, calculated_grids))

            if optimal_grids != base_grids:
                self.logger().info(
                    f"📊 Volatility-based grid adjustment: {base_grids} → {optimal_grids} "
                    f"(volatility: {volatility * 100:.2f}%)"
                )

            return optimal_grids
        except Exception as e:
            self.logger().error(f"❌ Error calculating volatility-based grid count: {e}")
            # Fallback to base grid count
            return self.config.num_grids

    def _calculate_volatility_adjusted_position_size(self, symbol: str, base_size: Decimal) -> Decimal:
        """
        PHASE 1 FIX #4: Calculate position size adjusted for volatility

        Uses ATR to adjust position size:
        - High volatility (>5% ATR) → 67% of base size (smaller position)
        - Medium volatility (3-5% ATR) → 83% of base size
        - Normal volatility (1.5-3% ATR) → 100% of base size
        - Low volatility (<1.5% ATR) → 133% of base size (larger position)

        This is how professional traders size positions!

        Args:
            symbol: Trading pair symbol
            base_size: Base position size from config

        Returns:
            Volatility-adjusted position size
        """
        try:
            # Get ATR and current price using TrendCalculator
            trend = self.trend_calculator.get_trend(symbol)
            atr = self._calculate_atr(symbol, trend)
            current_price = self.connector.get_mid_price(symbol)

            if not atr or not current_price or atr <= 0 or current_price <= 0:
                self.logger().warning(f"⚠️  No ATR/price for {symbol}, using base size €{base_size}")
                return base_size

            # Calculate volatility percentage (convert both to Decimal for safety)
            volatility_pct = float(Decimal(str(atr)) / Decimal(str(current_price)) * 100)

            # Determine size multiplier based on volatility
            if volatility_pct > 5.0:  # Very high volatility
                multiplier = Decimal("0.67")  # 67% of base
                volatility_level = "HIGH"
            elif volatility_pct > 3.0:  # Medium-high volatility
                multiplier = Decimal("0.83")  # 83% of base
                volatility_level = "MEDIUM-HIGH"
            elif volatility_pct < 1.5:  # Very low volatility
                multiplier = Decimal("1.33")  # 133% of base
                volatility_level = "LOW"
            else:  # Normal volatility (1.5-3%)
                multiplier = Decimal("1.0")  # 100% of base
                volatility_level = "NORMAL"

            # Apply multiplier
            adjusted_size = base_size * multiplier

            # Ensure within reasonable bounds (50%-150% of base)
            min_size = base_size * Decimal("0.5")
            max_size = base_size * Decimal("1.5")
            final_size = max(min_size, min(adjusted_size, max_size))

            self.logger().info(
                f"💰 {symbol} position sizing: "
                f"Base: €{base_size} → Final: €{final_size:.2f} "
                f"(Volatility: {volatility_level} {volatility_pct:.1f}%, Multiplier: {multiplier})"
            )

            return final_size

        except Exception as e:
            self.logger().error(f"Error calculating volatility-adjusted size for {symbol}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            # Fallback to base size on error
            return base_size

    def _is_trading_pair_tradeable(self, symbol: str) -> bool:
        """
        Check if a trading pair is actually tradeable on the connector.

        This performs multiple checks:
        1. The symbol is in the connector's trading_pairs
        2. An order book exists for the symbol
        3. The connector can actually trade this pair

        Args:
            symbol: Trading pair symbol (e.g., "XRP-EUR")

        Returns:
            True if the pair is tradeable, False otherwise
        """
        try:
            if not self.connector:
                self.logger().warning(f"⚠️ Connector not initialized - cannot verify {symbol}")
                return False

            # Check 1: Is the symbol in connector's trading_pairs?
            # DYNAMIC DISCOVERY: Skip this check if dynamic discovery is enabled
            use_dynamic = getattr(self.config, 'use_dynamic_pair_discovery', False)
            if not use_dynamic:
                connector_pairs = getattr(self.connector, '_trading_pairs', None)
                if connector_pairs is None:
                    # Try alternative attribute names
                    connector_pairs = getattr(self.connector, 'trading_pairs', [])

                if symbol not in connector_pairs:
                    self.logger().warning(
                        f"⚠️ {symbol} NOT in connector's trading_pairs - "
                        f"cannot trade (have: {len(connector_pairs)} pairs)"
                    )
                    # Auto-blacklist this coin to prevent repeated failures
                    self.auto_blacklisted_coins.add(symbol)
                    self.logger().info(f"🚫 Auto-blacklisted {symbol} (not in connector's trading pairs)")
                    return False
            else:
                self.logger().debug(f"✅ {symbol} - Dynamic discovery enabled, skipping trading_pairs check")

            # Check 2: Does an order book exist?
            # DYNAMIC DISCOVERY: Fail-open if order book doesn't exist yet
            try:
                order_book = self.connector.get_order_book(symbol)
                if order_book is None:
                    if use_dynamic:
                        self.logger().debug(f"⚠️ No order book for {symbol} - will be initialized on trade")
                        return True  # Dynamic discovery: Allow trading, order book will be created
                    else:
                        self.logger().warning(f"⚠️ No order book for {symbol} - cannot trade")
                        return False
            except (ValueError, KeyError) as e:
                if use_dynamic:
                    self.logger().debug(f"⚠️ Order book for {symbol} not yet initialized: {e}")
                    return True  # Dynamic discovery: Allow trading
                else:
                    self.logger().warning(f"⚠️ Cannot get order book for {symbol}: {e}")
                    return False

            # Check 3: Does the order book have data?
            # DYNAMIC DISCOVERY: Skip if order book is not yet populated
            try:
                if order_book and hasattr(order_book, 'snapshot') and order_book.snapshot:
                    bids, asks = order_book.snapshot
                    if bids is None or asks is None:
                        if use_dynamic:
                            self.logger().debug(f"⚠️ {symbol} order book has no bid/ask data yet")
                            return True  # Dynamic discovery: Allow, will populate later
                        else:
                            self.logger().warning(f"⚠️ {symbol} order book has no bid/ask data")
                            return False
                    # Check if empty
                    bids_empty = (
                        hasattr(
                            bids,
                            '__len__') and len(bids) == 0) or (
                        hasattr(
                            bids,
                            'empty') and bids.empty)
                    asks_empty = (
                        hasattr(
                            asks,
                            '__len__') and len(asks) == 0) or (
                        hasattr(
                            asks,
                            'empty') and asks.empty)
                    if bids_empty or asks_empty:
                        if use_dynamic:
                            self.logger().debug(f"⚠️ {symbol} order book is empty - will populate on trade")
                            return True  # Dynamic discovery: Allow
                        else:
                            self.logger().warning(f"⚠️ {symbol} order book is empty")
                            return False
                elif use_dynamic:
                    self.logger().debug(f"⚠️ {symbol} order book not yet populated (dynamic discovery)")
                    return True  # Dynamic discovery: Allow
            except Exception as e:
                if use_dynamic:
                    self.logger().debug(
                        f"⚠️ Error checking order book data for {symbol}: {e} - allowing for dynamic discovery")
                    return True  # Dynamic discovery: Fail-open
                else:
                    self.logger().warning(f"⚠️ Error checking order book data for {symbol}: {e}")
                    return False

            self.logger().debug(f"✅ {symbol} is tradeable")
            return True

        except Exception as e:
            self.logger().error(f"❌ Error checking if {symbol} is tradeable: {e}")
            return False

    def _check_spread_acceptable(self, symbol: str, max_spread_pct: Optional[float] = None) -> bool:
        """
        PHASE 1 FIX #1: Check if bid-ask spread is acceptable before entry

        Rejects entry if spread is too wide, preventing slippage losses.
        Professional bots check spread to avoid entering illiquid markets.

        Args:
            symbol: Trading pair symbol (e.g., "XRP-EUR")
            max_spread_pct: Maximum acceptable spread percentage (default from config)

        Returns:
            True if spread is acceptable, False if too wide
        """
        try:
            # DYNAMIC DISCOVERY: Skip spread check if order books don't exist yet
            use_dynamic = getattr(self.config, 'use_dynamic_pair_discovery', False)
            if use_dynamic:
                self.logger().debug(
                    f"✅ {symbol} - Dynamic discovery: skipping spread check (order books not pre-loaded)")
                return True  # Allow trading, spread will be checked when placing actual orders

            # First check if the pair is actually tradeable
            if not self._is_trading_pair_tradeable(symbol):
                return False

            # Get max spread from config or use default
            if max_spread_pct is None:
                max_spread_pct = getattr(self.config, 'max_entry_spread_pct', 0.5)  # Default 0.5%

            # Get order book (we already know it exists from _is_trading_pair_tradeable)
            try:
                order_book = self.connector.get_order_book(symbol)
                if not order_book or not order_book.snapshot:
                    self.logger().warning(f"⚠️  No order book snapshot for {symbol} - cannot check spread")
                    # Conservative: Reject if no order book data
                    return False

                # Get best bid and ask from snapshot
                # snapshot = (bids, asks) where each is [(price, amount), ...] or DataFrame
                bids, asks = order_book.snapshot

                # Handle both list and DataFrame types for bids/asks
                try:
                    # Check if bids/asks are empty (works for lists, DataFrames, arrays)
                    bids_empty = (
                        bids is None) or (
                        hasattr(
                            bids,
                            '__len__') and len(bids) == 0) or (
                        hasattr(
                            bids,
                            'empty') and bids.empty)
                    asks_empty = (
                        asks is None) or (
                        hasattr(
                            asks,
                            '__len__') and len(asks) == 0) or (
                        hasattr(
                            asks,
                            'empty') and asks.empty)

                    if bids_empty or asks_empty:
                        self.logger().warning(f"⚠️  Empty order book for {symbol} - rejecting")
                        return False
                except Exception as e:
                    self.logger().warning(f"⚠️  Error checking order book for {symbol}: {e}")
                    return False

                # Best bid (highest buy price) and best ask (lowest sell price)
                # Handle both list format [(price, amount), ...] and DataFrame format
                try:
                    if hasattr(bids, 'iloc'):  # DataFrame
                        best_bid = float(bids.iloc[0, 0])
                        best_ask = float(asks.iloc[0, 0])
                    else:  # List/tuple format
                        best_bid = float(bids[0][0])
                        best_ask = float(asks[0][0])
                except (IndexError, KeyError, TypeError) as e:
                    self.logger().warning(f"⚠️  Cannot extract bid/ask prices for {symbol}: {e}")
                    return False

                # Calculate mid price and spread
                mid_price = (best_bid + best_ask) / 2.0

                if mid_price <= 0:
                    self.logger().warning(f"⚠️  Invalid mid price for {symbol}: {mid_price}")
                    return False

                # Calculate spread percentage
                spread_pct = abs(best_ask - best_bid) / mid_price * 100.0

                # Check if spread is acceptable
                if spread_pct > max_spread_pct:
                    self.logger().warning(
                        f"🚫 {symbol} spread TOO WIDE: {spread_pct:.3f}% > {max_spread_pct}% "
                        f"(bid: €{best_bid:.4f}, ask: €{best_ask:.4f})"
                    )
                    return False

                # Spread is acceptable
                self.logger().info(
                    f"✅ {symbol} spread OK: {spread_pct:.3f}% < {max_spread_pct}% "
                    f"(bid: €{best_bid:.4f}, ask: €{best_ask:.4f})"
                )
                return True

            except (ValueError, KeyError, AttributeError) as e:
                self.logger().warning(f"⚠️  Cannot get order book for {symbol}: {e}")
                # Conservative: Reject if order book access fails
                return False

        except Exception as e:
            self.logger().error(f"❌ Error checking spread for {symbol}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            # Conservative: Reject on error to prevent bad entries
            return False

    def _check_order_book_depth(self, symbol: str, order_size_eur: float) -> bool:
        """
        PHASE 2: Check if order book has sufficient depth for order.

        Validates that both BID and ASK sides have at least 3x the order size
        to prevent slippage on market orders.

        Args:
            symbol: Trading pair symbol (e.g., "SUI-EUR")
            order_size_eur: Order size in EUR

        Returns:
            True if depth is sufficient, False if thin book
        """
        try:
            # Get depth multiplier from config
            min_depth_multiplier = getattr(self.config, 'min_depth_multiplier', 3.0)
            depth_check_enabled = getattr(self.config, 'depth_check_enabled', True)

            if not depth_check_enabled:
                return True  # Check disabled

            required_depth_eur = order_size_eur * min_depth_multiplier

            # Get order book - DYNAMIC DISCOVERY: Fail-open if order book doesn't exist yet
            try:
                order_book = self.connector.get_order_book(symbol)
            except (ValueError, KeyError) as e:
                self.logger().debug(f"[DEPTH] {symbol} - Order book not yet initialized (dynamic discovery): {e}")
                return True  # Fail-open: Allow trading without depth check for new pairs

            if not order_book or not order_book.snapshot:
                self.logger().warning(f"[DEPTH] {symbol} - No order book data available")
                return True  # Allow entry if no data (fail-open)

            bids, asks = order_book.snapshot

            # Sum BID side depth (total EUR available to buy from us)
            bid_total_eur = 0.0
            try:
                if hasattr(bids, 'iloc'):  # DataFrame
                    for i in range(len(bids)):
                        price = float(bids.iloc[i, 0])
                        volume = float(bids.iloc[i, 1])
                        bid_total_eur += price * volume
                        if bid_total_eur >= required_depth_eur:
                            break
                else:  # List format
                    for price, volume in bids:
                        bid_total_eur += float(price) * float(volume)
                        if bid_total_eur >= required_depth_eur:
                            break
            except Exception as e:
                self.logger().warning(f"[DEPTH] {symbol} - Error summing bids: {e}")
                return True  # Fail-open on error

            # Sum ASK side depth (total EUR available to sell to us)
            ask_total_eur = 0.0
            try:
                if hasattr(asks, 'iloc'):  # DataFrame
                    for i in range(len(asks)):
                        price = float(asks.iloc[i, 0])
                        volume = float(asks.iloc[i, 1])
                        ask_total_eur += price * volume
                        if ask_total_eur >= required_depth_eur:
                            break
                else:  # List format
                    for price, volume in asks:
                        ask_total_eur += float(price) * float(volume)
                        if ask_total_eur >= required_depth_eur:
                            break
            except Exception as e:
                self.logger().warning(f"[DEPTH] {symbol} - Error summing asks: {e}")
                return True  # Fail-open on error

            # Check if both sides have sufficient depth
            has_bid_depth = bid_total_eur >= required_depth_eur
            has_ask_depth = ask_total_eur >= required_depth_eur

            if not has_bid_depth or not has_ask_depth:
                self.logger().warning(
                    f"🚫 [DEPTH] {symbol} insufficient liquidity: "
                    f"BID {bid_total_eur:.0f}/{required_depth_eur:.0f} EUR, "
                    f"ASK {ask_total_eur:.0f}/{required_depth_eur:.0f} EUR "
                    f"(need {min_depth_multiplier}x of €{order_size_eur:.0f})"
                )
                return False

            self.logger().info(
                f"✅ [DEPTH] {symbol} sufficient liquidity: "
                f"BID {bid_total_eur:.0f} EUR ≥ {required_depth_eur:.0f}, "
                f"ASK {ask_total_eur:.0f} EUR ≥ {required_depth_eur:.0f} "
                f"({min_depth_multiplier}x confirmed)"
            )
            return True

        except Exception as e:
            self.logger().error(f"❌ Error checking depth for {symbol}: {e}")
            return True  # Fail-open on error (don't block trading due to check failure)

    async def _ensure_order_book_exists(self, symbol: str) -> bool:
        """
        Ensure order book exists for the trading pair.
        If it doesn't exist, try to initialize it.

        Args:
            symbol: Trading pair symbol

        Returns:
            True if order book exists or was successfully initialized
        """
        if not self.connector:
            self.logger().error("❌ Connector not initialized")
            return False

        # Check if order book exists
        try:
            order_book = self.connector.get_order_book(symbol)
            if order_book is not None:
                self.logger().debug(f"✅ Order book exists for {symbol}")
                return True
        except (ValueError, KeyError):
            # Order book doesn't exist
            pass

        # Order book doesn't exist - try to initialize it
        self.logger().warning(f"⚠️ Order book not found for {symbol} - attempting to initialize...")

        try:
            # Check if connector has order_book_tracker
            if not hasattr(self.connector, 'order_book_tracker') or self.connector.order_book_tracker is None:
                self.logger().error("❌ Connector has no order_book_tracker")
                return False

            tracker = self.connector.order_book_tracker

            # Check if trading pair is already in tracker's trading pairs (use private attribute)
            if symbol not in tracker._trading_pairs:
                # Add trading pair to tracker
                self.logger().info(f"📥 Adding {symbol} to order book tracker...")
                tracker._trading_pairs.append(symbol)
                # Also add to data source if it has trading pairs
                if hasattr(tracker._data_source,
                           '_trading_pairs') and symbol not in tracker._data_source._trading_pairs:
                    tracker._data_source._trading_pairs.append(symbol)

            # Initialize order book for this pair (use private attributes)
            if symbol not in tracker._order_books:
                self.logger().info(f"📚 Initializing order book for {symbol}...")
                order_book = await tracker._initial_order_book_for_trading_pair(symbol)
                tracker._order_books[symbol] = order_book
                tracker._tracking_message_queues[symbol] = asyncio.Queue()
                tracker._tracking_tasks[symbol] = safe_ensure_future(tracker._track_single_book(symbol))
                self.logger().info(f"✅ Order book initialized for {symbol}")

                # PAPER TRADING FIX: Also add to paper trading connector's _trading_pairs
                # This is needed because paper trading connector has its own _trading_pairs dict
                # that is separate from the tracker's _trading_pairs list
                if hasattr(self.connector, '_trading_pairs') and isinstance(self.connector._trading_pairs, dict):
                    # Paper trading connector uses dict, need to convert symbol format
                    try:
                        # Get exchange trading pair format (paper trading uses exchange format internally)
                        exchange_symbol = symbol
                        if hasattr(self.connector, '_target_market'):
                            # Convert to exchange format if needed
                            target_market_class = self.connector._target_market
                            if callable(target_market_class):
                                # Try to convert symbol format
                                try:
                                    exchange_symbol = target_market_class().convert_to_exchange_trading_pair(symbol)
                                except Exception:
                                    exchange_symbol = symbol

                        # Check if already in paper trading connector's trading pairs
                        hb_symbol = symbol  # Hummingbot format (e.g., "TNSR-EUR")
                        if hb_symbol not in self.connector._trading_pairs:
                            # Add to paper trading connector's _trading_pairs
                            from hummingbot.connector.exchange.paper_trade.trading_pair import TradingPair
                            base_asset, quote_asset = self.connector.split_trading_pair(exchange_symbol)
                            self.connector._trading_pairs[hb_symbol] = TradingPair(
                                exchange_symbol, base_asset, quote_asset
                            )
                            self.logger().info(f"✅ Added {hb_symbol} to paper trading connector's trading pairs")

                        # Add listener for order book trades (needed for order fills)
                        # This should happen after order book is initialized, regardless of whether trading pair was already added  # noqa: E501
                        # Note: tracker._order_books uses Hummingbot format, not exchange format
                        if symbol in tracker._order_books:
                            composite_order_book = tracker._order_books[symbol]
                            if hasattr(composite_order_book, 'c_add_listener'):
                                from hummingbot.core.event.events import OrderBookEvent
                                composite_order_book.c_add_listener(
                                    OrderBookEvent.TradeEvent.value,
                                    self.connector._order_book_trade_listener
                                )
                                self.logger().info(f"✅ Added trade listener for {symbol}")
                    except Exception as e:
                        self.logger().warning(f"⚠️ Could not add {symbol} to paper trading connector: {e}")
                        # Continue anyway - order book is initialized in tracker

            # Wait a moment for order book to populate
            await asyncio.sleep(2)

            # Verify order book is accessible
            try:
                order_book = self.connector.get_order_book(symbol)
                if order_book is not None:
                    self.logger().info(f"✅ Order book ready for {symbol}")
                    return True
            except (ValueError, KeyError):
                self.logger().warning(f"⚠️ Order book initialized but not yet accessible for {symbol}")
                return False

        except Exception as e:
            self.logger().error(f"❌ Failed to initialize order book for {symbol}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            return False

        return False

    def _create_grid_action(self, symbol: str, total_amount_quote: Optional[Decimal] = None) -> CreateExecutorAction:
        """
        Create a CreateExecutorAction for GridExecutor

        Phase 4: Enhanced grid creation with ATR-based ranges, volatility-based grid count,
        and asymmetric grid adjustment.

        Args:
            symbol: Trading pair symbol

        Returns:
            CreateExecutorAction with GridExecutorConfig
        """
        # Phase 4.4: Smart Refill Logic - Check if we should rebuild grid
        if self.active_coin == symbol and symbol in self.last_grid_price:
            current_trend = self.trend_calculator.get_trend(symbol)
            if current_trend:
                current_price = Decimal(str(current_trend.current_price))
                last_price = self.last_grid_price[symbol]
                price_change_pct = abs(float((current_price - last_price) / last_price * 100))
                threshold = float(getattr(self.config, 'smart_refill_threshold_pct', Decimal("3.0")))

                if price_change_pct > threshold:
                    self.logger().info(
                        f"🔄 Smart refill: Price moved {price_change_pct:.2f}% since last grid "
                        f"(threshold: {threshold}%) - rebuilding grid"
                    )
                    # Clear old grid price - will be updated below
                    del self.last_grid_price[symbol]

        # Get current price
        trend = self.trend_calculator.get_trend(symbol)
        if not trend or not trend.current_price or trend.current_price <= 0:
            self.logger().error(
                f"❌ Cannot create grid for {symbol}: Invalid trend data or price (trend={trend}, "
                f"price={trend.current_price if trend else 'None'})"
            )
            return None

        current_price = Decimal(str(trend.current_price))  # Convert float to Decimal

        # Validate current_price is positive
        if current_price <= 0:
            self.logger().error(
                f"❌ Cannot create grid for {symbol}: Invalid current_price ({current_price})"
            )
            return None

        # Phase 4.1: ATR-Based Grid Ranges (or fallback to fixed percentages)
        use_atr = getattr(self.config, 'use_atr_grid_ranges', True)
        if use_atr:
            atr_value = self._calculate_atr(symbol, trend)
            if atr_value and atr_value > 0:
                atr_mult_down = getattr(self.config, 'atr_multiplier_down', 1.0)
                atr_mult_up = getattr(self.config, 'atr_multiplier_up', 1.5)
                start_price = current_price - (Decimal(str(atr_value)) * Decimal(str(atr_mult_down)))
                end_price = current_price + (Decimal(str(atr_value)) * Decimal(str(atr_mult_up)))
                grid_method = "ATR-based"
            else:
                # Fallback to fixed percentages if ATR not available
                start_price = current_price * (
                    Decimal("1") - self.config.grid_range_pct_down / Decimal("100")
                )
                end_price = current_price * (
                    Decimal("1") + self.config.grid_range_pct_up / Decimal("100")
                )
                grid_method = "Fixed % (ATR unavailable)"
        else:
            # Use fixed percentages
            start_price = current_price * (
                Decimal("1") - self.config.grid_range_pct_down / Decimal("100")
            )
            end_price = current_price * (
                Decimal("1") + self.config.grid_range_pct_up / Decimal("100")
            )
            grid_method = "Fixed %"

        # Phase 4.2: Volatility-Based Grid Count
        num_grids = self._calculate_volatility_based_grid_count(symbol, trend)

        # Validate num_grids is positive
        if num_grids <= 0:
            self.logger().error(
                f"❌ Cannot create grid for {symbol}: Invalid num_grids ({num_grids})"
            )
            return None

        # Phase 4.3: Asymmetric Grid Adjustment (if enabled)
        # Note: GridExecutorConfig doesn't directly support asymmetric grids,
        # but we can adjust the range to favor buy or sell side
        use_asymmetric = getattr(self.config, 'use_asymmetric_grids', True)
        if use_asymmetric and trend:
            trend_value = trend.consensus_trend_pct if trend.consensus_trend_pct != 0.0 else trend.trend_pct
            if trend_value > 1.0:  # Uptrend - favor sell side (wider upper range)
                expansion = (end_price - current_price) * Decimal("0.2")  # Expand upper by 20%
                end_price = end_price + expansion
                self.logger().info(f"📈 Uptrend detected ({trend_value:+.2f}%) - expanding sell side range")
            elif trend_value < -1.0:  # Downtrend - favor buy side (wider lower range)
                expansion = (current_price - start_price) * Decimal("0.2")  # Expand lower by 20%
                start_price = start_price - expansion
                self.logger().info(f"📉 Downtrend detected ({trend_value:+.2f}%) - expanding buy side range")

        # Validate start_price and end_price are positive and valid
        if start_price <= 0 or end_price <= 0:
            self.logger().error(
                f"❌ Cannot create grid for {symbol}: Invalid price range "
                f"(start={start_price}, end={end_price})"
            )
            return None

        if start_price >= end_price:
            self.logger().error(
                f"❌ Cannot create grid for {symbol}: start_price ({start_price}) >= end_price ({end_price})"
            )
            return None

        # Validate grid range is large enough (minimum 1% spread)
        grid_range_pct = float((end_price - start_price) / current_price * 100)
        min_range_pct = 1.0  # Minimum 1% range
        if grid_range_pct < min_range_pct:
            self.logger().warning(
                f"⚠️  Grid range too small ({grid_range_pct:.2f}% < {min_range_pct}%) - expanding to minimum"
            )
            # Expand range symmetrically around current price
            half_range = current_price * Decimal(str(min_range_pct / 200))  # Half of min_range_pct
            start_price = current_price - half_range
            end_price = current_price + half_range
            grid_range_pct = min_range_pct
            self.logger().info(
                f"   Expanded range: €{start_price:.4f} - €{end_price:.4f} ({grid_range_pct:.2f}%)"
            )

        # Re-validate current price is still within range (check before creating grid)
        # If price moved outside range, adjust range to include current price
        if current_price < start_price:
            self.logger().warning(
                f"⚠️  Current price ({current_price:.4f}) below start_price ({start_price:.4f}) - adjusting range"
            )
            # Expand lower bound to include current price with some margin
            start_price = current_price * Decimal("0.995")  # 0.5% below current
            grid_range_pct = float((end_price - start_price) / current_price * 100)
            self.logger().info(f"   Adjusted start_price: €{start_price:.4f} (range: {grid_range_pct:.2f}%)")
        elif current_price > end_price:
            self.logger().warning(
                f"⚠️  Current price ({current_price:.4f}) above end_price ({end_price:.4f}) - adjusting range"
            )
            # Expand upper bound to include current price with some margin
            end_price = current_price * Decimal("1.005")  # 0.5% above current
            grid_range_pct = float((end_price - start_price) / current_price * 100)
            self.logger().info(f"   Adjusted end_price: €{end_price:.4f} (range: {grid_range_pct:.2f}%)")

        # Final validation
        if start_price >= end_price:
            self.logger().error(
                f"❌ Cannot create grid for {symbol}: After adjustments, start_price ({start_price}) >= end_price ({end_price})")  # noqa: E501
            return None

        # Use start_price as limit price (price-based circuit breaker)
        limit_price = start_price * Decimal("0.95")  # 5% below start as safety

        # Validate limit_price is positive
        if limit_price <= 0:
            self.logger().error(
                f"❌ Cannot create grid for {symbol}: Invalid limit_price ({limit_price})"
            )
            return None

        # 🔧 CRITICAL FIX: Calculate ATR-based stop-loss BEFORE creating grid
        dynamic_stop_loss_pct = self.config.stop_loss_pct  # Default fallback
        atr_info = ""

        # Use volatility-based stops if professional risk management is enabled
        use_atr_stops = getattr(self.config, 'use_professional_risk_mgmt', False)

        if use_atr_stops:
            try:
                # Get trend data (has volatility = rolling std dev)
                trend = self.trend_calculator.get_trend(symbol)

                if trend and trend.volatility and trend.volatility > 0:
                    # Volatility is rolling std dev as decimal (e.g., 0.035 = 3.5%)
                    volatility_pct = float(trend.volatility)
                    multiplier = float(getattr(self.config, 'atr_stop_multiplier', 2.0))
                    min_stop = float(getattr(self.config, 'min_stop_pct', 0.02))
                    max_stop = float(getattr(self.config, 'max_stop_pct', 0.05))

                    # Calculate: clamp(volatility × multiplier, min, max)
                    calculated_stop = volatility_pct * multiplier
                    dynamic_stop = max(min_stop, min(calculated_stop, max_stop))

                    dynamic_stop_loss_pct = Decimal(str(dynamic_stop))
                    atr_info = f" (volatility: {volatility_pct * 100:.2f}% × {multiplier} = {calculated_stop * 100:.2f}%, clamped to {dynamic_stop * 100:.2f}%)"

                    self.logger().info(
                        f"✅ Dynamic stop for {symbol}: -{dynamic_stop_loss_pct * 100:.2f}%{atr_info}"
                    )
                else:
                    self.logger().warning(
                        f"⚠️  No volatility data for {symbol} - using fixed stop {self.config.stop_loss_pct * 100:.0f}%"
                    )
            except Exception as e:
                self.logger().error(
                    f"❌ Failed to calculate dynamic stop for {symbol}: {e} - using fixed stop {self.config.stop_loss_pct * 100:.0f}%"
                )
                import traceback
                self.logger().error(traceback.format_exc())

        self.logger().info(
            f"\n📝 CREATING GRID for {symbol} (Phase 4 Enhanced):"
            f"\n   Current Price: €{current_price:.4f}"
            f"\n   Range: €{start_price:.4f} - €{end_price:.4f} ({grid_method})"
            f"\n   Grid Levels: {num_grids} (volatility-adjusted)"
            f"\n   Limit Price: €{limit_price:.4f} (circuit breaker)"
            f"\n   Capital: €{self.config.total_amount_quote}"
            f"\n   Stop Loss: -{dynamic_stop_loss_pct * 100:.2f}%{atr_info}"
        )

        # Create grid config
        # CRITICAL SAFETY CHECK: Verify we're using the correct connector for paper trading
        paper_trading_config = getattr(self.config, 'paper_trading', False)
        if paper_trading_config:
            # Paper trading is enabled - auto-adjust connector name if needed
            if not self.config.connector_name.endswith('_paper_trade'):
                # Auto-fix: append _paper_trade to connector name
                original_connector_name = self.config.connector_name
                self.config.connector_name = f"{original_connector_name}_paper_trade"
                self.logger().info(
                    f"🔧 Paper trading enabled: Auto-adjusting connector name "
                    f"'{original_connector_name}' → '{self.config.connector_name}'"
                )
                # Also update self.connector if it exists
                if self.connector and original_connector_name in self.connectors:
                    # Try to get paper trading connector
                    if self.config.connector_name in self.connectors:
                        self.connector = self.connectors[self.config.connector_name]
                        self.logger().info(f"✅ Switched to paper trading connector: {self.config.connector_name}")
                    else:
                        self.logger().warning(
                            f"⚠️  Paper trading connector '{self.config.connector_name}' not found in connectors dict. "
                            f"Will be created when needed."
                        )

        # Get leverage from config (for futures) or use default 1 (for spot)
        leverage = getattr(self.config, "derivative_leverage", 1)

        from hummingbot.core.data_type.common import TradeType

        trade_amount_quote = total_amount_quote if total_amount_quote is not None else Decimal(
            str(self.config.total_amount_quote))

        # Story D1: Calculate adaptive timeout based on market volatility
        adaptive_timeout_sec = self.config.no_fill_timeout_sec  # Default fallback
        try:
            # Fetch recent candle data for volatility calculation
            candle_df = self.market_data_provider.get_candles_df(
                connector_name=self.config.connector_name,
                trading_pair=symbol,
                interval="1m",  # 1-minute candles for responsiveness
                max_records=20  # 20 candles for ATR calculation (need 14+ for ATR-14)
            )

            if candle_df is not None and not candle_df.empty and len(candle_df) >= 14:
                # Extract OHLC data
                highs = [float(h) for h in candle_df['high'].tolist()]
                lows = [float(low) for low in candle_df['low'].tolist()]
                closes = [float(c) for c in candle_df['close'].tolist()]

                # Calculate adaptive timeout
                timeout_result = get_recommended_timeout(
                    symbol=symbol,
                    current_price=float(current_price),
                    high_prices=highs,
                    low_prices=lows,
                    close_prices=closes,
                    base_timeout_sec=self.config.no_fill_timeout_sec
                )

                adaptive_timeout_sec = timeout_result.adjusted_timeout_sec

                # Log timeout adjustment with reasoning
                if timeout_result.adjustment_factor != 1.0:
                    self.logger().info(
                        f"⏱️  Adaptive timeout for {symbol}: "
                        f"{adaptive_timeout_sec}s (was {self.config.no_fill_timeout_sec}s, "
                        f"factor: {timeout_result.adjustment_factor:.2f}x) - "
                        f"{timeout_result.reasoning}"
                    )
            else:
                self.logger().debug(
                    f"⚠️  Insufficient candle data for adaptive timeout ({len(candle_df) if candle_df is not None else 0} candles) - "
                    f"using base timeout {adaptive_timeout_sec}s"
                )
        except Exception as e:
            self.logger().warning(
                f"⚠️  Failed to calculate adaptive timeout for {symbol}: {e} - "
                f"using base timeout {adaptive_timeout_sec}s"
            )

        # 🔧 CRITICAL FIX: Create triple_barrier_config with dynamic stop-loss

        # 🔧 FIX: Bitget doesn't support LIMIT_MAKER, use LIMIT for all
        order_type = OrderType.LIMIT

        dynamic_triple_barrier = TripleBarrierConfig(
            stop_loss=dynamic_stop_loss_pct,  # ✅ USE DYNAMIC STOP!
            take_profit=self.config.take_profit_pct,
            time_limit=None,
            trailing_stop=None,
            open_order_type=order_type,
            take_profit_order_type=order_type,
            stop_loss_order_type=OrderType.MARKET,
            time_limit_order_type=OrderType.MARKET
        )

        grid_config = GridExecutorConfig(
            timestamp=self.market_data_provider.time(),
            connector_name=self.config.connector_name,
            trading_pair=symbol,
            side=TradeType.BUY,  # Buy-side grid
            start_price=start_price,
            end_price=end_price,
            limit_price=limit_price,
            total_amount_quote=trade_amount_quote,
            min_spread_between_orders=Decimal("0.001"),  # 0.1% min spread
            min_order_amount_quote=self.config.min_order_amount_quote,
            triple_barrier_config=dynamic_triple_barrier,  # ✅ USE DYNAMIC CONFIG!
            # Adjust max orders to grid count, ensure >= 1
            max_open_orders=max(1, min(self.config.max_open_orders, num_grids)),
            max_orders_per_batch=2,  # Can place 2 OPEN orders per batch
            order_frequency=self.config.order_frequency,
            activation_bounds=Decimal("0.05"),  # 5% activation bounds
            keep_position=False,  # Don't keep position on stop
            leverage=leverage,  # Use derivative_leverage from config (for futures) or 1 (for spot)
            deduct_base_fees=False,  # FALSE for Kraken EUR pairs (fees paid in quote, not base)
            # Story A1: Pass timeout config to executor via custom_info
            # Story D1: Use adaptive timeout (volatility-adjusted)
            custom_info={
                "no_fill_timeout_sec": adaptive_timeout_sec,  # D1: Dynamic timeout
                "no_progress_timeout_sec": self.config.no_progress_timeout_sec,
                "max_hold_time_sec": self.config.max_hold_time_seconds,  # Reuse existing config
                "close_grace_sec": self.config.close_grace_sec,
            }
        )

        # Ensure controller_id is set (fallback to controller_name if id is None)
        controller_id = self.config.id
        if not controller_id:
            controller_id = getattr(self.config, 'controller_name', 'multi_coin_grid')
            self.logger().warning(
                f"⚠️  config.id is None, using controller_name '{controller_id}' as fallback"
            )

        # Create action
        try:
            action = CreateExecutorAction(
                controller_id=controller_id,
                executor_config=grid_config
            )

            # Store executor ID
            self.active_executor_id = grid_config.id

            # BUG FIX: Track executor creation time for grace period check
            if not hasattr(self, '_executor_creation_times'):
                self._executor_creation_times = {}
            current_timestamp = self.market_data_provider.time()
            self._executor_creation_times[grid_config.id] = current_timestamp

            # Track creation timestamp for TTL-based cleanup
            if not hasattr(self, '_executor_creation_timestamps'):
                self._executor_creation_timestamps = {}
            self._executor_creation_timestamps[grid_config.id] = current_timestamp

            # Phase 1.1: Track entry price for stop-loss monitoring
            self.entry_prices[symbol] = current_price

            # Phase 4.4: Track grid creation time and price for smart refill
            self.last_grid_creation_time = self.market_data_provider.time()
            self.last_grid_price[symbol] = current_price

            self.logger().info(
                f"📌 Entry price tracked for {symbol}: €{current_price:.4f} "
                f"(Stop-loss will trigger at €{current_price * (Decimal('1') - self.config.stop_loss_pct):.4f})"
            )

            return action
        except Exception as e:
            self.logger().error(f"❌ Failed to create grid action for {symbol}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            return None

    def _create_stop_action(self) -> StopExecutorAction:
        """
        Create a StopExecutorAction for active executor

        Returns:
            StopExecutorAction
        """
        if not self.active_executor_id:
            self.logger().warning("⚠️  No executor ID to stop")
            return None

        # Validate executor exists before stopping
        executor_exists = any(
            e.id == self.active_executor_id for e in self.executors_info
        )

        if not executor_exists:
            self.logger().warning(
                f"⚠️  Executor {self.active_executor_id[:8]}... not found - "
                f"already stopped or never created"
            )
            # Clear state since executor doesn't exist
            # MULTI-COIN: Also remove from active_coins
            if self.active_coin and self.active_coin in self.active_coins:
                del self.active_coins[self.active_coin]
                self.logger().info(f"📊 Removed {self.active_coin} from active_coins: {list(self.active_coins.keys())}")
                # MEMORY LEAK FIX: Clean up price history for this coin
                if self.active_coin in self.price_history_for_volatility:
                    del self.price_history_for_volatility[self.active_coin]
                    self.logger().debug(f"🧹 Cleaned up price history for {self.active_coin}")
            self.active_executor_id = None
            self.active_coin = None
            return None

        # Ensure controller_id is set (fallback to controller_name if id is None)
        controller_id = self.config.id
        if not controller_id:
            controller_id = getattr(self.config, 'controller_name', 'multi_coin_grid')
            self.logger().warning(
                f"⚠️  config.id is None, using controller_name '{controller_id}' as fallback"
            )

        self.logger().info(f"🛑 STOPPING executor for {self.active_coin}")

        # Check if executor has open position that needs to be closed
        executor_info = next(
            (e for e in self.executors_info if e.id == self.active_executor_id),
            None
        )

        has_open_position = False
        if executor_info:
            # Task 2.3: Pre-close validation before stopping executor
            can_close, close_reason = self._can_safely_close_position(self.active_coin, executor_info)

            if not can_close:
                self.logger().warning(
                    f"⚠️ PRE-CLOSE CHECK FAILED: {self.active_coin} cannot be closed safely\n"
                    f"   Reason: {close_reason}\n"
                    f"   Action: Marking executor for manual review (will not attempt close)"
                )
                # Still create stop action, but log the issue
                # Executor's early_stop() will handle the dust scenario gracefully
            else:
                self.logger().info(f"✅ Pre-close check passed: {self.active_coin} can be closed safely")

            # Check custom_info for grid executor position
            custom_info = executor_info.custom_info
            position_size_quote = custom_info.get("position_size_quote", Decimal("0"))
            if isinstance(position_size_quote, (int, float)):
                position_size_quote = Decimal(str(position_size_quote))

            # Also check filled_amount_quote as fallback
            if position_size_quote == Decimal("0"):
                filled_amount = executor_info.filled_amount_quote
                if filled_amount and filled_amount > Decimal("0"):
                    has_open_position = True
                    self.logger().warning(
                        f"⚠️  Executor has open position: {filled_amount} EUR filled - "
                        f"position should be closed when executor stops"
                    )
            elif position_size_quote > Decimal("0"):
                has_open_position = True
                self.logger().warning(
                    f"⚠️  Executor has open position: {position_size_quote} EUR - "
                    f"position should be closed when executor stops"
                )

        # Phase 1.1: Clear entry price tracking when stopping executor
        if self.active_coin in self.entry_prices:
            entry_price = self.entry_prices[self.active_coin]
            del self.entry_prices[self.active_coin]
            self.logger().info(f"📌 Cleared entry price tracking for {self.active_coin} (was €{entry_price:.4f})")

        # Phase 1.4: Clear exposure tracking when stopping executor
        if self.active_coin:
            exposure_to_remove = self.current_exposure_per_coin.get(
                self.active_coin,
                self._active_executor_notional if self._active_executor_notional > Decimal("0") else Decimal(str(self.config.total_amount_quote)),  # noqa: E501
            )
            self._update_exposure_tracking(self.active_coin, -exposure_to_remove)
            self._active_executor_notional = Decimal("0")

        try:
            # Explicitly set keep_position=False to ensure position is closed
            # GridExecutor should handle closing the position when keep_position=False
            stop_action = StopExecutorAction(
                controller_id=controller_id,
                executor_id=self.active_executor_id,
                keep_position=False  # Explicitly close position when switching coins
            )

            if has_open_position:
                self.logger().warning(
                    f"⚠️  ⚠️  ⚠️  CRITICAL: Executor {self.active_executor_id[:8]}... "
                    f"has open position but will be stopped with keep_position=False. "
                    f"GridExecutor should close the position, but if it doesn't, "
                    f"you may need to manually sell {self.active_coin}!"
                )

            return stop_action
        except Exception as e:
            self.logger().error(f"❌ Failed to create stop action: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            return None

    def to_format_status(self) -> List[str]:
        """
        Format status for display in Hummingbot UI

        Returns:
            List of status strings
        """
        status = []

        status.append("\n╔═══════════════════════════════════════════════════════════════╗")
        status.append("║          MULTI-COIN GRID TRADING STATUS                      ║")
        status.append("╠═══════════════════════════════════════════════════════════════╣")

        # Paper Trading Status
        connector_name = self.config.connector_name
        paper_trading_config = getattr(self.config, 'paper_trading', False)
        is_paper_trading = connector_name.endswith('_paper_trade') or paper_trading_config

        # Log paper trading status for debugging
        self.logger().debug(
            f"🔍 Paper Trading Check: connector_name={connector_name}, paper_trading_config={paper_trading_config}, is_paper_trading={is_paper_trading}")  # noqa: E501

        if is_paper_trading:
            status.append("║ 📝 MODE: PAPER TRADING (No real money - simulated orders)    ║")
            status.append(f"║ Connector: {connector_name:55} ║")
            # Also log it prominently
            self.logger().info("=" * 80)
            self.logger().info("📝 PAPER TRADING MODE ACTIVE - No real money will be used!")
            self.logger().info(f"   Connector: {connector_name}")
            self.logger().info("=" * 80)
        else:
            status.append("║ 💰 MODE: LIVE TRADING (Real money - be careful!)            ║")
            status.append(f"║ Connector: {connector_name:55} ║")
            # Warn if paper trading is enabled in config but connector name doesn't match
            if paper_trading_config and not connector_name.endswith('_paper_trade'):
                status.append("║ ⚠️  WARNING: paper_trading=True but connector not _paper_trade! ║")
                self.logger().warning("⚠️  Paper trading is enabled in config but connector name doesn't end with '_paper_trade'!")  # noqa: E501
                self.logger().warning(f"   Config says paper_trading=True, but connector={connector_name}")
                self.logger().warning("   Bot may be using LIVE trading instead of paper trading!")
                self.logger().warning("   Restart the bot to apply paper trading mode.")

        # Circuit Breaker Status
        if self.circuit_breaker_active:
            status.append("║ 🛑 CIRCUIT BREAKER: ACTIVE - Trading PAUSED                ║")
            if self.circuit_breaker_triggered_at:
                time_since = self.market_data_provider.time() - self.circuit_breaker_triggered_at
                status.append(f"║ Triggered: {time_since / 60:.1f} minutes ago                        ║")

        # Phase 1.3: API Error Status
        if self.api_error_paused:
            status.append("║ 🛑 API ERRORS: PAUSED - Trading PAUSED                     ║")
            if self.api_error_paused_at:
                time_since = self.market_data_provider.time() - self.api_error_paused_at
                status.append(f"║ Paused: {time_since / 60:.1f} min ago ({self.consecutive_api_errors} errors) ║")
        elif self.consecutive_api_errors > 0:
            status.append(
                f"║ ⚠️  API Errors: {self.consecutive_api_errors}/{self.api_error_threshold} consecutive    ║")

        # Phase 1.4: Position Limits Status
        if self.total_exposure > Decimal("0"):
            total_capital = self.config.total_amount_quote
            exposure_pct = float(self.total_exposure / total_capital * 100) if total_capital > 0 else 0
            status.append(f"║ 📊 Total Exposure: €{self.total_exposure:.2f} ({exposure_pct:.1f}%)              ║")

        # Active coin
        if self.active_coin:
            trend = self.trend_calculator.get_trend(self.active_coin)
            if trend:
                status.append(f"║ Active Coin: {self.active_coin:12} | Trend: {trend.trend_pct:+6.2f}%          ║")
                status.append(f"║ Price: €{trend.current_price:8.4f}                                    ║")

                # Phase 1.1: Show entry price and stop-loss status
                entry_price = self.entry_prices.get(self.active_coin)
                if entry_price:
                    loss_pct = float((Decimal(str(trend.current_price)) - entry_price) / entry_price * 100)
                    stop_loss_pct = float(self.config.stop_loss_pct * 100)
                    stop_loss_price = entry_price * (Decimal('1') - self.config.stop_loss_pct)
                    status.append(
                        f"║ Entry: €{entry_price:.4f} | Stop-Loss: €{stop_loss_price:.4f} (-{stop_loss_pct:.2f}%) ║")
                    status.append(
                        f"║ Current P&L: {loss_pct:+.2f}% from entry                              ║")

                # Show executor P&L if available
                if self.active_executor_id:
                    executor_info = next(
                        (e for e in self.executors_info if e.id == self.active_executor_id),
                        None
                    )
                    if executor_info:
                        pnl_quote = executor_info.net_pnl_quote
                        pnl_pct = float(executor_info.net_pnl_pct) * 100  # Convert fraction to percentage
                        fees = executor_info.cum_fees_quote
                        filled = executor_info.filled_amount_quote

                        # Format P&L with emoji
                        if pnl_quote > 0:
                            pnl_emoji = "💰"
                        elif pnl_quote < 0:
                            pnl_emoji = "📉"
                        else:
                            pnl_emoji = "➖"

                        status.append(f"║ {pnl_emoji} P&L: €{pnl_quote:+.2f} ({pnl_pct:+.2f}%) | Fees: €{fees:.2f} ║")
                        if filled > 0:
                            status.append(f"║ 📊 Volume Traded: €{filled:.2f}                              ║")

                        # MONITORING FIX: Log executor P&L to log file so collector can find it
                        self.logger().info(
                            f"📊 MONITORING: Executor P&L: €{pnl_quote:+.2f} ({pnl_pct:+.2f}%) | Active Coin: {self.active_coin or 'None'}")  # noqa: E501
        else:
            status.append("║ Active Coin: None (waiting for opportunity)                  ║")

        # Show total P&L from all executors
        if self.executors_info:
            total_pnl_quote = sum(Decimal(str(e.net_pnl_quote)) for e in self.executors_info)
            total_fees = sum(Decimal(str(e.cum_fees_quote)) for e in self.executors_info)
            total_volume = sum(Decimal(str(e.filled_amount_quote)) for e in self.executors_info)
            # Calculate correct P&L percentage: (total_pnl / total_volume) * 100
            total_pnl_pct = (total_pnl_quote / total_volume * Decimal("100")) if total_volume > 0 else Decimal("0")

            if total_volume > 0:
                if total_pnl_quote > 0:
                    total_emoji = "💰"
                elif total_pnl_quote < 0:
                    total_emoji = "📉"
                else:
                    total_emoji = "➖"

                status.append(
                    f"║ {total_emoji} Total P&L: €{total_pnl_quote:+.2f} ({total_pnl_pct:+.2f}%) | Fees: €{total_fees:.2f} ║")  # noqa: E501
                status.append(f"║ 📊 Total Volume: €{total_volume:.2f} ({len(self.executors_info)} executor(s)) ║")

                # MONITORING FIX: Log P&L to log file so collector can find it
                self.logger().info(
                    f"📊 MONITORING: Total P&L: €{
                        total_pnl_quote:+.2f} ({
                        total_pnl_pct:+.2f}%) | Active Coin: {
                        self.active_coin or 'None'} | Exposure: €{
                        self.total_exposure:.2f}")

                # MONITORING FIX: Log P&L to log file so collector can find it
                self.logger().info(
                    f"📊 MONITORING: Total P&L: €{
                        total_pnl_quote:+.2f} ({
                        total_pnl_pct:+.2f}%) | Active Coin: {
                        self.active_coin or 'None'} | Exposure: €{
                        self.total_exposure:.2f}")

        # Time since last switch
        if self.last_switch_time > 0:
            time_since = self.market_data_provider.time() - self.last_switch_time
            status.append(f"║ Time Since Switch: {time_since / 60:.1f} minutes                        ║")

        # Monitored coins summary
        if self.trend_calculator:
            coins_with_data = sum(
                1 for t in self.trend_calculator.trends.values()
                if t.has_sufficient_data
            )
            status.append(
                f"║ Monitored Coins: {len(self.monitored_coins)} total, {coins_with_data} with full data    ║")

        # Memory usage tracking (Phase 6: Memory Leak Fix)
        num_price_histories = len(self.price_history_for_volatility)
        num_active_coins = len(self.active_coins)
        num_executors = len(self._executor_creation_times) if hasattr(self, '_executor_creation_times') else 0
        if num_price_histories > 0 or num_executors > 0:
            status.append("║ ─────────────────────────────────────────────────────────── ║")
            status.append(f"║ 🧠 Memory: {num_price_histories} price histories, {num_active_coins} active, {num_executors} tracked     ║")
            # Warn if price histories growing without bound
            if num_price_histories > num_active_coins + 5:
                status.append("║ ⚠️  WARNING: Too many price histories - possible memory leak! ║")

        status.append("╚═══════════════════════════════════════════════════════════════╝\n")

        return status

    # Phase 2.5: Multi-Timeframe Buy Conditions
    def _check_multi_timeframe_buy_conditions(self, coin: str) -> bool:
        """
        Phase 2.5: Check if coin meets multi-timeframe buy conditions

        Two-layer validation:
        1. Quick filter: validate_trend() checks 360 candles + MIN_TREND_THRESHOLD
        2. Detailed checks: staleness, consensus, multi-timeframe confirmation

        Buy conditions:
        - trend_1440m > +1% (24h trend positive)
        - trend_240m > +1% (4h trend positive)
        - trend_60m >= 0% (1h trend not negative)

        Args:
            coin: Coin symbol to check

        Returns:
            True if coin meets buy conditions
        """
        try:
            # ============================================================
            # PHASE 1: Quick validation with new framework
            # ============================================================
            validation = self.trend_calculator.validate_trend(coin)
            if not validation:
                self.logger().debug(f"⚠️  {coin}: No validation data available")
                return False

            # Reject if basic validation fails
            if not validation.passes:
                reason_map = {
                    TrendStatus.WARMUP: f"insufficient data ({validation.candle_count} candles < 360)",
                    TrendStatus.BEARISH: f"bearish trend ({validation.trend_score_pct:+.2f}% < -0.5%)",
                    TrendStatus.SIDEWAYS: f"sideways trend ({validation.trend_score_pct:+.2f}% < +0.5%)",
                }
                reason = reason_map.get(validation.status, "unknown reason")
                self.logger().info(
                    f"[DECISION] ❌ {coin} BUY REJECTED (Phase 1 - Quick Filter): {reason}"
                )
                return False

            self.logger().debug(
                f"✅ {coin} passed Phase 1 validation: {validation.status.value} "
                f"({validation.trend_score_pct:+.2f}%, {validation.candle_count} candles)"
            )

            # ============================================================
            # PHASE 2: Detailed checks (existing logic)
            # ============================================================
            trend = self.trend_calculator.get_trend(coin)
            if not trend:
                return False

            # Reject stale trend data (90s = 3x refresh interval = reasonable for real-time trading)
            staleness_threshold = getattr(self.config, "price_update_interval", 30) * 3  # 90s with 30s interval
            if self.market_data_provider.time() - trend.last_updated > staleness_threshold:
                self.logger().info(
                    f"[DECISION] ❌ {coin} BUY REJECTED (Phase 2 - Staleness): "
                    f"data {self.market_data_provider.time() - trend.last_updated:.1f}s old (max {staleness_threshold}s)"  # noqa: E501
                )
                return False

            trend_strength = self._compute_trend_strength(trend)

            # DEBUG: Log trend attributes
            self.logger().debug(
                f"🔍 {coin} trend_strength calculation: "
                f"consensus={getattr(trend, 'consensus_trend_pct', 'N/A')}, "
                f"score={getattr(trend, 'trend_score', 'N/A')}, "
                f"trend_pct={getattr(trend, 'trend_pct', 'N/A')}, "
                f"→ strength={trend_strength:.4f}"
            )

            # Use small epsilon for floating point comparison (avoid 0.10 < 0.10 false rejections)
            epsilon = 0.001  # 0.001 tolerance
            if trend_strength < (self.config.trend_min_entry_strength - epsilon):
                self.logger().info(
                    f"[DECISION] ❌ {coin} BUY REJECTED (Phase 2 - Strength): "
                    f"strength {trend_strength:+.2f} < {self.config.trend_min_entry_strength:+.2f}"
                )
                return False

            # Check if multi-timeframe data is available
            # Only allow if in warm-up mode (first 24h) - don't allow if trend_60m ==
            # 0.0 (that means 0% trend, not "no data")
            if not hasattr(trend, 'trend_60m'):
                # Multi-timeframe fields don't exist - fallback to old logic
                self.logger().debug(f"⚠️  Multi-timeframe fields not available for {coin} - allowing (fallback)")
                return True

            # Confirmation count across timeframes
            timeframe_values = [
                trend.trend_60m,
                trend.trend_240m,
                trend.trend_1440m,
            ]
            confirmations = sum(1 for value in timeframe_values if value > 0.0)

            # EXCEPTION: Strong consensus allows entry even with 0 confirming timeframes
            # This catches "buy the dip" opportunities on pullbacks
            strong_consensus_threshold = 0.02  # 2% consensus
            has_strong_consensus = trend_strength >= strong_consensus_threshold

            if confirmations < self.config.trend_confirmation_timeframes:
                if has_strong_consensus:
                    self.logger().info(
                        f"[DECISION] ✅ {coin} BUY APPROVED (Phase 2 - Strong Consensus Override): "
                        f"{confirmations} timeframes but consensus {trend_strength * 100:.2f}% >= {strong_consensus_threshold * 100:.0f}%"  # noqa: E501
                    )
                else:
                    self.logger().info(
                        f"[DECISION] ❌ {coin} BUY REJECTED (Phase 2 - Confirmation): " f"only {confirmations} confirming timeframes (requires {  # noqa: E501
                            self.config.trend_confirmation_timeframes}, or {
                            strong_consensus_threshold * 100:.0f}% consensus)")
                    return False

            # Check if in warm-up mode (first 24h after bot start)
            if hasattr(trend, 'long_trend_warmup') and trend.long_trend_warmup:
                # CRITICAL FIX: During warm-up, be MUCH more conservative
                # The 24h trend fallback (240m * 2) can be misleading if coin is crashing
                # We need STRONG positive trends in ALL timeframes to buy during warm-up

                # Stricter requirements during warm-up:
                # 1. 240m trend must be STRONGLY positive (> warmup_4h_strong_min)
                # 2. 60m trend must be neutral or positive (>= 0.0%)
                # 3. Both must be positive (reject if either is negative)

                # 🔧 FIX: Use same logic as normal MTF checks - warmup_4h_strong_min is the THRESHOLD
                # If warmup_4h_strong_min = -0.5, then -2.08% should be REJECTED (< -0.5)
                # If warmup_4h_strong_min = -2.5, then -2.08% should be ACCEPTED (> -2.5)
                warmup_4h_threshold = getattr(self.config, 'warmup_4h_strong_min', -0.5)
                warmup_1h_threshold = getattr(self.config, 'warmup_1h_min_if_4h_strong', -2.0)

                warmup_240m_ok = trend.trend_240m > warmup_4h_threshold
                warmup_60m_ok = trend.trend_60m >= warmup_1h_threshold  # 🔧 FIX: Use config, not hardcoded 0.0
                both_positive = trend.trend_240m > warmup_4h_threshold and trend.trend_60m > warmup_1h_threshold

                # NEW: Warmup Override - Allow 1H negative if 4H is VERY strong (pullback buying)
                override_active = False
                if self.config.warmup_override_enabled:
                    # Override already works correctly - warmup_240m_ok checks if 4h > threshold
                    if warmup_240m_ok:  # 4H is acceptable
                        if trend.trend_60m >= warmup_1h_threshold:  # 1H is acceptable (uses config threshold now)
                            warmup_60m_ok = True  # Override: accept 1h within configured limit
                            both_positive = True  # Override: ignore strict positive check
                            override_active = True

                if warmup_240m_ok and warmup_60m_ok and both_positive:
                    # Check if we're using loaded historical data or calculated warm-up data
                    data_source = "historical data" if len(trend.price_history) > 1000 else "short-term avg"
                    override_msg = " (4H OVERRIDE: pullback buy)" if override_active else ""
                    self.logger().info(
                        f"[DECISION] ✅ {coin} BUY APPROVED (warm-up mode - CONSERVATIVE{override_msg}):\n"
                        f"   [TREND] 24h: {trend.trend_1440m:+.2f}% ({data_source}) | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"  # noqa: E501
                        f"   [SCORE] Composite: {trend.trend_score:+.2f}%\n"
                        f"   [NOTE] Warm-up mode: {'Strong 4H overrides weak 1H (professional pullback buy)' if override_active else 'Stricter criteria applied for safety'}"  # noqa: E501
                    )
                    return True
                else:
                    # Reject with detailed reason
                    reasons = []
                    if not warmup_240m_ok:
                        reasons.append(
                            f"4h trend ({trend.trend_240m:+.2f}%) <= {warmup_4h_threshold:+.2f}% (warm-up requires > {warmup_4h_threshold:+.2f}%)")  # noqa: E501
                    if not warmup_60m_ok:
                        override_status = f" (override needs 4H ≥ {warmup_4h_threshold:+.1f}%, 1H ≥ {warmup_1h_threshold:+.1f}%)" if self.config.warmup_override_enabled else ""  # noqa: E501
                        reasons.append(f"1h trend ({trend.trend_60m:+.2f}%) < {warmup_1h_threshold:+.2f}%{override_status}")
                    if not both_positive:
                        reasons.append(
                            f"One or both trends negative (4h: {trend.trend_240m:+.2f}%, 1h: {trend.trend_60m:+.2f}%)")
                    if not both_positive:
                        reasons.append(
                            f"One or both trends negative (4h: {trend.trend_240m:+.2f}%, 1h: {trend.trend_60m:+.2f}%)")

                    self.logger().warning(
                        f"[DECISION] ❌ {coin} BUY REJECTED (warm-up mode - TOO RISKY):\n"
                        f"   [TREND] 24h: {trend.trend_1440m:+.2f}% (warm-up fallback) | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"  # noqa: E501
                        f"   [REASON] {' | '.join(reasons)}\n"
                        f"   [NOTE] Warm-up mode requires STRONG positive trends to avoid buying crashing coins"
                    )
                    return False

            # Buy conditions (exit thresholds are only used in exit conditions, not here)
            # 🔧 FIX: Use config values instead of hardcoded thresholds!
            # This allows multi-coin trading in choppy/pullback conditions
            trend_1440m_threshold = getattr(self.config, 'mtf_24h_min_pct', -2.5)  # Default: -2.5% (allow pullbacks)
            trend_240m_threshold = getattr(self.config, 'mtf_4h_min_pct', -2.5)    # Default: -2.5% (allow pullbacks)
            trend_60m_threshold = getattr(self.config, 'mtf_1h_min_pct', -3.0)     # Default: -3.0% (allow pullbacks)

            trend_1440m_ok = trend.trend_1440m > trend_1440m_threshold
            trend_240m_ok = trend.trend_240m > trend_240m_threshold
            trend_60m_ok = trend.trend_60m >= trend_60m_threshold

            # CRITICAL: Additional check - reject if both short-term trends are negative
            # This prevents trading during declining trends even if 24h trend is positive
            # 🔧 FIX: Use mtf_declining thresholds from config (less conservative)
            declining_1h_threshold = getattr(self.config, 'mtf_declining_1h_max', -4.0)  # Default: -4%
            declining_4h_threshold = getattr(self.config, 'mtf_declining_4h_max', -2.0)  # Default: -2%

            declining_trend = trend.trend_60m < declining_1h_threshold and trend.trend_240m < declining_4h_threshold

            if declining_trend:
                self.logger().warning(
                    f"[DECISION] ❌ {coin} BUY REJECTED: Severe declining trend detected!\n"
                    f"   [TREND] 24h: {trend.trend_1440m:+.2f}% | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"  # noqa: E501
                    f"   [REASON] 1h trend ({trend.trend_60m:+.2f}%) < {declining_1h_threshold}% AND 4h trend ({trend.trend_240m:+.2f}%) < {declining_4h_threshold}%\n"  # noqa: E501
                    f"   [NOTE] Avoiding trade during severe crashes (uses mtf_declining thresholds)"
                )
                return False

            if not trend_1440m_ok:
                self.logger().info(
                    f"[DECISION] ❌ {coin} BUY REJECTED: 24h trend ({trend.trend_1440m:+.2f}%) <= {trend_1440m_threshold:+.2f}%"
                )
                return False

            if not trend_240m_ok:
                self.logger().info(
                    f"[DECISION] ❌ {coin} BUY REJECTED: 4h trend ({trend.trend_240m:+.2f}%) <= {trend_240m_threshold:+.2f}%"
                )
                return False

            if not trend_60m_ok:
                self.logger().info(
                    f"[DECISION] ❌ {coin} BUY REJECTED: 1h trend ({trend.trend_60m:+.2f}%) < {trend_60m_threshold:+.2f}%"
                )
                return False

            # All conditions met - both Phase 1 and Phase 2 passed!
            self.logger().info(
                f"[DECISION] ✅ {coin} BUY APPROVED (All Phases Passed):\n"
                f"   [PHASE 1] Validation: {validation.status.value} | Score: {validation.trend_score_pct:+.2f}% | Candles: {validation.candle_count}\n"  # noqa: E501
                f"   [PHASE 2] Timeframes - 24h: {trend.trend_1440m:+.2f}% | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"  # noqa: E501
                f"   [SCORE] Composite: {trend.trend_score:+.2f}% | Strength: {trend_strength * 100:+.2f}%"
            )
            return True

        except Exception as e:
            self.logger().error(f"❌ Error checking multi-timeframe buy conditions for {coin}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            # On error, allow (fail open)
            return True

    # PRO EXIT SYSTEM - 5-Layer Stack
    def should_exit_position(self, coin: str) -> Optional[str]:
        """
        PRO EXIT SYSTEM: Check if position should be exited using 5-layer stack.

        Layer 1: Minimum Hold Time (Anti-Whipsaw)
        Layer 2: Trend Exit (Macro Confirmation)
        Layer 3: Price-Based Exit (Emergency Protection) - PRIORITY #1
        Layer 4: Trailing Trend Exit (Not implemented yet)
        Layer 5: Grid Profit Exit (Guaranteed Profit)

        Args:
            coin: Coin symbol to check

        Returns:
            Exit reason string if exit should occur, None otherwise.
            Possible values:
            - "emergency_exit" (Layer 3)
            - "hard_stop_exit" (Layer 3)
            - "trend_exit" (Layer 2)
            - "grid_profit_exit" (Layer 5)
            - None (no exit)
        """
        try:
            # Get entry price
            entry_price = self.entry_prices.get(coin)
            if not entry_price:
                # No entry price tracked - can't check price-based exits
                return None

            # Get current price and trends
            trend = self.trend_calculator.get_trend(coin)
            if not trend:
                return None

            current_price = Decimal(str(trend.current_price))
            time_since_switch = self.market_data_provider.time() - self.last_switch_time
            self._compute_trend_strength(trend)

            # Calculate price change for logging
            price_change_pct = float((current_price - entry_price) / entry_price * 100)

            # ---------------------------------------
            # LAYER 1: HOLD TIME FILTER
            # ---------------------------------------
            min_hold_time = float(self.risk_manager.min_hold_seconds)
            max_hold_time = float(getattr(self.risk_manager, 'max_hold_seconds', 0))

            # CRITICAL FIX: Hard minimum hold time for trend exits (defaults to half the min hold, minimum 10 minutes)
            # Only emergency exits can bypass this
            hard_min_hold_time = float(max(600.0, min_hold_time))
            in_hard_grace_period = time_since_switch < hard_min_hold_time

            # NEW: Check max hold time (force rotation to better opportunities)
            if max_hold_time > 0 and time_since_switch >= max_hold_time:
                self.logger().warning(
                    f"[EXIT] ⏰ {coin} MAX HOLD TIME EXCEEDED:\n"
                    f"   Hold Time: {time_since_switch / 3600:.1f} hours (max: {max_hold_time / 3600:.1f}h)\n"
                    f"   Price Change: {price_change_pct:+.2f}%\n"
                    f"   [REASON] Position held too long - forcing rotation to find better opportunities\n"
                    f"   (Prevents 21h+ stuck positions like VSN-EUR case)"
                )
                return "max_hold_time_exit"

            if in_hard_grace_period:
                # Still in hard grace period - only allow emergency exits
                remaining = hard_min_hold_time - time_since_switch
                self.logger().info(
                    f"⏰ {coin} exit check: still in HARD grace period ({remaining / 60:.1f} min remaining) - "
                    f"only emergency exits allowed (prevents premature exits)"
                )
                # Allow emergency exits even in grace period
                # Will be checked below

            if time_since_switch < min_hold_time:
                # Still in grace period - don't exit even if conditions are met (except emergency)
                remaining = min_hold_time - time_since_switch
                self.logger().debug(
                    f"⏰ {coin} exit check: still in grace period - "
                    f"wait {remaining / 60:.1f} more minutes (hold time protection)"
                )
                # Don't return None yet - check emergency exits first

            # Calculate price change percentage
            price_change_pct = float((current_price - entry_price) / entry_price * 100)

            # Account for round-trip fees (maker + taker ≈ 0.31%)
            estimated_fees_pct = 0.31
            price_change_pct - estimated_fees_pct

            # ---------------------------------------
            # LAYER 3: EMERGENCY EXIT (PRIORITY #1)
            # ---------------------------------------
            emergency_exit_pct = getattr(self.config, 'emergency_exit_pct', -2.0)  # Default tightened to -2.0%
            if price_change_pct <= emergency_exit_pct:
                self.logger().critical(
                    f"[EXIT] 🚨 {coin} EMERGENCY EXIT TRIGGERED:\n" f"   Entry Price: €{
                        entry_price:.4f}\n" f"   Current Price: €{
                        current_price:.4f}\n" f"   Price Change: {
                        price_change_pct:.2f}% (threshold: {
                        emergency_exit_pct
                        * 100:.2f}%)\n" f"   [REASON] Price dropped {
                        abs(price_change_pct):.2f}% below entry - emergency exit to prevent further losses")
                return "emergency_exit"

            # ---------------------------------------
            # LAYER 3: HARD STOP (Fail-safe)
            # ---------------------------------------
            hard_stop_pct = getattr(self.config, 'hard_stop_pct', -3.0)  # Default tightened to -3.0%
            if price_change_pct <= hard_stop_pct:
                self.logger().critical(
                    f"[EXIT] 🛑 {coin} HARD STOP TRIGGERED:\n" f"   Entry Price: €{
                        entry_price:.4f}\n" f"   Current Price: €{
                        current_price:.4f}\n" f"   Price Change: {
                        price_change_pct:.2f}% (threshold: {
                        hard_stop_pct
                        * 100:.2f}%)\n" f"   [REASON] Price dropped {
                        abs(price_change_pct):.2f}% below entry - hard stop fail-safe activated")
                return "hard_stop_exit"

            # ---------------------------------------
            # LAYER 5: GRID PROFIT EXIT (Check FIRST - Priority)
            # ---------------------------------------
            # Get executor info to check realized profit
            grid_profit_blocking_exit = False
            if self.active_executor_id:
                executor_info = next(
                    (e for e in self.executors_info if e.id == self.active_executor_id),
                    None
                )
                if executor_info:
                    # Check realized PnL from custom_info (more accurate for grid executor)
                    custom_info = executor_info.custom_info
                    realized_pnl_quote = custom_info.get("realized_pnl_quote", Decimal("0"))
                    if isinstance(realized_pnl_quote, (int, float)):
                        realized_pnl_quote = Decimal(str(realized_pnl_quote))

                    # Calculate realized PnL percentage
                    position_size_quote = custom_info.get("position_size_quote", Decimal("0"))
                    if isinstance(position_size_quote, (int, float)):
                        position_size_quote = Decimal(str(position_size_quote))

                    if position_size_quote > 0:
                        realized_pnl_pct = float((realized_pnl_quote / position_size_quote) * 100)
                    else:
                        # Fallback to net_pnl_pct if position_size not available
                        realized_pnl_pct = float(executor_info.net_pnl_pct) * 100

                    min_grid_profit_pct = getattr(self.config, 'min_grid_profit_pct', 0.6)  # Default: 0.6%

                    net_realized_pnl_pct = realized_pnl_pct - estimated_fees_pct
                    min_grid_profit_block_pct = 0.3  # Block exit if grid profit > 0.3%

                    if net_realized_pnl_pct >= min_grid_profit_pct:
                        self.logger().info(
                            f"[EXIT] 💰 {coin} GRID PROFIT EXIT TRIGGERED:\n"
                            f"   Grid Realized Profit (gross): {realized_pnl_pct:.2f}%\n"
                            f"   Grid Realized Profit (net): {net_realized_pnl_pct:.2f}% (threshold: {min_grid_profit_pct}%)\n"  # noqa: E501
                            f"   [REASON] Grid has achieved target profit - exiting to lock in gains"
                        )
                        return "grid_profit_exit"
                    elif net_realized_pnl_pct > min_grid_profit_block_pct:
                        # Grid has positive profit but below exit threshold - BLOCK other exits
                        grid_profit_blocking_exit = True
                        self.logger().info(
                            f"⏸️  {coin} EXIT BLOCKED: Grid has positive profit (net: {net_realized_pnl_pct:.2f}%) > {min_grid_profit_block_pct}%\n"  # noqa: E501
                            f"   Waiting for grid profit to reach {min_grid_profit_pct}% before allowing exit"
                        )

            # ---------------------------------------
            # LAYER 2: TREND EXIT (Macro Confirmation)
            # ---------------------------------------
            # CRITICAL FIX: Block trend exit if grid has positive profit
            if grid_profit_blocking_exit:
                self.logger().info(
                    f"⏸️  {coin} TREND EXIT BLOCKED: Grid profit protection active"
                )
                return None
            # Check if multi-timeframe data is available
            if hasattr(trend, 'trend_60m') and trend.trend_60m != 0.0:
                exit_short_threshold = getattr(self.config, 'exit_short_threshold', -1.5)
                exit_mid_threshold = getattr(self.config, 'exit_mid_threshold', -0.5)

                severe_short_trend = trend.trend_60m < exit_short_threshold
                mid_term_break_with_price = trend.trend_240m < exit_mid_threshold and price_change_pct < -1.0

                if severe_short_trend or mid_term_break_with_price:
                    if in_hard_grace_period:
                        self.logger().info(
                            f"⏸️  {coin} TREND EXIT BLOCKED: Hard minimum hold time not met "
                            f"({time_since_switch / 60:.1f} min < {hard_min_hold_time / 60:.1f} min)"
                        )
                        return None

                    reason_text = (
                        f"1h trend ({trend.trend_60m:+.2f}%) < {exit_short_threshold}%"
                        if severe_short_trend else
                        f"4h trend ({trend.trend_240m:+.2f}%) < {exit_mid_threshold}% and price down {price_change_pct:.2f}% (< -1.0%)"  # noqa: E501
                    )

                    self.logger().critical(
                        f"[EXIT] 🚨 {coin} TREND EXIT TRIGGERED (after {time_since_switch / 60:.1f} min hold time):\n"
                        f"   [TREND] 24h: {trend.trend_1440m:+.2f}% | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"  # noqa: E501
                        f"   [REASON] {reason_text}\n"
                        f"   [PRICE] Entry: €{entry_price:.4f} | Current: €{current_price:.4f} | Change: {price_change_pct:+.2f}%"  # noqa: E501
                    )
                    return "trend_exit"

            # ---------------------------------------
            # NO EXIT
            # ---------------------------------------
            return None

        except Exception as e:
            self.logger().error(f"❌ Error checking exit conditions for {coin}: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            # On error, don't exit (fail closed)
            return None

    async def _detect_current_regime(self):
        """
        Detect current market regime using multi-timeframe analysis.

        Returns:
            RegimeState or None if detection failed
        """
        if not self.regime_detector:
            return None

        try:
            # Get a sample coin for market-wide regime detection
            # Use the most liquid / most stable coin from monitored_coins
            sample_pairs = self.monitored_coins[:5] if self.monitored_coins else []
            if not sample_pairs:
                return None

            # Try to find a major coin (BTC, ETH, etc.) for market-wide signal
            major_coins = ['BTC', 'ETH', 'SOL', 'UNI', 'LINK']
            sample_pair = None
            for coin in major_coins:
                test_pair = f"{coin}-{self.config.quote_asset}"
                if test_pair in sample_pairs:
                    sample_pair = test_pair
                    break

            # Fallback: use first available pair
            if not sample_pair:
                sample_pair = sample_pairs[0]

            # Get trend data from trend_calculator
            if sample_pair not in self.trend_calculator.trends:
                return None

            trend_obj = self.trend_calculator.trends[sample_pair]

            # Map CoinTrend attributes to dict expected by RegimeDetector
            trend_data = {
                'trend_1h': trend_obj.trend_60m,      # 1h = 60min
                'trend_4h': trend_obj.trend_240m,     # 4h = 240min
                'trend_24h': trend_obj.trend_1440m,   # 24h = 1440min
                'consensus': trend_obj.consensus_trend_pct
            }

            # Get candle data if available
            candles_1h = []
            candles_4h = []
            if hasattr(trend_obj, 'candles') and len(trend_obj.candles) > 0:
                # Convert CandleData to dict format for RegimeDetector
                candles_1h = [
                    {
                        'timestamp': c.timestamp,
                        'open': float(c.open),
                        'high': float(c.high),
                        'low': float(c.low),
                        'close': float(c.close),
                        'volume': float(c.volume)
                    }
                    for c in trend_obj.candles
                ]
                # For 4h, use the same candles (RegimeDetector will aggregate as needed)
                candles_4h = candles_1h

            # Calculate metrics
            metrics = self.regime_detector.calculate_metrics(
                trend_data=trend_data,
                candles_1h=candles_1h,
                candles_4h=candles_4h
            )

            # Detect regime
            regime_state = self.regime_detector.detect_regime(metrics)

            return regime_state

        except Exception as e:
            self.logger().error(f"❌ Regime detection failed: {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            return None

    def _apply_adaptive_filters(self, filters: Dict[str, any]) -> None:
        """
        Apply resolved adaptive filters to SmartEntry filter.

        Args:
            filters: Dict with resolved filter parameters from AdaptiveFilterResolver
                     Keys: rsi_buy_min, rsi_buy_max, vwap_max_deviation_pct, etc.
        """
        try:
            if not self.smart_entry_v2:
                self.logger().warning("⚠️  SmartEntry v2 not initialized - cannot apply adaptive filters")
                return

            # DEBUG: Log incoming filter keys
            self.logger().debug(f"🔍 Adaptive filters to apply: {list(filters.keys())}")

            # Map resolved filters to SmartEntry config format
            # AdaptiveFilterResolver returns: rsi_buy_min, rsi_buy_max, vwap_max_deviation_pct, etc.
            # SmartEntryBaseConfig expects: rsi_buy_max, rsi_extreme_low, vwap_max_deviation_pct, etc.
            filter_mapping = {
                # RSI filters
                'rsi_buy_max': 'rsi_buy_max',           # Direct match ✅
                'rsi_buy_min': 'rsi_extreme_low',       # Resolver:rsi_buy_min → Config:rsi_extreme_low
                'rsi_extreme_min': 'rsi_extreme_low',   # Fallback if config uses old key

                # VWAP and volatility
                'vwap_max_deviation_pct': 'vwap_max_deviation_pct',  # Direct match ✅

                # Acceleration filters
                'max_up_accel_pct': 'max_up_accel_pct',    # Direct match ✅
                'max_down_accel_pct': 'max_down_accel_pct',  # Direct match ✅

                # ATR filters
                'atr_min_pct': 'min_atr_pct_for_grid',     # Resolver:atr_min_pct → Config:min_atr_pct_for_grid
                'atr_max_pct': 'max_atr_pct_for_grid',     # Resolver:atr_max_pct → Config:max_atr_pct_for_grid

                # Spike and structure filters
                'spike_5m_max_pct': 'max_5m_spike_pct',    # Direct match ✅
                'wick_ratio_min': 'min_wick_ratio',        # Direct match ✅

                # Note: grid_spacing_mult and max_active_grids are NOT SmartEntry params
                # They belong to DynamicGridSizer - don't map them here
            }

            # Update base config with resolved filters
            updated_fields = []
            skipped_fields = []

            for filter_key, config_key in filter_mapping.items():
                if filter_key in filters:
                    value = filters[filter_key]
                    if hasattr(self.smart_entry_v2.base_cfg, config_key):
                        old_value = getattr(self.smart_entry_v2.base_cfg, config_key)
                        setattr(self.smart_entry_v2.base_cfg, config_key, value)
                        updated_fields.append(f"{config_key}: {old_value:.1f}→{value:.1f}" if isinstance(value, (int, float)) else f"{config_key}={value}")
                    else:
                        skipped_fields.append(f"{config_key} (attr not found)")

            # Log unmapped filters (might be for DynamicGridSizer)
            unmapped = [k for k in filters.keys() if k not in filter_mapping]
            if unmapped:
                self.logger().debug(f"🔸 Unmapped filters (ignored): {unmapped}")

            if updated_fields:
                self.logger().info("✅ Adaptive filters applied to SmartEntry:")
                for field in updated_fields:
                    self.logger().info(f"   {field}")
            else:
                self.logger().warning(f"⚠️  No SmartEntry fields updated! Available filters: {list(filters.keys())}")

            if skipped_fields:
                self.logger().warning(f"⚠️  Skipped (attr not found): {skipped_fields}")

        except Exception as e:
            self.logger().error(f"❌ Failed to apply adaptive filters: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

    # Phase 2.5: Multi-Timeframe Exit Conditions (DEPRECATED - use should_exit_position instead)
    def _check_multi_timeframe_exit_conditions(self, coin: str) -> bool:
        """
        DEPRECATED: Use should_exit_position() instead.

        This method is kept for backward compatibility but now calls should_exit_position().
        """
        exit_reason = self.should_exit_position(coin)
        return exit_reason is not None
    # ===== PHASE 4 (US-E3): ON-DEMAND REPORTING METHODS =====

    def report_why_no_trade(self, hours: int = 1):
        """
        Generate on-demand "Why No Trade?" report.

        US-E3: Shows rejection reasons breakdown for last N hours.

        Args:
            hours: Number of hours to analyze (default: 1)
        """
        if not self._console_reporter:
            self.logger().warning("⚠️  ConsoleReporter not initialized. Enable observability.structured_events_enabled in config.")
            return

        try:
            self.logger().info("\n" + "=" * 80)
            self.logger().info(f"📊 WHY NO TRADE REPORT (Last {hours}h)")
            self.logger().info("=" * 80)
            self._console_reporter.report_summary(hours=hours)
        except Exception as e:
            self.logger().error(f"❌ Failed to generate report: {e}")

    def report_by_stage(self, hours: int = 6):
        """
        Generate rejection breakdown by pipeline stage.

        US-E3: Shows which stage (SMART_ENTRY, MTF, RISK, EXECUTION) blocks most.

        Args:
            hours: Number of hours to analyze (default: 6)
        """
        if not self._console_reporter:
            self.logger().warning("⚠️  ConsoleReporter not initialized. Enable observability in config.")
            return

        try:
            self._console_reporter.report_by_stage(hours=hours)
        except Exception as e:
            self.logger().error(f"❌ Failed to generate stage report: {e}")

    def report_by_symbol(self, hours: int = 6, top_n: int = 10):
        """
        Generate top rejected symbols report.

        US-E3: Shows which coins get rejected most often.

        Args:
            hours: Number of hours to analyze (default: 6)
            top_n: Number of top symbols to show (default: 10)
        """
        if not self._console_reporter:
            self.logger().warning("⚠️  ConsoleReporter not initialized. Enable observability in config.")
            return

        try:
            self._console_reporter.report_by_symbol(hours=hours, top_n=top_n)
        except Exception as e:
            self.logger().error(f"❌ Failed to generate symbol report: {e}")

    def report_full_dashboard(self, hours: int = 24):
        """
        Generate comprehensive observability dashboard.

        US-E3: Shows all reports (summary, by_stage, by_symbol).

        Args:
            hours: Number of hours to analyze (default: 24)
        """
        if not self._console_reporter:
            self.logger().warning("⚠️  ConsoleReporter not initialized. Enable observability in config.")
            return

        try:
            self._console_reporter.report_full_dashboard(hours=hours)
        except Exception as e:
            self.logger().error(f"❌ Failed to generate dashboard: {e}")
