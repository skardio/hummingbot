# Copilot Instructions — Trading Bot Repo

## Related documents
- **Analysis context**: See `.github/analysis-context.md` for log paths, database locations, and analysis commands.
- **Agents**: See `.github/agents/` for specialized planner, implementer, and reviewer agents.

## High-level principles
- Safety first: never introduce code paths that can place real orders without explicit enable flags.
- **NEVER kill, stop, or restart running bot processes** - only the operator may do this manually.
- Config-driven behavior: strategies and risk parameters must be configurable.
- Deterministic tests: no network calls, no wall-clock dependencies in tests.

## Repo conventions
- Python 3.11+, strict typing where feasible.
- Prefer `dataclasses` or `pydantic` for configuration models.
- Use structured logging (log dict-like payloads).
- Keep strategy logic pure (no exchange calls in strategy module).

## Code quality (flake8)
- All code MUST pass `flake8` before commit (enforced by pre-commit hook).
- **F401**: No unused imports — remove or use `# noqa: F401` only when the import is intentional (re-exports, type stubs).
- **F841**: No unused local variables — delete or prefix with `_` if intentionally ignored.
- **F541**: No f-strings without placeholders — use a plain string instead.
- **E402**: Module-level imports must be at top of file — use `# noqa: E402` only after necessary `sys.path` manipulation.
- Run `flake8 <file>` to verify before committing.

## Trading invariants
- Every order must be validated against:
  - min_notional
  - min_qty
  - tick_size/step_size rounding
  - max_exposure constraints
- All order submissions must be idempotent:
  - compute an `order_intent_id` from deterministic inputs
  - store intent -> submit -> reconcile on restart
- On startup:
  - load open orders
  - load positions
  - reconcile local state vs exchange state
  - do not trade until “warmup_complete”

## Risk management requirements
- Implement and respect:
  - per-symbol max notional
  - portfolio max notional
  - max daily loss / drawdown kill switch
  - max open orders per symbol
- Fail closed: if risk module errors -> block trading.

## Testing
- Unit tests for:
  - rounding utils
  - exposure calculations
  - kill switch decisions
  - signal generation
- Integration tests using mocked exchange adapter.

## Observability
- Emit structured logs for:
  - signals, risk blocks, orders, fills, pnl, errors
- Provide metrics hooks for:
  - orders (placed/canceled/rejected)
  - pnl/drawdown
  - exposure
  - latency

## What to avoid
- No hidden magic constants: all thresholds in config.
- No silent exception swallowing.
- No direct `time.time()` in core logic: use injectable clock.

## Circuit breakers
- Exchange connectivity: timeout after configurable duration, halt trading on disconnect.
- Rate limit handling: respect exchange rate limits, implement exponential backoff.
- Abnormal spread detection: pause trading if bid-ask spread exceeds threshold.
- Stale data protection: do not trade on orderbook data older than `max_data_age_ms`.

## Position sizing
- Configurable sizing method: fixed fractional, Kelly criterion, or manual.
- Volatility adjustment: scale position size inversely with recent volatility if enabled.
- Never exceed `max_position_size_pct` of portfolio per symbol.
- Include slippage buffer in min_notional validation.

## Concurrency & state
- Order fills may arrive during strategy tick: use event queue, not direct mutation.
- State mutations must be atomic: lock or serialize access to positions/orders.
- Async operations: await exchange calls, don't fire-and-forget.
- Handle partial fills: update position incrementally, recompute exposure.

## Replay & backtesting
- Support event sourcing: log all inputs (market data, signals, orders, fills) for replay.
- Deterministic replay: same inputs must produce same outputs.
- Historical data: require OHLCV + orderbook snapshots for realistic backtest.
- Time simulation: use injectable clock for backtesting, never wall-clock.

## Versioning & migrations
- Config schema versioning: include `schema_version` in all config files.
- State migration: provide upgrade scripts when state format changes.
- Backward compatibility: support loading configs from N-1 version.
- Breaking changes: fail fast with clear error if incompatible version detected.

## Warmup criteria
- `warmup_complete` requires:
  - open orders loaded and reconciled
  - positions synced with exchange
  - required market data buffers filled (e.g., N candles for indicators)
  - risk module initialized and healthy
- Log warmup progress: "warmup 3/4: waiting for market data"
