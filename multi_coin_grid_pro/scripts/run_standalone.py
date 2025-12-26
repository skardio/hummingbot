#!/usr/bin/env python3
"""
Standalone launcher for Multi-Coin Grid Bot V2

This script runs the bot without the Hummingbot CLI.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

# Add hummingbot to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Check API keys
if not os.getenv('KRAKEN_API_KEY') or not os.getenv('KRAKEN_SECRET_KEY'):
    logger.error("❌ Missing Kraken API keys!")
    logger.error("   Set KRAKEN_API_KEY and KRAKEN_SECRET_KEY environment variables")
    sys.exit(1)

logger.info("=" * 70)
logger.info("  MULTI-COIN GRID BOT V2.0 - STANDALONE MODE")
logger.info("=" * 70)
logger.info(f"✓ Kraken API Key: {os.getenv('KRAKEN_API_KEY')[:10]}...")
logger.info(f"✓ Working Directory: {Path.cwd()}")
logger.info("=" * 70)

# Import Hummingbot components
try:
    import ccxt

    logger.info("✓ Hummingbot modules loaded")
except ImportError as e:
    logger.error(f"❌ Failed to import Hummingbot: {e}")
    logger.error("   Make sure you're in the Hummingbot venv")
    sys.exit(1)

# Import strategy
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    # Load config and controller modules directly
    import importlib.util

    def load_module(name, path):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        # Fix relative imports by adding parent to sys.modules
        if '.' not in name:
            parent_pkg = f"{name}_pkg"
            sys.modules[parent_pkg] = module
        spec.loader.exec_module(module)
        return module

    # Load utility modules first
    utils_path = project_root / 'utils'
    coin_discovery = load_module('coin_discovery', utils_path / 'coin_discovery.py')
    trend_calculator = load_module('trend_calculator', utils_path / 'trend_calculator.py')

    # Load controller modules
    controllers_path = project_root / 'controllers'
    config_mod = load_module('multi_coin_grid_config', controllers_path / 'multi_coin_grid_config.py')

    # Inject dependencies into controller module namespace
    sys.modules['coin_discovery'] = coin_discovery
    sys.modules['trend_calculator'] = trend_calculator
    sys.modules['multi_coin_grid_config'] = config_mod

    controller_mod = load_module('multi_coin_grid_controller', controllers_path / 'multi_coin_grid_controller.py')

    MultiCoinGridConfig = config_mod.MultiCoinGridConfig
    MultiCoinGridController = controller_mod.MultiCoinGridController

    logger.info("✓ Strategy modules loaded")

except Exception as e:
    logger.error(f"❌ Failed to load strategy: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


async def main():
    """Main bot loop"""
    logger.info("\n🚀 Starting bot...")

    try:
        # Create Kraken connector using ccxt
        exchange = ccxt.kraken({
            'apiKey': os.getenv('KRAKEN_API_KEY'),
            'secret': os.getenv('KRAKEN_SECRET_KEY'),
            'enableRateLimit': True,
        })

        # Test connection
        balance = exchange.fetch_balance()
        eur_balance = balance.get('EUR', {}).get('free', 0)
        logger.info(f"✓ Connected to Kraken | Balance: €{eur_balance:.2f}")

        # Load config
        config_path = project_root / 'config' / 'multi_coin_grid.yml'
        import yaml
        with open(config_path) as f:
            config_data = yaml.safe_load(f)

        config = MultiCoinGridConfig(**config_data)
        logger.info(f"✓ Config loaded | Capital: €{config.total_amount_quote}")

        # TODO: Create connector wrapper that works with Hummingbot ControllerBase
        # This requires proper Hummingbot Application initialization

        logger.warning("\n⚠️  STANDALONE MODE NOT FULLY IMPLEMENTED")
        logger.warning("   The strategy needs Hummingbot's full application framework")
        logger.warning("   to work properly (ExecutorOrchestrator, MarketDataProvider, etc.)")
        logger.warning("\n💡 TO RUN THIS BOT:")
        logger.warning("   1. Start Hummingbot: bin/hummingbot.py")
        logger.warning("   2. Use 'import' command to load strategy")
        logger.warning("   3. Or integrate into Hummingbot scripts/ directory")

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n\n⏸️  Bot stopped by user")
        sys.exit(0)
