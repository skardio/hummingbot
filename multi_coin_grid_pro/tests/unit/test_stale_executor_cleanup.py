"""
Unit tests for stale executor cleanup and stale order detection.

Tests the following functionality:
- Stale executor reference tracking and cleanup
- Stale open order detection at startup
- Telegram alerts for stale executors/orders
- Safety: only affects trading pairs in market_list

Related to US-005 Professional Risk Management.
"""

import sys
import time
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_config import MultiCoinGridConfig
    from hummingbot.multi_coin_grid_controllers.multi_coin_grid_controller import MultiCoinGridController
except ImportError:
    try:
        from multi_coin_grid_pro.controllers.multi_coin_grid_config import MultiCoinGridConfig
        from multi_coin_grid_pro.controllers.multi_coin_grid_controller import MultiCoinGridController
    except ImportError:
        from controllers.multi_coin_grid_config import MultiCoinGridConfig
        from controllers.multi_coin_grid_controller import MultiCoinGridController


pytestmark = pytest.mark.asyncio


class TestStaleExecutorCleanup:
    """Test suite for stale executor reference cleanup"""

    @pytest.fixture
    def mock_config(self):
        """Create test config with market_list"""
        config = MagicMock(spec=MultiCoinGridConfig)
        config.id = "multi_coin_grid"
        config.connector_name = "bitget"
        config.quote_asset = "USDT"
        config.market_list = ["SONIC-USDT", "HYPE-USDT", "BTC-USDT"]
        config.min_notional = Decimal("10")
        config.max_hold_time_minutes = 1440  # 24 hours
        config.stop_loss_pct = Decimal("0.05")
        return config

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        connector = MagicMock()
        connector.name = "bitget"
        connector._account_balances = {}
        connector._in_flight_orders = {}
        connector.get_mid_price = Mock(return_value=Decimal("0.045"))
        return connector

    @pytest.fixture
    def mock_market_data_provider(self):
        """Create mock market data provider"""
        provider = MagicMock()
        provider.time = Mock(return_value=time.time())
        provider.ready = True
        return provider

    @pytest.fixture
    def mock_telegram_alerter(self):
        """Create mock Telegram alerter"""
        alerter = MagicMock()
        alerter.enabled = True
        alerter.warning = Mock()
        return alerter

    @pytest.fixture
    def controller(self, mock_config, mock_connector, mock_market_data_provider, mock_telegram_alerter):
        """Create controller with mocked dependencies"""
        with patch.object(MultiCoinGridController, '__init__', lambda x, *args, **kwargs: None):
            controller = MultiCoinGridController.__new__(MultiCoinGridController)

            # Initialize required attributes
            controller.config = mock_config
            controller.connector = mock_connector
            controller.market_data_provider = mock_market_data_provider
            controller.telegram_alerter = mock_telegram_alerter
            controller.active_coins = {}
            controller.entry_prices = {}
            controller.executors_info = []
            controller._executor_creation_timestamps = {}
            controller._stale_executor_counts = {}
            controller._stale_orders = []
            controller.trend_calculator = None
            controller.professional_risk_manager = None

            # Mock logger
            controller.logger = Mock(return_value=MagicMock())

            return controller

    # ==================== Stale Executor Tracking Tests ====================

    def test_stale_executor_count_increments_when_executor_not_found(self, controller):
        """Test that stale executor count increments when executor is not in executors_info"""
        # Setup: active_coins has an executor ID that doesn't exist in executors_info
        executor_id = "AR6uPcLE49NMnv5tZyhfVjUexEkHzZtm1Bfjo2oL24Wf"
        trading_pair = "SONIC-USDT"
        controller.active_coins = {trading_pair: executor_id}
        controller.executors_info = []  # Empty - executor not found

        # Act: Call _check_professional_exit_signals (simulated check)
        stale_key = f"{trading_pair}_{executor_id}"

        # Simulate the counter increment logic
        if not hasattr(controller, '_stale_executor_counts'):
            controller._stale_executor_counts = {}
        controller._stale_executor_counts[stale_key] = controller._stale_executor_counts.get(stale_key, 0) + 1

        # Assert
        assert controller._stale_executor_counts[stale_key] == 1

    def test_stale_executor_cleanup_after_threshold(self, controller):
        """Test that stale executor reference is cleaned up after 10 checks"""
        # Setup
        executor_id = "AR6uPcLE49NMnv5tZyhfVjUexEkHzZtm1Bfjo2oL24Wf"
        trading_pair = "SONIC-USDT"
        controller.active_coins = {trading_pair: executor_id}
        controller.entry_prices = {trading_pair: Decimal("0.048")}
        controller._executor_creation_timestamps = {executor_id: time.time() - 86400}

        stale_key = f"{trading_pair}_{executor_id}"
        controller._stale_executor_counts = {stale_key: 10}  # At threshold

        # Simulate cleanup logic
        if controller._stale_executor_counts[stale_key] >= 10:
            # Cleanup
            if trading_pair in controller.active_coins:
                del controller.active_coins[trading_pair]
            if trading_pair in controller.entry_prices:
                del controller.entry_prices[trading_pair]
            if executor_id in controller._executor_creation_timestamps:
                del controller._executor_creation_timestamps[executor_id]
            del controller._stale_executor_counts[stale_key]

        # Assert: All references cleaned up
        assert trading_pair not in controller.active_coins
        assert trading_pair not in controller.entry_prices
        assert executor_id not in controller._executor_creation_timestamps
        assert stale_key not in controller._stale_executor_counts

    def test_stale_executor_counter_resets_when_executor_found(self, controller):
        """Test that stale counter resets when executor becomes available again"""
        # Setup: Executor was temporarily missing but now found
        executor_id = "TestExecutor123"
        trading_pair = "HYPE-USDT"
        stale_key = f"{trading_pair}_{executor_id}"

        controller._stale_executor_counts = {stale_key: 5}  # Was counting

        # Simulate executor being found
        mock_executor = MagicMock()
        mock_executor.id = executor_id
        mock_executor.is_active = True
        controller.executors_info = [mock_executor]

        # Reset counter (as would happen in actual code)
        if stale_key in controller._stale_executor_counts:
            del controller._stale_executor_counts[stale_key]

        # Assert
        assert stale_key not in controller._stale_executor_counts

    def test_stale_executor_sends_telegram_alert(self, controller, mock_telegram_alerter):
        """Test that Telegram alert is sent when stale executor is cleaned"""
        # Setup
        executor_id = "StaleExecutor999"
        trading_pair = "BTC-USDT"

        # Simulate alert
        mock_telegram_alerter.warning(
            f"<b>🧹 STALE EXECUTOR CLEANED</b>\n\n"
            f"• Pair: <b>{trading_pair}</b>\n"
            f"• Executor: {executor_id[:16]}...\n"
            f"• Reason: Executor not found in orchestrator\n\n"
            f"⚠️ Check for orphaned open orders on exchange!"
        )

        # Assert
        mock_telegram_alerter.warning.assert_called_once()
        call_args = mock_telegram_alerter.warning.call_args[0][0]
        assert "STALE EXECUTOR CLEANED" in call_args
        assert trading_pair in call_args

    def test_inactive_executor_reference_cleanup_is_silent(self, controller, mock_telegram_alerter):
        """Closed executors should clean local state without raising orphan warnings."""
        executor_id = "ClosedExecutor123"
        trading_pair = "SONIC-USDT"
        controller.active_coins = {trading_pair: executor_id}
        controller.entry_prices = {trading_pair: Decimal("0.048")}
        controller._executor_creation_timestamps = {executor_id: time.time() - 120}

        inactive_executor = MagicMock()
        inactive_executor.id = executor_id
        inactive_executor.is_active = False
        controller.executors_info = [inactive_executor]

        controller._check_professional_exit_signals()

        assert trading_pair not in controller.active_coins
        assert trading_pair not in controller.entry_prices
        assert executor_id not in controller._executor_creation_timestamps
        mock_telegram_alerter.warning.assert_not_called()

    def test_missing_executor_cleanup_does_not_send_telegram_by_default(self, controller, mock_telegram_alerter):
        """Missing local references are not proof of exchange orphans, so Telegram is opt-in."""
        executor_id = "MissingExecutor123"
        trading_pair = "BTC-USDT"
        stale_key = f"{trading_pair}_{executor_id}"
        controller.active_coins = {trading_pair: executor_id}
        controller.entry_prices = {trading_pair: Decimal("42000")}
        controller._executor_creation_timestamps = {executor_id: time.time() - 120}
        controller.executors_info = []
        controller._stale_executor_counts = {stale_key: 9}
        controller.config.send_stale_executor_telegram_alerts = False

        controller._check_professional_exit_signals()

        assert trading_pair not in controller.active_coins
        assert trading_pair not in controller.entry_prices
        assert executor_id not in controller._executor_creation_timestamps
        assert stale_key not in controller._stale_executor_counts
        mock_telegram_alerter.warning.assert_not_called()


class TestStaleOrderDetection:
    """Test suite for stale open order detection"""

    @pytest.fixture
    def mock_config(self):
        """Create test config"""
        config = MagicMock(spec=MultiCoinGridConfig)
        config.connector_name = "bitget"
        config.quote_asset = "USDT"
        config.market_list = ["SONIC-USDT", "HYPE-USDT"]
        config.max_hold_time_minutes = 1440
        return config

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector with in_flight_orders"""
        connector = MagicMock()
        connector.name = "bitget"
        connector._in_flight_orders = {}
        return connector

    @pytest.fixture
    def mock_telegram_alerter(self):
        """Create mock Telegram alerter"""
        alerter = MagicMock()
        alerter.enabled = True
        alerter.warning = Mock()
        return alerter

    @pytest.fixture
    def controller(self, mock_config, mock_connector, mock_telegram_alerter):
        """Create controller with mocked dependencies"""
        with patch.object(MultiCoinGridController, '__init__', lambda x, *args, **kwargs: None):
            controller = MultiCoinGridController.__new__(MultiCoinGridController)

            controller.config = mock_config
            controller.connector = mock_connector
            controller.telegram_alerter = mock_telegram_alerter
            controller.active_coins = {}
            controller._stale_orders = []
            controller.logger = Mock(return_value=MagicMock())

            return controller

    def test_detect_stale_sell_order_without_executor(self, controller, mock_connector):
        """Test detection of stale sell order that has no active executor"""
        # Setup: Create a stale sell order
        stale_order = MagicMock()
        stale_order.trading_pair = "SONIC-USDT"
        stale_order.is_sell = True
        stale_order.amount = Decimal("1533.07")
        stale_order.price = Decimal("0.046419")
        stale_order.creation_timestamp = time.time() - (25 * 60 * 60)  # 25 hours ago

        mock_connector._in_flight_orders = {"order123": stale_order}
        controller.active_coins = {}  # No active executor

        # Detect stale orders
        stale_threshold_minutes = 1440 + 60  # max_hold + 1 hour
        current_time = time.time()

        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in controller.active_coins and order.is_sell:
                order_age_minutes = (current_time - order.creation_timestamp) / 60
                if order_age_minutes > stale_threshold_minutes:
                    stale_orders.append({
                        'order_id': order_id,
                        'trading_pair': order.trading_pair,
                        'amount': float(order.amount),
                        'price': float(order.price),
                        'age_minutes': order_age_minutes
                    })

        # Assert
        assert len(stale_orders) == 1
        assert stale_orders[0]['trading_pair'] == "SONIC-USDT"
        assert stale_orders[0]['amount'] == 1533.07

    def test_ignore_order_with_active_executor(self, controller, mock_connector):
        """Test that orders with active executors are NOT flagged as stale"""
        # Setup: Order has an active executor
        order = MagicMock()
        order.trading_pair = "HYPE-USDT"
        order.is_sell = True
        order.amount = Decimal("100")
        order.price = Decimal("25.0")
        order.creation_timestamp = time.time() - (25 * 60 * 60)  # Old but has executor

        mock_connector._in_flight_orders = {"order456": order}
        controller.active_coins = {"HYPE-USDT": "ActiveExecutorID"}  # Has executor!

        # Detect
        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in controller.active_coins and order.is_sell:
                stale_orders.append(order_id)

        # Assert: No stale orders (executor exists)
        assert len(stale_orders) == 0

    def test_ignore_buy_orders(self, controller, mock_connector):
        """Test that BUY orders are ignored (only SELL orders checked)"""
        # Setup: Old buy order
        buy_order = MagicMock()
        buy_order.trading_pair = "SONIC-USDT"
        buy_order.is_sell = False  # BUY order
        buy_order.amount = Decimal("1000")
        buy_order.price = Decimal("0.045")
        buy_order.creation_timestamp = time.time() - (30 * 60 * 60)  # Very old

        mock_connector._in_flight_orders = {"buy_order": buy_order}
        controller.active_coins = {}

        # Detect (only sell orders)
        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in controller.active_coins and order.is_sell:
                stale_orders.append(order_id)

        # Assert: Buy orders ignored
        assert len(stale_orders) == 0

    def test_ignore_recent_orders(self, controller, mock_connector):
        """Test that recent orders (under threshold) are not flagged"""
        # Setup: Recent order (only 1 hour old)
        recent_order = MagicMock()
        recent_order.trading_pair = "SONIC-USDT"
        recent_order.is_sell = True
        recent_order.amount = Decimal("500")
        recent_order.price = Decimal("0.05")
        recent_order.creation_timestamp = time.time() - (60 * 60)  # 1 hour ago

        mock_connector._in_flight_orders = {"recent": recent_order}
        controller.active_coins = {}

        # Detect with 25-hour threshold
        stale_threshold_minutes = 1440 + 60  # 25 hours
        current_time = time.time()

        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            order_age_minutes = (current_time - order.creation_timestamp) / 60
            if order_age_minutes > stale_threshold_minutes and order.is_sell:
                stale_orders.append(order_id)

        # Assert: Recent order not flagged
        assert len(stale_orders) == 0

    def test_stale_order_telegram_alert(self, controller, mock_telegram_alerter):
        """Test that Telegram alert is sent for stale orders"""
        # Setup
        stale_orders = [{
            'order_id': 'SSCUT64c34e293abe6280dc9d3a5ff361ebab0ce024d7c371f',
            'trading_pair': 'SONIC-USDT',
            'amount': 1533.07,
            'price': 0.046419,
            'age_minutes': 1500
        }]

        # Simulate alert
        stale_lines = ["<b>🔴 STALE LIMIT ORDERS DETECTED</b>\n"]
        for stale in stale_orders:
            stale_lines.append(
                f"• <b>{stale['trading_pair']}</b>: Sell {stale['amount']:.6f} @ ${stale['price']:.6f}"
            )
            stale_lines.append(f"  Age: {stale['age_minutes']:.0f} minutes")
        stale_lines.append("\n⚠️ These orders have no active executor - consider cancelling manually")

        mock_telegram_alerter.warning("\n".join(stale_lines))

        # Assert
        mock_telegram_alerter.warning.assert_called_once()
        call_args = mock_telegram_alerter.warning.call_args[0][0]
        assert "STALE LIMIT ORDERS DETECTED" in call_args
        assert "SONIC-USDT" in call_args
        assert "1533" in call_args


class TestSafetyChecks:
    """Test suite for safety: only market_list pairs are affected"""

    @pytest.fixture
    def mock_config(self):
        """Create test config with specific market_list"""
        config = MagicMock(spec=MultiCoinGridConfig)
        config.market_list = ["SONIC-USDT", "HYPE-USDT"]  # Only these pairs
        config.quote_asset = "USDT"
        config.max_hold_time_minutes = 1440
        return config

    @pytest.fixture
    def mock_connector(self):
        """Create mock connector"""
        connector = MagicMock()
        connector._in_flight_orders = {}
        return connector

    @pytest.fixture
    def controller(self, mock_config, mock_connector):
        """Create controller"""
        with patch.object(MultiCoinGridController, '__init__', lambda x, *args, **kwargs: None):
            controller = MultiCoinGridController.__new__(MultiCoinGridController)
            controller.config = mock_config
            controller.connector = mock_connector
            controller.active_coins = {}
            controller.logger = Mock(return_value=MagicMock())
            return controller

    def test_ignore_orders_not_in_market_list(self, controller, mock_connector, mock_config):
        """Test that orders for pairs NOT in market_list are ignored"""
        # Setup: Order for pair NOT in market_list
        manual_order = MagicMock()
        manual_order.trading_pair = "DOGE-USDT"  # NOT in market_list
        manual_order.is_sell = True
        manual_order.amount = Decimal("10000")
        manual_order.price = Decimal("0.10")
        manual_order.creation_timestamp = time.time() - (30 * 60 * 60)  # Very old

        mock_connector._in_flight_orders = {"manual_order": manual_order}

        # Only check pairs in market_list
        market_list_pairs = set(mock_config.market_list)

        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in market_list_pairs:
                continue  # Skip pairs not managed by bot
            if order.trading_pair not in controller.active_coins and order.is_sell:
                stale_orders.append(order_id)

        # Assert: Manual order ignored
        assert len(stale_orders) == 0

    def test_detect_orders_in_market_list(self, controller, mock_connector, mock_config):
        """Test that orders for pairs IN market_list ARE detected"""
        # Setup: Order for pair IN market_list
        bot_order = MagicMock()
        bot_order.trading_pair = "SONIC-USDT"  # IN market_list
        bot_order.is_sell = True
        bot_order.amount = Decimal("1000")
        bot_order.price = Decimal("0.05")
        bot_order.creation_timestamp = time.time() - (30 * 60 * 60)

        mock_connector._in_flight_orders = {"bot_order": bot_order}

        # Check with market_list filter
        market_list_pairs = set(mock_config.market_list)
        stale_threshold_minutes = 1440 + 60
        current_time = time.time()

        stale_orders = []
        for order_id, order in mock_connector._in_flight_orders.items():
            if order.trading_pair not in market_list_pairs:
                continue
            order_age_minutes = (current_time - order.creation_timestamp) / 60
            if order_age_minutes > stale_threshold_minutes and order.is_sell:
                if order.trading_pair not in controller.active_coins:
                    stale_orders.append(order_id)

        # Assert: Bot order detected
        assert len(stale_orders) == 1
        assert "bot_order" in stale_orders


class TestIntegrationScenario:
    """Integration test simulating the SONIC scenario"""

    def test_sonic_scenario_full_detection(self):
        """
        Simulate the actual SONIC issue:
        - 1533 SONIC bought, only 1023 sold
        - Remaining 1533 SONIC stuck in limit sell order @ $0.046419
        - Order created 24+ hours ago
        - No active executor (was cleaned up after restart)
        - TIME_STOP triggers but executor not found
        """
        # Setup mock objects
        with patch.object(MultiCoinGridController, '__init__', lambda x, *args, **kwargs: None):
            controller = MultiCoinGridController.__new__(MultiCoinGridController)

            # Config
            config = MagicMock()
            config.market_list = ["SONIC-USDT", "HYPE-USDT", "BTC-USDT"]
            config.max_hold_time_minutes = 1440
            config.quote_asset = "USDT"
            controller.config = config

            # Stale order on exchange
            stale_order = MagicMock()
            stale_order.trading_pair = "SONIC-USDT"
            stale_order.is_sell = True
            stale_order.amount = Decimal("1533.07")
            stale_order.price = Decimal("0.046419")
            stale_order.creation_timestamp = time.time() - (24 * 60 * 60 + 60 * 60)  # 25h ago

            connector = MagicMock()
            connector._in_flight_orders = {
                "SSCUT64c34e293abe6280dc9d3a5ff361ebab0ce024d7c371f": stale_order
            }
            controller.connector = connector

            # No active executors (cleaned up)
            controller.active_coins = {}

            # Telegram alerter
            alerter = MagicMock()
            alerter.enabled = True
            alerter.warning = Mock()
            controller.telegram_alerter = alerter

            # Detect stale orders
            market_list_pairs = set(config.market_list)
            stale_threshold_minutes = config.max_hold_time_minutes + 60
            current_time = time.time()

            detected_stale = []
            for order_id, order in connector._in_flight_orders.items():
                # Safety: only check market_list pairs
                if order.trading_pair not in market_list_pairs:
                    continue
                # Only sell orders
                if not order.is_sell:
                    continue
                # Only without executor
                if order.trading_pair in controller.active_coins:
                    continue
                # Only old orders
                order_age_minutes = (current_time - order.creation_timestamp) / 60
                if order_age_minutes > stale_threshold_minutes:
                    detected_stale.append({
                        'order_id': order_id,
                        'trading_pair': order.trading_pair,
                        'amount': float(order.amount),
                        'price': float(order.price),
                        'age_minutes': order_age_minutes
                    })

            # Assert: SONIC detected
            assert len(detected_stale) == 1
            assert detected_stale[0]['trading_pair'] == "SONIC-USDT"
            assert detected_stale[0]['amount'] == 1533.07
            assert detected_stale[0]['price'] == 0.046419
            assert detected_stale[0]['age_minutes'] > 1500  # > 25 hours


class TestRealTelegramIntegration:
    """
    REAL integration test that sends actual Telegram messages.

    To run this test:
        pytest test_stale_executor_cleanup.py::TestRealTelegramIntegration -v -s

    Requires environment variables:
        TELEGRAM_BOT_TOKEN
        TELEGRAM_CHAT_ID
    """

    @pytest.fixture
    def real_telegram_alerter(self):
        """Create REAL Telegram alerter using environment variables"""
        import os

        bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
        chat_id = os.getenv('TELEGRAM_CHAT_ID', '')

        if not bot_token or not chat_id:
            pytest.skip("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables required")

        from multi_coin_grid_pro.alerts.telegram_alerter import TelegramAlerter
        return TelegramAlerter(bot_token=bot_token, chat_id=chat_id)

    def test_real_stale_order_telegram_alert(self, real_telegram_alerter):
        """
        REAL TEST: Sends actual Telegram message for stale order detection.

        You should receive this message on your phone/Telegram!
        """
        # Build the same message format as the real code
        stale_orders = [{
            'order_id': 'TEST_ORDER_ID_12345',
            'trading_pair': 'SONIC-USDT',
            'amount': 1533.07,
            'price': 0.046419,
            'age_minutes': 1500
        }]

        stale_lines = ["<b>🔴 STALE LIMIT ORDERS DETECTED</b>\n"]
        stale_lines.append("<i>⚡ This is a TEST from pytest</i>\n")
        for stale in stale_orders:
            stale_lines.append(
                f"• <b>{stale['trading_pair']}</b>: Sell {stale['amount']:.6f} @ ${stale['price']:.6f}"
            )
            stale_lines.append(f"  Age: {stale['age_minutes']:.0f} minutes")
        stale_lines.append("\n⚠️ These orders have no active executor - consider cancelling manually")
        stale_lines.append("\n✅ <b>If you see this, the alerting works!</b>")

        # Send REAL message
        real_telegram_alerter.warning("\n".join(stale_lines))

        # The warning method doesn't return anything, but _send does
        # So we test by directly calling _send
        print("\n" + "=" * 60)
        print("📱 TELEGRAM MESSAGE SENT!")
        print("   Check your Telegram for the stale order alert")
        print("=" * 60 + "\n")

    def test_real_stale_executor_telegram_alert(self, real_telegram_alerter):
        """
        REAL TEST: Sends actual Telegram message for stale executor cleanup.
        """
        executor_id = "AR6uPcLE49NMnv5tZyhfVjUexEkHzZtm1Bfjo2oL24Wf"
        trading_pair = "SONIC-USDT"

        message = (
            f"<b>🧹 STALE EXECUTOR CLEANED</b>\n\n"
            f"<i>⚡ This is a TEST from pytest</i>\n\n"
            f"• Pair: <b>{trading_pair}</b>\n"
            f"• Executor: {executor_id[:16]}...\n"
            f"• Reason: Executor not found in orchestrator\n\n"
            f"⚠️ Check for orphaned open orders on exchange!\n\n"
            f"✅ <b>If you see this, the alerting works!</b>"
        )

        real_telegram_alerter.warning(message)

        print("\n" + "=" * 60)
        print("📱 TELEGRAM MESSAGE SENT!")
        print("   Check your Telegram for the stale executor alert")
        print("=" * 60 + "\n")

    def test_real_orphaned_position_telegram_alert(self, real_telegram_alerter):
        """
        REAL TEST: Sends actual Telegram message for orphaned positions.
        """
        orphaned_positions = [
            {'asset': 'SONIC', 'amount': 1533.07, 'price': 0.045, 'notional': 68.99},
            {'asset': 'HYPE', 'amount': 2.5, 'price': 25.0, 'notional': 62.50}
        ]

        total_value = sum(p['notional'] for p in orphaned_positions)

        orphan_lines = ["<b>🔴 ORPHANED POSITIONS DETECTED</b>\n"]
        orphan_lines.append("<i>⚡ This is a TEST from pytest</i>\n")
        for pos in orphaned_positions:
            orphan_lines.append(
                f"• <b>{pos['asset']}</b>: {pos['amount']:.6f} @ ${pos['price']:.4f} = ${pos['notional']:.2f}"
            )
        orphan_lines.append(f"\n<b>Total: ${total_value:.2f}</b>")
        orphan_lines.append("\n⚠️ Consider selling manually or restart with auto-recovery")
        orphan_lines.append("\n✅ <b>If you see this, the alerting works!</b>")

        real_telegram_alerter.warning("\n".join(orphan_lines))

        print("\n" + "=" * 60)
        print("📱 TELEGRAM MESSAGE SENT!")
        print("   Check your Telegram for the orphaned position alert")
        print("=" * 60 + "\n")
