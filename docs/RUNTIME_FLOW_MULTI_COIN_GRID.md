# Runtime Flow: Start to Order Execution

This document describes the runtime path of your `multi_coin_grid_v2` strategy from process start to actual exchange order submission.

## 1. Process bootstrap

The usual headless entry point is `bin/hummingbot_quickstart.py`.

Main flow:

1. Parse CLI arguments such as `--config-file-name`, `--script-conf`, and `--headless`.
2. Load client config and unlock encrypted secrets.
3. Initialize logging and system config.
4. Create the singleton `HummingbotApplication`.
5. Load the selected strategy and ask `TradingCore` to start it.
6. Wait for Gateway if needed.
7. Run the application loop.

Relevant code:

- `bin/hummingbot_quickstart.py:83` `quick_start(...)`
- `bin/hummingbot_quickstart.py:138` `load_and_start_strategy(...)`
- `bin/hummingbot_quickstart.py:216` `run_application(...)`

## 2. App shell and trading core

`HummingbotApplication` is the application wrapper. It owns a `TradingCore` instance and delegates strategy lifecycle to it.

Relevant code:

- `hummingbot/client/hummingbot_application.py:54` `__init__(...)`
- `hummingbot/client/hummingbot_application.py:64` creates `TradingCore`

`TradingCore.start_strategy(...)` is the main runtime handoff point.

What happens there:

1. Detect whether the strategy is a regular strategy, script strategy, or V2 script.
2. For script/V2 strategies, import the script module and inspect its class.
3. Read the script class’ `markets` definition.
4. Initialize connectors for those markets.
5. Instantiate the strategy class.
6. Start the clock, add the strategy to the clock, and start supporting services like the rate oracle.

Relevant code:

- `hummingbot/core/trading_core.py:455` `start_strategy(...)`
- `hummingbot/core/trading_core.py:512` `_initialize_script_strategy(...)`
- `hummingbot/core/trading_core.py:538` `_start_strategy_execution(...)`
- `hummingbot/core/trading_core.py:576` `_run_clock(...)`

## 3. Script import-time setup

Your strategy file is `scripts/multi_coin_grid_v2.py`.

One important detail: this script does work at import time.

At the bottom of the file:

- `MultiCoinGridStrategyV2.markets = MultiCoinGridStrategyV2._load_markets_from_config()`

That means connector selection is decided before the strategy instance exists.

During `_load_markets_from_config()` the script:

1. Looks for config files such as `spot_grid_kraken_eur.yaml`.
2. Expands environment variables.
3. Chooses either:
   - a static whitelist of pairs, or
   - dynamic pair discovery using Kraken REST.
4. Falls back to a default seed list if discovery/config fails.

Relevant code:

- `scripts/multi_coin_grid_v2.py:74` `_load_markets_from_config(...)`
- `scripts/multi_coin_grid_v2.py:162` `_discover_pairs_sync(...)`
- `scripts/multi_coin_grid_v2.py:697` import-time `markets` assignment

Why this matters:

- startup can do network I/O before the bot is fully running
- the initial connector subscriptions are determined here
- runtime pair rotation later is narrower than “all exchange pairs” unless your own logic expands it

## 4. Strategy instantiation

After `TradingCore` has initialized markets/connectors, it instantiates your strategy class.

Your strategy extends `StrategyV2Base`:

- `scripts/multi_coin_grid_v2.py:55` `class MultiCoinGridStrategyV2(StrategyV2Base)`

Inside `StrategyV2Base.__init__`, Hummingbot creates:

1. `MarketDataProvider`
2. candles feeds from config
3. an `actions_queue`
4. controllers via `initialize_controllers()`
5. an `ExecutorOrchestrator`

Relevant code:

- `hummingbot/strategy/strategy_v2_base.py:176` `__init__(...)`
- `hummingbot/strategy/strategy_v2_base.py:188` `initialize_controllers()`

Your script overrides `initialize_controllers()` and does not rely on generic controller config loading.

It:

1. loads the custom YAML config via `ConfigManager`
2. expands env vars
3. switches connector name to `_paper_trade` if paper trading is enabled
4. builds `MultiCoinGridConfig`
5. instantiates `MultiCoinGridController`
6. stores it in `self.controllers["multi_coin_grid"]`

Relevant code:

- `scripts/multi_coin_grid_v2.py:396` `initialize_controllers(...)`

## 5. Clock starts and the strategy starts

When `TradingCore` starts execution, it adds connectors to the clock and then adds the strategy itself to the clock.

Relevant code:

- `hummingbot/core/trading_core.py:168` `start_clock(...)`
- `hummingbot/core/trading_core.py:552` `self.clock.add_iterator(self.strategy)`

Then the strategy `start(...)` method is called by the clock lifecycle.

In `StrategyV2Base.start(...)`:

1. initial settings are applied
2. MQTT publishing is optionally enabled
3. every controller is started

Relevant code:

- `hummingbot/strategy/strategy_v2_base.py:201` `start(...)`

Your script adds extra logging around this step:

- `scripts/multi_coin_grid_v2.py:574` `start(...)`

## 6. Controller runtime loop

Controllers are `RunnableBase` components with their own async control loop.

Base loop behavior:

1. `start()` sets status to running
2. `control_loop()` calls `on_start()`
3. then repeatedly calls `control_task()`
4. sleeps `update_interval` seconds between iterations

Relevant code:

- `hummingbot/strategy_v2/runnable_base.py:23` `RunnableBase`
- `hummingbot/strategy_v2/runnable_base.py:57` `control_loop(...)`

The generic `ControllerBase` normally only produces actions when market data is ready and `executors_update_event` is set.

Relevant code:

- `hummingbot/strategy_v2/controllers/controller_base.py:171` `control_task(...)`
- `hummingbot/strategy_v2/controllers/controller_base.py:180` `send_actions(...)`

Your controller overrides this with a much richer loop:

- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py:2211` `control_task(...)`

High-level responsibilities in your custom controller loop:

- risk guard / kill switch enforcement
- PnL period resets
- cooldown cleanup
- metrics calculation
- dynamic pair scanning
- memory cleanup
- trend updates and selection logic
- stop-loss / circuit-breaker / API-pause handling
- deciding whether to create, stop, or rotate executors

## 7. Decision stage: when a new grid is created

The main decision method is:

- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py:3495` `determine_executor_actions(...)`

This method:

1. syncs risk state
2. checks professional exit signals
3. blocks entries if time filters, regime filters, risk limits, circuit breakers, or API pause are active
4. evaluates monitored coins
5. picks the best candidate(s)
6. applies budget/risk/position/tradeability checks
7. creates one or more `CreateExecutorAction`s

The actual grid creation happens in:

- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py:8288` `_create_grid_action(...)`

That method builds a `GridExecutorConfig` using:

- current price from trend data
- ATR-based or fixed grid range
- dynamic grid count
- asymmetric range expansion
- stop-loss and take-profit settings
- adaptive no-fill timeout
- position sizing / min-order checks

It returns:

- `CreateExecutorAction(controller_id=..., executor_config=grid_config)`

Relevant config build point:

- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py:8676` `GridExecutorConfig(...)`
- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py:8718` `CreateExecutorAction(...)`

## 8. From controller action to live executor

There are two paths that can execute actions in Strategy V2:

### Path A: queued controller actions

`ControllerBase.send_actions(...)` puts action lists into the strategy’s shared `actions_queue`.

Relevant code:

- `hummingbot/strategy_v2/controllers/controller_base.py:180` `await self.actions_queue.put(executor_actions)`

`StrategyV2Base.listen_to_executor_actions()` consumes that queue and forwards actions to the `ExecutorOrchestrator`.

Relevant code:

- `hummingbot/strategy/strategy_v2_base.py:281` `listen_to_executor_actions(...)`

### Path B: direct strategy tick actions

`StrategyV2Base.on_tick()` also calls `determine_executor_actions()` on the strategy itself and executes those actions directly.

Relevant code:

- `hummingbot/strategy/strategy_v2_base.py:330` `on_tick(...)`

In your script, `create_actions_proposal()` returns an empty list, so the meaningful create/stop decisions are coming from the controller side, not from the script class itself:

- `scripts/multi_coin_grid_v2.py:600` `create_actions_proposal(...)`
- `scripts/multi_coin_grid_v2.py:608` `stop_actions_proposal(...)`

When the orchestrator receives a `CreateExecutorAction`, it:

1. looks up the executor class from `executor_config.type`
2. instantiates that executor
3. starts it immediately
4. stores it under the controller’s active executor list

Relevant code:

- `hummingbot/strategy_v2/executors/executor_orchestrator.py:354` `execute_action(...)`
- `hummingbot/strategy_v2/executors/executor_orchestrator.py:378` `create_executor(...)`

For your grids, the concrete class is `GridExecutor`.

## 9. GridExecutor lifecycle

`GridExecutor` extends `ExecutorBase`, which is also a `RunnableBase`.

Relevant code:

- `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py:38` `class GridExecutor(ExecutorBase)`
- `hummingbot/strategy_v2/executors/executor_base.py:27` `class ExecutorBase(RunnableBase)`

When the orchestrator calls `executor.start()`:

1. the executor starts its own async control loop
2. order-event listeners are registered on the connector
3. balance validation runs on startup

Relevant code:

- `hummingbot/strategy_v2/executors/executor_base.py:148` `start(...)`
- `hummingbot/strategy_v2/executors/executor_base.py:160` `on_start(...)`
- `hummingbot/strategy_v2/executors/executor_base.py:222` `register_events(...)`

The executor then manages:

- grid level generation
- open order placement
- close order placement
- retries, balance sync delays, emergency exits, timeouts, and early-stop behavior

## 10. The first actual order placement

The practical order submission path inside `GridExecutor` is:

1. build an `OrderCandidate`
2. adjust it against budget/trading rules
3. call `_validated_place_order(...)`
4. fall back to `place_order(...)` if validation is skipped or unavailable
5. that eventually calls connector `buy(...)` or `sell(...)`

Relevant code:

- `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py:405` `adjust_order_candidates(...)`
- `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py:1760` `adjust_and_place_open_order(...)`
- `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py:1788` `adjust_and_place_close_order(...)`
- `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py:178` `_validated_place_order(...)`

## 11. Connector submission path

At the connector layer, the order becomes asynchronous exchange submission work.

In `ExchangePyBase`:

1. `buy(...)` or `sell(...)` creates a client order id
2. schedules `_create_order(...)`
3. `_create_order(...)` quantizes amount/price and checks min size / min notional
4. `_place_order_and_process_update(...)` calls the exchange-specific `_place_order(...)`
5. the order tracker is updated to `OPEN`

Relevant code:

- `hummingbot/connector/exchange_py_base.py:260` `buy(...)`
- `hummingbot/connector/exchange_py_base.py:287` `sell(...)`
- `hummingbot/connector/exchange_py_base.py:391` `_create_order(...)`
- `hummingbot/connector/exchange_py_base.py:469` `_place_order_and_process_update(...)`
- `hummingbot/connector/exchange_py_base.py:640` abstract `_place_order(...)`

The base connector interface is defined in:

- `hummingbot/connector/connector_base.pyx:230` `buy(...)`
- `hummingbot/connector/connector_base.pyx:245` `sell(...)`

So the final execution step is exchange-connector specific, but the generic path is:

`MultiCoinGridController -> CreateExecutorAction -> ExecutorOrchestrator -> GridExecutor -> connector.buy/sell -> exchange API`

## 12. Event feedback after order submission

After submission, the executor listens for connector events such as:

- order created
- order filled
- order completed
- order cancelled
- order failure

Relevant code:

- `hummingbot/strategy_v2/executors/executor_base.py:48` event forwarders
- `hummingbot/strategy_v2/executors/executor_base.py:58` `_event_pairs`

This feedback updates executor state, which then flows back into:

- `ExecutorOrchestrator` reports
- `StrategyV2Base.update_executors_info()`
- controller `executors_info`
- next controller decision cycle

Relevant code:

- `hummingbot/strategy/strategy_v2_base.py:296` `update_executors_info(...)`

## 13. Important project-specific quirks

### Import path quirk

Your script imports custom code through symlinked `hummingbot` package paths:

- `scripts/multi_coin_grid_v2.py:15`

That means the runtime path looks native to `hummingbot`, but the ownership is actually in `multi_coin_grid_pro/`.

### Market bootstrap is not the same as runtime selection

The script-level `markets` selection only decides which pairs/connectors are initialized early.

The actual trading choice happens later in the controller via trend analysis and candidate selection:

- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py:3495`

### Your real “brain” is the controller

The script class is mostly a thin Strategy V2 wrapper.

The custom decision engine lives in:

- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`

That file owns the majority of runtime behavior, risk gating, coin rotation, and grid creation.

## 14. End-to-end summary

Short version:

1. `hummingbot_quickstart.py` boots the app.
2. `TradingCore.start_strategy(...)` imports `scripts/multi_coin_grid_v2.py`.
3. The script computes initial `markets` and connectors are initialized.
4. `MultiCoinGridStrategyV2` is instantiated.
5. It creates `MarketDataProvider`, `actions_queue`, `ExecutorOrchestrator`, and `MultiCoinGridController`.
6. The clock starts; the strategy starts; the controller starts its async loop.
7. The controller analyzes market/risk state and emits `CreateExecutorAction`.
8. `ExecutorOrchestrator` creates a `GridExecutor`.
9. `GridExecutor` builds and validates orders.
10. The connector submits `buy(...)` / `sell(...)` to the exchange-specific `_place_order(...)`.
11. Exchange/order events flow back into the executor and controller for the next decision cycle.

## 15. Best files to read in order

If you want to trace the runtime in code, this is the fastest reading order:

1. `bin/hummingbot_quickstart.py`
2. `hummingbot/core/trading_core.py`
3. `scripts/multi_coin_grid_v2.py`
4. `hummingbot/strategy/strategy_v2_base.py`
5. `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
6. `hummingbot/strategy_v2/executors/executor_orchestrator.py`
7. `hummingbot/strategy_v2/executors/grid_executor/grid_executor.py`
8. `hummingbot/connector/exchange_py_base.py`
