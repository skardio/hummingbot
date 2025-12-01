"""
Multi-Coin Grid Trading Controller

Main controller that implements the multi-coin grid trading strategy using
Hummingbot's Strategy V2 architecture.
"""

import asyncio
import logging
import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

from hummingbot.connector.connector_base import ConnectorBase
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.data_feed.market_data_provider import MarketDataProvider
from hummingbot.strategy_v2.controllers.controller_base import ControllerBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, ExecutorAction, StopExecutorAction
from hummingbot.strategy_v2.models.executors_info import ExecutorInfo

# Try relative imports first (for standalone), fall back to absolute (for hummingbot)
try:
    from ..utils.coin_discovery import CoinDiscovery
    from ..utils.trend_calculator import TrendCalculator
    from .multi_coin_grid_config import MultiCoinGridConfig
except ImportError:
    # Fall back to absolute imports via hummingbot package
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
    from hummingbot.multi_coin_grid_utils.coin_discovery import CoinDiscovery
    from hummingbot.multi_coin_grid_utils.trend_calculator import TrendCalculator


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
        self.monitored_coins: List[str] = []
        self.all_available_pairs: List[str] = []  # All EUR pairs from exchange
        self.pair_volumes: Dict[str, float] = {}  # Store volume data for rotation: {pair: volume_eur}
        self.pair_spreads: Dict[str, float] = {}  # Store spread data: {pair: spread}
        self.coin_performance: Dict[str, int] = {}  # Track updates without trades per coin
        # Get rotation threshold from config, default to 90 if not set
        self.rotation_threshold: int = getattr(config, 'coin_rotation_threshold', 90)  # Replace coin after X updates without trades

        # State tracking
        self.active_coin: Optional[str] = None
        self.last_switch_time: float = 0
        self.active_executor_id: Optional[str] = None
        self.bot_start_time: float = time.time()  # Track when bot started (for startup delay)

        # Phase 1.1: Stop-Loss tracking
        self.entry_prices: Dict[str, Decimal] = {}  # Track entry price per coin: {coin: entry_price}
        self.stop_loss_triggered: Dict[str, float] = {}  # Track stop-loss events: {coin: timestamp}

        # Phase 1.2: Circuit Breaker state
        self.circuit_breaker_active: bool = False
        self.circuit_breaker_triggered_at: Optional[float] = None
        self.price_history_for_volatility: Dict[str, List[Dict]] = {}  # {coin: [{price, timestamp}]}
        self.circuit_breaker_threshold_pct: float = 5.0  # 5% move in 1 minute = circuit breaker
        self.circuit_breaker_window_seconds: int = 60  # 1 minute window

        # Phase 1.3: API Error Handling state
        self.consecutive_api_errors: int = 0
        self.api_error_threshold: int = 3  # Pause after 3 consecutive errors
        self.api_error_paused: bool = False
        self.api_error_paused_at: Optional[float] = None
        self.last_api_error_time: float = 0
        self.api_error_backoff_seconds: float = 1.0  # Start with 1 second backoff
        self.max_backoff_seconds: float = 60.0  # Max 60 seconds backoff
        self.last_successful_api_call: float = time.time()

        # Phase 1.4: Position Size Limits state
        self.current_exposure_per_coin: Dict[str, Decimal] = {}  # {coin: exposure_amount}
        self.total_exposure: Decimal = Decimal("0")

        # Phase 3: Switch Logic Improvements state
        self.last_grid_creation_time: float = 0  # Track when grid was created (Phase 4.4)
        self.last_grid_price: Dict[str, Decimal] = {}  # Track price when grid was created: {coin: price} (Phase 4.4)
        self.switch_costs: Dict[str, float] = {}  # Track calculated switch costs: {coin: cost} (Phase 3.2)

        # Insufficient balance cooldown tracking
        self.last_insufficient_balance_time: Dict[str, float] = {}  # Track when executor failed due to insufficient balance: {coin: timestamp}
        self.insufficient_balance_cooldown_seconds: int = 300  # 5 minutes cooldown before retry

        # Automatic blacklist tracking (prevent loops)
        self.coin_error_count: Dict[str, int] = {}  # Track errors per coin: {coin: error_count}
        self.max_errors_per_coin: int = 5  # Auto-blacklist after 5 errors
        self.auto_blacklisted_coins: set = set()  # Coins automatically blacklisted

        # Trend update scheduling
        self._last_trend_update: float = 0.0  # Track last time we fetched ticker data

        self.logger().info("=" * 80)
        self.logger().info("🚀 MULTI-COIN GRID CONTROLLER INITIALIZED")
        self.logger().info("=" * 80)
        self.logger().info(f"Exchange: {config.connector_name}")
        self.logger().info(f"Quote Asset: {config.quote_asset}")
        self.logger().info(f"Max Coins: {config.max_coins_to_monitor}")
        self.logger().info(f"Trend Lookback: {config.trend_lookback_minutes} min")
        self.logger().info(f"Min Trend: {config.trend_min_change_pct}%")
        self.logger().info(f"Switch Cooldown: {config.min_switch_interval_seconds / 60:.0f} min")
        self.logger().info(f"Grid Capital: €{config.total_amount_quote}")
        self.logger().info(f"Stop Loss: -{config.stop_loss_pct * 100}%")
        self.logger().info("=" * 80)

    async def _handle_api_error(self, error: Exception, operation: str) -> None:
        """
        Phase 1.3: Handle API errors with consecutive counting and exponential backoff

        Args:
            error: The exception that occurred
            operation: Description of the operation that failed
        """
        current_time = time.time()
        self.last_api_error_time = current_time
        self.consecutive_api_errors += 1

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

    async def _api_call_with_error_handling(self, func, *args, **kwargs):
        """
        Phase 1.3: Wrapper for API calls with error handling

        Args:
            func: Async function to call
            *args, **kwargs: Arguments to pass to function

        Returns:
            Result of function call, or None if error occurred
        """
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
                                self.logger().debug(f"✅ Using base connector for price fetching: {len(prices_dict)} prices")
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
                    # Store base connector for price fetching (paper trading connector doesn't have order books for all coins)
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
                    # Store base connector for price fetching (paper trading connector doesn't have order books for all coins)
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

            # Phase 2.5: Set multi-timeframe lookback periods if configured
            if hasattr(self.config, 'trend_lookback_short_minutes'):
                self.trend_calculator.trend_lookback_short_minutes = self.config.trend_lookback_short_minutes
            if hasattr(self.config, 'trend_lookback_mid_minutes'):
                self.trend_calculator.trend_lookback_mid_minutes = self.config.trend_lookback_mid_minutes
            if hasattr(self.config, 'trend_lookback_long_minutes'):
                self.trend_calculator.trend_lookback_long_minutes = self.config.trend_lookback_long_minutes

    async def on_start(self):
        """Override to log when control_loop starts"""
        self.logger().info("🚀 Controller.on_start() called - control_loop is starting!")
        await super().on_start()

    async def control_task(self):
        """Override to always update trends and determine actions, even if market_data_provider isn't ready"""
        mdp_ready = self.market_data_provider.ready if self.market_data_provider else False
        event_set = self.executors_update_event.is_set() if hasattr(self, 'executors_update_event') else False

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

        self.logger().info(f"🔍 control_task: mdp_ready={mdp_ready}, event_set={event_set}")
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
            # Check if manual trading pairs are configured
            manual_pairs = getattr(self.config, 'manual_trading_pairs', None)
            if manual_pairs and len(manual_pairs) > 0:
                # Use manual trading pairs - validate and set them
                self.logger().info("=" * 80)
                self.logger().info("🎯 Using MANUAL trading pairs from config...")
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

            else:
                # Auto-discovery mode
                self.logger().info("💫 First run - discovering coins automatically...")
                self.logger().info("DEBUG: INSIDE if not self.monitored_coins block!")
                try:
                    # Wait for connector to be ready (trading pair map loaded)
                    if not self.connector.ready:
                        self.logger().warning(f"⏳ Connector {self.config.connector_name} not ready yet, waiting...")
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

                    self.logger().info(f"📊 Found {len(eur_pairs)} {quote} pairs from {len(trading_pair_map)} total pairs")

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
                    sorted_pairs = sorted(pair_volumes.items(), key=lambda x: x[1], reverse=True)

                    # Take top N by volume that meet minimum threshold and not blacklisted
                    min_volume = self.config.min_24h_volume_eur
                    blacklist = set(getattr(self.config, 'blacklist', []) or [])
                    filtered_pairs = [(pair, vol) for pair, vol in sorted_pairs if vol >= min_volume and pair not in blacklist]

                    # Spread check: only include coins with spread < 0.5% using ticker bid/ask
                    spread_limit = 0.005  # 0.5%
                    spread_checked_pairs = []
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
                    self.logger().info("=" * 80)
                    self.logger().info("📊 COIN DISCOVERY - VOLLEDIGE LIJST VAN 50 COINS")
                    self.logger().info("=" * 80)
                    for i, (pair, vol, spread) in enumerate(spread_checked_pairs[:50], 1):
                        self.logger().info(
                            f"  {i:2}. {pair:15} | Volume: €{vol:>12,.0f} | Spread: {spread * 100:>5.3f}%"
                        )
                    self.logger().info("=" * 80)
                    self.monitored_coins = [pair for pair, vol, spread in spread_checked_pairs[:50]]

                    self.logger().info(f"✅ All {len(self.monitored_coins)} selected coins by 24h volume and spread < 0.5%:")
                    for i, (pair, vol, spread) in enumerate(spread_checked_pairs[:50], 1):
                        self.logger().info(f"   {i}. {pair}: €{vol:,.0f} (spread: {spread:.3%})")

                    self.logger().info(f"🎯 Selected {len(self.monitored_coins)} pairs (min €{min_volume:,} volume, spread < 0.5%, not blacklisted)")
                    self.logger().info(f"💡 Pool size: {len(self.all_available_pairs)} pairs available for rotation")

                    if not self.monitored_coins:
                        self.logger().error("❌ No coins discovered!")
                        return

                    self.logger().info("=" * 80)
                    self.logger().info(f"✅ Discovery complete: Monitoring {len(self.monitored_coins)} coins")
                    self.logger().info(f"✅ Top 20: {', '.join(self.monitored_coins[:20])}")
                    self.logger().info("=" * 80)

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

        # Rotate underperforming coins if we have a pool to rotate from
        # BUT: Skip rotation if manual trading pairs are configured (user wants specific coins)
        manual_pairs = getattr(self.config, 'manual_trading_pairs', None)
        if not manual_pairs or len(manual_pairs) == 0:
            # Only rotate in auto-discovery mode
            if len(self.all_available_pairs) > len(self.monitored_coins):
                self._rotate_underperforming_coins()
        else:
            self.logger().debug("⏭️  Skipping coin rotation (manual trading pairs mode)")

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
                await self.trend_calculator.update_all_trends_v2(self.monitored_coins)
                self._last_trend_update = time.time()
            except Exception as e:
                self.logger().error(f"❌ Error updating trends: {e}")
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
        min_volume = float(self.config.min_24h_volume_eur)
        spread_limit = 0.005  # 0.5%

        # Find new coins not yet monitored, sorted by volume (highest first)
        # Filter by: not monitored, not blacklisted, meets volume threshold, meets spread threshold
        candidate_pairs = []
        for pair in self.all_available_pairs:
            if pair in self.monitored_coins:
                continue  # Already monitored
            if pair in blacklist:
                continue  # Blacklisted
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
        self.logger().info(f"🔧 DEBUG: trend_calculator.trends has {len(self.trend_calculator.trends) if self.trend_calculator else 0} coins")

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

            # Combine cooldown coins, auto-blacklisted coins, and config blacklist
            excluded_coins = set(coins_in_cooldown) | self.auto_blacklisted_coins | config_blacklist
            if excluded_coins:
                self.logger().debug(f"🚫 Excluding coins: {excluded_coins}")
                if config_blacklist:
                    self.logger().debug(f"   Config blacklist: {config_blacklist}")
                if self.auto_blacklisted_coins:
                    self.logger().debug(f"   Auto-blacklisted: {self.auto_blacklisted_coins}")
                if coins_in_cooldown:
                    self.logger().debug(f"   In cooldown: {coins_in_cooldown}")

            # Get best coin, but exclude coins in cooldown, auto-blacklisted coins, and config blacklist
            best_coin = self.trend_calculator.get_best_coin(
                min_trend_pct=float(self.config.trend_min_change_pct),
                exclude_coins=list(excluded_coins) if excluded_coins else None
            )

            # Double-check: reject if somehow a blacklisted coin was selected
            if best_coin and best_coin in config_blacklist:
                self.logger().warning(
                    f"🚨 CRITICAL: {best_coin} is in blacklist but was selected! Rejecting..."
                )
                best_coin = None

            # Phase 2.5: Apply multi-timeframe buy conditions if enabled
            rejection_reason = None
            if best_coin and use_multi_timeframe:
                if not self._check_multi_timeframe_buy_conditions(best_coin):
                    # Get rejection reason from trend data
                    trend_obj = self.trend_calculator.get_trend(best_coin)
                    if trend_obj and hasattr(trend_obj, 'trend_240m') and hasattr(trend_obj, 'trend_60m'):
                        if hasattr(trend_obj, 'long_trend_warmup') and trend_obj.long_trend_warmup:
                            if trend_obj.trend_240m <= 1.5:
                                rejection_reason = f"4h trend ({trend_obj.trend_240m:+.2f}%) <= +1.5% (warm-up requires > +1.5%)"
                            elif trend_obj.trend_60m < 0.3:
                                rejection_reason = f"1h trend ({trend_obj.trend_60m:+.2f}%) < +0.3% (warm-up requires >= +0.3%)"
                            else:
                                rejection_reason = "Warm-up mode: trends niet sterk genoeg"
                        else:
                            if trend_obj.trend_1440m <= 1.0:
                                rejection_reason = f"24h trend ({trend_obj.trend_1440m:+.2f}%) <= +1%"
                            elif trend_obj.trend_240m <= 1.0:
                                rejection_reason = f"4h trend ({trend_obj.trend_240m:+.2f}%) <= +1%"
                            elif trend_obj.trend_60m < 0.0:
                                rejection_reason = f"1h trend ({trend_obj.trend_60m:+.2f}%) < 0% (crash detected)"
                            else:
                                rejection_reason = "Multi-timeframe buy conditions niet voldaan"
                    else:
                        rejection_reason = "Multi-timeframe data niet beschikbaar"

                    self.logger().warning(
                        f"❌ {best_coin} does not meet multi-timeframe buy conditions - rejecting"
                    )
                    best_coin = None

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

            # Only log selected coin if one was found
            if best_coin:
                self.logger().info(f"🔍 Selected coin: {best_coin}")
                # MONITORING FIX: Also log in format collector can easily find
                self.logger().info(f"📊 MONITORING: Active Coin: {best_coin}")
            else:
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
                                f"⚠️  Best coin {sym} ({tr:+.2f}%) werd afgewezen:\n"
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
                            return actions
                    except Exception as e:
                        self.logger().error(f"❌ Error creating stop action for exit: {e}")

        # No coin meets criteria - check if we should stop active executor
        if not best_coin:
            self.logger().info(f"❌ No coin found with trend >= {self.config.trend_min_change_pct}%")

            # CRITICAL FIX: Only stop executor if PRO EXIT SYSTEM triggers OR active coin has severe negative trend
            # DO NOT stop just because no better coin is found - let the active coin continue trading!
            if self.active_coin and self.active_executor_id:
                active_trend = self.trend_calculator.get_trend(self.active_coin)
                if active_trend:
                    # Phase 2.5: Use multi-timeframe trends if available
                    if use_multi_timeframe and hasattr(active_trend, 'trend_60m') and active_trend.trend_60m != 0.0:
                        # Use 60m trend for panic detection (more responsive)
                        active_trend_value = active_trend.trend_60m
                    else:
                        active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct

                    # Only stop if active coin has SEVERE negative trend (< -1%)
                    # This prevents premature exits when active coin is still performing well
                    negative_trend_threshold = -1.0  # -1% threshold

                    if active_trend_value < negative_trend_threshold:
                        # Active coin is losing badly and no better coin available - FORCE stop
                        self.logger().critical(
                            f"🚨 PANIC STOP: Active coin {self.active_coin} has negative trend ({active_trend_value:+.2f}%) "
                            f"< {negative_trend_threshold}% and no better coin available - FORCING stop to limit losses"
                        )
                        if self._is_executor_actually_active():
                            try:
                                stop_action = self._create_stop_action()
                                if stop_action:
                                    actions.append(stop_action)
                                else:
                                    self.logger().warning("⚠️  Failed to create stop action")
                            except Exception as e:
                                self.logger().error(f"❌ Error creating stop action: {e}")
                                import traceback
                                self.logger().error(traceback.format_exc())
                        return actions
                    else:
                        # Active coin is still performing well (or neutral) - KEEP IT RUNNING
                        # Don't stop just because no better coin was found!
                        self.logger().info(
                            f"✅ Keeping active coin {self.active_coin} running (trend: {active_trend_value:+.2f}%) - "
                            f"no better coin found, but active coin is still performing well"
                        )
                        # Return empty actions - let the active executor continue
                        return actions

            # No active coin - nothing to do
            return actions

        # Check if we should create/switch grid
        # Note: best_coin is already filtered to exclude coins in cooldown
        if self._should_create_new_grid(best_coin):
            # For paper trading, we can skip order book check if we have price from trend data
            # The GridExecutor will use fallback logic to get price from base connector if needed
            paper_trading = getattr(self.config, 'paper_trading', False)
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
                try:
                    # First check if order book exists
                    try:
                        order_book = self.connector.get_order_book(best_coin)
                        if order_book is not None:
                            order_book_ready = True
                            self.logger().debug(f"✅ Order book exists for {best_coin}")
                    except (ValueError, KeyError):
                        # Order book doesn't exist - need to initialize
                        self.logger().warning(f"⚠️ Order book not found for {best_coin} - initializing...")

                        # Try to initialize synchronously if possible
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            # Event loop is running - we need to wait for async initialization
                            # Schedule initialization and skip executor creation this cycle
                            # The order book will be ready next cycle
                            try:
                                safe_ensure_future(self._ensure_order_book_exists(best_coin))
                                self.logger().info(f"⏳ Order book initialization scheduled for {best_coin} - will retry next cycle")
                                return actions  # Skip executor creation this cycle, retry next time
                            except Exception as init_error:
                                self.logger().error(f"❌ Failed to schedule order book initialization: {init_error}")
                                return actions
                        else:
                            # Loop not running, can run directly
                            order_book_ready = loop.run_until_complete(self._ensure_order_book_exists(best_coin))
                            if not order_book_ready:
                                self.logger().error(f"❌ Cannot create executor for {best_coin} - order book initialization failed")
                                return actions
                except Exception as e:
                    self.logger().error(f"❌ Error checking/initializing order book for {best_coin}: {e}")
                    import traceback
                    self.logger().error(traceback.format_exc())
                    return actions  # Don't create executor if order book check fails

                # Final check - don't create executor if order book is not ready
                if not order_book_ready:
                    try:
                        # Double-check order book exists
                        order_book = self.connector.get_order_book(best_coin)
                        if order_book is None:
                            self.logger().warning(f"⚠️ Order book still not available for {best_coin} - skipping executor creation")
                            return actions
                    except (ValueError, KeyError):
                        self.logger().warning(f"⚠️ Order book check failed for {best_coin} - skipping executor creation")
                        return actions

            # Stop old executor if exists and is actually active
            if self.active_coin and self.active_executor_id and self._is_executor_actually_active():
                self.logger().info(
                    f"🔄 SWITCHING: {self.active_coin} → {best_coin}"
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
                grid_action = self._create_grid_action(best_coin)
                if grid_action:
                    actions.append(grid_action)
                    # Phase 1.4: Track exposure when creating executor
                    self._update_exposure_tracking(best_coin, self.config.total_amount_quote)
                else:
                    self.logger().error(f"❌ Failed to create grid action for {best_coin}")
            except Exception as e:
                self.logger().error(f"❌ Error creating grid action for {best_coin}: {e}")
                import traceback
                self.logger().error(traceback.format_exc())

            # Reset performance counter for this coin (it's performing!)
            if best_coin in self.coin_performance:
                self.coin_performance[best_coin] = 0

            # Update state
            self.active_coin = best_coin
            self.last_switch_time = self.market_data_provider.time()

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
            # Executor doesn't exist or is not active - check why it failed
            failed_executor = self._get_executor_info(self.active_executor_id)

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
                            f"🚨 AUTO-BLACKLIST: {self.active_coin} has {self.coin_error_count[self.active_coin]} errors "
                            f"(threshold: {self.max_errors_per_coin}) - adding to blacklist to prevent loops"
                        )
                        # Also add to config blacklist if possible (persistent)
                        if hasattr(self.config, 'blacklist'):
                            if self.config.blacklist is None:
                                self.config.blacklist = []
                            if self.active_coin not in self.config.blacklist:
                                self.config.blacklist.append(self.active_coin)
                                self.logger().info(f"✅ Added {self.active_coin} to persistent blacklist")

            # Check if executor failed due to insufficient balance
            if failed_executor and not failed_executor.is_active:
                close_type = str(failed_executor.close_type) if failed_executor.close_type else ""
                close_type_str = close_type.upper()

                # Check for insufficient balance indicators
                is_insufficient_balance = (
                    'INSUFFICIENT_BALANCE' in close_type_str or
                    'INSUFFICIENT' in close_type_str or
                    ('BALANCE' in close_type_str and 'NOT ENOUGH' in close_type_str) or
                    'budget' in close_type.lower() or
                    'Not enough budget' in close_type
                )

                if is_insufficient_balance:
                    # Executor failed due to insufficient balance - set cooldown
                    if self.active_coin:
                        self.logger().warning(
                            f"⚠️  Executor {self.active_executor_id[:8]}... failed due to insufficient balance "
                            f"(close_type: {close_type}). Setting 5-minute cooldown for {self.active_coin} before retry."
                        )
                        # Set cooldown: don't retry this coin for 5 minutes
                        self.last_insufficient_balance_time[self.active_coin] = self.market_data_provider.time()
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
            self.active_executor_id = None
            self.active_coin = None
            return False

        return True

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

    def _check_position_limits(self, symbol: str) -> bool:
        """
        Phase 1.4: Check if position limits allow creating executor for this coin

        Note: Since we only have 1 active executor at a time, we mainly check:
        - Max exposure per coin (if switching to same coin)
        - Max total exposure (should always be <= 1 executor worth)

        Args:
            symbol: Trading pair symbol

        Returns:
            True if position limits allow, False otherwise
        """
        try:
            # Calculate new exposure
            new_exposure = self.config.total_amount_quote
            current_coin_exposure = self.current_exposure_per_coin.get(symbol, Decimal("0"))

            # For now, use grid amount as capital reference
            # In future, could get actual account balance
            total_capital = self.config.total_amount_quote

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

        Args:
            best_coin: Symbol of best trending coin

        Returns:
            True if should create new grid
        """
        # No active coin - check startup delay first
        if not self.active_coin:
            # Check if minimum startup wait time has passed
            min_startup_wait = getattr(self.config, 'min_startup_wait_seconds', 3600)
            time_since_start = time.time() - self.bot_start_time

            if time_since_start < min_startup_wait:
                remaining = min_startup_wait - time_since_start
                self.logger().info(
                    f"⏰ Startup delay active - waiting {remaining / 60:.1f} more minutes "
                    f"({remaining:.0f} seconds) before first trade"
                )
                return False

            # Startup delay passed - allow first trade
            self.logger().info(
                f"✅ Startup delay passed ({time_since_start / 60:.1f} minutes) - "
                f"ready to create first grid for {best_coin}"
            )
            return True

        # Validate executor is actually active
        if not self._is_executor_actually_active():
            # Executor doesn't exist - create new one
            self.logger().info(f"🔄 No active executor found - creating new grid for {best_coin}")
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
        time_since_switch = self.market_data_provider.time() - self.last_switch_time
        min_hold_time = getattr(self.config, 'min_hold_time_seconds', 900)

        # Get trend values
        active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct
        best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct
        trend_difference = best_trend_value - active_trend_value

        # CRITICAL: If active coin is losing significantly, FORCE switch (panic protection)
        negative_trend_threshold = -1.0  # -1% threshold for "panic" switch
        is_panic_switch = active_trend_value < negative_trend_threshold

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
        opportunity_threshold = 2.0  # Best coin must have > 2% trend
        opportunity_difference = 2.0  # Must be at least 2% better
        opportunity_multiplier = 2.0  # Best must be at least 2x better

        is_opportunity_switch = (
            best_trend_value > opportunity_threshold and
            trend_difference > opportunity_difference and
            best_trend_value >= active_trend_value * opportunity_multiplier
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
                f"allowing early exit to {best_coin} (hold time: {time_since_switch / 60:.1f}/{min_hold_time / 60:.1f} min)"
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
        active_has_strong_trend = active_trend_value > 2.0  # Active coin has >2% trend (good long-term trend)
        best_has_strong_trend = best_trend_value > 2.0  # Best coin has >2% trend

        # If active coin has strong trend, require larger difference to switch (prevent premature exits)
        if active_has_strong_trend and not best_has_strong_trend:
            # Active coin has strong trend, best coin doesn't - require even larger difference
            trend_difference = best_trend_value - active_trend_value
            if trend_difference < 1.5:  # Require at least 1.5% better to switch away from strong trend
                self.logger().info(
                    f"📊 Active coin {self.active_coin} has strong trend ({active_trend_value:+.2f}%) - "
                    f"requiring larger difference ({trend_difference:+.2f}% < 1.5%) to switch"
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

        # All checks passed - switch to new coin
        self.logger().info(
            f"🔄 SWITCH APPROVED: "
            f"{self.active_coin} ({active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct:+.2f}%) → "
            f"{best_coin} ({best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct:+.2f}%)"
        )
        return True

    # Phase 3.1: Smart Switch Threshold (relaxed for negative trends)
    def _check_smart_switch_threshold_relaxed(self, active_trend, best_trend) -> bool:
        """
        Relaxed version of smart switch threshold for when active coin is losing

        Uses 50% of normal K multiplier to allow switching more easily
        """
        try:
            active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct
            best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct

            volatility = active_trend.volatility if active_trend.volatility > 0 else 1.0
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
            active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct
            best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct

            # Get volatility (use active coin's volatility as baseline)
            volatility = active_trend.volatility if active_trend.volatility > 0 else 1.0

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

            active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct
            best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct
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
            active_trend_value = active_trend.consensus_trend_pct if active_trend.consensus_trend_pct != 0.0 else active_trend.trend_pct
            best_trend_value = best_trend.consensus_trend_pct if best_trend.consensus_trend_pct != 0.0 else best_trend.trend_pct
            expected_profit_pct = best_trend_value - active_trend_value

            # Get multiplier from config
            cost_multiplier = getattr(self.config, 'switch_cost_multiplier', 2.0)
            required_profit = total_switch_cost_pct * cost_multiplier

            # Store switch cost for logging
            self.switch_costs[best_coin] = total_switch_cost_pct

            if expected_profit_pct <= required_profit:
                self.logger().info(
                    f"💰 Switch cost analysis:\n"
                    f"   Expected profit: {expected_profit_pct:+.3f}%\n"
                    f"   Switch cost: {total_switch_cost_pct:.3f}% (fees: {fee_cost:.3f}%, spread: {spread_cost:.3f}%, slippage: {slippage_cost:.3f}%)\n"
                    f"   Required profit: {required_profit:.3f}% (cost * {cost_multiplier})\n"
                    f"   ❌ Not profitable - skipping switch"
                )
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
            min_volume = float(self.config.min_24h_volume_eur)
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

            # Use volatility from trend if available
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
                if hasattr(tracker._data_source, '_trading_pairs') and symbol not in tracker._data_source._trading_pairs:
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
                        # This should happen after order book is initialized, regardless of whether trading pair was already added
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

    def _create_grid_action(self, symbol: str) -> CreateExecutorAction:
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
                f"❌ Cannot create grid for {symbol}: After adjustments, start_price ({start_price}) >= end_price ({end_price})"
            )
            return None

        # Use start_price as limit price (price-based circuit breaker)
        limit_price = start_price * Decimal("0.95")  # 5% below start as safety

        # Validate limit_price is positive
        if limit_price <= 0:
            self.logger().error(
                f"❌ Cannot create grid for {symbol}: Invalid limit_price ({limit_price})"
            )
            return None

        self.logger().info(
            f"\n📝 CREATING GRID for {symbol} (Phase 4 Enhanced):"
            f"\n   Current Price: €{current_price:.4f}"
            f"\n   Range: €{start_price:.4f} - €{end_price:.4f} ({grid_method})"
            f"\n   Grid Levels: {num_grids} (volatility-adjusted)"
            f"\n   Limit Price: €{limit_price:.4f} (circuit breaker)"
            f"\n   Capital: €{self.config.total_amount_quote}"
            f"\n   Stop Loss: -{self.config.stop_loss_pct * 100}%"
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

        max_position_size_overrides = getattr(self.config, "max_position_size_per_symbol", {}) or {}
        max_position_size_quote = max_position_size_overrides.get(symbol)
        if max_position_size_quote is not None:
            max_position_size_quote = Decimal(str(max_position_size_quote))

        min_liquidation_distance_overrides = getattr(self.config, "min_liquidation_distance_pct_per_symbol", {}) or {}
        min_liquidation_distance_pct = min_liquidation_distance_overrides.get(symbol)
        if min_liquidation_distance_pct is not None:
            min_liquidation_distance_pct = Decimal(str(min_liquidation_distance_pct))

        from hummingbot.core.data_type.common import TradeType

        grid_config = GridExecutorConfig(
            timestamp=self.market_data_provider.time(),
            connector_name=self.config.connector_name,
            trading_pair=symbol,
            side=TradeType.BUY,  # Buy-side grid
            start_price=start_price,
            end_price=end_price,
            limit_price=limit_price,
            total_amount_quote=self.config.total_amount_quote,
            min_spread_between_orders=Decimal("0.001"),  # 0.1% min spread
            min_order_amount_quote=self.config.min_order_amount_quote,
            triple_barrier_config=self.config.triple_barrier_config,
            max_open_orders=max(1, min(self.config.max_open_orders, num_grids)),  # Adjust max orders to grid count, ensure >= 1
            max_orders_per_batch=2,
            order_frequency=self.config.order_frequency,
            activation_bounds=Decimal("0.05"),  # 5% activation bounds
            keep_position=False,  # Don't keep position on stop
            leverage=leverage,  # Use derivative_leverage from config (for futures) or 1 (for spot)
            max_position_size_quote=max_position_size_quote,
            min_liquidation_distance_pct=min_liquidation_distance_pct,
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
            self._update_exposure_tracking(self.active_coin, -self.config.total_amount_quote)

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
        self.logger().debug(f"🔍 Paper Trading Check: connector_name={connector_name}, paper_trading_config={paper_trading_config}, is_paper_trading={is_paper_trading}")

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
                self.logger().warning("⚠️  Paper trading is enabled in config but connector name doesn't end with '_paper_trade'!")
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
            status.append(f"║ ⚠️  API Errors: {self.consecutive_api_errors}/{self.api_error_threshold} consecutive    ║")

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
                    stop_loss_price = entry_price * (Decimal('1') - self.config.stop_loss_pct)
                    status.append(f"║ Entry: €{entry_price:.4f} | Stop-Loss: €{stop_loss_price:.4f} ({loss_pct:+.2f}%) ║")

                # Show executor P&L if available
                if self.active_executor_id:
                    executor_info = next(
                        (e for e in self.executors_info if e.id == self.active_executor_id),
                        None
                    )
                    if executor_info:
                        pnl_quote = executor_info.net_pnl_quote
                        pnl_pct = executor_info.net_pnl_pct
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
                        self.logger().info(f"📊 MONITORING: Executor P&L: €{pnl_quote:+.2f} ({pnl_pct:+.2f}%) | Active Coin: {self.active_coin or 'None'}")
        else:
            status.append("║ Active Coin: None (waiting for opportunity)                  ║")

        # Show total P&L from all executors
        if self.executors_info:
            total_pnl_quote = sum(Decimal(str(e.net_pnl_quote)) for e in self.executors_info)
            total_pnl_pct = sum(Decimal(str(e.net_pnl_pct)) for e in self.executors_info) / len(self.executors_info) if self.executors_info else Decimal("0")
            total_fees = sum(Decimal(str(e.cum_fees_quote)) for e in self.executors_info)
            total_volume = sum(Decimal(str(e.filled_amount_quote)) for e in self.executors_info)

            if total_volume > 0:
                if total_pnl_quote > 0:
                    total_emoji = "💰"
                elif total_pnl_quote < 0:
                    total_emoji = "📉"
                else:
                    total_emoji = "➖"

                status.append(f"║ {total_emoji} Total P&L: €{total_pnl_quote:+.2f} ({total_pnl_pct:+.2f}%) | Fees: €{total_fees:.2f} ║")
                status.append(f"║ 📊 Total Volume: €{total_volume:.2f} ({len(self.executors_info)} executor(s)) ║")

                # MONITORING FIX: Log P&L to log file so collector can find it
                self.logger().info(f"📊 MONITORING: Total P&L: €{total_pnl_quote:+.2f} ({total_pnl_pct:+.2f}%) | Active Coin: {self.active_coin or 'None'} | Exposure: €{self.total_exposure:.2f}")

                # MONITORING FIX: Log P&L to log file so collector can find it
                self.logger().info(f"📊 MONITORING: Total P&L: €{total_pnl_quote:+.2f} ({total_pnl_pct:+.2f}%) | Active Coin: {self.active_coin or 'None'} | Exposure: €{self.total_exposure:.2f}")

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
            status.append(f"║ Monitored Coins: {len(self.monitored_coins)} total, {coins_with_data} with full data    ║")

        status.append("╚═══════════════════════════════════════════════════════════════╝\n")

        return status

    # Phase 2.5: Multi-Timeframe Buy Conditions
    def _check_multi_timeframe_buy_conditions(self, coin: str) -> bool:
        """
        Phase 2.5: Check if coin meets multi-timeframe buy conditions

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
            trend = self.trend_calculator.get_trend(coin)
            if not trend:
                return False

            # Check if multi-timeframe data is available
            # Only allow if in warm-up mode (first 24h) - don't allow if trend_60m == 0.0 (that means 0% trend, not "no data")
            if not hasattr(trend, 'trend_60m'):
                # Multi-timeframe fields don't exist - fallback to old logic
                self.logger().debug(f"⚠️  Multi-timeframe fields not available for {coin} - allowing (fallback)")
                return True

            # Check if in warm-up mode (first 24h after bot start)
            if hasattr(trend, 'long_trend_warmup') and trend.long_trend_warmup:
                # CRITICAL FIX: During warm-up, be MUCH more conservative
                # The 24h trend fallback (240m * 2) can be misleading if coin is crashing
                # We need STRONG positive trends in ALL timeframes to buy during warm-up

                # Stricter requirements during warm-up:
                # 1. 240m trend must be STRONGLY positive (> +2.0%) - verlaagd van 2.5% naar 2.0%
                # 2. 60m trend must be positive (>= +0.5%) - not just >= 0%
                # 3. Both must be positive (reject if either is negative)

                warmup_240m_ok = trend.trend_240m > 1.5  # STRONG 4h trend required (verlaagd van 2.0% naar 1.5%)
                warmup_60m_ok = trend.trend_60m >= 0.3  # Positive 1h trend required (verlaagd van 0.5% naar 0.3%)
                both_positive = trend.trend_240m > 0.0 and trend.trend_60m > 0.0  # Both must be positive

                if warmup_240m_ok and warmup_60m_ok and both_positive:
                    self.logger().info(
                        f"[DECISION] ✅ {coin} BUY APPROVED (warm-up mode - CONSERVATIVE):\n"
                        f"   [TREND] 24h: {trend.trend_1440m:+.2f}% (warm-up fallback) | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"
                        f"   [SCORE] Composite: {trend.trend_score:+.2f}%\n"
                        f"   [WARNING] Warm-up mode: Using 4h*2 fallback for 24h trend - be cautious!"
                    )
                    return True
                else:
                    # Reject with detailed reason
                    reasons = []
                    if not warmup_240m_ok:
                        reasons.append(f"4h trend ({trend.trend_240m:+.2f}%) <= +1.5% (warm-up requires > +1.5%)")
                    if not warmup_60m_ok:
                        reasons.append(f"1h trend ({trend.trend_60m:+.2f}%) < +0.3% (warm-up requires >= +0.3%)")
                    if not both_positive:
                        reasons.append(f"One or both trends negative (4h: {trend.trend_240m:+.2f}%, 1h: {trend.trend_60m:+.2f}%)")

                    self.logger().warning(
                        f"[DECISION] ❌ {coin} BUY REJECTED (warm-up mode - TOO RISKY):\n"
                        f"   [TREND] 24h: {trend.trend_1440m:+.2f}% (warm-up fallback) | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"
                        f"   [REASON] {' | '.join(reasons)}\n"
                        f"   [NOTE] Warm-up mode requires STRONG positive trends to avoid buying crashing coins"
                    )
                    return False

            # Buy conditions (exit thresholds are only used in exit conditions, not here)
            # IMPROVED: Stricter checks to avoid trading during declining trends
            trend_1440m_ok = trend.trend_1440m > 1.0  # 24h trend > +1%
            trend_240m_ok = trend.trend_240m > 1.0  # 4h trend > +1%
            trend_60m_ok = trend.trend_60m >= 0.0  # 1h trend >= 0%

            # CRITICAL: Additional check - reject if both short-term trends are negative
            # This prevents trading during declining trends even if 24h trend is positive
            declining_trend = trend.trend_60m < -0.5 and trend.trend_240m < 0.0

            if declining_trend:
                self.logger().warning(
                    f"[DECISION] ❌ {coin} BUY REJECTED: Declining trend detected!\n"
                    f"   [TREND] 24h: {trend.trend_1440m:+.2f}% | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"
                    f"   [REASON] 1h trend ({trend.trend_60m:+.2f}%) < -0.5% AND 4h trend ({trend.trend_240m:+.2f}%) < 0%\n"
                    f"   [NOTE] Avoiding trade during declining trends to prevent losses"
                )
                return False

            if not trend_1440m_ok:
                self.logger().info(
                    f"[DECISION] ❌ {coin} BUY REJECTED: 24h trend ({trend.trend_1440m:+.2f}%) < +1%"
                )
                return False

            if not trend_240m_ok:
                self.logger().info(
                    f"[DECISION] ❌ {coin} BUY REJECTED: 4h trend ({trend.trend_240m:+.2f}%) < +1%"
                )
                return False

            if not trend_60m_ok:
                self.logger().info(
                    f"[DECISION] ❌ {coin} BUY REJECTED: 1h trend ({trend.trend_60m:+.2f}%) < 0% (crash detected!)"
                )
                return False

            # All conditions met
            self.logger().info(
                f"[DECISION] ✅ {coin} BUY APPROVED:\n"
                f"   [TREND] 24h: {trend.trend_1440m:+.2f}% | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"
                f"   [SCORE] Composite: {trend.trend_score:+.2f}%"
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

            # ---------------------------------------
            # LAYER 1: HOLD TIME FILTER
            # ---------------------------------------
            min_hold_time = getattr(self.config, 'min_hold_time_seconds', 3600)  # Default: 1 hour

            # CRITICAL FIX: Hard minimum hold time for trend exits (30 minutes)
            # Only emergency exits can bypass this
            hard_min_hold_time = 1800  # 30 minutes hard minimum for trend exits
            in_hard_grace_period = time_since_switch < hard_min_hold_time

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

            # CRITICAL FIX: Calculate NET profit (after fees)
            # Kraken fees: ~€0.02-0.03 maker, ~€0.17-0.18 taker per trade
            # Estimate fees: 0.05% maker + 0.26% taker = ~0.31% total per round trip
            # Note: Fee calculation reserved for future use in exit logic
            # estimated_fees_pct = 0.31  # Estimated total fees per round trip (buy + sell)
            # _net_price_change_pct = price_change_pct - estimated_fees_pct  # Reserved for future use

            # ---------------------------------------
            # LAYER 3: EMERGENCY EXIT (PRIORITY #1)
            # ---------------------------------------
            emergency_exit_pct = getattr(self.config, 'emergency_exit_pct', -4.5)  # Default: -4.5% (relaxed)
            if price_change_pct <= emergency_exit_pct:
                self.logger().critical(
                    f"[EXIT] 🚨 {coin} EMERGENCY EXIT TRIGGERED:\n"
                    f"   Entry Price: €{entry_price:.4f}\n"
                    f"   Current Price: €{current_price:.4f}\n"
                    f"   Price Change: {price_change_pct:.2f}% (threshold: {emergency_exit_pct}%)\n"
                    f"   [REASON] Price dropped {abs(price_change_pct):.2f}% below entry - emergency exit to prevent further losses"
                )
                return "emergency_exit"

            # CRITICAL FIX: Block exits for small losses (< -0.3%) - give market time to recover
            min_loss_threshold = -0.3  # Don't exit for losses smaller than 0.3%
            if price_change_pct < 0 and price_change_pct > min_loss_threshold:
                # Small loss - block exit unless it's been a long time
                if time_since_switch < 3600:  # Less than 1 hour
                    self.logger().info(
                        f"⏸️  {coin} EXIT BLOCKED: Small loss ({price_change_pct:.2f}%) < {min_loss_threshold}% - "
                        f"waiting for recovery (hold time: {time_since_switch / 60:.1f} min)"
                    )
                    return None

            # ---------------------------------------
            # LAYER 3: HARD STOP (Fail-safe)
            # ---------------------------------------
            hard_stop_pct = getattr(self.config, 'hard_stop_pct', -6.0)  # Default: -6.0% (relaxed)
            if price_change_pct <= hard_stop_pct:
                self.logger().critical(
                    f"[EXIT] 🛑 {coin} HARD STOP TRIGGERED:\n"
                    f"   Entry Price: €{entry_price:.4f}\n"
                    f"   Current Price: €{current_price:.4f}\n"
                    f"   Price Change: {price_change_pct:.2f}% (threshold: {hard_stop_pct}%)\n"
                    f"   [REASON] Price dropped {abs(price_change_pct):.2f}% below entry - hard stop fail-safe activated"
                )
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

                    # CRITICAL FIX: Block exit if grid has positive profit (even small)
                    # This prevents premature exits before grid orders can realize profit
                    min_grid_profit_block_pct = 0.3  # Block exit if grid profit > 0.3%

                    if realized_pnl_pct >= min_grid_profit_pct:
                        self.logger().info(
                            f"[EXIT] 💰 {coin} GRID PROFIT EXIT TRIGGERED:\n"
                            f"   Grid Realized Profit: {realized_pnl_pct:.2f}% (threshold: {min_grid_profit_pct}%)\n"
                            f"   [REASON] Grid has achieved target profit - exiting to lock in gains"
                        )
                        return "grid_profit_exit"
                    elif realized_pnl_pct > min_grid_profit_block_pct:
                        # Grid has positive profit but below exit threshold - BLOCK other exits
                        grid_profit_blocking_exit = True
                        self.logger().info(
                            f"⏸️  {coin} EXIT BLOCKED: Grid has positive profit ({realized_pnl_pct:.2f}%) > {min_grid_profit_block_pct}%\n"
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
                exit_short_threshold = getattr(self.config, 'exit_short_threshold', -2.5)  # Default: -2.5% (relaxed)
                exit_mid_threshold = getattr(self.config, 'exit_mid_threshold', -1.0)  # Default: -1.0% (relaxed)

                trend_60m_break = trend.trend_60m < exit_short_threshold
                trend_240m_weak = trend.trend_240m < exit_mid_threshold

                # CRITICAL FIX: Block trend exits if price change is not severe enough
                # Only exit if price is also down significantly (not just trend)
                price_down_severely = price_change_pct < -1.5  # Price must be down > 1.5%

                if trend_60m_break and trend_240m_weak and price_down_severely:
                    # Check hard minimum hold time for trend exits
                    if in_hard_grace_period:
                        self.logger().info(
                            f"⏸️  {coin} TREND EXIT BLOCKED: Hard minimum hold time not met "
                            f"({time_since_switch / 60:.1f} min < {hard_min_hold_time / 60:.1f} min)"
                        )
                        return None

                    self.logger().critical(
                        f"[EXIT] 🚨 {coin} TREND EXIT TRIGGERED (after {time_since_switch / 60:.1f} min hold time):\n"
                        f"   [TREND] 24h: {trend.trend_1440m:+.2f}% | 4h: {trend.trend_240m:+.2f}% | 1h: {trend.trend_60m:+.2f}%\n"
                        f"   [REASON] 1h trend ({trend.trend_60m:+.2f}%) < {exit_short_threshold}% AND "
                        f"4h trend ({trend.trend_240m:+.2f}%) < {exit_mid_threshold}% AND "
                        f"price down {price_change_pct:.2f}% (threshold: -1.5%)\n"
                        f"   [PRICE] Entry: €{entry_price:.4f} | Current: €{current_price:.4f} | Change: {price_change_pct:+.2f}%"
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

    # Phase 2.5: Multi-Timeframe Exit Conditions (DEPRECATED - use should_exit_position instead)
    def _check_multi_timeframe_exit_conditions(self, coin: str) -> bool:
        """
        DEPRECATED: Use should_exit_position() instead.

        This method is kept for backward compatibility but now calls should_exit_position().
        """
        exit_reason = self.should_exit_position(coin)
        return exit_reason is not None
