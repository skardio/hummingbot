"""
Multi-Coin Grid Trading Strategy V2

Entry point script for running the multi-coin grid trading strategy using
Hummingbot's Strategy V2 architecture.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from hummingbot.connector.connector_base import ConnectorBase

# Import from symlinked modules in hummingbot package
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
from hummingbot.strategy.strategy_v2_base import StrategyV2Base, StrategyV2ConfigBase


def expand_env_vars(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively expand environment variables in config dict.
    Supports ${VAR_NAME} and $VAR_NAME syntax.

    Example:
        bot_token: "${TELEGRAM_BOT_TOKEN}" -> bot_token: "123456:ABC..."
    """
    if isinstance(config, dict):
        return {k: expand_env_vars(v) for k, v in config.items()}
    elif isinstance(config, list):
        return [expand_env_vars(item) for item in config]
    elif isinstance(config, str):
        # Replace ${VAR} and $VAR with environment variable value
        def replace_env(match):
            var_name = match.group(1) or match.group(2)
            return os.environ.get(var_name, match.group(0))

        # Match ${VAR_NAME} or $VAR_NAME
        return re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)', replace_env, config)
    else:
        return config


class MultiCoinGridStrategyConfig(StrategyV2ConfigBase):
    """
    Minimal config for Strategy V2
    Controller handles all trading logic
    """
    # Empty config - markets defined at class level below
    markets: Dict = {}
    candles_config: List = []


class MultiCoinGridStrategyV2(StrategyV2Base):
    """
    Multi-Coin Grid Trading Strategy V2

    This strategy automatically:
    1. Discovers tradeable coins on the exchange
    2. Monitors their price trends
    3. Creates grid trading setups on the best trending coin
    4. Switches to different coins as trends change

    Built on Hummingbot's Strategy V2 architecture with:
    - GridExecutor for order management
    - Stop-loss protection
    - Event-driven async architecture
    - Automatic risk management
    """

    # Class variable - used by Hummingbot to initialize connectors BEFORE strategy __init__
    # Format: {"exchange_name": {"trading_pair1", "trading_pair2"}}
    #
    # TWO-TIER SYSTEM:
    # 1. At startup: Use seed pairs from config OR dynamic scan
    # 2. At runtime: DynamicPairManager scans ALL pairs and recommends rotations
    #
    # NOTE: Kraken WebSocket limit is ~25-30 subscriptions
    markets = {}

    @classmethod
    def _load_markets_from_config(cls) -> Dict[str, set]:
        """
        Load initial markets for WebSocket subscription

        Strategy:
        1. Try to load from config (whitelisted_pairs)
        2. If not set, use dynamic discovery via REST API
        3. Fallback to default seed pairs
        """
        import os
        from pathlib import Path

        import yaml

        # Determine config file based on BOT_ENV
        env = os.environ.get("BOT_ENV", "prod")
        config_file = f"config.{env}.yaml"
        config_path = Path(__file__).parent.parent / "multi_coin_grid_pro" / "config" / config_file

        # Fallback to default config
        if not config_path.exists():
            config_path = Path(__file__).parent.parent / "multi_coin_grid_pro" / "config" / "config.prod.yaml"

        # Default seed pairs (always liquid, used as fallback)
        default_pairs = {
            "USDC-EUR", "USDT-EUR", "BTC-EUR", "ETH-EUR", "SOL-EUR",
            "ADA-EUR", "XRP-EUR", "DOGE-EUR", "LINK-EUR", "DOT-EUR",
            "SUI-EUR", "AVAX-EUR", "LINK-EUR", "DOT-EUR", "TRX-EUR"
        }

        try:
            if config_path.exists():
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    # Expand environment variables
                    config = expand_env_vars(config)

                    connector = config.get("connector_name", "kraken")
                    pairs = config.get("whitelisted_pairs", [])
                    use_dynamic = config.get("use_dynamic_pair_discovery", True)

                    # Option 1: Static whitelist from config
                    if pairs and not use_dynamic:
                        print(f"📋 Using static whitelist: {len(pairs)} pairs from config")
                        return {connector: set(pairs)}

                    # Option 2: Dynamic discovery at startup
                    if use_dynamic:
                        print("🔍 Dynamic pair discovery enabled - scanning exchange...")
                        try:
                            discovered = cls._discover_pairs_sync(config)
                            if discovered:
                                print(f"✅ Discovered {len(discovered)} pairs dynamically")
                                return {connector: discovered}
                        except Exception as discover_error:
                            print(f"⚠️  Dynamic discovery failed: {discover_error}")
                            print(f"⚠️  Falling back to whitelist...")

                    # Fallback to whitelist if dynamic fails
                    if pairs:
                        print(f"📋 Fallback to whitelist: {len(pairs)} pairs")
                        return {connector: set(pairs)}

        except Exception as e:
            print(f"⚠️  Error loading markets: {e}")

        # Final fallback to defaults
        print(f"📋 Using default seed pairs: {len(default_pairs)} pairs")
        return {"kraken": default_pairs}

    @classmethod
    def _discover_pairs_sync(cls, config: dict) -> set:
        """
        Synchronously discover best pairs via REST API

        This runs at module load time to select initial pairs
        """
        import asyncio

        import aiohttp

        async def fetch_and_rank():
            try:
                quote_asset = config.get("quote_asset", "EUR")
                min_volume = config.get("min_24h_volume_eur", 100000)
                max_pairs = config.get("max_coins_to_monitor", 25)
                max_spread = config.get("max_entry_spread_pct", 0.5)
                blacklist = set(config.get("blacklist", []))

                print(f"   Fetching all tickers from Kraken...")

                async with aiohttp.ClientSession() as session:
                    url = "https://api.kraken.com/0/public/Ticker"
                    async with session.get(url, timeout=30) as response:
                        if response.status != 200:
                            print(f"   ❌ API returned {response.status}")
                            return set()

                        data = await response.json()
                        if data.get("error"):
                            print(f"   ❌ API error: {data['error']}")
                            return set()

                        tickers = data.get("result", {})
                        print(f"   Got {len(tickers)} tickers from API")

                        # Process and rank pairs
                        pairs_data = []

                        for kraken_sym, ticker in tickers.items():
                            # Convert symbol
                            symbol = cls._convert_kraken_symbol_static(kraken_sym, quote_asset)
                            if not symbol:
                                continue

                            if symbol in blacklist:
                                continue

                            try:
                                ask = float(ticker.get("a", [0])[0])
                                bid = float(ticker.get("b", [0])[0])
                                last = float(ticker.get("c", [0])[0])
                                vol_24h = float(ticker.get("v", [0, 0])[1])
                                open_price = float(ticker.get("o", 0))

                                # Volume in quote currency
                                vol_eur = vol_24h * last

                                # Spread
                                spread = ((ask - bid) / bid * 100) if bid > 0 else 999

                                # 24h change
                                change = ((last - open_price) / open_price * 100) if open_price > 0 else 0

                                # Filter
                                if vol_eur < min_volume or spread > max_spread:
                                    continue

                                # Score: 40% volume, 40% trend, 20% spread
                                vol_score = min(100, (vol_eur / 100000) * 10)
                                trend_score = min(100, max(0, (change + 10) * 5))
                                spread_score = max(0, 100 - spread * 100)
                                score = vol_score * 0.4 + trend_score * 0.4 + spread_score * 0.2

                                pairs_data.append({
                                    "symbol": symbol,
                                    "volume": vol_eur,
                                    "change": change,
                                    "spread": spread,
                                    "score": score
                                })
                            except (IndexError, ValueError, TypeError):
                                continue

                        # Sort by score and take top N
                        pairs_data.sort(key=lambda x: x["score"], reverse=True)
                        selected = pairs_data[:max_pairs]

                        print(f"   Selected {len(selected)} pairs (vol>€{min_volume / 1000:.0f}k, spread<{max_spread}%)")

                        # Log top 10
                        for i, p in enumerate(selected[:10], 1):
                            print(f"     {i}. {p['symbol']}: vol=€{p['volume'] / 1000:.0f}k, Δ{p['change']:+.1f}%, spread={p['spread']:.2f}%")

                        return {p["symbol"] for p in selected}

            except Exception as e:
                print(f"   ❌ Discovery error: {e}")
                return set()

        # Run async function synchronously
        try:
            # Try to get existing event loop
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Event loop is already running (Hummingbot context)
                # We can't use run_until_complete, so create a new thread with its own loop
                import concurrent.futures
                print("   Running discovery in separate thread (event loop already active)...")
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(lambda: asyncio.run(fetch_and_rank()))
                    return future.result(timeout=30)  # 30s timeout
            else:
                # Event loop exists but not running
                return loop.run_until_complete(fetch_and_rank())
        except RuntimeError as e:
            # No event loop at all, create one
            print(f"   Creating new event loop for discovery...")
            return asyncio.run(fetch_and_rank())
        except Exception as e:
            print(f"   Discovery error: {type(e).__name__}: {e}")
            return None

    @staticmethod
    def _convert_kraken_symbol_static(kraken_symbol: str, quote_asset: str) -> str:
        """
        Convert Kraken's internal symbol format to standard format

        Kraken uses weird formats:
        - XXBTZEUR → BTC-EUR (X prefix for crypto, Z prefix for fiat)
        - XETHZEUR → ETH-EUR
        - SOLEUR → SOL-EUR (newer coins don't have X prefix)
        - USDCEUR → USDC-EUR
        - XDGEUR → DOGE-EUR (XDG = Dogecoin)
        - XLTCZEUR → LTC-EUR
        - XXRPZEUR → XRP-EUR
        """
        symbol = kraken_symbol.upper()
        quote = quote_asset.upper()

        # Skip non-quote pairs
        if not symbol.endswith(quote) and not symbol.endswith(f"Z{quote}"):
            return ""

        # Skip fiat-to-fiat pairs (EUR/USD, EUR/GBP, etc.)
        # But allow stablecoins (USDC, USDT, EURC)
        fiat_to_fiat = [
            "ZEURZUSD", "EURUSD", "EURGBP", "EURCHF", "EURCAD", "EURAUD", "EURJPY",
            "USDJPY", "GBPUSD", "USDCHF", "USDCAD"
        ]
        if symbol in fiat_to_fiat:
            return ""

        # Skip if starts with Z (Kraken's fiat prefix) but isn't a crypto pair
        if symbol.startswith("ZEUR") or symbol.startswith("ZUSD"):
            return ""

        # Known Kraken base symbol mappings
        kraken_base_map = {
            "XXBT": "BTC",
            "XBT": "BTC",
            "XXDG": "DOGE",
            "XDG": "DOGE",
            "XXRP": "XRP",
            "XETH": "ETH",
            "XLTC": "LTC",
            "XXLM": "XLM",
            "XZEC": "ZEC",
            "XXMR": "XMR",
            "XREP": "REP",
            "XETC": "ETC",
        }

        # Extract base asset
        if symbol.endswith(f"Z{quote}"):
            base = symbol[:-len(f"Z{quote}")]
        else:
            base = symbol[:-len(quote)]

        # Check if full base is in mapping (handles XXBT, XXRP, etc.)
        if base in kraken_base_map:
            base = kraken_base_map[base]
        else:
            # Remove single X prefix for old-style symbols (XETH -> ETH)
            # But NOT for symbols like XNY, XPL (which are actual coin names)
            if base.startswith("X") and len(base) == 4:
                stripped = base[1:]
                # Only strip if it's a known pattern (3-letter code after X)
                if stripped in ["ETH", "LTC", "XLM", "ZEC", "XMR", "REP", "ETC", "DG"]:
                    base = stripped
                    if base == "DG":
                        base = "DOGE"

        # Skip if base is too short or invalid
        if len(base) < 2:
            return ""

        # Skip EURC pairs (complex handling)
        if base == "EURC":
            return ""

        return f"{base}-{quote}"

    def __init__(self, connectors: Dict[str, ConnectorBase], config: MultiCoinGridStrategyConfig = None):
        """
        Initialize the strategy

        Args:
            connectors: Dictionary of exchange connectors
            config: Strategy configuration (optional, will create default if None)
        """
        if config is None:
            config = MultiCoinGridStrategyConfig()
        super().__init__(connectors, config)
        self.config = config

        # Load controller config from YAML (validation only - controller loads it separately)
        # Note: ConfigManager handles the actual loading in initialize_controllers()
        try:
            import yaml
            config_path = Path(__file__).parent.parent / "multi_coin_grid_pro" / "config" / "multi_coin_grid.yml"
            if config_path.exists():
                with open(config_path) as f:
                    config_data = yaml.safe_load(f)
                    # Expand environment variables
                    config_data = expand_env_vars(config_data)
        except Exception:
            # Config loading will be handled by ConfigManager in initialize_controllers()
            pass

        self.logger().info("=" * 70)
        self.logger().info("  MULTI-COIN GRID STRATEGY V2.0 INITIALIZED")
        self.logger().info("=" * 70)

    def initialize_controllers(self):
        """
        Initialize controllers - called by StrategyV2Base
        """
        try:
            # Use ConfigManager to load environment-specific config
            from multi_coin_grid_pro.config.config_manager import ConfigManager

            self.logger().info("🔧 Loading controller config...")

            # Load config using ConfigManager (supports dev/test/prod)
            config_manager = ConfigManager()
            env = config_manager.get_environment()
            config_data = config_manager.load_config('multi_coin_grid', env)

            # Expand environment variables in config
            config_data = expand_env_vars(config_data)

            config_path = config_manager.get_config_path('multi_coin_grid')
            self.logger().info(f"📁 Config path: {config_path}")
            self.logger().info(f"🌍 Environment: {env}")

            self.logger().info("📝 Creating controller config...")

            # Check if paper trading is enabled
            paper_trading = config_data.get('paper_trading', False)
            connector_name = config_data.get('connector_name', 'kraken')

            # CRITICAL: For paper trading, adjust connector name BEFORE creating config
            # Hummingbot will create the paper trade connector automatically if kraken is in paper_trade_exchanges
            if paper_trading:
                # Use paper trade connector name - Hummingbot will create it if configured
                paper_connector_name = f"{connector_name}_paper_trade"
                connector_name = paper_connector_name
                self.logger().info("=" * 80)
                self.logger().info("📝 PAPER TRADING MODE ENABLED - No real money will be used!")
                self.logger().info(f"   Using connector: {connector_name}")
                self.logger().info("=" * 80)
                self.logger().info("💡 Note: Make sure 'kraken' is in paper_trade_exchanges in Hummingbot config")
            else:
                self.logger().info("=" * 80)
                self.logger().info("💰 LIVE TRADING MODE - Real money will be used!")
                self.logger().info(f"   Connector: {connector_name}")
                self.logger().info("=" * 80)

            # CRITICAL: Update config_data with adjusted connector name BEFORE creating config
            config_data['connector_name'] = connector_name
            config_data['paper_trading'] = paper_trading  # Store actual paper trading status

            # Create controller config
            controller_config = MultiCoinGridConfig(
                controller_name="multi_coin_grid",
                **config_data
            )

            self.logger().info("🚀 Creating controller instance...")
            self.logger().info(f"DEBUG: self.controllers = {type(self.controllers)}")
            self.logger().info(f"DEBUG: market_data_provider = {type(self.market_data_provider)}")
            self.logger().info(f"DEBUG: actions_queue = {type(self.actions_queue)}")
            self.logger().info(f"DEBUG: self.connectors = {self.connectors}")
            self.logger().info(f"DEBUG: self.connectors keys = {list(self.connectors.keys()) if self.connectors else 'None'}")

            # Add controller to strategy
            controller = MultiCoinGridController(
                config=controller_config,
                market_data_provider=self.market_data_provider,
                actions_queue=self.actions_queue,
                connectors=self.connectors,  # Pass connectors dict from strategy
                update_interval=10.0  # Update every 10 seconds
            )

            self.logger().info(f"DEBUG: Controller object created: {type(controller)}")
            self.logger().info(f"DEBUG: Controller has __init__: {hasattr(controller, '__init__')}")
            self.logger().info(f"DEBUG: Controller class: {controller.__class__.__name__}")
            self.logger().info(f"DEBUG: Controller module: {controller.__class__.__module__}")
            self.controllers["multi_coin_grid"] = controller
            self.logger().info(f"DEBUG: Controller added to dict, count = {len(self.controllers)}")
            self.logger().info(f"DEBUG: Controllers in dict: {list(self.controllers.keys())}")

            # Try to access controller's config
            try:
                self.logger().info(f"DEBUG: Controller config: {controller.config.connector_name}")
            except Exception as e:
                self.logger().error(f"DEBUG: Failed to access controller.config: {e}")

            mode_str = "📝 PAPER TRADING" if paper_trading else "💰 LIVE TRADING"
            self.logger().info(f"✅ Controller initialized: {controller_config.connector_name} ({mode_str})")
            self.logger().info(f"💰 Capital: €{controller_config.total_amount_quote}")
            self.logger().info(f"⚠️  Stop Loss: {controller_config.stop_loss_pct * 100}%")
        except Exception as e:
            self.logger().error(f"❌ Failed to initialize controller: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

    @classmethod
    def init_markets(cls, config: MultiCoinGridConfig = None):
        """
        Initialize markets for the strategy

        This is called by Hummingbot to determine which markets to connect to.
        """
        if config is None:
            # Use ConfigManager to load environment-specific config
            connector_name = "kraken"
            quote_asset = "EUR"
            paper_trading = False

            try:
                from multi_coin_grid_pro.config.config_manager import ConfigManager
                config_manager = ConfigManager()
                env = config_manager.get_environment()
                yaml_config = config_manager.load_config('multi_coin_grid', env)
                connector_name = yaml_config.get('connector_name', 'kraken')
                quote_asset = yaml_config.get('quote_asset', 'EUR')
                paper_trading = yaml_config.get('paper_trading', False)
            except Exception as e:
                # Use defaults if config loading fails
                import logging
                logging.getLogger(__name__).warning(f"Failed to load config in init_markets: {e}")

            # CRITICAL: For paper trading, adjust connector name BEFORE setting markets
            # Hummingbot needs to know which connector to initialize
            # IMPORTANT: Paper trading connector must be created by Hummingbot's connector manager
            # The connector name should end with '_paper_trade' for Hummingbot to recognize it

            # 🔧 FIX: Set up common trading pairs for order book initialization
            # This ensures the connector has order books for coins we might trade
            common_pairs = {
                f"BTC-{quote_asset}",
                f"ETH-{quote_asset}",
                f"SOL-{quote_asset}",
                f"ADA-{quote_asset}",
                f"XRP-{quote_asset}",
                f"DOGE-{quote_asset}",
                f"LINK-{quote_asset}",
                f"DOT-{quote_asset}",
                f"SUI-{quote_asset}",
                f"AVAX-{quote_asset}",
                f"MON-{quote_asset}",
                f"USDC-{quote_asset}",
                f"USDT-{quote_asset}",
            }

            if paper_trading:
                # Use paper trade connector name
                paper_connector_name = f"{connector_name}_paper_trade"
                cls.markets = {paper_connector_name: common_pairs}
                # Log warning if paper trading is enabled but connector might not be configured
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"📝 PAPER TRADING MODE: Using connector '{paper_connector_name}'\n"
                    f"   Make sure '{connector_name}' is in paper_trade_exchanges in Hummingbot config!\n"
                    f"   If connector is not found, bot will fall back to LIVE trading!"
                )
            else:
                cls.markets = {connector_name: common_pairs}
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"✅ init_markets: Setting up {len(common_pairs)} trading pairs for {connector_name}")
        else:
            # When config is provided, use same common pairs as fallback
            quote = config.quote_asset
            common_pairs = {
                f"BTC-{quote}",
                f"ETH-{quote}",
                f"SOL-{quote}",
                f"ADA-{quote}",
                f"XRP-{quote}",
                f"DOGE-{quote}",
                f"LINK-{quote}",
                f"DOT-{quote}",
                f"SUI-{quote}",
                f"AVAX-{quote}",
                f"MON-{quote}",
                f"USDC-{quote}",
            }
            cls.markets = {config.connector_name: common_pairs}

    def start(self, clock, timestamp):
        """Override start to add logging"""
        self.logger().info(f"🚀 Strategy.start() called - {len(self.controllers)} controllers to start")

        # Check controller status before starting
        for name, controller in self.controllers.items():
            self.logger().info(f"DEBUG: Controller '{name}' status BEFORE start: {controller.status}")

        super().start(clock, timestamp)

        # Check controller status after starting
        for name, controller in self.controllers.items():
            self.logger().info(f"DEBUG: Controller '{name}' status AFTER start: {controller.status}")

        self.logger().info("✅ Strategy.start() completed - controllers should be running")

    def on_tick(self):
        """
        Called on every tick (regular interval)

        The actual trading logic is handled by the controller.
        """
        super().on_tick()  # Controller handles all trading logic

    def create_actions_proposal(self) -> List:
        """
        Create action proposals - required by StrategyV2Base

        Returns empty list because actions come from controllers.
        """
        return []

    def stop_actions_proposal(self) -> List:
        """
        Stop action proposals - required by StrategyV2Base

        Returns empty list because actions come from controllers.
        """
        return []

    def format_status(self) -> str:
        """
        Format strategy status for display

        Returns:
            Formatted status string
        """
        lines = []

        # Get controller status
        for controller in self.controllers.values():
            if isinstance(controller, MultiCoinGridController):
                lines.extend(controller.to_format_status())

        # Add executor status
        if self.executor_orchestrator:
            # Get executor report from orchestrator
            try:
                executors_report = self.executor_orchestrator.get_executors_report()
                active_executors = []

                # Flatten all executors from all controllers
                for controller_id, executor_list in executors_report.items():
                    active_executors.extend([e for e in executor_list if e.is_active])

                if active_executors:
                    lines.append("\n╔═══════════════════════════════════════════════════════════════╗")
                    lines.append("║                    ACTIVE EXECUTORS                           ║")
                    lines.append("╠═══════════════════════════════════════════════════════════════╣")

                    for executor in active_executors:
                        lines.append(
                            f"║ ID: {executor.id[:8]}... | "
                            f"Status: {executor.status.name:10} | "
                            f"P&L: {float(executor.net_pnl_pct) * 100:+.2f}%   ║"
                        )

                    lines.append("╚═══════════════════════════════════════════════════════════════╝\n")
            except Exception:
                # If there's an error getting executor info, just skip it
                # The controller status above is more important
                pass

        return "\n".join(lines)


# =============================================================================
# LOAD MARKETS FROM CONFIG AT MODULE IMPORT TIME
# =============================================================================
# This MUST happen before Hummingbot tries to initialize connectors
MultiCoinGridStrategyV2.markets = MultiCoinGridStrategyV2._load_markets_from_config()


# For running directly via Hummingbot CLI
def create_strategy(connectors: Dict[str, ConnectorBase]) -> MultiCoinGridStrategyV2:
    """
    Factory function to create strategy instance

    This is called by Hummingbot's trading core when loading the strategy.

    Args:
        connectors: Dictionary of exchange connectors

    Returns:
        Strategy instance
    """
    config = MultiCoinGridStrategyConfig()
    return MultiCoinGridStrategyV2(connectors, config)
# Force reload: Sat Nov 15 20:43:00 CET 2025
