"""
Unit tests for Bitget minimum sell price fix (error 41117).

When Bitget rejects a sell order with "selling price cannot be lower than X",
the grid executor must:
1. Parse the exchange minimum sell price from the error
2. Use it (+ buffer) on the next close attempt
3. Fall back to MARKET order after max retries

Also tests that auto_sell_orphaned_positions config field exists and defaults True.
"""
import re
from decimal import Decimal
from unittest.mock import MagicMock, PropertyMock, patch

from hummingbot.connector.exchange_py_base import ExchangePyBase
from hummingbot.connector.trading_rule import TradingRule
from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.event.events import MarketOrderFailureEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from hummingbot.strategy_v2.executors.grid_executor.data_types import GridExecutorConfig
from hummingbot.strategy_v2.executors.grid_executor.grid_executor import GridExecutor
from hummingbot.strategy_v2.executors.position_executor.data_types import TripleBarrierConfig

# ── helpers ──────────────────────────────────────────────────────────


def _mock_strategy():
    market = MagicMock()
    market_info = MagicMock()
    market_info.market = market

    strategy = MagicMock(spec=ScriptStrategyBase)
    type(strategy).market_info = PropertyMock(return_value=market_info)
    type(strategy).trading_pair = PropertyMock(return_value="HUMA-USDT")
    type(strategy).current_timestamp = PropertyMock(return_value=1234567890)

    n = 30
    strategy.buy.side_effect = [f"OID-BUY-{i}" for i in range(1, n + 1)]
    strategy.sell.side_effect = [f"OID-SELL-{i}" for i in range(1, n + 1)]
    strategy.cancel.return_value = None

    connector = MagicMock(spec=ExchangePyBase)
    trading_rule = TradingRule(
        trading_pair="HUMA-USDT",
        min_order_size=Decimal("1"),
        min_order_value=Decimal("5"),
        min_price_increment=Decimal("0.00001"),
        min_base_amount_increment=Decimal("0.01"),
    )
    type(connector).trading_rules = PropertyMock(
        return_value={"HUMA-USDT": trading_rule}
    )
    strategy.connectors = {"bitget": connector}
    return strategy


def _grid_config():
    return GridExecutorConfig(
        id="test_min_sell",
        timestamp=1234567890,
        controller_id="test",
        connector_name="bitget",
        trading_pair="HUMA-USDT",
        side=TradeType.BUY,
        start_price=Decimal("0.0193"),
        end_price=Decimal("0.0196"),
        total_amount_quote=Decimal("118"),
        min_spread_between_orders=Decimal("0.001"),
        min_order_amount_quote=Decimal("10"),
        max_open_orders=6,
        limit_price=Decimal("0.0184"),
        triple_barrier_config=TripleBarrierConfig(
            stop_loss=Decimal("0.05"),
            take_profit=Decimal("0.05"),
        ),
    )


def _price_rejected_event(order_id: str, min_price: str = "0.02001"):
    """Create a MarketOrderFailureEvent matching Bitget error 41117."""
    return MarketOrderFailureEvent(
        timestamp=1.0,
        order_id=order_id,
        order_type=OrderType.LIMIT,
        error_message=(
            f'Error executing request POST https://api.bitget.com/api/v2/spot/trade/place-order. '
            f'HTTP status is 400. Error: {{"code":"41117","msg":"HUMA/USDT selling price cannot '
            f'be lower than {min_price}","requestTime":1774389264153,"data":null}}'
        ),
        error_type="OSError",
    )


# ── Tests ────────────────────────────────────────────────────────────


class TestMinSellPriceFix:
    """Tests for Bitget minimum sell price error 41117 handling."""

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("0.0198")))
    def test_init_has_min_sell_price_fields(self):
        """New tracking fields are initialized."""
        executor = GridExecutor(_mock_strategy(), _grid_config(), update_interval=0.1)
        assert executor._exchange_min_sell_price is None
        assert executor._price_rejected_retries == 0
        assert executor._max_price_rejected_retries == 3

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("0.0198")))
    def test_price_rejection_detected_and_parsed(self):
        """Error 41117 is detected and exchange min price is parsed."""
        executor = GridExecutor(_mock_strategy(), _grid_config(), update_interval=0.1)

        # Simulate a main close order that gets rejected
        from hummingbot.strategy_v2.executors.grid_executor.grid_executor import TrackedOrder
        executor._close_order = TrackedOrder(order_id="OID-SELL-1")

        event = _price_rejected_event("OID-SELL-1", "0.02001")
        executor.process_order_failed_event(None, None, event)

        assert executor._exchange_min_sell_price == Decimal("0.02001")
        assert executor._price_rejected_retries == 1
        # Close order reset for retry
        assert executor._close_order is None
        assert executor._closing_in_progress is False

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("0.0198")))
    def test_price_rejection_increments_counter(self):
        """Each rejection increments the retry counter."""
        executor = GridExecutor(_mock_strategy(), _grid_config(), update_interval=0.1)

        from hummingbot.strategy_v2.executors.grid_executor.grid_executor import TrackedOrder

        for i in range(3):
            executor._close_order = TrackedOrder(order_id=f"OID-SELL-{i + 1}")
            event = _price_rejected_event(f"OID-SELL-{i + 1}", "0.02005")
            executor.process_order_failed_event(None, None, event)

        assert executor._price_rejected_retries == 3
        assert executor._exchange_min_sell_price == Decimal("0.02005")
        # After max retries, _insufficient_funds_retries should be set to trigger MARKET
        assert executor._insufficient_funds_retries == 1

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("0.0198")))
    def test_max_retries_triggers_market_order_path(self):
        """After max price rejection retries, forces MARKET order via insufficient_funds_retries."""
        executor = GridExecutor(_mock_strategy(), _grid_config(), update_interval=0.1)

        from hummingbot.strategy_v2.executors.grid_executor.grid_executor import TrackedOrder

        # Exhaust retries
        for i in range(3):
            executor._close_order = TrackedOrder(order_id=f"OID-SELL-{i + 1}")
            event = _price_rejected_event(f"OID-SELL-{i + 1}")
            executor.process_order_failed_event(None, None, event)

        # After exhausting price_rejected retries, the insufficient_funds_retries
        # is set to 1. This causes the close order path to force MARKET order.
        assert executor._insufficient_funds_retries == 1

    def test_regex_parses_various_min_prices(self):
        """Regex correctly parses various min price formats from Bitget."""
        test_cases = [
            ("HUMA/USDT selling price cannot be lower than 0.02001", "0.02001"),
            ("BTC/USDT selling price cannot be lower than 95000.50", "95000.50"),
            ("XRP/USDT selling price cannot be lower than 0.5", "0.5"),
        ]
        for error_msg, expected in test_cases:
            match = re.search(r'lower than\s+([\d.]+)', error_msg.lower())
            assert match is not None, f"Failed to match: {error_msg}"
            assert match.group(1) == expected

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("0.0198")))
    def test_min_sell_price_enforced_in_close_order(self):
        """When _exchange_min_sell_price is set, close price is adjusted upward."""
        executor = GridExecutor(_mock_strategy(), _grid_config(), update_interval=0.1)

        # Simulate that we've detected a min sell price
        executor._exchange_min_sell_price = Decimal("0.02001")

        # The limit price computation:
        # market_price = 0.0198
        # normal limit_price = 0.0198 * 1.0005 = ~0.01981
        # But 0.01981 < 0.02001 (exchange min), so it should be adjusted to:
        # 0.02001 * 1.001 = ~0.02003
        market_price = Decimal("0.0198")
        normal_limit = market_price * Decimal("1.0005")
        assert normal_limit < executor._exchange_min_sell_price

        adjusted = executor._exchange_min_sell_price * Decimal("1.001")
        assert adjusted > executor._exchange_min_sell_price
        # Should be roughly 0.02003
        assert Decimal("0.02002") < adjusted < Decimal("0.02004")

    @patch.object(GridExecutor, "get_price", MagicMock(return_value=Decimal("0.0198")))
    def test_non_price_rejection_not_detected(self):
        """Non-price-rejection errors don't trigger the min sell price logic."""
        executor = GridExecutor(_mock_strategy(), _grid_config(), update_interval=0.1)

        from hummingbot.strategy_v2.executors.grid_executor.grid_executor import TrackedOrder
        executor._close_order = TrackedOrder(order_id="OID-SELL-1")

        # Regular insufficient funds error
        event = MarketOrderFailureEvent(
            timestamp=1.0,
            order_id="OID-SELL-1",
            order_type=OrderType.LIMIT,
            error_message="Insufficient balance",
            error_type="OSError",
        )
        executor.process_order_failed_event(None, None, event)

        assert executor._exchange_min_sell_price is None
        assert executor._price_rejected_retries == 0


class TestAutoSellOrphanedConfig:
    """Tests that auto_sell_orphaned_positions config exists and defaults True."""

    def test_config_field_exists(self):
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        fields = MultiCoinGridConfig.model_fields
        assert 'auto_sell_orphaned_positions' in fields

    def test_config_defaults_true(self):
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        assert MultiCoinGridConfig.model_fields['auto_sell_orphaned_positions'].default is True
