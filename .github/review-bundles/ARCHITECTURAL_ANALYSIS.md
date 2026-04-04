# Architectural Analysis: `multi_coin_grid_controller.py`

**File:** `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
**Lines:** 9,183
**Class:** `MultiCoinGridController(ControllerBase)`

---

## 1. Method Inventory (62 methods)

| # | Method | Lines | Async | Domain | State Access | I/O |
|---|--------|-------|-------|--------|--------------|-----|
| 1 | `__init__` | 117–730 (613 lines) | No | Initialization | Writes 80+ instance vars | No |
| 2 | `stop` | 731–743 | No | Lifecycle | Reads `telegram_alerter`, `pnl_tracker_v2` | No |
| 3 | `_log_decision_trace` | 745–819 | No | Observability | Reads `event_logger`, `debug_trace_enabled` | Writes file via event_logger |
| 4 | `_handle_parabolic_cooldown` | 821–857 | No | Cooldown Mgmt | Writes `parabolic_blacklist`, reads `cooldown_store` | DB write |
| 5 | `_calculate_portfolio_value` | 859–912 | No | Risk/Portfolio | Reads `connector._account_balances` (**private!**) | No |
| 6 | `_get_current_max_slots` | 913–955 | No | Slot Management | Reads `dynamic_slot_manager`, `market_regime_filter` | No |
| 7 | `_handle_api_error` | 956–1029 | Yes | Error Handling | Writes `consecutive_api_errors`, `api_error_paused`, etc. | No |
| 8 | `_api_call_with_error_handling` | 1031–1119 | Yes | Error Handling | Reads/writes error counters | Wraps exchange API calls |
| 9 | `_get_ticker_data_safe` | 1121–1185 | Yes | Market Data | Reads `connector`, `_last_ticker_call_time` | Exchange API |
| 10 | `_get_bitget_ticker_data` | 1187–1265 | Yes | Market Data | Reads `connector` | HTTP API (aiohttp) |
| 11 | `_initialize_components` | 1268–1514 | No | Initialization | Writes `connector`, `coin_discovery`, `trend_calculator`, etc. | No |
| 12 | `on_start` | 1516–1543 | Yes | Lifecycle | Reads `cooldown_store`, `parabolic_blacklist` | DB read |
| 13 | `_reconcile_external_fills` | 1545–1638 | Yes | State Reconciliation | Reads `connector`, `risk_manager` | Exchange API |
| 14 | `_detect_orphaned_positions` | 1640–1793 | Yes | State Reconciliation | Reads `connector._account_balances` (**private!**) | Exchange API |
| 15 | `_cleanup_stale_orders` | 1795–1897 | Yes | State Reconciliation | Reads `connector._in_flight_orders` (**private!**) | Exchange API |
| 16 | `control_task` | 1899–2280 | Yes | **Main Loop** | Reads/writes nearly everything | Memory profiling (psutil) |
| 17 | `update_processed_data` | 2282–2867 | Yes | Market Data / Coin Discovery | Reads/writes monitored_coins, trend_calculator | Exchange API |
| 18 | `_ensure_historical_data_loaded` | 2869–2938 | Yes | Market Data | Reads `market_data_provider`, `trend_calculator` | Candle API |
| 19 | `_refresh_coin_pool` | 2940–3008 | Yes | Coin Discovery | Reads `coin_discovery` | Exchange API |
| 20 | `_update_monitored_coins_from_pool` | 3010–3101 | Yes | Coin Discovery | Writes `monitored_coins`, `pair_volumes`, etc. | No |
| 21 | `_rotate_underperforming_coins` | 3103–3178 | No | Rotation Logic | Reads `trend_calculator`, writes `monitored_coins` | No |
| 22 | `determine_executor_actions` | 3180–4522 | No | **Core Decision Logic** (1,342 lines!) | Reads/writes nearly everything | No (delegates I/O) |
| 23 | `_get_executor_info` | 4524–4539 | No | Executor Lifecycle | Reads `executors_info` | No |
| 24 | `_is_executor_actually_active` | 4541–4703 | No | Executor Lifecycle (+ side effects!) | Writes `active_coins`, `session_blacklist`, exposure | No |
| 25 | `_should_bypass_grace_period` | 4705–4765 | No | Rotation Logic | Reads `_executor_creation_times` | No |
| 26 | `_can_safely_close_position` | 4767–4830 | No | Exit Logic | Reads `connector`, executor info | No |
| 27 | `_monitor_stop_loss_and_volatility` | 4832–4939 | No | Risk Management | Reads `entry_prices`, `trend_calculator` | No |
| 28 | `reset_circuit_breaker` | 4941–4954 | No | Risk Management | Writes `circuit_breaker_active` | No |
| 29 | `reset_api_errors` | 4956–4973 | No | Error Handling | Writes error counters | No |
| 30 | `_is_blacklisted` | 4975–4990 | No | Anti-Flipflop | Reads `session_blacklist` | No |
| 31 | `_add_to_blacklist` | 4992–5016 | No | Anti-Flipflop | Writes `session_blacklist` | No |
| 32 | `_purge_expired_blacklist` | 5018–5029 | No | Anti-Flipflop | Writes `session_blacklist` | No |
| 33 | `_get_blacklist_info` | 5031–5051 | No | Anti-Flipflop | Reads `session_blacklist` | No |
| 34 | `_sync_risk_state` | 5053–5259 | No | Risk/State Sync | Reads `executors_info`, writes `risk_manager` | File audit write |
| 35 | `_check_professional_exit_signals` | 5261–5419 | No | Risk/Exit | Reads `professional_risk_manager`, `active_coins` | No |
| 36 | `_compute_trend_strength` | 5421–5452 | No (static) | Trend Analysis | None (static method) | No |
| 37 | `_check_position_limits` | 5454–5561 | No | Risk Management | Reads `total_exposure`, `current_exposure_per_coin` | No |
| 38 | `_emit_execution_denial` | 5563–5591 | No | Observability | Reads `event_logger` | Event emission |
| 39 | `_emit_regime_denial` | 5593–5621 | No | Observability | Reads `event_logger` | Event emission |
| 40 | `_build_portfolio_risk` | 5623–5718 | No | Risk Management | Reads `connector`, `risk_manager`, `professional_risk_manager` | No |
| 41 | `_run_dynamic_pair_scan` | 5680–5718 | Yes | Coin Discovery | Reads `dynamic_pair_manager` | Exchange API |
| 42 | `_update_exposure_tracking` | 5720–5747 | No | Risk Management | Writes `current_exposure_per_coin`, `total_exposure` | No |
| 43 | `_should_create_new_grid` | 5749–6097 | No | Switch Decision (348 lines) | Reads trends, risk_manager, executor info | No |
| 44 | `_check_smart_switch_threshold_relaxed` | 6099–6141 | No | Switch Logic | Reads trend data | No |
| 45 | `_check_smart_switch_threshold` | 6143–6200 | No | Switch Logic | Reads trend data | No |
| 46 | `_check_switch_cost_relaxed` | 6202–6272 | No | Switch Logic | Reads trend data, `switch_costs` | No |
| 47 | `_check_switch_cost` | 6274–6375 | No | Switch Logic | Reads trend data, writes `switch_costs` | No |
| 48 | `_check_liquidity_requirements` | 6377–6413 | No | Liquidity Filter | Reads `pair_volumes`, `pair_spreads` | No |
| 49 | `_calculate_atr` | 6415–6464 | No | Volatility Calc | Reads trend price_history | No |
| 50 | `pick_first_inactive` | 6466–6487 | No | Multi-Coin Dedup | Reads `active_coins`, `auto_blacklisted_coins` | No |
| 51 | `_check_smart_entry_filter` | 6489–6563 | No | Entry Filter (dispatcher) | Reads `pair_health_monitor`, `staleness_guard` | No |
| 52 | `_build_orderbook_config` | 6565–6629 | No | Config Builder | Reads `market_regime_filter` | No |
| 53 | `_get_trade_direction_for_discovery` | 6631–6653 | No | Config Helper | Reads config | No |
| 54 | `_check_smart_entry_v2` | 6655–6755 | No | Entry Filter (v2) | Reads `smart_entry_v2`, `momentum_service`, candles | No |
| 55 | `_check_smart_entry_legacy` | 6757–6799 | No | Entry Filter (legacy) | Reads `smart_entry_filter` | No |
| 56 | `_calculate_smart_entry_indicators` | 6801–6849 | No | Indicator Calc | Reads `candle_calc`, trend candles | No |
| 57 | `_check_multi_timeframe_buy` | 6851–6925 | No | MTF Buy Check | Reads trend data, config | No |
| 58 | `_prefetch_orderbooks_shadow` | 6927–6984 | No | Orderbook Prefetch | Reads config, orderbook cache | No |
| 59 | `_is_orderbook_cached` | 6986–7011 | No | Orderbook Helper | Reads `connector` orderbook | No |
| 60 | `_subscribe_to_orderbook` | 7013–7058 | No | Orderbook Mgmt | Writes `tracker._trading_pairs` (**private!**) | No |
| 61 | `_initialize_orderbook` | 7060–7084 | Yes | Orderbook Mgmt | Writes `tracker._order_books` (**private!**) | Exchange API |
| 62 | `_calculate_volatility_based_grid_count` | 7086–7160 | No | Grid Sizing | Reads trend, grid_sizer_v2 | No |
| 63 | `_calculate_volatility_adjusted_position_size` | 7162–7234 | No | Position Sizing | Reads `trend_calculator`, `connector` mid_price | No |
| 64 | `_is_trading_pair_tradeable` | 7236–7347 | No | Pair Validation | Reads `connector`, writes `auto_blacklisted_coins` | No |
| 65 | `_check_spread_acceptable` | 7349–7466 | No | Spread Check | Reads connector orderbook | No |
| 66 | `_check_order_book_depth` | 7468–7566 | No | Depth Check | Reads connector orderbook | No |
| 67 | `_ensure_order_book_exists` | 7568–7687 | Yes | Orderbook Init | Writes tracker private attrs extensively (**private!**) | Exchange API |
| 68 | `_create_grid_action` | 7689–8160 | No | **Grid Creation** (471 lines) | Reads/writes many vars | Market data API |
| 69 | `_create_stop_action` | 8162–8290 | No | Executor Stop | Writes `active_coins`, `active_executor_id` | No |
| 70 | `to_format_status` | 8292–8472 | No | UI Display | Reads nearly all state | No |
| 71 | `_check_multi_timeframe_buy_conditions` | 8474–8717 | No | MTF Buy Logic (243 lines) | Reads `trend_calculator`, config | No |
| 72 | `should_exit_position` | 8719–8936 | No | **Pro Exit System** (217 lines) | Reads `entry_prices`, executor info, trends | No |
| 73 | `_detect_current_regime` | 8938–9017 | Yes | Regime Detection | Reads `trend_calculator`, `regime_detector` | No |
| 74 | `_apply_adaptive_filters` | 9019–9096 | No | Filter Tuning | Writes `smart_entry_v2.base_cfg` | No |
| 75 | `_check_multi_timeframe_exit_conditions` | 9098–9106 | No | **DEPRECATED** wrapper | Delegates to `should_exit_position` | No |
| 76 | `report_why_no_trade` | 9108–9127 | No | On-Demand Reporting | Reads `_console_reporter` | No |
| 77 | `report_by_stage` | 9129–9145 | No | On-Demand Reporting | Reads `_console_reporter` | No |
| 78 | `report_by_symbol` | 9147–9164 | No | On-Demand Reporting | Reads `_console_reporter` | No |
| 79 | `report_full_dashboard` | 9166–9183 | No | On-Demand Reporting | Reads `_console_reporter` | No |

**Totals: 79 methods** (62 `def` + 17 `async def`; grep finds 62 sync + 17 async = 79)

---

## 2. Instance Variable Count

**80+ instance variables** initialized in `__init__` (lines 117–730), categorized:

| Category | Count | Examples |
|----------|-------|---------|
| Connector/Exchange | 4 | `connector`, `base_connector`, `connectors`, `order_validator` |
| Coin Discovery & Monitoring | 8 | `coin_discovery`, `monitored_coins`, `all_available_pairs`, `pair_volumes`, `pair_spreads` |
| Trend & Indicators | 6 | `trend_calculator`, `candle_calc`, `smart_entry_filter`, `smart_entry_v2`, `momentum_service` |
| Active State Tracking | 8 | `active_coin`, `active_executor_id`, `active_coins` (dict), `last_switch_time`, `bot_start_time` |
| Risk Management | 8 | `risk_manager`, `professional_risk_manager`, `risk_guard_v2`, `drawdown_tracker` |
| Budget & Exposure | 6 | `budget_allocator`, `_next_allocation_quote`, `current_exposure_per_coin`, `total_exposure` |
| PnL Tracking | 5 | `pnl_tracker_v2`, `_last_pnl_reset_day/week/month` |
| Circuit Breaker & API Errors | 10 | `circuit_breaker_active`, `consecutive_api_errors`, `permanent_api_failure`, `api_error_paused`, etc. |
| Memory Management | 4 | `_executor_creation_timestamps`, `_trend_last_seen`, `_last_memory_cleanup_log` |
| Dynamic Slots | 1 | `dynamic_slot_manager` |
| Observability | 3 | `event_logger`, `_console_reporter`, `_last_report_time` |
| Grid Sizing | 3 | `dynamic_grid_sizer`, `grid_sizer_v2`, `_dynamic_num_grids` |
| Market Regime | 4 | `market_regime_filter`, `_market_regime_config`, `_market_regime_enabled`, `regime_detector` |
| Cooldowns & Blacklists | 5 | `cooldown_store`, `parabolic_blacklist`, `session_blacklist`, `auto_blacklisted_coins` |
| Telegram | 1 | `telegram_alerter` |
| Performance & Metrics | 3 | `performance_tracker`, `_last_metrics_calculation`, `filter_resolver` |
| Price/Grid Tracking | 5 | `entry_prices`, `last_grid_price`, `last_grid_creation_time`, `price_history_for_volatility` |
| Misc Flags | 6 | `_lookback_fix_applied`, `debug_trace_enabled`, `_last_smart_entry_trace`, etc. |

**Total: ~90 instance variables**

---

## 3. Imports Inside Methods (68 occurrences)

| Line | Method | Import | Notes |
|------|--------|--------|-------|
| 154 | `__init__` | `import traceback` | Error handler fallback |
| 219 | `__init__` | `from pathlib import Path` | MetricsCalculator setup |
| 331 | `__init__` | `from ...event_logger import compute_config_hash` | Lazy init |
| 349 | `__init__` | `from pathlib import Path` | **Duplicate** of line 219 |
| 351 | `__init__` | `from ...console_reporter import ConsoleReporter` | Lazy init |
| 616 | `__init__` | `from ...staleness_guard import StalenessGuard` | Lazy init |
| 631 | `__init__` | `from ...config_validator import ConfigValidator` | Lazy init |
| 647 | `__init__` | `from ...pair_health_monitor import PairHealthMonitor` | Lazy init |
| 666 | `__init__` | `from collections import deque` | Should be top-level |
| 673–674 | `__init__` | `from ...adaptive_filter_resolver`, `from ...regime_detector` | Lazy init |
| 691 | `__init__` | `import traceback` | **Duplicate** |
| 1199 | `_get_bitget_ticker_data` | `import aiohttp` | External HTTP lib |
| 1327 | `_initialize_components` | `from ...paper_trade import create_paper_trade_market` | Lazy |
| 1354 | `_initialize_components` | `from ...HummingbotApplication` | Lazy |
| 1654 | `_detect_orphaned_positions` | `import asyncio` | **Already top-level** |
| 1809 | `_cleanup_stale_orders` | `import time as time_module` | **Already top-level** |
| 1971, 1973 | `control_task` | `import os`, `import psutil` | Memory profiling |
| 2129 | `control_task` | `import gc` | Garbage collection |
| 5093 | `_sync_risk_state` | `from ...executors import CloseType` | |
| 5191 | `_sync_risk_state` | `from datetime import datetime` | **Already top-level** |
| 5223 | `_sync_risk_state` | `from ...executors import CloseType` | **Exact duplicate of 5093** |
| 5391 | `_check_professional_exit_signals` | `from ...executor_actions import StopExecutorAction` | **Already top-level** |
| 5472 | `_check_position_limits` | `import uuid` | **Already top-level** |
| 6211–6214 | `_check_switch_cost_relaxed` | `from decimal import Decimal` + 2 more | **All already top-level** |
| 6294–6297 | `_check_switch_cost` | `from decimal import Decimal` + 2 more | **Exact duplicates of 6211–6214** |
| 6524 | `_check_smart_entry_filter` | `from ...reason_codes import ReasonCode, Stage` | |
| 6671 | `_check_smart_entry_v2` | `from ...models import CandleIndicators` | |
| 7645 | `_ensure_order_book_exists` | `from ...TradingPair` | Paper trading |
| 7658 | `_ensure_order_book_exists` | `from ...events import OrderBookEvent` | |
| 7949 | `_create_grid_action` | `from ...common import TradeType` | **Already top-level** |
| — | **24× locations** | `import traceback` | Scattered across ~24 methods |

**Total: 68 import statements inside methods**
- **24** are `import traceback` (should be one top-level import)
- **~12** are duplicates of top-level imports (`Decimal`, `uuid`, `time`, `asyncio`, `datetime`, `TradeType`, etc.)
- **~10** are intentional lazy imports for optional components
- **~22** are unique imports that could potentially be moved to top-level

---

## 4. `time.time()` Usage (34 occurrences)

| Line | Method | Usage |
|------|--------|-------|
| 188 | `__init__` | `self.bot_start_time = time.time()` |
| 260 | `__init__` | `self.last_successful_api_call = time.time()` |
| 461 | `__init__` | `self._last_cooldown_cleanup = time.time()` |
| 597 | `__init__` | `self._last_performance_report_time = time.time()` |
| 837 | `_handle_parabolic_cooldown` | `expiry_ts = time.time() + cooldown_sec` |
| 965 | `_handle_api_error` | `current_time = time.time()` |
| 1049 | `_api_call_with_error_handling` | `time_since_pause = time.time() - ...` |
| 1058 | `_api_call_with_error_handling` | `time_since_last_error = time.time() - ...` |
| 1073 | `_api_call_with_error_handling` | `self.last_successful_api_call = time.time()` |
| 1141 | `_get_ticker_data_safe` | `current_time = time.time()` |
| 1155 | `_get_ticker_data_safe` | `self._last_ticker_call_time = time.time()` |
| 1170 | `_get_ticker_data_safe` | `self.last_successful_api_call = time.time()` |
| 1176 | `_get_ticker_data_safe` | `self._last_ticker_call_time = time.time()` |
| 1258 | `_get_bitget_ticker_data` | `self.last_successful_api_call = time.time()` |
| 1528 | `on_start` | `remaining = int(expiry_ts - time.time())` |
| 1927 | `control_task` | `current_time = time.time()` |
| 2217 | `control_task` | `current_time = time.time()` |
| 2247 | `control_task` | `current_time = time.time()` |
| 2408 | `update_processed_data` | `now_ts = time.time()` |
| 2653 | `update_processed_data` | `self._last_coin_discovery = time.time()` |
| 2731 | `update_processed_data` | `now_ts = time.time()` |
| 2798 | `update_processed_data` | `time_since_last_discovery = time.time() - ...` |
| 2805 | `update_processed_data` | `self._last_coin_discovery = time.time()` |
| 2814 | `update_processed_data` | `time_since_last_update = time.time() - ...` |
| 2833 | `update_processed_data` | `self._last_trend_update = time.time()` |
| 2887 | `_ensure_historical_data_loaded` | `if time.time() - last_check < ...` |
| 2890 | `_ensure_historical_data_loaded` | `self._last_historical_check = time.time()` |
| 4316 | `determine_executor_actions` | `timestamp=time.time()` |
| 4502 | `determine_executor_actions` | `timestamp=time.time()` |
| 5402 | `_check_professional_exit_signals` | `correlation_id=f"exit_..._{int(time.time())}"` |
| 5835 | `_should_create_new_grid` | `time_since_start = time.time() - self.bot_start_time` |
| 5855 | `_should_create_new_grid` | `"timestamp": time.time()` |
| 6503 | `_check_smart_entry_filter` | `remaining = (info.release_at - time.time()) / 60` |
| 6532 | `_check_smart_entry_filter` | `correlation_id=f"staleness_..._{time.time()}"` |

**Violation:** The repo conventions (`.github/copilot-instructions.md`) explicitly state: *"No direct `time.time()` in core logic: use injectable clock."* The `market_data_provider.time()` is used in some places but `time.time()` is used in 34 other locations, creating a **non-deterministic** codebase that **cannot be replayed or backtested**.

---

## 5. Connector Private Attribute Access (33 occurrences)

| Line(s) | Method | Private Attribute | Risk |
|---------|--------|---------|------|
| 883 | `_calculate_portfolio_value` | `connector._account_balances` | Fragile — internal API |
| 1161–1168 | `_get_ticker_data_safe` | `connector._get_ticker_data` | Internal method |
| 1673 | `_detect_orphaned_positions` | `connector._account_balances` | Fragile |
| 1820 | `_cleanup_stale_orders` | `connector._in_flight_orders` | Fragile |
| 7034–7049 | `_subscribe_to_orderbook` | `tracker._trading_pairs`, `tracker._data_source._trading_pairs`, `tracker._order_books` | **Deeply coupled** |
| 7072–7075 | `_initialize_orderbook` | `tracker._initial_order_book_for_trading_pair`, `tracker._order_books` | **Deeply coupled** |
| 7605–7661 | `_ensure_order_book_exists` | `tracker._trading_pairs`, `tracker._data_source._trading_pairs`, `tracker._order_books`, `tracker._tracking_message_queues`, `tracker._tracking_tasks`, `tracker._track_single_book`, `connector._trading_pairs`, `connector._target_market`, `connector._order_book_trade_listener` | **Extremely fragile — 10+ private attrs** |
| 7236 | `_is_trading_pair_tradeable` | `connector._trading_pairs` | Fragile |

The `_ensure_order_book_exists` method at line 7568 is the worst offender, accessing **10+ private attributes** of the connector and its order book tracker, making it extremely vulnerable to upstream changes.

---

## 6. Domain Groupings

| Domain | Methods | Lines (approx) | % of File |
|--------|---------|----------------|-----------|
| **Core Decision Logic** | `determine_executor_actions` | ~1,342 | 14.6% |
| **Initialization & Lifecycle** | `__init__`, `_initialize_components`, `on_start`, `stop` | ~900 | 9.8% |
| **Grid Creation & Management** | `_create_grid_action`, `_create_stop_action`, `_calculate_volatility_based_grid_count`, `_calculate_atr`, position sizing | ~700 | 7.6% |
| **Switch/Rotation Decision** | `_should_create_new_grid`, `_check_smart_switch_*` (×2), `_check_switch_cost*` (×2), `_check_liquidity_requirements`, `_rotate_underperforming_coins` | ~650 | 7.1% |
| **Entry Filters** | `_check_smart_entry_filter`, `_check_smart_entry_v2`, `_check_smart_entry_legacy`, `_calculate_smart_entry_indicators`, `_check_multi_timeframe_buy`, `_check_multi_timeframe_buy_conditions` | ~650 | 7.1% |
| **Risk Management** | `_monitor_stop_loss_and_volatility`, `_check_position_limits`, `_build_portfolio_risk`, `_update_exposure_tracking`, `_sync_risk_state`, `_check_professional_exit_signals`, `reset_circuit_breaker` | ~600 | 6.5% |
| **Exit System** | `should_exit_position`, `_can_safely_close_position`, `_check_multi_timeframe_exit_conditions` | ~280 | 3.0% |
| **Market Data & I/O** | `_get_ticker_data_safe`, `_get_bitget_ticker_data`, `update_processed_data`, `_ensure_historical_data_loaded` | ~700 | 7.6% |
| **Coin Discovery** | `_refresh_coin_pool`, `_update_monitored_coins_from_pool`, `_run_dynamic_pair_scan`, `pick_first_inactive` | ~200 | 2.2% |
| **State Reconciliation** | `_reconcile_external_fills`, `_detect_orphaned_positions`, `_cleanup_stale_orders` | ~350 | 3.8% |
| **Orderbook Management** | `_prefetch_orderbooks_shadow`, `_is_orderbook_cached`, `_subscribe_to_orderbook`, `_initialize_orderbook`, `_ensure_order_book_exists`, `_check_spread_acceptable`, `_check_order_book_depth`, `_is_trading_pair_tradeable`, `_build_orderbook_config` | ~600 | 6.5% |
| **Error Handling / API** | `_handle_api_error`, `_api_call_with_error_handling`, `reset_api_errors` | ~200 | 2.2% |
| **Anti-Flipflop / Blacklist** | `_is_blacklisted`, `_add_to_blacklist`, `_purge_expired_blacklist`, `_get_blacklist_info`, `_handle_parabolic_cooldown` | ~100 | 1.1% |
| **Observability & Reporting** | `_log_decision_trace`, `_emit_execution_denial`, `_emit_regime_denial`, `to_format_status`, `report_*` (×4) | ~350 | 3.8% |
| **Main Loop & Memory** | `control_task` (incl. memory cleanup) | ~380 | 4.1% |
| **Regime & Adaptive** | `_detect_current_regime`, `_apply_adaptive_filters`, `_get_trade_direction_for_discovery` | ~200 | 2.2% |
| **Portfolio/Slot** | `_calculate_portfolio_value`, `_get_current_max_slots` | ~100 | 1.1% |

---

## 7. Architectural Anti-Patterns

### 7.1 God Class
- **Single class: 9,183 lines, 79 methods, ~90 instance variables**
- Handles: coin discovery, trend analysis, entry filtering, risk management, grid creation, exit logic, state reconciliation, memory management, observability, UI formatting, API error handling, orderbook management, regime detection, and reporting
- **Recommendation:** Extract into ~10 focused collaborator classes (SwitchDecisionEngine, EntryGatekeeper, RiskCoordinator, OrderbookManager, GridFactory, ExecutorLifecycleManager, etc.)

### 7.2 God Method: `determine_executor_actions()` (1,342 lines)
- Lines 3180–4522 — the entire decision pipeline in a single method
- Interleaves: active executor checks, exit signals, multi-coin iteration, entry filtering, MTF checks, regime checks, risk checks, spread checks, depth checks, grid creation, and exposure tracking
- **Recommendation:** Decompose into a pipeline of ~8 stages, each <100 lines

### 7.3 Massive `__init__` (613 lines)
- Lines 117–730 — initializes ~90 instance variables, creates ~15 collaborator objects inline with try/except blocks
- Many lazy imports inside __init__ to avoid circular deps
- **Recommendation:** Use a builder pattern or factory; group instance vars into dataclasses

### 7.4 Query Method With Side Effects: `_is_executor_actually_active()`
- Line 4541 — named as a query (`is_*`) but performs:
  - Blacklist additions
  - Error counter increments
  - State dict clearing (`active_coins`, `active_executor_id`)
  - Exposure reset
  - Budget release
- **Recommendation:** Split into `is_executor_active()` (pure query) and `handle_executor_terminated()` (mutation)

### 7.5 `time.time()` Scattered Everywhere (34 calls)
- Violates repo invariant: *"No direct `time.time()` in core logic: use injectable clock"*
- `self.market_data_provider.time()` is available and used in some places but not consistently
- Makes backtesting/replay **impossible** for affected code paths
- **Recommendation:** Replace all 34 `time.time()` with `self.market_data_provider.time()` or an injected clock

### 7.6 Massive Connector Private API Coupling (33 accesses)
- Accesses `_account_balances`, `_in_flight_orders`, `_get_ticker_data`, `_trading_pairs`, `_order_books`, `_data_source._trading_pairs`, `_tracking_message_queues`, `_tracking_tasks`, `_track_single_book`, `_target_market`, `_order_book_trade_listener`, `_initial_order_book_for_trading_pair`
- Any Hummingbot connector refactor will break this code
- **Recommendation:** Use public connector API or create an adapter/facade

### 7.7 Import Pollution (68 imports inside methods)
- 24 `import traceback` scattered across methods (should be 1 top-level)
- ~12 redundant re-imports of already top-level modules (`Decimal`, `uuid`, `asyncio`, `datetime`, `TradeType`)
- Duplicate imports within same method (`CloseType` imported twice in `_sync_risk_state`)
- **Recommendation:** Move all to top-level; use `# noqa: F401` for intentional re-exports

### 7.8 Inline Memory Management (200+ lines in `control_task`)
- Lines ~1930–2200 — raw `psutil`, `gc.collect()`, manual dict pruning inline
- **Recommendation:** Extract to a `MemoryManager` class

### 7.9 Dead/Deprecated Code
- `_check_multi_timeframe_exit_conditions` (line 9098) — explicitly marked DEPRECATED, delegates to `should_exit_position()`
- Duplicate MONITORING log blocks in `to_format_status` (lines ~8453–8462 are copy-pasted)
- `_check_multi_timeframe_buy` (line 6851) appears to overlap significantly with `_check_multi_timeframe_buy_conditions` (line 8474) — two similar methods for the same purpose

### 7.10 Mixed Natural Language
- Dutch comments mixed with English: `"Forceer rotatie naar volgende coin"`, `"Parabolic cooldown"`
- Magic numbers scattered despite repo rule against them (e.g., `0.31` fee estimate, `0.5` min profit threshold, `0.3` block threshold, `600.0` hard min hold)
- **Recommendation:** Move all magic numbers to config; standardize to English comments

### 7.11 Discarded Expression (Bug)
- Line ~8844 in `should_exit_position`: `price_change_pct - estimated_fees_pct` — the result is computed but **never assigned to anything** (a no-op expression)

---

## 8. Summary Statistics

| Metric | Value |
|--------|-------|
| Total lines | 9,183 |
| Total methods | 79 (62 sync + 17 async) |
| Instance variables in `__init__` | ~90 |
| Imports inside methods | 68 |
| `time.time()` calls | 34 |
| Connector private attr accesses | 33 |
| Largest method | `determine_executor_actions()` — 1,342 lines |
| Second largest | `__init__` — 613 lines |
| Third largest | `_create_grid_action` — 471 lines |
| Deprecated methods | 1 (`_check_multi_timeframe_exit_conditions`) |
| Duplicate method pairs | 1 (`_check_multi_timeframe_buy` vs `_check_multi_timeframe_buy_conditions`) |
| Discarded expressions (bugs) | 1 (line ~8844) |
