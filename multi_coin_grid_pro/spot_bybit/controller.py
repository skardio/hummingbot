"""
Bybit SPOT Grid Controller

Extends MultiCoinGridController with Bybit spot-specific logic:
- No leverage/margin
- USDT quote asset
- Bybit.eu fee structure (0.10% maker / 0.10% taker standard tier)
- LIMIT_MAKER order type supported
"""

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.spot_bybit.config_schema import SpotGridBybitConfig


class SpotGridBybitController(MultiCoinGridController):
    """
    Controller for Bybit SPOT grid trading.

    Inherits all base functionality from MultiCoinGridController.
    Bybit supports LIMIT_MAKER unlike Bitget, so no order type override needed.
    """

    def __init__(self, config: SpotGridBybitConfig, **kwargs):
        super().__init__(config=config, **kwargs)
        self.config: SpotGridBybitConfig = config

        # Initialize trends dict (required for volatility-adjusted sizing)
        self.trends = {}

        self.logger().info("=" * 80)
        self.logger().info("  BYBIT SPOT GRID CONTROLLER INITIALIZED")
        self.logger().info("=" * 80)
        self.logger().info("  Exchange: Bybit SPOT (bybit.com / bybit.eu MiCA)")
        self.logger().info(f"  Quote Asset: {config.quote_asset}")
        self.logger().info(f"  Capital: {config.total_amount_quote} {config.quote_asset}")
        self.logger().info(f"  Trading Pairs: {len(config.manual_trading_pairs)}")
        self.logger().info(f"  Grid Levels: {config.num_grids}")
        self.logger().info(f"  Order Size: {config.min_order_amount_quote} {config.quote_asset}")
        self.logger().info("=" * 80)

    def _validate_trading_pair(self, trading_pair: str) -> bool:
        """
        Validate if trading pair is suitable for Bybit SPOT.

        Args:
            trading_pair: Trading pair (e.g., "BTC-USDT")

        Returns:
            True if valid for Bybit spot
        """
        # Bybit spot: only USDT pairs
        if not trading_pair.endswith(f"-{self.config.quote_asset}"):
            self.logger().warning(
                f"⚠️  {trading_pair}: Not a {self.config.quote_asset} pair, skipping"
            )
            return False

        # Exclude stablecoin pairs (no grid trading on stable-stable)
        base = trading_pair.split("-")[0]
        stablecoins = {"USDC", "BUSD", "DAI", "TUSD", "FDUSD", "USDT"}
        if base in stablecoins:
            return False

        return True
