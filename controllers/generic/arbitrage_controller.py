from decimal import Decimal
from typing import List, Optional

import pandas as pd

from hummingbot.client.ui.interface_utils import format_df_for_printout
from hummingbot.core.data_type.common import MarketDict
from hummingbot.core.gateway.gateway_http_client import GatewayHttpClient
from hummingbot.data_feed.candles_feed.data_types import CandlesConfig
from hummingbot.strategy_v2.controllers.controller_base import ControllerBase, ControllerConfigBase
from hummingbot.strategy_v2.executors.arbitrage_executor.data_types import ArbitrageExecutorConfig
from hummingbot.strategy_v2.executors.data_types import ConnectorPair
from hummingbot.strategy_v2.models.base import RunnableStatus
from hummingbot.strategy_v2.models.executor_actions import CreateExecutorAction, ExecutorAction

try:
    from multi_coin_grid_pro.core.global_risk_manager import GlobalRiskManager, RiskLimits  # type: ignore[import]
except ImportError:
    GlobalRiskManager = None  # type: ignore
    RiskLimits = None  # type: ignore


class ArbitrageControllerConfig(ControllerConfigBase):
    controller_name: str = "arbitrage_controller"
    candles_config: List[CandlesConfig] = []
    exchange_pair_1: ConnectorPair = ConnectorPair(connector_name="binance", trading_pair="SOL-USDT")
    exchange_pair_2: ConnectorPair = ConnectorPair(connector_name="jupiter/router", trading_pair="SOL-USDC")
    min_profitability: Decimal = Decimal("0.01")
    min_profit_after_fees_pct: Decimal = Decimal("0.3")
    estimated_fee_pct: Decimal = Decimal("0.2")
    delay_between_executors: int = 10  # in seconds
    max_executors_imbalance: int = 1
    rate_connector: str = "binance"
    quote_conversion_asset: str = "USDT"
    depth_checks: bool = True
    max_capital_per_route_pct: Decimal = Decimal("5")
    risk_reference_balance_quote: Decimal = Decimal("1000")
    risk_max_daily_loss_pct: Decimal = Decimal("3")
    risk_max_balance_per_trade_pct: Decimal = Decimal("1")
    risk_max_total_open_risk_pct: Decimal = Decimal("5")
    risk_exit_cooldown_minutes: int = 5
    risk_switch_cooldown_minutes: int = 5
    risk_consecutive_loss_cooldown_minutes: int = 10

    def update_markets(self, markets: MarketDict) -> MarketDict:
        return [markets.add_or_update(cp.connector_name, cp.trading_pair) for cp in [self.exchange_pair_1, self.exchange_pair_2]][-1]

    @property
    def risk_limits(self) -> RiskLimits:
        if RiskLimits is None:
            raise RuntimeError("RiskLimits class not available")
        return RiskLimits(
            max_daily_loss_pct=self.risk_max_daily_loss_pct,
            max_balance_risk_per_trade_pct=self.risk_max_balance_per_trade_pct,
            max_total_open_risk_pct=self.risk_max_total_open_risk_pct,
            min_hold_seconds=0,
            exit_cooldown_seconds=self.risk_exit_cooldown_minutes * 60,
            symbol_switch_cooldown_seconds=self.risk_switch_cooldown_minutes * 60,
            consecutive_loss_cooldown_seconds=self.risk_consecutive_loss_cooldown_minutes * 60,
        )

    @property
    def risk_reference_balance(self) -> Decimal:
        return self.risk_reference_balance_quote


class ArbitrageController(ControllerBase):
    def __init__(self, config: ArbitrageControllerConfig, *args, **kwargs):
        self.config = config
        super().__init__(config, *args, **kwargs)
        self._imbalance = 0
        self._last_buy_closed_timestamp = 0
        self._last_sell_closed_timestamp = 0
        self._len_active_buy_arbitrages = 0
        self._len_active_sell_arbitrages = 0
        self.base_asset = self.config.exchange_pair_1.trading_pair.split("-")[0]
        self._gas_token_cache = {}  # Cache for gas tokens by connector
        self._initialize_gas_tokens()  # Fetch gas tokens during init
        self.initialize_rate_sources()
        if GlobalRiskManager is None:
            raise RuntimeError("GlobalRiskManager not available for arbitrage controller.")
        self.risk_manager = GlobalRiskManager(
            reference_balance_quote=self.config.risk_reference_balance,
            limits=self.config.risk_limits,
        )
        self._tracked_executor_notional: Dict[str, Decimal] = {}

    def initialize_rate_sources(self):
        rates_required = []
        for connector_pair in [self.config.exchange_pair_1, self.config.exchange_pair_2]:
            base, quote = connector_pair.trading_pair.split("-")

            # Add rate source for gas token if it's an AMM connector
            if connector_pair.is_amm_connector():
                gas_token = self.get_gas_token(connector_pair.connector_name)
                if gas_token and gas_token != quote:
                    rates_required.append(ConnectorPair(connector_name=self.config.rate_connector,
                                                        trading_pair=f"{gas_token}-{quote}"))

            # Add rate source for quote conversion asset
            if quote != self.config.quote_conversion_asset:
                rates_required.append(ConnectorPair(connector_name=self.config.rate_connector,
                                                    trading_pair=f"{quote}-{self.config.quote_conversion_asset}"))

            # Add rate source for trading pairs
            rates_required.append(ConnectorPair(connector_name=connector_pair.connector_name,
                                                trading_pair=connector_pair.trading_pair))
        if len(rates_required) > 0:
            self.market_data_provider.initialize_rate_sources(rates_required)

    def _initialize_gas_tokens(self):
        """Initialize gas tokens for AMM connectors during controller initialization."""
        import asyncio

        async def fetch_gas_tokens():
            for connector_pair in [self.config.exchange_pair_1, self.config.exchange_pair_2]:
                if connector_pair.is_amm_connector():
                    connector_name = connector_pair.connector_name
                    if connector_name not in self._gas_token_cache:
                        try:
                            gateway_client = GatewayHttpClient.get_instance()

                            # Get chain and network for the connector
                            chain, network, error = await gateway_client.get_connector_chain_network(
                                connector_name
                            )

                            if error:
                                self.logger().warning(f"Failed to get chain info for {connector_name}: {error}")
                                continue

                            # Get native currency symbol
                            native_currency = await gateway_client.get_native_currency_symbol(chain, network)

                            if native_currency:
                                self._gas_token_cache[connector_name] = native_currency
                                self.logger().info(f"Gas token for {connector_name}: {native_currency}")
                            else:
                                self.logger().warning(f"Failed to get native currency for {connector_name}")
                        except Exception as e:
                            self.logger().error(f"Error getting gas token for {connector_name}: {e}")

        # Run the async function to fetch gas tokens
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.create_task(fetch_gas_tokens())
        else:
            loop.run_until_complete(fetch_gas_tokens())

    def get_gas_token(self, connector_name: str) -> Optional[str]:
        """Get the cached gas token for a connector."""
        return self._gas_token_cache.get(connector_name)

    def _sync_risk_state(self) -> None:
        if GlobalRiskManager is None:
            return
        now = self.market_data_provider.time()
        completed_ids = []
        for executor in self.executors_info:
            if executor.status == RunnableStatus.TERMINATED and executor.id in self._tracked_executor_notional:
                realised = Decimal(str(executor.net_pnl_quote))
                notional_symbol = getattr(getattr(executor, "config", None), "buying_market", None)
                symbol = getattr(notional_symbol, "trading_pair", self.base_asset)
                self.risk_manager.register_close_trade(
                    symbol=symbol,
                    realised_pnl_quote=realised,
                    now=now,
                )
                completed_ids.append(executor.id)
        for executor_id in completed_ids:
            self._tracked_executor_notional.pop(executor_id, None)

    async def update_processed_data(self):
        pass

    def determine_executor_actions(self) -> List[ExecutorAction]:
        self._sync_risk_state()
        self.update_arbitrage_stats()
        executor_actions = []
        current_time = self.market_data_provider.time()
        if self.risk_manager.daily_loss_pct >= self.config.risk_limits.max_daily_loss_pct:
            self.logger().warning(
                f"🛑 Daily loss limit reached ({self.risk_manager.daily_loss_pct:.2f}%), "
                "suspending new arbitrage executors."
            )
            return executor_actions
        if (abs(self._imbalance) >= self.config.max_executors_imbalance or
                self._last_buy_closed_timestamp + self.config.delay_between_executors > current_time or
                self._last_sell_closed_timestamp + self.config.delay_between_executors > current_time):
            return executor_actions
        if self._len_active_buy_arbitrages == 0:
            executor_actions.append(self.create_arbitrage_executor_action(self.config.exchange_pair_1,
                                                                          self.config.exchange_pair_2))
        if self._len_active_sell_arbitrages == 0:
            executor_actions.append(self.create_arbitrage_executor_action(self.config.exchange_pair_2,
                                                                          self.config.exchange_pair_1))
        return [action for action in executor_actions if action is not None]

    def create_arbitrage_executor_action(self, buying_exchange_pair: ConnectorPair,
                                         selling_exchange_pair: ConnectorPair):
        try:
            current_time = self.market_data_provider.time()
            buy_price = self.market_data_provider.get_rate(buying_exchange_pair.trading_pair)
            sell_price = self.market_data_provider.get_rate(selling_exchange_pair.trading_pair)
            if not buy_price or not sell_price:
                self.logger().debug(
                    f"⚠️  Unable to price arbitrage route "
                    f"{buying_exchange_pair.trading_pair} → {selling_exchange_pair.trading_pair}"
                )
                return None

            buy_price_dec = Decimal(str(buy_price))
            sell_price_dec = Decimal(str(sell_price))
            if buy_price_dec <= Decimal("0") or sell_price_dec <= Decimal("0"):
                self.logger().debug("⚠️  Invalid arbitrage pricing detected; skipping.")
                return None

            gross_spread_pct = float(((sell_price_dec - buy_price_dec) / buy_price_dec) * Decimal("100"))
            fee_buffer = float(self.config.estimated_fee_pct) * 2.0
            net_spread_pct = gross_spread_pct - fee_buffer
            if net_spread_pct < float(self.config.min_profit_after_fees_pct):
                self.logger().debug(
                    f"⚖️  Net profitability {net_spread_pct:.3f}% below threshold "
                    f"{self.config.min_profit_after_fees_pct}% - skipping route."
                )
                return None

            if buying_exchange_pair.is_amm_connector():
                gas_token = self.get_gas_token(buying_exchange_pair.connector_name)
                if gas_token:
                    pair = buying_exchange_pair.trading_pair.split("-")[0] + "-" + gas_token
                    gas_conversion_price = self.market_data_provider.get_rate(pair)
                else:
                    gas_conversion_price = None
            elif selling_exchange_pair.is_amm_connector():
                gas_token = self.get_gas_token(selling_exchange_pair.connector_name)
                if gas_token:
                    pair = selling_exchange_pair.trading_pair.split("-")[0] + "-" + gas_token
                    gas_conversion_price = self.market_data_provider.get_rate(pair)
                else:
                    gas_conversion_price = None
            else:
                gas_conversion_price = None

            budget_from_pct = self.config.risk_reference_balance_quote * self.config.max_capital_per_route_pct / Decimal("100")
            per_trade_cap = self.config.risk_reference_balance_quote * self.config.risk_max_balance_per_trade_pct / Decimal("100")
            requested_notional = min(budget_from_pct, per_trade_cap)
            allowed_notional = self.risk_manager.can_open_trade(
                symbol=buying_exchange_pair.trading_pair,
                requested_notional=requested_notional,
                now=current_time,
            )
            if allowed_notional is None or allowed_notional <= Decimal("0"):
                self.logger().debug("🛑 Risk manager blocked arbitrage allocation.")
                return None

            base_amount = allowed_notional / buy_price_dec
            amount_quantized = self.market_data_provider.quantize_order_amount(
                buying_exchange_pair.connector_name,
                buying_exchange_pair.trading_pair,
                base_amount,
            )
            if amount_quantized <= Decimal("0"):
                self.logger().debug("⚠️  Quantized arbitrage amount is zero after risk adjustment.")
                return None

            applied_notional = Decimal(str(amount_quantized)) * buy_price_dec

            arbitrage_config = ArbitrageExecutorConfig(
                timestamp=current_time,
                buying_market=buying_exchange_pair,
                selling_market=selling_exchange_pair,
                order_amount=amount_quantized,
                min_profitability=self.config.min_profitability,
                gas_conversion_price=gas_conversion_price,
            )
            action = CreateExecutorAction(
                executor_config=arbitrage_config,
                controller_id=self.config.id)
            self.risk_manager.register_open_trade(
                symbol=buying_exchange_pair.trading_pair,
                notional=applied_notional,
                now=current_time,
            )
            self._tracked_executor_notional[arbitrage_config.id] = applied_notional
            return action
        except Exception as e:
            self.logger().error(
                f"Error creating executor to buy on {buying_exchange_pair.connector_name} and sell on {selling_exchange_pair.connector_name}, {e}")

    def update_arbitrage_stats(self):
        closed_executors = [e for e in self.executors_info if e.status == RunnableStatus.TERMINATED]
        active_executors = [e for e in self.executors_info if e.status != RunnableStatus.TERMINATED]
        buy_arbitrages = [arbitrage for arbitrage in closed_executors if
                          arbitrage.config.buying_market == self.config.exchange_pair_1]
        sell_arbitrages = [arbitrage for arbitrage in closed_executors if
                           arbitrage.config.buying_market == self.config.exchange_pair_2]
        self._imbalance = len(buy_arbitrages) - len(sell_arbitrages)
        self._last_buy_closed_timestamp = max([arbitrage.close_timestamp for arbitrage in buy_arbitrages]) if len(
            buy_arbitrages) > 0 else 0
        self._last_sell_closed_timestamp = max([arbitrage.close_timestamp for arbitrage in sell_arbitrages]) if len(
            sell_arbitrages) > 0 else 0
        self._len_active_buy_arbitrages = len([arbitrage for arbitrage in active_executors if
                                               arbitrage.config.buying_market == self.config.exchange_pair_1])
        self._len_active_sell_arbitrages = len([arbitrage for arbitrage in active_executors if
                                                arbitrage.config.buying_market == self.config.exchange_pair_2])

    def to_format_status(self) -> List[str]:
        all_executors_custom_info = pd.DataFrame(e.custom_info for e in self.executors_info)
        return [format_df_for_printout(all_executors_custom_info, table_format="psql", )]
