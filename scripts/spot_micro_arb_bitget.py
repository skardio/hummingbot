"""
Changelog (micro-arb hardening)
- Add orderbook caching per tick to avoid repeated snapshots per symbol
- Handle partial fills (buy/sell) with position accounting and dust threshold
- Maker-only guard with fast-fill detection and spread shrink cancel
- Refined timeouts: distinct cancel cooldown and force-exit cooldown
- Decision logging with block reasons and trade summary
- Cancel throttling and inventory breach safety (force exit + disable window)

Bitget SPOT micro-arbitrage bot (maker-first, ultra-short lifecycle).

Environment overrides (optional)
- MICRO_ARB_EXCHANGE=bitget or bitget_paper_trade
- MICRO_ARB_SYMBOLS=BTC-USDT,ETH-USDT
- MICRO_ARB_PAPER=true to append _paper_trade automatically
- MICRO_ARB_ORDER_USDT=10 custom order size in quote
"""
import os
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from hummingbot.core.data_type.common import OrderType, TradeType
from hummingbot.core.event.events import OrderFilledEvent
from hummingbot.strategy.script_strategy_base import ScriptStrategyBase
from multi_coin_grid_pro.spot_microarb_bitget.config_manager import MicroArbBitgetConfigManager
from multi_coin_grid_pro.spot_microarb_bitget.config_schema import MicroArbBitgetConfig


class MicroArbBitget(ScriptStrategyBase):
    # Defaults (will be overridden by YAML and env)
    exchange: str = os.getenv("MICRO_ARB_EXCHANGE", "bitget")
    use_paper: bool = os.getenv("MICRO_ARB_PAPER", "false").lower() == "true"
    # Extended default symbols matching config_schema.py
    symbols: List[str] = [s.strip() for s in os.getenv(
        "MICRO_ARB_SYMBOLS",
        "BTC-USDT,ETH-USDT,SOL-USDT,XRP-USDT,DOGE-USDT"  # Start small, dynamic discovery adds more
    ).split(",") if s.strip()]

    min_spread_pct: Decimal = Decimal("0.10")  # LOWERED from 0.35%
    maker_fee_pct: Decimal = Decimal("0.10")  # percent
    buffer_pct: Decimal = Decimal("0.02")  # LOWERED from 0.05%
    order_size_usdt: Decimal = Decimal(os.getenv("MICRO_ARB_ORDER_USDT", "50"))  # Increased to $50
    price_offset_ticks: int = 1
    maker_only: bool = True

    buy_timeout_sec: int = 3
    max_hold_sec: int = 6
    cooldown_after_trade_sec: int = 5

    min_depth_usdt: Decimal = Decimal("10000")  # LOWERED from 50000 ($10k minimum)
    volatility_block_pct_30s: Decimal = Decimal("0.30")
    max_inventory_usdt: Decimal = Decimal("200")  # INCREASED from $15 to $200

    # Dynamic symbol discovery
    auto_discover_symbols: bool = True  # If True, ignore fixed list and discover from exchange
    min_volume_24h_usdt: Decimal = Decimal("1000000")  # $1M daily volume minimum
    max_symbols: int = 50  # Max pairs to monitor
    symbol_refresh_interval_sec: int = 3600  # Refresh symbol list every hour

    order_refresh_time: int = 2
    rate_limit_buffer: Decimal = Decimal("0.8")
    log_decisions: bool = True

    cooldown_after_cancel_sec: int = 2
    cooldown_after_force_exit_sec: int = 10
    inventory_breach_cooldown_sec: int = 30
    min_cancel_interval_sec: int = 1
    dust_threshold: Decimal = Decimal("1e-8")
    log_block_reasons: bool = True
    log_trade_summary: bool = True
    log_metrics_interval_sec: int = 30

    # Initialize markets dict - auto-populated from config at import time
    # Hummingbot framework requires this as a class attribute
    @classmethod
    def _auto_init_markets(cls):
        """Auto-initialize markets - always start with config symbols, discovery expands later"""
        try:
            cfg = cls._load_config_static()
            exchange, symbols, use_paper = cls._resolve_exchange_symbols(cfg)
            # Always use explicit symbols for markets - base class needs proper trading pairs
            # Dynamic discovery works by checking connector.trading_pairs later
            return {exchange: set(symbols)}
        except Exception:
            # Fallback to minimal set if config fails
            return {"bitget": {"BTC-USDT", "ETH-USDT", "SOL-USDT"}}

    markets = {}  # Will be set below

    @classmethod
    def _load_config_static(cls) -> MicroArbBitgetConfig:
        try:
            raw = MicroArbBitgetConfigManager().load_config()
            payload = raw.get("micro_arb", raw)
            return MicroArbBitgetConfig(**payload)
        except FileNotFoundError:
            return MicroArbBitgetConfig()
        except Exception:
            return MicroArbBitgetConfig()

    @staticmethod
    def _resolve_exchange_symbols(cfg: MicroArbBitgetConfig) -> Tuple[str, List[str], bool]:
        exchange_env = os.getenv("MICRO_ARB_EXCHANGE")
        paper_env = os.getenv("MICRO_ARB_PAPER")
        symbols_env = os.getenv("MICRO_ARB_SYMBOLS")
        exchange = exchange_env or "bitget"
        use_paper = paper_env.lower() == "true" if paper_env else False
        symbols = [s.strip() for s in symbols_env.split(",") if s.strip()] if symbols_env else cfg.symbols
        if use_paper and not exchange.endswith("_paper_trade"):
            exchange = f"{exchange}_paper_trade"
        return exchange, symbols, use_paper

    @classmethod
    def init_markets(cls, config: Optional[MicroArbBitgetConfig] = None):
        cfg = config or cls._load_config_static()
        exchange, symbols, use_paper = cls._resolve_exchange_symbols(cfg)

        # If auto_discover enabled: let connector discover all pairs dynamically
        if cfg.auto_discover_symbols and not use_paper:
            cls.markets = {exchange: {"USDT"}}  # Connector auto-discovers all *-USDT pairs
        else:
            cls.markets = {exchange: set(symbols)}

    def __init__(self, connectors, config: Optional[MicroArbBitgetConfig] = None):
        cfg = config or self._load_config()
        exchange, symbols, use_paper = self._resolve_exchange_symbols(cfg)
        self.exchange = exchange
        self.use_paper = use_paper

        # Symbol management: start with config symbols, discovery expands from connector.trading_pairs
        self.symbols = symbols
        self.markets = {exchange: set(symbols)}

        super().__init__(connectors, cfg)
        self._apply_config(cfg, exchange, symbols, use_paper)

        # Log startup configuration
        # Dynamic symbol discovery if enabled
        if self.auto_discover_symbols:
            self.logger().info(f"🔍 Dynamic discovery enabled - connector tracks ALL USDT pairs, filtering to best {self.max_symbols}")
            self._last_symbol_refresh = 0

        self.logger().info("=== Micro-Arb Bot Initialized ===")
        self.logger().info(f"Exchange: {self.exchange}, Paper: {self.use_paper}")
        self.logger().info(f"Symbols: {len(self.symbols)} pairs: {', '.join(sorted(self.symbols)[:10])}{'...' if len(self.symbols) > 10 else ''}")
        required_spread = self.maker_fee_pct * 2 + self.min_spread_pct + self.buffer_pct
        self.logger().info(f"Order size: ${self.order_size_usdt}, Required spread: {required_spread:.2f}% (fees={self.maker_fee_pct * 2:.2f}% + min={self.min_spread_pct:.2f}% + buffer={self.buffer_pct:.2f}%)")
        self.logger().info(f"Min depth: ${self.min_depth_usdt}, Max inventory: ${self.max_inventory_usdt}")
        self.logger().info(f"Logging: decisions={self.log_decisions}, block_reasons={self.log_block_reasons}, metrics_interval={self.log_metrics_interval_sec}s")

        # Per-symbol state
        self.state: Dict[str, Dict[str, Optional[Decimal]]] = {}
        self._ob_cache: Dict[str, Tuple[float, Dict[str, Decimal]]] = {}
        self._last_cancel_ts: Dict[str, float] = {}
        self._last_block_log_ts: Dict[str, float] = {}
        self._last_metrics_ts: float = 0
        self._cancel_count: int = 0
        self._fill_count: int = 0
        self.trading_disabled_until: float = 0
        self._last_order_placed_ts: float = 0  # Global rate limit for order placement
        now = self.current_timestamp
        for symbol in self.symbols:
            self.state[symbol] = {
                "mode": "IDLE",
                "buy_order_id": None,
                "sell_order_id": None,
                "buy_time": None,
                "entry_time": None,
                "entry_price": None,
                "position_size": Decimal("0"),
                "cooldown_until": now,
                "price_history": [],
            }

    # === Core loop ===
    def on_tick(self):
        try:
            # ALWAYS log first to prove on_tick is called
            if not hasattr(self, '_tick_count'):
                self._tick_count = 0
                self.logger().info("!!! on_tick() FIRST CALL - method is being executed !!!")
            self._tick_count += 1
            if self._tick_count % 60 == 0:  # Log every 60 ticks (60 seconds)
                self.logger().info(f"!!! on_tick() alive: {self._tick_count} ticks, ready={self.ready_to_trade} !!!")

            if not self.ready_to_trade:
                # Log every 60 seconds when not ready
                now = self.current_timestamp
                if not hasattr(self, '_last_not_ready_log'):
                    self._last_not_ready_log = 0
                if now - self._last_not_ready_log >= 60:
                    self.log_with_clock(self.logger().info, "Bot not ready to trade yet (ready_to_trade=False)")
                    self._last_not_ready_log = now
                return

            # CRITICAL: Wait for orderbooks to be initialized!
            if not hasattr(self, '_orderbooks_ready'):
                try:
                    # Test if we can get at least one orderbook
                    test_symbol = self.symbols[0]
                    _ = self.connectors[self.exchange].get_order_book(test_symbol)
                    self._orderbooks_ready = True
                    self.logger().info("✓ Orderbooks initialized and ready! Starting trading logic...")
                except Exception:
                    # Orderbooks not ready yet, skip this tick
                    if not hasattr(self, '_orderbook_wait_count'):
                        self._orderbook_wait_count = 0
                    self._orderbook_wait_count += 1
                    if self._orderbook_wait_count % 30 == 0:  # Log every 30 seconds
                        self.logger().info(f"Waiting for orderbooks to initialize... ({self._orderbook_wait_count}s)")
                    return

            now = self.current_timestamp

            # Dynamic symbol discovery - refresh periodically
            if self.auto_discover_symbols:
                if not hasattr(self, '_last_symbol_refresh'):
                    self._last_symbol_refresh = 0
                    self.logger().info(f"🔎 Discovery initialized: will scan connector.trading_pairs every {self.symbol_refresh_interval_sec}s")
                if now - self._last_symbol_refresh >= self.symbol_refresh_interval_sec:
                    self.logger().info("🔄 Running symbol discovery scan...")
                    self._discover_symbols()
                    self._last_symbol_refresh = now

            if now < self.trading_disabled_until:
                return

            # Log periodic status
            if self.log_decisions and self.log_metrics_interval_sec > 0:
                if now - self._last_metrics_ts >= self.log_metrics_interval_sec:
                    active_symbol = self._active_symbol()
                    modes = {s: self.state[s]["mode"] for s in self.symbols}
                    active_modes = [f"{s}:{m}" for s, m in modes.items() if m != "IDLE"]
                    if active_modes:
                        self.log_with_clock(self.logger().info, f"Status: active={active_symbol or 'none'} modes={active_modes}")
                    self._last_metrics_ts = now

            active_symbol = self._active_symbol()

            # Log every 30 seconds what we're evaluating
            if not hasattr(self, '_last_eval_log'):
                self._last_eval_log = 0
            if now - self._last_eval_log >= 30:
                self.logger().info(f"Evaluating {len(self.symbols)} symbols for trades, active={active_symbol or 'none'}")
                self._last_eval_log = now

            for symbol in self.symbols:
                ctx = self.state[symbol]
                ob = self._get_top_of_book_cached(symbol, now)
                # Enforce single active symbol at a time
                if active_symbol and active_symbol != symbol and ctx["mode"] == "IDLE":
                    continue
                # Update price history for volatility calc
                self._record_price(symbol, now, ob)

                # Cooldown gate
                if now < ctx["cooldown_until"]:
                    continue

                if ctx["mode"] == "IDLE":
                    self._maybe_start_trade(symbol, now, ob)
                elif ctx["mode"] == "WAIT_BUY":
                    self._check_buy_timeout(symbol, now)
                    # Maker-only guard: if spread shrinks, cancel
                    if self.maker_only and ob:
                        if not self._spread_ok(ob):
                            self._throttled_cancel(symbol, ctx.get("buy_order_id"))
                            ctx.update({
                                "mode": "IDLE",
                                "buy_order_id": None,
                                "buy_time": None,
                                "position_size": Decimal("0"),
                                "cooldown_until": now + self.cooldown_after_cancel_sec,
                            })
                elif ctx["mode"] == "WAIT_SELL":
                    self._check_hold_timeout(symbol, now)
                    # Maker-only guard for sell side
                    if self.maker_only and ob and ctx.get("sell_order_id"):
                        if not self._spread_ok(ob):
                            self._throttled_cancel(symbol, ctx.get("sell_order_id"))
                            self._force_exit(symbol, reason="spread_shrunk")

            # Periodic metrics line + debug info
            if self.log_metrics_interval_sec and now - self._last_metrics_ts >= self.log_metrics_interval_sec:
                modes = ", ".join([f"{s}:{c['mode']}" for s, c in self.state.items()])
                # Add eval_count debug info
                eval_info = f" evals={getattr(self, '_eval_count', 0)}" if hasattr(self, '_eval_count') else ""
                self.log_with_clock(
                    self.logger().info,
                    f"metrics modes=[{modes}] cancels={self._cancel_count} fills={self._fill_count}{eval_info}",
                )
                self._last_metrics_ts = now
                if hasattr(self, '_eval_count'):
                    self._eval_log_time = now
                    self._eval_count = 0  # Reset counter

        except Exception as e:
            self.logger().error(f"!!! EXCEPTION in on_tick(): {type(e).__name__}: {e}")
            import traceback
            self.logger().error(f"!!! TRACEBACK:\n{traceback.format_exc()}")

    # === Event handlers ===
    def did_fill_order(self, event: OrderFilledEvent):
        symbol = event.trading_pair
        if symbol not in self.state:
            return
        ctx = self.state[symbol]
        now = self.current_timestamp

        # BUY filled -> place SELL
        if ctx["buy_order_id"] and event.order_id == ctx["buy_order_id"] and event.trade_type == TradeType.BUY:
            self._fill_count += 1
            ctx["position_size"] += event.amount
            ctx["position_size"] = max(ctx["position_size"], Decimal("0"))
            ctx["entry_time"] = now
            ctx["entry_price"] = event.price

            # Check if buy order is FULLY filled before placing sell
            connector = self.connectors[self.exchange]
            order = connector.get_order(event.order_id)
            if order and order.is_done:
                # Order fully filled - now place sell for ENTIRE position
                ctx["buy_order_id"] = None
                ctx["mode"] = "WAIT_SELL"
                # detect potential taker fill (very fast fill)
                if self.maker_only and ctx.get("buy_time") and now - ctx["buy_time"] < 0.5:
                    self.log_with_clock(self.logger().warning, f"{symbol} BUY filled instantly; possible taker fill")
                    ctx["cooldown_until"] = max(ctx["cooldown_until"], now + self.cooldown_after_force_exit_sec)
                self.logger().info(f"{symbol} BUY order FULLY filled, position={ctx['position_size']:.4f}, placing SELL now")
                self._place_sell(symbol, ctx["position_size"])
            else:
                # Partial fill - wait for more fills
                self.logger().info(f"{symbol} BUY partial fill: {event.amount:.4f}, total position now={ctx['position_size']:.4f}")
            return

        # SELL filled -> reset
        if ctx["sell_order_id"] and event.order_id == ctx["sell_order_id"] and event.trade_type == TradeType.SELL:
            self._fill_count += 1
            ctx["position_size"] -= event.amount
            ctx["position_size"] = max(ctx["position_size"], Decimal("0"))
            pnl_pct = None
            if ctx.get("entry_price") and ctx["position_size"] == Decimal("0"):
                try:
                    pnl_pct = (event.price - ctx["entry_price"]) / ctx["entry_price"] * Decimal("100")
                except Exception:
                    pnl_pct = None
            if ctx["position_size"] <= self.dust_threshold:
                ctx["position_size"] = Decimal("0")
                ctx["sell_order_id"] = None
                ctx["mode"] = "IDLE"
                ctx["entry_time"] = None
                ctx["entry_price"] = None
                ctx["cooldown_until"] = now + self.cooldown_after_trade_sec
                if self.log_decisions:
                    self.log_with_clock(
                        self.logger().info,
                        f"{symbol} round-trip done pnl_pct={pnl_pct:.4f}%" if pnl_pct is not None else f"{symbol} round-trip done",
                    )
            else:
                # partial sell fill: keep waiting
                ctx["sell_order_id"] = event.order_id
            return

    # === Trade lifecycle ===
    def _maybe_start_trade(self, symbol: str, now: float, ob: Optional[Dict[str, Decimal]]):
        # CRITICAL: Global rate limit - only 1 new order per 5 seconds across ALL symbols
        if now - self._last_order_placed_ts < 5.0:
            return

        # Debug: track how many symbols evaluated
        if not hasattr(self, '_eval_count'):
            self._eval_count = 0
            self._eval_log_time = 0
            self._first_eval_logged = False

        self._eval_count += 1

        # Log first evaluation to prove function is called
        if not self._first_eval_logged:
            self.logger().info(f"✓ _maybe_start_trade() called for {symbol} - trading logic is active!")
            self._first_eval_logged = True

        if ob is None:
            # Log why orderbook is None (throttled to 30s)
            if self.log_decisions and now - self._eval_log_time >= 30:
                self.logger().info(f"DEBUG: {symbol} orderbook is None!")
            return

        if not self._is_tradeable(symbol, ob, now):
            return

        # DEBUG: Log that we're about to place order
        self.logger().info(f">>> {symbol} passed _is_tradeable, calling _place_buy now!")
        self._place_buy(symbol, ob)

    def _place_buy(self, symbol: str, ob: Dict[str, Decimal]):
        connector = self.connectors[self.exchange]
        # MICRO-ARB: Buy just BELOW ask (cheap) to be a maker
        best_ask = ob["ask"]
        tick = self._get_tick_size(symbol, best_ask)
        raw_price = best_ask - (tick * self.price_offset_ticks if tick else Decimal("0"))
        price = connector.quantize_order_price(symbol, raw_price)

        amount = self.order_size_usdt / price
        amount = connector.quantize_order_amount(symbol, amount)
        if amount <= 0:
            if self.log_decisions:
                self.log_with_clock(self.logger().warning, f"{symbol} BUY blocked: amount={amount} is zero after quantize")
            return

        # Budget guard: quote balance must cover the quote notional
        quote = symbol.split("-")[1]
        quote_balance = connector.get_available_balance(quote)
        if quote_balance < self.order_size_usdt:
            if self.log_decisions:
                self.log_with_clock(self.logger().warning,
                                    f"{symbol} BUY blocked: insufficient {quote} balance ${quote_balance:.2f} < ${self.order_size_usdt:.2f}")
            return

        # Log BEFORE placing order to debug
        self.logger().info(f">>> PLACING BUY: {symbol} @ {price:.8f} size {amount:.8f}")

        try:
            order_id = self.buy(
                connector_name=self.exchange,
                trading_pair=symbol,
                amount=amount,
                order_type=OrderType.LIMIT,
                price=price,
            )

            # Log order creation result
            self.logger().info(f">>> ORDER CREATED: {symbol} order_id={order_id}")

            ctx = self.state[symbol]
            ctx["buy_order_id"] = order_id
            ctx["buy_time"] = self.current_timestamp
            ctx["mode"] = "WAIT_BUY"
            self._last_order_placed_ts = self.current_timestamp  # Track global order placement
            if self.log_decisions:
                self.log_with_clock(self.logger().info, f"{symbol} BUY placed @ {price} size {amount} id={order_id}")
        except Exception as e:
            self.logger().error(f"❌ FAILED to place {symbol} BUY order: {e}")
            import traceback
            self.logger().error(traceback.format_exc())

    def _place_sell(self, symbol: str, size: Decimal):
        connector = self.connectors[self.exchange]
        ctx = self.state[symbol]

        # CRITICAL: Use entry_price as minimum to ensure we don't sell at a loss
        entry_price = ctx.get("entry_price")
        if not entry_price:
            self.logger().warning(f"{symbol} _place_sell called without entry_price, skipping")
            return

        ob = self._get_top_of_book(symbol)
        if ob is None:
            return

        # Calculate desired sell price (BID + tick)
        best_bid = ob["bid"]
        tick = self._get_tick_size(symbol, best_bid)
        raw_price = best_bid + (tick * self.price_offset_ticks if tick else Decimal("0"))

        # SAFETY: Never sell below buy price! Use at least entry_price + 1 tick
        min_profitable_price = entry_price + (tick if tick else Decimal("0.00001"))
        if raw_price < min_profitable_price:
            self.logger().warning(f"{symbol} SELL price {raw_price:.6f} < entry {entry_price:.6f}, using min profitable {min_profitable_price:.6f}")
            raw_price = min_profitable_price

        price = connector.quantize_order_price(symbol, raw_price)
        amount = connector.quantize_order_amount(symbol, size)
        if amount <= 0:
            return

        order_id = self.sell(
            connector_name=self.exchange,
            trading_pair=symbol,
            amount=amount,
            order_type=OrderType.LIMIT,
            price=price,
        )
        ctx["sell_order_id"] = order_id
        ctx["mode"] = "WAIT_SELL"
        if self.log_decisions:
            self.log_with_clock(self.logger().info, f"{symbol} SELL placed @ {price} (entry={entry_price:.6f}) size {amount}")

    def _force_exit(self, symbol: str, reason: str = ""):
        ctx = self.state[symbol]
        connector = self.connectors[self.exchange]
        if ctx["sell_order_id"]:
            try:
                self.cancel(self.exchange, symbol, ctx["sell_order_id"])
            except Exception:
                pass
            ctx["sell_order_id"] = None
        amount = ctx.get("position_size", Decimal("0"))
        if amount > 0:
            amount = connector.quantize_order_amount(symbol, amount)
            self.sell(
                connector_name=self.exchange,
                trading_pair=symbol,
                amount=amount,
                order_type=OrderType.MARKET,
            )
        ctx.update({
            "mode": "IDLE",
            "position_size": Decimal("0"),
            "entry_time": None,
            "cooldown_until": self.current_timestamp + self.cooldown_after_trade_sec,
        })
        if self.log_decisions:
            suffix = f" ({reason})" if reason else ""
            self.log_with_clock(self.logger().warning, f"{symbol} force-exit executed{suffix}")

    # === Guards ===
    def _is_tradeable(self, symbol: str, ob: Dict[str, Decimal], now: float) -> bool:
        reasons: List[str] = []
        spread_pct = (ob["ask"] - ob["bid"]) / ob["mid"] * Decimal("100")
        fee_cost = self.maker_fee_pct * 2
        required_spread = fee_cost + self.min_spread_pct + self.buffer_pct

        if spread_pct < required_spread:
            reasons.append(f"spread={spread_pct:.3f}%<{required_spread:.3f}%")
        if ob["depth_usdt"] < self.min_depth_usdt:
            reasons.append(f"depth=${ob['depth_usdt']:.0f}<${self.min_depth_usdt:.0f}")

        vol_30s = self._volatility_30s(symbol)
        if vol_30s > self.volatility_block_pct_30s:
            reasons.append(f"vol={vol_30s:.2f}%>{self.volatility_block_pct_30s:.2f}%")

        if self._inventory_exceeds_cap(symbol, ob["mid"]):
            reasons.append("inventory")
        if self._active_symbol() and self._active_symbol() != symbol:
            reasons.append("other_symbol_active")

        if reasons:
            if self.log_block_reasons:
                # ALWAYS log first blocked reason per symbol
                if not hasattr(self, '_first_block_logged'):
                    self._first_block_logged = set()

                if symbol not in self._first_block_logged:
                    self.logger().info(f"{symbol} blocked: {', '.join(reasons)} | bid={ob['bid']:.6f} ask={ob['ask']:.6f}")
                    self._first_block_logged.add(symbol)
                else:
                    # Throttled logging after first
                    last = self._last_block_log_ts.get(symbol, 0)
                    if now - last >= self.log_metrics_interval_sec:
                        self.logger().info(f"{symbol} blocked: {', '.join(reasons)} | bid={ob['bid']:.6f} ask={ob['ask']:.6f}")
                        self._last_block_log_ts[symbol] = now
            return False

        # When tradeable, return True (order will be attempted in _place_buy)
        if self.log_decisions:
            self.logger().info(f"✓ {symbol} TRADEABLE: spread={spread_pct:.3f}% depth=${ob['depth_usdt']:.0f} vol={vol_30s:.2f}%")
        return True

    def _inventory_exceeds_cap(self, symbol: str, mid: Decimal) -> bool:
        connector = self.connectors[self.exchange]
        base = symbol.split("-")[0]
        base_hold = connector.get_available_balance(base)
        return base_hold * mid > self.max_inventory_usdt

    # === Timeouts ===
    def _check_buy_timeout(self, symbol: str, now: float):
        ctx = self.state[symbol]
        if ctx["buy_time"] and now - ctx["buy_time"] > self.buy_timeout_sec:
            if ctx["buy_order_id"]:
                self._throttled_cancel(symbol, ctx["buy_order_id"])
            ctx.update({
                "mode": "IDLE",
                "buy_order_id": None,
                "buy_time": None,
                "position_size": Decimal("0"),
                "cooldown_until": now + self.cooldown_after_cancel_sec,
            })

    def _check_hold_timeout(self, symbol: str, now: float):
        ctx = self.state[symbol]
        if ctx["entry_time"] and now - ctx["entry_time"] > self.max_hold_sec:
            if ctx.get("sell_order_id"):
                self._throttled_cancel(symbol, ctx["sell_order_id"])
            self._force_exit(symbol, reason="max_hold")

    # === Market data helpers ===
    def _get_top_of_book_cached(self, symbol: str, now: float) -> Optional[Dict[str, Decimal]]:
        cached = self._ob_cache.get(symbol)
        if cached and cached[0] == now:
            return cached[1]
        ob = self._get_top_of_book(symbol)
        if ob:
            self._ob_cache[symbol] = (now, ob)
        return ob

    def _get_top_of_book(self, symbol: str) -> Optional[Dict[str, Decimal]]:
        try:
            bids, asks = self.connectors[self.exchange].get_order_book(symbol).snapshot
            if bids.empty or asks.empty:
                return None
            best_bid = Decimal(str(bids.iloc[0].price))
            best_ask = Decimal(str(asks.iloc[0].price))
            mid = (best_bid + best_ask) / 2
            depth_usdt = self._depth_usdt(bids, asks, levels=5)
            return {"bid": best_bid, "ask": best_ask, "mid": mid, "depth_usdt": depth_usdt}
        except Exception as e:
            # Log the first few errors to understand the issue
            if not hasattr(self, '_ob_error_count'):
                self._ob_error_count = {}
            if symbol not in self._ob_error_count:
                self._ob_error_count[symbol] = 0
            if self._ob_error_count[symbol] < 2:  # Only log first 2 errors per symbol
                self.logger().warning(f"Failed to get orderbook for {symbol}: {type(e).__name__}: {e}")
                self._ob_error_count[symbol] += 1
            return None

    def _depth_usdt(self, bids_df, asks_df, levels: int = 5) -> Decimal:
        depth = Decimal("0")
        for df in (bids_df.head(levels), asks_df.head(levels)):
            for _, row in df.iterrows():
                depth += Decimal(str(row.price)) * Decimal(str(row.amount))
        return depth

    def _get_tick_size(self, symbol: str, price: Decimal) -> Optional[Decimal]:
        try:
            tick = self.connectors[self.exchange].get_order_price_quantum(trading_pair=symbol, price=price)
            return Decimal(str(tick)) if tick else None
        except Exception:
            return None

    # === Volatility tracking ===
    def _record_price(self, symbol: str, now: float, ob: Optional[Dict[str, Decimal]]):
        if ob is None:
            return
        hist: List[Tuple[float, Decimal]] = self.state[symbol]["price_history"]
        hist.append((now, ob["mid"]))
        cutoff = now - 60
        while hist and hist[0][0] < cutoff:
            hist.pop(0)

    def _volatility_30s(self, symbol: str) -> Decimal:
        hist: List[Tuple[float, Decimal]] = self.state[symbol]["price_history"]
        now = self.current_timestamp
        recent = [p for t, p in hist if now - t <= 30]
        if len(recent) < 2:
            return Decimal("0")
        max_p = max(recent)
        min_p = min(recent)
        if min_p == 0:
            return Decimal("0")
        return (max_p - min_p) / min_p * Decimal("100")

    # === Utilities ===
    def _active_symbol(self) -> Optional[str]:
        for sym, ctx in self.state.items():
            if ctx["mode"] in ("WAIT_BUY", "WAIT_SELL"):
                return sym
        return None

    def format_status(self) -> str:
        lines = ["Micro-Arb Bitget status"]
        for sym, ctx in self.state.items():
            lines.append(
                f"{sym}: {ctx['mode']} size={ctx.get('position_size', Decimal('0'))} cooldown_until={ctx['cooldown_until']:.0f}"
            )
        return "\n".join(lines)

    # === Config helpers ===
    def _load_config(self) -> MicroArbBitgetConfig:
        return self._load_config_static()

    def _apply_config(self, cfg: MicroArbBitgetConfig, exchange: str, symbols: List[str], use_paper: bool) -> None:
        # YAML overrides defaults; env overrides YAML for exchange/paper/symbols/order size
        self.min_spread_pct = cfg.min_spread_pct
        self.maker_fee_pct = cfg.maker_fee_pct
        self.buffer_pct = cfg.buffer_pct
        self.order_size_usdt = cfg.order_size_usdt
        self.price_offset_ticks = cfg.price_offset_ticks
        self.maker_only = cfg.maker_only
        self.buy_timeout_sec = cfg.buy_timeout_sec
        self.max_hold_sec = cfg.max_hold_sec
        self.cooldown_after_trade_sec = cfg.cooldown_after_trade_sec
        self.cooldown_after_cancel_sec = cfg.cooldown_after_cancel_sec
        self.cooldown_after_force_exit_sec = cfg.cooldown_after_force_exit_sec
        self.min_depth_usdt = cfg.min_depth_usdt
        self.volatility_block_pct_30s = cfg.volatility_block_pct_30s
        self.max_inventory_usdt = cfg.max_inventory_usdt
        self.inventory_breach_cooldown_sec = cfg.inventory_breach_cooldown_sec
        self.dust_threshold = cfg.dust_threshold_base
        self.order_refresh_time = cfg.order_refresh_time
        self.rate_limit_buffer = cfg.rate_limit_buffer
        self.min_cancel_interval_sec = cfg.min_cancel_interval_sec
        self.log_decisions = cfg.log_decisions
        self.log_block_reasons = cfg.log_block_reasons
        self.log_trade_summary = cfg.log_trade_summary
        self.log_metrics_interval_sec = cfg.log_metrics_interval_sec

        # Dynamic discovery settings
        self.auto_discover_symbols = cfg.auto_discover_symbols
        self.min_volume_24h_usdt = cfg.min_volume_24h_usdt
        self.max_symbols = cfg.max_symbols
        self.symbol_refresh_interval_sec = cfg.symbol_refresh_interval_sec

        order_env = os.getenv("MICRO_ARB_ORDER_USDT")
        self.exchange = exchange
        self.use_paper = use_paper
        self.symbols = symbols
        if order_env:
            self.order_size_usdt = Decimal(order_env)

        self.markets = {self.exchange: set(self.symbols)}

    # === Spread helper ===
    def _spread_ok(self, ob: Dict[str, Decimal]) -> bool:
        spread_pct = (ob["ask"] - ob["bid"]) / ob["mid"] * Decimal("100")
        fee_cost = self.maker_fee_pct * 2
        return spread_pct >= fee_cost + self.min_spread_pct + self.buffer_pct

    # === Cancel throttling ===
    def _throttled_cancel(self, symbol: str, order_id: Optional[str]):
        if not order_id:
            return
        last = self._last_cancel_ts.get(symbol, 0)
        now = self.current_timestamp
        min_interval = max(float(self.min_cancel_interval_sec), float(self.order_refresh_time) * float(self.rate_limit_buffer))
        if now - last < min_interval:
            return
        try:
            self.cancel(self.exchange, symbol, order_id)
            self._cancel_count += 1
        finally:
            self._last_cancel_ts[symbol] = now

    # === Safety: inventory breach ===
    def _handle_inventory_breach(self, symbol: str, mid: Decimal):
        ctx = self.state[symbol]
        if ctx.get("buy_order_id"):
            self._throttled_cancel(symbol, ctx["buy_order_id"])
            ctx["buy_order_id"] = None
        if ctx.get("sell_order_id"):
            self._throttled_cancel(symbol, ctx["sell_order_id"])
            ctx["sell_order_id"] = None
        self._force_exit(symbol, mid, "inventory_breach")
        self.trading_disabled_until = self.current_timestamp + self.inventory_breach_cooldown_sec

    # === Dynamic Symbol Discovery ===
    async def _fetch_all_exchange_pairs(self):
        """Fetch ALL trading pairs from Bitget API directly"""
        try:
            from hummingbot.connector.exchange.bitget import bitget_constants as CONSTANTS

            connector = self.connectors.get(self.exchange)
            if not connector:
                return []

            # Call Bitget's public symbols endpoint directly
            response = await connector._api_get(
                path_url=CONSTANTS.PUBLIC_SYMBOLS_ENDPOINT,
                is_auth_required=False
            )

            if not response or "data" not in response:
                self.logger().warning("Discovery: failed to fetch symbols from API")
                return []

            # Extract all USDT pairs
            from hummingbot.connector.utils import combine_to_hb_trading_pair
            usdt_pairs = []
            for symbol_data in response["data"]:
                if symbol_data.get("quoteCoin") == "USDT" and symbol_data.get("status") == "online":
                    try:
                        pair = combine_to_hb_trading_pair(
                            symbol_data["baseCoin"],
                            symbol_data["quoteCoin"]
                        )
                        usdt_pairs.append(pair)
                    except Exception:
                        continue

            self.logger().info(f"Discovery: fetched {len(usdt_pairs)} active USDT pairs from Bitget API")
            return usdt_pairs

        except Exception as e:
            self.logger().warning(f"Discovery: API fetch failed: {e}")
            return []

    def _discover_symbols(self):
        """Dynamically discover best trading pairs from ALL available pairs on exchange"""
        try:
            from hummingbot.core.utils.async_utils import safe_ensure_future

            connector = self.connectors.get(self.exchange)
            if not connector:
                self.logger().warning("Discovery: connector not found")
                return

            # Schedule async fetch to run in event loop
            safe_ensure_future(self._async_discover_symbols())

        except Exception as e:
            self.logger().warning(f"Symbol discovery failed: {e}")

    async def _async_discover_symbols(self):
        """Async version of symbol discovery"""
        try:
            # Fetch ALL USDT pairs from exchange API
            usdt_pairs = await self._fetch_all_exchange_pairs()

            if not usdt_pairs:
                self.logger().warning("Discovery: no USDT pairs received from API")
                return

            # Score pairs by spread and depth
            candidates = []
            checked = 0
            errors = 0

            for symbol in usdt_pairs:
                try:
                    ob = self._get_top_of_book(symbol)
                    if not ob:
                        continue

                    checked += 1

                    # Filter by depth
                    if ob["depth_usdt"] < self.min_depth_usdt:
                        continue

                    spread_pct = (ob["ask"] - ob["bid"]) / ob["mid"] * Decimal("100")

                    # Calculate score: higher spread = better, weighted by depth
                    score = float(spread_pct) * float(ob["depth_usdt"]) / 10000
                    candidates.append((symbol, score, spread_pct, ob["depth_usdt"]))
                except Exception:
                    errors += 1
                    continue

            if not candidates:
                self.logger().warning(f"Discovery checked {checked} pairs but found 0 candidates (errors={errors})")
                return

            # Sort by score and take top N (uses self.max_symbols from config)
            candidates.sort(key=lambda x: x[1], reverse=True)
            new_symbols = [c[0] for c in candidates[:self.max_symbols]]

            # Update symbols if changed
            if set(new_symbols) != set(self.symbols):
                added = set(new_symbols) - set(self.symbols)
                removed = set(self.symbols) - set(new_symbols)

                self.logger().info(f"🔄 Symbol list updated: {len(new_symbols)} pairs")
                if added:
                    self.logger().info(f"  ➕ Added: {', '.join(sorted(added)[:5])}{'...' if len(added) > 5 else ''}")
                if removed:
                    self.logger().info(f"  ➖ Removed: {', '.join(sorted(removed)[:5])}{'...' if len(removed) > 5 else ''}")

                # Show top 5 best spreads
                top5 = candidates[:5]
                self.logger().info(f"  📊 Top spreads: {', '.join([f'{s}={sp:.2f}%' for s, _, sp, _ in top5])}")

                # Update symbol list and initialize state for new symbols
                old_symbols = set(self.symbols)
                self.symbols = new_symbols
                now = self.current_timestamp

                for symbol in new_symbols:
                    if symbol not in old_symbols:
                        # Initialize state for new symbol
                        self.state[symbol] = {
                            "mode": "IDLE",
                            "buy_order_id": None,
                            "sell_order_id": None,
                            "buy_time": None,
                            "entry_time": None,
                            "entry_price": None,
                            "position_size": Decimal("0"),
                            "cooldown_until": now,
                            "price_history": [],
                        }
        except Exception as e:
            self.logger().warning(f"Async symbol discovery failed: {e}")


# Auto-initialize markets from config at module load time
# This satisfies Hummingbot's requirement for a static markets dict
MicroArbBitget.markets = MicroArbBitget._auto_init_markets()
