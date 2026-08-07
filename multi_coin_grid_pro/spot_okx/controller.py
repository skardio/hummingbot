"""
OKX SPOT Grid Controller

Extends MultiCoinGridController with OKX spot-specific logic:
- No leverage/margin
- USD pair names with USDC wallet balance support
- OKX fee structure (0.08% maker / 0.10% taker at VIP0)
- Rate limiting for OKX API
"""

from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
from multi_coin_grid_pro.spot_okx.config_schema import SpotGridOKXConfig


class SpotGridOKXController(MultiCoinGridController):
    """
    Controller for OKX SPOT grid trading.

    Inherits all base functionality from MultiCoinGridController and adds:
    - OKX-specific rate limiting
    - USD pair filtering
    - Spot-specific risk management (no liquidation)
    """

    def __init__(self, config: SpotGridOKXConfig, **kwargs):
        """
        Initialize OKX SPOT controller

        Args:
            config: SpotGridOKXConfig with OKX parameters
            **kwargs: Additional arguments passed to parent (connectors, market_data_provider, etc.)
        """
        super().__init__(config=config, **kwargs)
        self.config: SpotGridOKXConfig = config

        # Initialize trends dict (required for volatility-adjusted sizing)
        self.trends = {}

        self.logger().info("=" * 80)
        self.logger().info("  OKX SPOT GRID CONTROLLER INITIALIZED")
        self.logger().info("=" * 80)
        self.logger().info("  Exchange: OKX SPOT")
        self.logger().info(f"  Quote Asset: {config.quote_asset}")
        self.logger().info(f"  Capital: {config.total_amount_quote} {config.quote_asset}")
        self.logger().info(f"  Trading Pairs: {len(config.manual_trading_pairs)}")
        self.logger().info(f"  Grid Levels: {config.num_grids}")
        self.logger().info(f"  Order Size: {config.min_order_amount_quote} {config.quote_asset}")
        self.logger().info("=" * 80)

    def _validate_trading_pair(self, trading_pair: str) -> bool:
        """
        Validate if trading pair is suitable for OKX SPOT.

        Args:
            trading_pair: Trading pair (e.g., "BTC-USDT")

        Returns:
            True if valid for OKX spot
        """
        # OKX spot: only USDT pairs
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
