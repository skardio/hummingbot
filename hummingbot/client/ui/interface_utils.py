import asyncio
from decimal import Decimal
from typing import List, Optional, Set, Tuple

import pandas as pd
import psutil
import tabulate

from hummingbot.client.config.config_data_types import ClientConfigEnum
from hummingbot.client.performance import PerformanceMetrics
from hummingbot.model.trade_fill import TradeFill

s_decimal_0 = Decimal("0")


def _is_strategy_v2_instance(strategy) -> bool:
    return any(
        cls.__name__ == "StrategyV2Base" and cls.__module__ == "hummingbot.strategy.strategy_v2_base"
        for cls in type(strategy).mro()
    )


def _as_decimal(value) -> Decimal:
    if value is None:
        return s_decimal_0
    try:
        return Decimal(str(value))
    except Exception:
        return s_decimal_0


def _as_float_or_none(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _quote_from_pair(trading_pair: Optional[str]) -> Optional[str]:
    if isinstance(trading_pair, str) and "-" in trading_pair:
        return trading_pair.rsplit("-", 1)[1]
    return None


def _executor_started_in_run(executor_info, run_start_time: Optional[float]) -> bool:
    if run_start_time is None:
        return True
    executor_timestamp = _as_float_or_none(getattr(executor_info, "timestamp", None))
    return executor_timestamp is not None and executor_timestamp >= run_start_time


def _executor_trade_count(executor_info) -> int:
    custom_info = getattr(executor_info, "custom_info", None) or {}
    filled_orders = custom_info.get("filled_orders") or []
    held_orders = custom_info.get("held_position_orders") or []
    order_count = len(filled_orders) + len(held_orders)
    if order_count == 0 and _as_decimal(getattr(executor_info, "filled_amount_quote", 0)) > s_decimal_0:
        order_count = 1
    return order_count


def _strategy_v2_trade_monitor_status(strategy, run_start_time: Optional[float] = None) -> Optional[str]:
    """
    StrategyV2 executors track live/unrealized PnL independently from TradeFill rows.
    The generic trade monitor only looks at fills since process start, which makes
    restarted bots with restored executors show zero trades and zero PnL.

    Keep this footer run-scoped: restored/all-time executor rows can be loaded into
    controller reports after startup, but the CLI trade monitor should match the
    current Hummingbot process, not the full database history.
    """
    try:
        if hasattr(strategy, "update_executors_info"):
            strategy.update_executors_info()
    except Exception:
        pass

    reports = getattr(strategy, "controller_reports", None) or {}
    if not reports and hasattr(strategy, "executor_orchestrator"):
        try:
            reports = strategy.executor_orchestrator.get_all_reports()
        except Exception:
            reports = {}

    trade_count = 0
    total_pnl = s_decimal_0
    total_volume = s_decimal_0
    quote_assets: Set[str] = set()

    for controller_id, report in reports.items():
        executors = report.get("executors", []) if isinstance(report, dict) else []
        executors = [
            executor_info for executor_info in executors
            if _executor_started_in_run(executor_info, run_start_time)
        ]
        active_has_data = False
        for executor_info in executors:
            pnl_quote = _as_decimal(getattr(executor_info, "net_pnl_quote", 0))
            volume_quote = _as_decimal(getattr(executor_info, "filled_amount_quote", 0))
            orders = _executor_trade_count(executor_info)
            if orders > 0 or volume_quote != s_decimal_0 or pnl_quote != s_decimal_0:
                active_has_data = True
            trade_count += orders
            total_pnl += pnl_quote
            total_volume += volume_quote
            quote = _quote_from_pair(getattr(executor_info, "trading_pair", None))
            if quote is not None:
                quote_assets.add(quote)

        # If no active executor has live data, use the cached performance report
        # so the footer still reflects restored/stored StrategyV2 performance.
        performance = report.get("performance") if isinstance(report, dict) else None
        if run_start_time is None and not active_has_data and performance is not None:
            pnl_quote = _as_decimal(getattr(performance, "global_pnl_quote", 0))
            volume_quote = _as_decimal(getattr(performance, "volume_traded", 0))
            if pnl_quote != s_decimal_0 or volume_quote != s_decimal_0:
                total_pnl += pnl_quote
                total_volume += volume_quote
                close_type_counts = getattr(performance, "close_type_counts", None) or {}
                trade_count += sum(int(v) for v in close_type_counts.values()) if close_type_counts else 1

        controller = getattr(strategy, "controllers", {}).get(controller_id)
        controller_config = getattr(controller, "config", None)
        quote = getattr(controller_config, "quote_asset", None)
        if isinstance(quote, str) and quote:
            quote_assets.add(quote)

    if trade_count == 0 and total_pnl == s_decimal_0 and total_volume == s_decimal_0:
        return None

    return_pct = total_pnl / total_volume if total_volume != s_decimal_0 else s_decimal_0
    if len(quote_assets) == 1:
        total_pnl_display = f"{PerformanceMetrics.smart_round(total_pnl)} {next(iter(quote_assets))}"
    else:
        total_pnl_display = "N/A"
    return f"Trades: {trade_count}, Total P&L: {total_pnl_display}, Return %: {return_pct:.2%}"


def format_bytes(size):
    for unit in ["B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB"]:
        if abs(size) < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} YB"


async def start_timer(timer):
    count = 1
    while True:
        count += 1

        mins, sec = divmod(count, 60)
        hour, mins = divmod(mins, 60)
        days, hour = divmod(hour, 24)

        timer.log(f"Uptime: {days:>3} day(s), {hour:02}:{mins:02}:{sec:02}")
        await _sleep(1)


async def _sleep(delay):
    """
    A wrapper function that facilitates patching the sleep in unit tests without affecting the asyncio module
    """
    await asyncio.sleep(delay)


async def start_process_monitor(process_monitor):
    hb_process = psutil.Process()
    while True:
        with hb_process.oneshot():
            threads = hb_process.num_threads()
            process_monitor.log("CPU: {:>5}%, ".format(hb_process.cpu_percent()) +
                                "Mem: {:>10} ({}), ".format(
                                    format_bytes(hb_process.memory_info().vms / threads),
                                    format_bytes(hb_process.memory_info().rss)) +
                                "Threads: {:>3}, ".format(threads)
                                )
        await _sleep(1)


async def start_trade_monitor(trade_monitor):
    from hummingbot.client.hummingbot_application import HummingbotApplication
    hb = HummingbotApplication.main_application()
    trade_monitor.log("Trades: 0, Total P&L: 0.00, Return %: 0.00%")

    while True:
        try:
            if hb.trading_core._strategy_running and hb.trading_core.strategy is not None:
                if all(market.ready for market in hb.trading_core.markets.values()):
                    if _is_strategy_v2_instance(hb.trading_core.strategy):
                        run_start_time = _as_float_or_none(getattr(hb, "init_time", None))
                        strategy_v2_status = _strategy_v2_trade_monitor_status(
                            hb.trading_core.strategy,
                            run_start_time=run_start_time,
                        )
                        if strategy_v2_status is not None:
                            trade_monitor.log(strategy_v2_status)
                            await _sleep(2.0)
                            continue

                    with hb.trading_core.trade_fill_db.get_new_session() as session:
                        trades: List[TradeFill] = hb._get_trades_from_session(
                            int(hb.init_time * 1e3),
                            session=session,
                            config_file_path=hb.strategy_file_name)
                        if len(trades) > 0:
                            return_pcts = []
                            pnls = []
                            market_info: Set[Tuple[str, str]] = set((t.market, t.symbol) for t in trades)
                            for market, symbol in market_info:
                                cur_trades = [t for t in trades if t.market == market and t.symbol == symbol]
                                cur_balances = await hb.trading_core.get_current_balances(market)
                                perf = await PerformanceMetrics.create(symbol, cur_trades, cur_balances)
                                return_pcts.append(perf.return_pct)
                                pnls.append(perf.total_pnl)
                            avg_return = sum(return_pcts) / len(return_pcts) if len(return_pcts) > 0 else s_decimal_0
                            quote_assets = set(t.symbol.split("-")[1] for t in trades)
                            if len(quote_assets) == 1:
                                total_pnls = f"{PerformanceMetrics.smart_round(sum(pnls))} {list(quote_assets)[0]}"
                            else:
                                total_pnls = "N/A"
                            trade_monitor.log(f"Trades: {len(trades)}, Total P&L: {total_pnls}, "
                                              f"Return %: {avg_return:.2%}")
            await _sleep(2.0)  # sleeping for longer to manage resources
        except asyncio.CancelledError:
            raise
        except Exception:
            hb.logger().exception("start_trade_monitor failed.")
            await _sleep(2.0)


def format_df_for_printout(
    df: pd.DataFrame, table_format: ClientConfigEnum, max_col_width: Optional[int] = None, index: bool = False
) -> str:
    if max_col_width is not None:  # in anticipation of the next release of tabulate which will include maxcolwidth
        max_col_width = max(max_col_width, 4)
        df = df.astype(str).apply(
            lambda s: s.apply(
                lambda e: e if len(e) < max_col_width else f"{e[:max_col_width - 3]}..."
            )
        )
        df.columns = [c if len(c) < max_col_width else f"{c[:max_col_width - 3]}..." for c in df.columns]

    original_preserve_whitespace = tabulate.PRESERVE_WHITESPACE
    tabulate.PRESERVE_WHITESPACE = True
    try:
        formatted_df = tabulate.tabulate(df, tablefmt=table_format, showindex=index, headers="keys")
    finally:
        tabulate.PRESERVE_WHITESPACE = original_preserve_whitespace
    return formatted_df
