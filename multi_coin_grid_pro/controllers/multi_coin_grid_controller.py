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
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.data_feed.market_data_provider import MarketDataProvider
from hummingbot.strategy_v2.controllers.controller_base import ControllerBase
from hummingbot.strategy_v2.executors.data_types import ConnectorPair
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
            print(f"\n🎯 CONTROLLER __INIT__ START\n")
            self.logger().info(f"🎯 CONTROLLER __INIT__ START - update_interval={update_interval}s")

            super().__init__(
                config=config,
                market_data_provider=market_data_provider,
                actions_queue=actions_queue,
                update_interval=update_interval
            )

            print(f"\n✅ super().__init__() completed\n")
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

        # Coin discovery and trend tracking
        self.coin_discovery: Optional[CoinDiscovery] = None
        self.trend_calculator: Optional[TrendCalculator] = None
        self.monitored_coins: List[str] = []
        self.all_available_pairs: List[str] = []  # All EUR pairs from exchange
        self.pair_volumes: Dict[str, float] = {}  # Store volume data for rotation: {pair: volume_eur}
        self.pair_spreads: Dict[str, float] = {}  # Store spread data: {pair: spread}
        self.coin_performance: Dict[str, int] = {}  # Track updates without trades per coin
        self.rotation_threshold: int = 90  # Replace coin after X updates without trades (15 min @ 10s interval)

        # State tracking
        self.active_coin: Optional[str] = None
        self.last_switch_time: float = 0
        self.active_executor_id: Optional[str] = None

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

    async def _get_ticker_data_safe(self) -> Dict[str, Any]:
        """
        Safely get ticker data from connector.
        
        This method attempts to use the connector's ticker data method if available.
        For Kraken specifically, this provides volume and spread data needed for
        coin selection. Falls back to empty dict if method doesn't exist.
        
        Returns:
            Dict of ticker data keyed by exchange symbol, or empty dict if unavailable
        """
        if not self.connector:
            self.logger().warning("⚠️  Connector not initialized, cannot fetch ticker data")
            return {}
        
        # Check if connector has the ticker data method (Kraken-specific)
        if hasattr(self.connector, '_get_ticker_data'):
            try:
                # Call the method - it's async for Kraken
                if asyncio.iscoroutinefunction(self.connector._get_ticker_data):
                    ticker_data = await self.connector._get_ticker_data()
                else:
                    ticker_data = self.connector._get_ticker_data()
                return ticker_data
            except Exception as e:
                self.logger().error(f"❌ Failed to fetch ticker data: {e}")
                import traceback
                self.logger().error(traceback.format_exc())
                return {}
        else:
            # Connector doesn't support ticker data - use fallback approach
            self.logger().warning(
                f"⚠️  Connector {type(self.connector).__name__} doesn't support ticker data. "
                f"Volume-based selection will be limited."
            )
            return {}

    def _initialize_components(self):
        """Initialize coin discovery and trend calculator"""
        if not self.connector:
            # Get connector from connectors dict
            # Note: connectors dict is passed from the strategy which has access to all exchange connectors
            connectors = getattr(self, 'connectors', {})
            if not connectors:
                self.logger().error(f"❌ No connectors available! Make sure connectors are passed to controller.")
                return

            self.connector = connectors.get(self.config.connector_name)

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
            self.trend_calculator = TrendCalculator(
                connector=self.connector,
                lookback_minutes=self.config.trend_lookback_minutes
            )

    async def on_start(self):
        """Override to log when control_loop starts"""
        self.logger().info("🚀 Controller.on_start() called - control_loop is starting!")
        await super().on_start()

    async def control_task(self):
        """Override to log why update isn't called"""
        mdp_ready = self.market_data_provider.ready if self.market_data_provider else False
        event_set = self.executors_update_event.is_set() if hasattr(self, 'executors_update_event') else False
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
            self.logger().info("💫 First run - discovering coins...")
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
                trading_pair_map = await self.connector.trading_pair_symbol_map()

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
                spread_checked_pairs.sort(key=lambda x: x[1], reverse=True)
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
                # Use fallback list on error
                self.monitored_coins = [
                    f"XRP/{self.config.quote_asset}",
                    f"ADA/{self.config.quote_asset}",
                    f"DOT/{self.config.quote_asset}",
                    f"SOL/{self.config.quote_asset}",
                    f"LINK/{self.config.quote_asset}",
                ]
                self.logger().warning(f"⚠️  Using emergency fallback: {self.monitored_coins}")

        # Rotate underperforming coins if we have a pool to rotate from
        if len(self.all_available_pairs) > len(self.monitored_coins):
            self._rotate_underperforming_coins()

        # Update trends for all monitored coins
        self.logger().info(f"📊 Updating trends for {len(self.monitored_coins)} coins...")
        self.logger().info(f"🔧 DEBUG: First 5 coins to update: {self.monitored_coins[:5]}")

        # Check BEFORE update
        trends_before = len(self.trend_calculator.trends)
        self.logger().info(f"🔧 DEBUG: Trends BEFORE update: {trends_before}")

        # SYNTAX ERROR TEST - if this doesn't crash, Python loads OLD code!
        SYNTAX_ERROR_TEST_NEW_CODE_LOADED = "YES"  # This line will crash if old code

        # BYPASS trend_calculator entirely - fetch prices DIRECTLY here
        try:
            self.logger().info("🔥🔥🔥 NEW CODE LOADED! DIRECT PRICE FETCH TEST")
            test_symbols = self.monitored_coins[:3]  # Just test 3 coins
            self.logger().info(f"🔥 Testing with symbols: {test_symbols}")

            prices = await self.connector.get_last_traded_prices(test_symbols)
            self.logger().info(f"🔥 PRICE RESULT: {prices}")

            if prices:
                for symbol, price in prices.items():
                    self.logger().info(f"✅ {symbol}: €{price}")
            else:
                self.logger().error("❌ get_last_traded_prices returned None or empty!")

        except Exception as e:
            self.logger().error(f"❌ DIRECT TEST CRASHED: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

        # NOW ACTUALLY CALL THE TREND UPDATE!
        try:
            self.logger().info("🔥 Calling trend_calculator.update_all_trends_v2()...")
            await self.trend_calculator.update_all_trends_v2(self.monitored_coins)
            self.logger().info("✅ trend_calculator.update_all_trends_v2() completed!")
        except Exception as e:
            self.logger().error(f"❌ update_all_trends_v2 CRASHED: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

        # Check AFTER update
        trends_after = len(self.trend_calculator.trends)
        self.logger().info(f"🔧 DEBUG: Trends AFTER update: {trends_after}")

        if trends_after == 0 and trends_before == 0:
            self.logger().error("⚠️ WARNING: update_all_trends did NOTHING!")
            # Manual test - bypass trend_calculator entirely
            try:
                test_symbol = self.monitored_coins[0] if self.monitored_coins else "BTC-EUR"
                self.logger().error(f"🔧 MANUAL TEST: Fetching price for {test_symbol}...")

                # Kraken uses PLURAL method get_last_traded_prices()
                prices = await self.connector.get_last_traded_prices([test_symbol])
                test_price = prices.get(test_symbol) if prices else None
                self.logger().error(f"🔧 MANUAL TEST: Price = €{test_price}")

                if test_price:
                    self.logger().error(f"✅ Price fetch WORKS! Problem is in trend_calculator.update_all_trends()")
                else:
                    self.logger().error(f"❌ Price is None - connector can't fetch prices")
            except Exception as e:
                self.logger().error(f"🔧 MANUAL TEST ERROR: {e}")
                import traceback
                self.logger().error(traceback.format_exc())

        self.logger().info("✅ Update completed")

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

        # Find best coin
        self.logger().info("🔎 Analyzing coins for best trading opportunity...")
        self.logger().info(f"🎯 Looking for trend >= {self.config.trend_min_change_pct}%")
        self.logger().info(f"🔧 DEBUG: trend_calculator exists = {self.trend_calculator is not None}")
        self.logger().info(f"🔧 DEBUG: trend_calculator.trends has {len(self.trend_calculator.trends) if self.trend_calculator else 0} coins")

        try:
            best_coin = self.trend_calculator.get_best_coin(
                min_trend_pct=float(self.config.trend_min_change_pct)
            )

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
                        self.logger().info(f"  {i}. {sym}: {tr:+.3f}%")

                if info.get('best'):
                    sym, tr = info['best']
                    self.logger().info(f"🏆 BEST: {sym} with {tr:+.2f}% trend")
                else:
                    self.logger().info(f"❌ No coin >= {info['min_trend']}% threshold")

            self.logger().info(f"🔍 Selected coin: {best_coin}")
        except Exception as e:
            self.logger().error(f"💥 CRASH in get_best_coin(): {e}")
            import traceback
            self.logger().error(traceback.format_exc())
            return actions

        # No coin meets criteria - stop active executor
        if not best_coin:
            self.logger().info(f"❌ No coin found with trend >= {self.config.trend_min_change_pct}%")
            if self.active_coin and self.active_executor_id:
                # Validate executor exists before stopping
                if self._is_executor_actually_active():
                    self.logger().warning(
                        f"⚠️  No coin meets minimum trend - "
                        f"stopping executor for {self.active_coin}"
                    )
                    try:
                        stop_action = self._create_stop_action()
                        if stop_action:
                            actions.append(stop_action)
                        else:
                            self.logger().warning(f"⚠️  Failed to create stop action")
                    except Exception as e:
                        self.logger().error(f"❌ Error creating stop action: {e}")
                        import traceback
                        self.logger().error(traceback.format_exc())
                else:
                    # Executor already gone - just clear state
                    self.logger().info(f"ℹ️  Executor for {self.active_coin} already stopped")
                    self.active_coin = None
                    self.active_executor_id = None
            return actions

        # Check if we should create/switch grid
        if self._should_create_new_grid(best_coin):
            # Ensure order book exists before creating executor
            try:
                # Run async check synchronously
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If loop is running, schedule the check
                    # For now, we'll do a simple sync check and log warning if needed
                    try:
                        order_book = self.connector.get_order_book(best_coin)
                        if order_book is None:
                            self.logger().warning(f"⚠️ Order book not available for {best_coin} - will attempt async initialization")
                    except (ValueError, KeyError):
                        self.logger().warning(f"⚠️ Order book not found for {best_coin} - executor creation may fail")
                        # Schedule async initialization for next cycle
                        safe_ensure_future(self._ensure_order_book_exists(best_coin))
                else:
                    # Loop not running, can run directly
                    order_book_ready = loop.run_until_complete(self._ensure_order_book_exists(best_coin))
                    if not order_book_ready:
                        self.logger().error(f"❌ Cannot create executor for {best_coin} - order book not available")
                        return actions
            except Exception as e:
                self.logger().error(f"❌ Error checking order book for {best_coin}: {e}")
                # Continue anyway - executor will handle the error

            # Stop old executor if exists and is actually active
            if self.active_coin and self.active_executor_id and self._is_executor_actually_active():
                self.logger().info(
                    f"🔄 SWITCHING: {self.active_coin} → {best_coin}"
                )
                try:
                    stop_action = self._create_stop_action()
                    if stop_action:
                        actions.append(stop_action)
                    else:
                        self.logger().warning(f"⚠️  Failed to create stop action for {self.active_coin}")
                except Exception as e:
                    self.logger().error(f"❌ Error creating stop action: {e}")
                    import traceback
                    self.logger().error(traceback.format_exc())
            else:
                self.logger().info(f"✨ STARTING new grid on {best_coin}")

            # Create new grid executor
            try:
                grid_action = self._create_grid_action(best_coin)
                if grid_action:
                    actions.append(grid_action)
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
            # Executor doesn't exist or is not active - clear tracking
            self.logger().warning(
                f"⚠️  Tracked executor {self.active_executor_id[:8]}... "
                f"not found or inactive - clearing state"
            )
            self.active_executor_id = None
            self.active_coin = None
            return False

        return True

    def _should_create_new_grid(self, best_coin: str) -> bool:
        """
        Determine if we should create a new grid

        Args:
            best_coin: Symbol of best trending coin

        Returns:
            True if should create new grid
        """
        # No active coin - always create
        if not self.active_coin:
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

        # Check cooldown period
        time_since_switch = self.market_data_provider.time() - self.last_switch_time
        if time_since_switch < self.config.min_switch_interval_seconds:
            remaining = self.config.min_switch_interval_seconds - time_since_switch
            self.logger().warning(
                f"⏰ Switch cooldown active - "
                f"wait {remaining / 60:.1f} more minutes"
            )
            return False

        # All checks passed - switch to new coin
        active_trend = self.trend_calculator.get_trend(self.active_coin)
        best_trend = self.trend_calculator.get_trend(best_coin)

        self.logger().info(
            f"🔄 SWITCH APPROVED: "
            f"{self.active_coin} ({active_trend.trend_pct:+.2f}%) → "
            f"{best_coin} ({best_trend.trend_pct:+.2f}%)"
        )
        return True

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
            self.logger().error(f"❌ Connector not initialized")
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
                self.logger().error(f"❌ Connector has no order_book_tracker")
                return False

            tracker = self.connector.order_book_tracker

            # Check if trading pair is already in tracker's trading pairs
            if symbol not in tracker.trading_pairs:
                # Add trading pair to tracker
                self.logger().info(f"📥 Adding {symbol} to order book tracker...")
                tracker.trading_pairs.append(symbol)

            # Initialize order book for this pair
            if symbol not in tracker.order_books:
                self.logger().info(f"📚 Initializing order book for {symbol}...")
                order_book = await tracker._initial_order_book_for_trading_pair(symbol)
                tracker.order_books[symbol] = order_book
                tracker.tracking_message_queues[symbol] = asyncio.Queue()
                tracker.tracking_tasks[symbol] = safe_ensure_future(tracker._track_single_book(symbol))
                self.logger().info(f"✅ Order book initialized for {symbol}")

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

        Args:
            symbol: Trading pair symbol

        Returns:
            CreateExecutorAction with GridExecutorConfig
        """
        # Get current price
        trend = self.trend_calculator.get_trend(symbol)
        current_price = Decimal(str(trend.current_price))  # Convert float to Decimal

        # Calculate grid range
        start_price = current_price * (
            Decimal("1") - self.config.grid_range_pct_down / Decimal("100")
        )
        end_price = current_price * (
            Decimal("1") + self.config.grid_range_pct_up / Decimal("100")
        )

        # Use start_price as limit price (price-based circuit breaker)
        limit_price = start_price * Decimal("0.95")  # 5% below start as safety

        self.logger().info(
            f"\n📝 CREATING GRID for {symbol}:"
            f"\n   Current Price: €{current_price:.4f}"
            f"\n   Range: €{start_price:.4f} - €{end_price:.4f}"
            f"\n   Limit Price: €{limit_price:.4f} (circuit breaker)"
            f"\n   Capital: €{self.config.total_amount_quote}"
            f"\n   Stop Loss: -{self.config.stop_loss_pct * 100}%"
        )

        # Create grid config
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
            max_open_orders=self.config.max_open_orders,
            max_orders_per_batch=2,
            order_frequency=self.config.order_frequency,
            activation_bounds=Decimal("0.05"),  # 5% activation bounds
            keep_position=False,  # Don't keep position on stop
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

        try:
            return StopExecutorAction(
                controller_id=controller_id,
                executor_id=self.active_executor_id
            )
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

        # Active coin
        if self.active_coin:
            trend = self.trend_calculator.get_trend(self.active_coin)
            if trend:
                status.append(f"║ Active Coin: {self.active_coin:12} | Trend: {trend.trend_pct:+6.2f}%          ║")
                status.append(f"║ Price: €{trend.current_price:8.4f}                                    ║")
        else:
            status.append("║ Active Coin: None (waiting for opportunity)                  ║")

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
