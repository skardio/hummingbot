"""
Background risk monitor that feeds ArbitrageRiskScanner with live market data and
pushes Telegram notifications whenever the trade status changes.

This module intentionally lives outside the main bot loop so it can be executed as
a stand-alone process:

    python -m multi_coin_grid_pro.monitoring.risk_monitor \
        --config /home/mo/repos/hummingbot/multi_coin_grid_pro/config/risk_monitor.yaml
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Dict, Iterable, List, Optional

import ccxt
import yaml

from multi_coin_grid_pro.core.risk_scanner import ArbitrageRiskScanner
from multi_coin_grid_pro.monitoring.telegram_notifier import TelegramNotifier

LOGGER = logging.getLogger("risk_monitor")
DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "risk_monitor.yaml"
)


@dataclass
class MarketMetrics:
    returns_1m: List[float]
    avg_spread_bps: float
    latency_ms_by_exchange: Dict[str, float]
    total_volume_24h_usd: float
    status_by_exchange: Dict[str, str]
    symbols_count_by_exchange: Dict[str, int]


def load_config(path: Path) -> Dict:
    if not path.exists():
        raise FileNotFoundError(f"Risk monitor config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def build_exchange_clients(
    exchanges_cfg: Iterable,
) -> Dict[str, ccxt.Exchange]:
    """
    Build ccxt exchange clients from config.

    Config items can be:
      - plain strings (exchange ids, e.g. "kraken")
      - dictionaries:
            id: bitget           # ccxt id
            name: bitget_spot    # internal label (used in metrics/notifications)
            params: {...}        # passed to ccxt constructor

    When name is omitted, id is used as the label.
    """
    clients: Dict[str, ccxt.Exchange] = {}
    for entry in exchanges_cfg:
        if isinstance(entry, str):
            exchange_id = entry
            client_name = exchange_id
            params = {}
        elif isinstance(entry, dict):
            exchange_id = entry.get("id") or entry.get("name")
            client_name = entry.get("name") or exchange_id
            params = entry.get("params", {})
        else:
            raise ValueError(f"Unsupported exchange config entry: {entry}")

        if not exchange_id:
            raise ValueError("Exchange entry requires an 'id' or 'name'")

        if not hasattr(ccxt, exchange_id):
            raise ValueError(f"ccxt has no exchange id '{exchange_id}'")

        params = {"enableRateLimit": True, **params}
        exchange_cls = getattr(ccxt, exchange_id)
        client: ccxt.Exchange = exchange_cls(params)
        client.load_markets()
        clients[client_name] = client
        LOGGER.info(
            "Connected ccxt exchange '%s' (id=%s, %d markets)",
            client_name,
            exchange_id,
            len(client.markets),
        )
    return clients


def resolve_symbol(exchange: ccxt.Exchange, pair: str) -> Optional[str]:
    """
    Convert configuration pair notation (BTC-EUR / BTC/EUR) into a ccxt symbol
    that exists on the exchange. Includes special-casing for Kraken's XBT ticker.

    This is mainly used when you explicitly configure trading_pairs in YAML.
    For the dynamic whole-market scan we directly use the exchange.markets symbols.
    """
    candidates = [
        pair.replace("-", "/"),
        pair.replace("-", "/").replace("BTC", "XBT"),
    ]

    for candidate in candidates:
        if candidate in exchange.markets:
            return candidate
    return None


def compute_returns_from_ohlcv(ohlcv: List[List[float]]) -> List[float]:
    returns: List[float] = []
    if len(ohlcv) < 2:
        return returns
    closes = [candle[4] for candle in ohlcv if candle and len(candle) >= 5]
    for prev, curr in zip(closes, closes[1:]):
        if prev:
            returns.append((curr - prev) / prev)
    return returns


def build_trading_universe(
    exchanges: Dict[str, ccxt.Exchange],
    monitor_cfg: Dict,
) -> Dict[str, List[str]]:
    """
    Determine which symbols to monitor per exchange.

    If risk_monitor.trading_pairs is set in YAML, we:
      - map those pairs to real ccxt symbols per exchange (resolve_symbol)
    Else:
      - dynamic universe: scan the entire market for each exchange
        and filter on:
            - quote currencies (risk_monitor.quotes)
            - include_futures flag
            - max_symbols_per_exchange cap
    """
    trading_pairs_cfg = monitor_cfg.get("trading_pairs") or []
    quotes = monitor_cfg.get("quotes") or ["EUR", "USD", "USDT"]
    include_futures = bool(monitor_cfg.get("include_futures", True))
    max_symbols_per_exchange = int(monitor_cfg.get("max_symbols_per_exchange", 100))

    trading_pairs_by_exchange: Dict[str, List[str]] = {}

    if trading_pairs_cfg:
        # Use manually configured universe; resolve per exchange.
        LOGGER.info("Using manually configured trading_pairs from YAML")
        for name, client in exchanges.items():
            symbols: List[str] = []
            for pair in trading_pairs_cfg:
                symbol = resolve_symbol(client, pair)
                if symbol is not None:
                    symbols.append(symbol)
                else:
                    LOGGER.debug("Pair %s not available on %s", pair, name)
            # Deduplicate and cap
            symbols = sorted(set(symbols))
            if max_symbols_per_exchange and len(symbols) > max_symbols_per_exchange:
                LOGGER.info(
                    "Capping %s symbols for %s from %d to %d",
                    len(symbols),
                    name,
                    len(symbols),
                    max_symbols_per_exchange,
                )
                symbols = symbols[:max_symbols_per_exchange]
            trading_pairs_by_exchange[name] = symbols
    else:
        # Dynamic whole-market universe (filtered)
        LOGGER.info("Building dynamic trading universe from exchange markets")
        for name, client in exchanges.items():
            symbols: List[str] = []

            for market in client.markets.values():
                if not market.get("active", True):
                    continue

                quote = market.get("quote")
                if quote not in quotes:
                    continue

                mtype = market.get("type")
                # Fallback for some exchanges
                if not mtype:
                    if market.get("swap"):
                        mtype = "swap"
                    else:
                        mtype = "spot"

                if mtype == "spot":
                    symbols.append(market["symbol"])
                elif include_futures and mtype in ("swap", "future", "perpetual"):
                    symbols.append(market["symbol"])

            symbols = sorted(set(symbols))
            original_count = len(symbols)
            if max_symbols_per_exchange and original_count > max_symbols_per_exchange:
                LOGGER.info(
                    "Capping symbols for %s from %d to %d",
                    name,
                    original_count,
                    max_symbols_per_exchange,
                )
                symbols = symbols[:max_symbols_per_exchange]

            trading_pairs_by_exchange[name] = symbols
            LOGGER.info(
                "Exchange %s – using %d symbols (filtered by quotes=%s, include_futures=%s)",
                name,
                len(symbols),
                ",".join(quotes),
                include_futures,
            )

    return trading_pairs_by_exchange


def collect_market_metrics(
    exchanges: Dict[str, ccxt.Exchange],
    trading_pairs_by_exchange: Dict[str, List[str]],
    ohlcv_limit: int,
) -> MarketMetrics:
    returns_1m: List[float] = []
    spreads_bps: List[float] = []
    latency_ms: Dict[str, float] = {}
    total_volume_usd = 0.0
    exchange_status: Dict[str, str] = {}
    symbols_count_by_exchange: Dict[str, int] = {}

    for name, client in exchanges.items():
        pairs = trading_pairs_by_exchange.get(name, [])
        symbols_count_by_exchange[name] = len(pairs)

        if not pairs:
            LOGGER.warning("No trading pairs configured for exchange %s", name)
            latency_ms[name] = 9999.0
            exchange_status[name] = "down"
            continue

        per_exchange_spreads: List[float] = []
        per_exchange_latency: List[float] = []
        per_exchange_returns: List[float] = []
        per_exchange_volume = 0.0
        status = "ok"

        for symbol in pairs:
            # Spread + latency sample
            try:
                start = time.time()
                ticker = client.fetch_ticker(symbol)
                per_exchange_latency.append((time.time() - start) * 1000)

                bid = ticker.get("bid")
                ask = ticker.get("ask")
                if bid and ask and bid > 0:
                    mid = (bid + ask) / 2
                    spread_bps = ((ask - bid) / mid) * 10_000
                    per_exchange_spreads.append(spread_bps)

                base_volume = ticker.get("baseVolume") or 0
                last_price = ticker.get("last") or ticker.get("close") or 0
                if base_volume and last_price:
                    # Rough USD approximation (assume EUR≈USD)
                    per_exchange_volume += float(base_volume) * float(last_price)
            except Exception as exc:
                status = "degraded"
                LOGGER.warning(
                    "Failed to fetch ticker for %s on %s: %s", symbol, name, exc
                )

            # Returns sample (1m candles)
            try:
                ohlcv = client.fetch_ohlcv(symbol, timeframe="1m", limit=ohlcv_limit)
                per_exchange_returns.extend(compute_returns_from_ohlcv(ohlcv))
            except Exception as exc:
                status = "degraded"
                LOGGER.debug(
                    "Failed to fetch OHLCV for %s on %s: %s", symbol, name, exc
                )

        if not per_exchange_latency:
            latency_ms[name] = 9999.0
            if status == "ok":
                status = "down"
        else:
            latency_ms[name] = sum(per_exchange_latency) / len(per_exchange_latency)

        if per_exchange_returns:
            returns_1m.extend(per_exchange_returns)
        if per_exchange_spreads:
            spreads_bps.extend(per_exchange_spreads)

        total_volume_usd += per_exchange_volume
        exchange_status[name] = status

    avg_spread = sum(spreads_bps) / len(spreads_bps) if spreads_bps else 0.0

    if not latency_ms:
        latency_ms = {"kraken": 9999.0}
    if not exchange_status:
        exchange_status = {"kraken": "down"}
    if not symbols_count_by_exchange:
        symbols_count_by_exchange = {name: 0 for name in exchanges.keys()}

    return MarketMetrics(
        returns_1m=returns_1m or [0.0],
        avg_spread_bps=avg_spread,
        latency_ms_by_exchange=latency_ms,
        total_volume_24h_usd=total_volume_usd,
        status_by_exchange=exchange_status,
        symbols_count_by_exchange=symbols_count_by_exchange,
    )


def build_telegram_notifier(config: Dict) -> Optional[TelegramNotifier]:
    telegram_cfg = config.get("telegram", {})
    enabled = telegram_cfg.get("enabled", True)
    if not enabled:
        return None

    bot_token = telegram_cfg.get("bot_token") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = telegram_cfg.get("chat_id") or os.getenv("TELEGRAM_CHAT_ID")

    if not (bot_token and chat_id):
        LOGGER.warning("Telegram notifier disabled (missing bot token or chat id)")
        return None

    return TelegramNotifier(
        bot_token=bot_token,
        chat_id=chat_id,
        notify_on_status_change=telegram_cfg.get("notify_on_status_change", True),
        notify_on_do_not_trade=telegram_cfg.get("notify_on_do_not_trade", True),
    )


def build_detailed_explanation(result, metrics: MarketMetrics) -> str:
    """
    Build a human-readable explanation string that combines:
      - global risk score
      - volatility summary (min/max/avg |return|)
      - liquidity & spreads
      - per-exchange status / latency / universe size
      - simple pump/dump hints
      - trade guidance based on status
    """

    returns = metrics.returns_1m or [0.0]
    max_ret = max(returns)
    min_ret = min(returns)
    avg_abs = mean([abs(r) for r in returns]) if returns else 0.0

    lines: List[str] = []

    lines.append(f"📊 Global Risk Score: {result.score:.1f} ({result.status.value})")
    lines.append("")
    lines.append("📈 Volatility snapshot (1m returns across sampled markets)")
    lines.append(f"• Samples: {len(returns)}")
    lines.append(f"• Max 1m move: {max_ret * 100:.2f}%")
    lines.append(f"• Min 1m move: {min_ret * 100:.2f}%")
    lines.append(f"• Avg |1m return|: {avg_abs * 100:.2f}%")
    lines.append("")
    lines.append("💧 Liquidity & spreads")
    lines.append(f"• Approx. 24h volume: ${metrics.total_volume_24h_usd:,.0f}")
    lines.append(f"• Avg spread: {metrics.avg_spread_bps:.2f} bps")
    lines.append("")
    lines.append("🏦 Exchange status")

    for ex, st in metrics.status_by_exchange.items():
        lat = metrics.latency_ms_by_exchange.get(ex, 0.0)
        n_pairs = metrics.symbols_count_by_exchange.get(ex, 0)
        lines.append(
            f"• {ex}: {st}, latency ~{lat:.0f} ms, markets sampled: {n_pairs}"
        )

    lines.append("")

    # Guidance based on status
    status_str = str(result.status.value).lower()
    if "do_not_trade" in status_str or status_str == "do_not_trade":
        lines.append(
            "⚠️ Marktomstandigheden zijn vijandig. "
            "Overweeg om geen nieuwe posities te openen en risico's strakker te managen."
        )
    elif "caution" in status_str:
        lines.append(
            "⚠️ Voorzichtigheid geboden. Condities zijn schokkerig; "
            "kleinere posities en ruimere stops zijn verstandiger."
        )
    else:
        lines.append(
            "✅ Condities lijken acceptabel voor trading, binnen je normale risk rules."
        )

    # Simple pump/dump hints
    dump_threshold = -0.03  # -3% in 1m
    pump_threshold = 0.03   # +3% in 1m
    has_dumps = any(r < dump_threshold for r in returns)
    has_pumps = any(r > pump_threshold for r in returns)

    if has_dumps:
        lines.append(
            "• Er zijn scherpe neerwaartse bewegingen gedetecteerd (≥ 3% in 1 minuut) "
            "in (een deel van) de markt."
        )
    if has_pumps:
        lines.append(
            "• Er zijn scherpe opwaartse bewegingen gedetecteerd (≥ 3% in 1 minuut)."
        )

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Arbitrage risk monitor daemon")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to risk_monitor.yaml",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Override evaluation interval in seconds",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single evaluation and exit",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console log level",
    )
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )


def main():
    args = parse_args()
    configure_logging(args.log_level)

    config = load_config(args.config)
    monitor_cfg = config.get("risk_monitor", {})
    interval = args.interval or int(monitor_cfg.get("interval_seconds", 120))
    ohlcv_limit = int(monitor_cfg.get("ohlcv_limit", 30))
    exchanges_cfg = monitor_cfg.get("exchanges") or ["kraken"]

    try:
        exchanges = build_exchange_clients(exchanges_cfg)
    except Exception as exc:
        LOGGER.error("Failed to initialize exchanges: %s", exc)
        sys.exit(1)

    # Determine trading universe per exchange (whole-market scan or from config)
    trading_pairs_by_exchange = build_trading_universe(exchanges, monitor_cfg)

    risk_cfg = config.get("risk", {})
    scanner = ArbitrageRiskScanner(
        weights=risk_cfg.get("weights"),
        trade_min_score=risk_cfg.get("trade_min_score", 70),
        caution_min_score=risk_cfg.get("caution_min_score", 40),
    )

    telegram_notifier = build_telegram_notifier(config)
    LOGGER.info(
        "Risk monitor started with %s exchanges (interval=%ss)",
        len(exchanges),
        interval,
    )

    try:
        while True:
            try:
                metrics = collect_market_metrics(
                    exchanges, trading_pairs_by_exchange, ohlcv_limit
                )

                result = scanner.evaluate(
                    returns_1m=metrics.returns_1m,
                    avg_spread_bps=metrics.avg_spread_bps,
                    latency_ms_by_exchange=metrics.latency_ms_by_exchange,
                    total_volume_24h_usd=metrics.total_volume_24h_usd,
                    status_by_exchange=metrics.status_by_exchange,
                )

                # Enrich explanation with global market summary (for logs + Telegram)
                result.explanation = build_detailed_explanation(result, metrics)

                LOGGER.info(
                    "Risk score %.1f (%s) | spreads %.1fbps | volume $%.0f | latency %s",
                    result.score,
                    result.status.value,
                    metrics.avg_spread_bps,
                    metrics.total_volume_24h_usd,
                    ", ".join(
                        f"{ex}:{latency:.0f}ms"
                        for ex, latency in metrics.latency_ms_by_exchange.items()
                    ),
                )

                LOGGER.debug("Explanation:\n%s", result.explanation)

                if telegram_notifier:
                    # Preview the message text for logging/diagnostics
                    try:
                        preview = None
                        if hasattr(telegram_notifier, "format_risk_message"):
                            preview = telegram_notifier.format_risk_message(result)
                        if preview:
                            LOGGER.info("Telegram preview: %s", preview.replace("\n", " | "))
                        telegram_notifier.handle_risk_result(result)
                    except Exception as exc:
                        LOGGER.exception("Telegram notifier failed: %s", exc)
            except Exception as exc:
                LOGGER.error("Risk evaluation failed: %s", exc, exc_info=True)

            if args.once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        LOGGER.info("Risk monitor interrupted by user")


if __name__ == "__main__":
    main()
