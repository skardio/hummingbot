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
    symbols: List[str] = [s.strip() for s in os.getenv("MICRO_ARB_SYMBOLS", "BTC-USDT,ETH-USDT,SOL-USDT").split(",") if s.strip()]

    min_spread_pct: Decimal = Decimal("0.35")
    maker_fee_pct: Decimal = Decimal("0.10")  # percent
    buffer_pct: Decimal = Decimal("0.05")
    order_size_usdt: Decimal = Decimal(os.getenv("MICRO_ARB_ORDER_USDT", "10"))
    price_offset_ticks: int = 1
    maker_only: bool = True

    buy_timeout_sec: int = 3
    max_hold_sec: int = 6
    cooldown_after_trade_sec: int = 5

    min_depth_usdt: Decimal = Decimal("50000")
    volatility_block_pct_30s: Decimal = Decimal("0.30")
    max_inventory_usdt: Decimal = Decimal("15")

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

    # Initialize markets dict statically for Hummingbot
    markets = {"bitget": {"BTC-USDT", "ETH-USDT", "SOL-USDT"}}

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
        exchange, symbols, _ = cls._resolve_exchange_symbols(cfg)
        cls.markets = {exchange: set(symbols)}

    def __init__(self, connectors, config: Optional[MicroArbBitgetConfig] = None):
        cfg = config or self._load_config()
        exchange, symbols, use_paper = self._resolve_exchange_symbols(cfg)
        self.exchange = exchange
        self.symbols = symbols
        self.use_paper = use_paper
        super().__init__(connectors, cfg)
        self._apply_config(cfg, exchange, symbols, use_paper)

        # Per-symbol state
        self.state: Dict[str, Dict[str, Optional[Decimal]]] = {}
        self._ob_cache: Dict[str, Tuple[float, Dict[str, Decimal]]] = {}
        self._last_cancel_ts: Dict[str, float] = {}
        self._last_block_log_ts: Dict[str, float] = {}
        self._last_metrics_ts: float = 0
        self._cancel_count: int = 0
        self._fill_count: int = 0
        self.trading_disabled_until: float = 0
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
        if not self.ready_to_trade:
            return
        now = self.current_timestamp
        if now < self.trading_disabled_until:
            return
        active_symbol = self._active_symbol()

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

        # Periodic metrics line
        if self.log_metrics_interval_sec and now - self._last_metrics_ts >= self.log_metrics_interval_sec:
            modes = ", ".join([f"{s}:{c['mode']}" for s, c in self.state.items()])
            self.log_with_clock(
                self.logger().info,
                f"metrics modes=[{modes}] cancels={self._cancel_count} fills={self._fill_count}",
            )
            self._last_metrics_ts = now

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
            ctx["buy_order_id"] = None
            ctx["mode"] = "WAIT_SELL"
            ctx["entry_time"] = now
            ctx["entry_price"] = event.price
            # detect potential taker fill (very fast fill)
            if self.maker_only and ctx.get("buy_time") and now - ctx["buy_time"] < 0.5:
                self.log_with_clock(self.logger().warning, f"{symbol} BUY filled instantly; possible taker fill")
                ctx["cooldown_until"] = max(ctx["cooldown_until"], now + self.cooldown_after_force_exit_sec)
            self._place_sell(symbol, ctx["position_size"])
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
        if ob is None:
            return
        if not self._is_tradeable(symbol, ob, now):
            return
        self._place_buy(symbol, ob)

    def _place_buy(self, symbol: str, ob: Dict[str, Decimal]):
        connector = self.connectors[self.exchange]
        best_bid = ob["bid"]
        tick = self._get_tick_size(symbol, best_bid)
        raw_price = best_bid + (tick * self.price_offset_ticks if tick else Decimal("0"))
        price = connector.quantize_order_price(symbol, raw_price)

        amount = self.order_size_usdt / price
        amount = connector.quantize_order_amount(symbol, amount)
        if amount <= 0:
            return

        # Budget guard: quote balance must cover the quote notional
        quote = symbol.split("-")[1]
        quote_balance = connector.get_available_balance(quote)
        if quote_balance < self.order_size_usdt:
            return

        order_id = self.buy(
            connector_name=self.exchange,
            trading_pair=symbol,
            amount=amount,
            order_type=OrderType.LIMIT,
            price=price,
        )
        ctx = self.state[symbol]
        ctx["buy_order_id"] = order_id
        ctx["buy_time"] = self.current_timestamp
        ctx["mode"] = "WAIT_BUY"
        if self.log_decisions:
            self.log_with_clock(self.logger().info, f"{symbol} BUY placed @ {price} size {amount}")

    def _place_sell(self, symbol: str, size: Decimal):
        connector = self.connectors[self.exchange]
        ob = self._get_top_of_book(symbol)
        if ob is None:
            return
        best_ask = ob["ask"]
        tick = self._get_tick_size(symbol, best_ask)
        raw_price = best_ask - (tick * self.price_offset_ticks if tick else Decimal("0"))
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
        ctx = self.state[symbol]
        ctx["sell_order_id"] = order_id
        ctx["mode"] = "WAIT_SELL"
        if self.log_decisions:
            self.log_with_clock(self.logger().info, f"{symbol} SELL placed @ {price} size {amount}")

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
        if spread_pct < fee_cost + self.min_spread_pct + self.buffer_pct:
            reasons.append("spread")
        if ob["depth_usdt"] < self.min_depth_usdt:
            reasons.append("depth")
        if self._volatility_30s(symbol) > self.volatility_block_pct_30s:
            reasons.append("vol")
        if self._inventory_exceeds_cap(symbol, ob["mid"]):
            reasons.append("inventory")
        if self._active_symbol() and self._active_symbol() != symbol:
            reasons.append("other_symbol_active")
        if reasons:
            if self.log_block_reasons and self.log_decisions:
                last = self._last_block_log_ts.get(symbol, 0)
                if now - last >= self.log_metrics_interval_sec:
                    self.log_with_clock(self.logger().info, f"{symbol} blocked: {','.join(reasons)}")
                    self._last_block_log_ts[symbol] = now
            return False
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
        except Exception:
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
        self._force_exit(symbol, reason="inventory_breach")
        self.trading_disabled_until = self.current_timestamp + self.inventory_breach_cooldown_sec
        self.log_with_clock(self.logger().critical, f"{symbol} inventory breach; trading paused")
