# Professional Bot Review Prompt — Multi-Coin Grid Pro

> Use this in 4 rounds. Each round focuses on one domain.
> Provide the listed attachments with each round.
> **This system runs 3 active bots** — evaluate all three.

---

## Round 1: Strategy & Profitability Review

```
Act as a senior quantitative crypto trading engineer with deep expertise
in grid trading strategies, mean-reversion systems, and systematic
trend-following. You specialize in evaluating whether a trading strategy
has genuine edge after all costs.

## What this bot system is

A multi-coin adaptive grid trading bot built on Hummingbot's StrategyV2
framework (GridExecutor). It does NOT do arbitrage. It is a grid trader
with trend-based coin rotation, running as 3 separate bot instances:

### Bot 1: Kraken USD (spot)
- Dynamic coin discovery (25 monitored USD pairs)
- €300 capital, 6 max slots (usually capped to 4 by min order size)
- Grid: 5–7 levels, ATR-based asymmetric ranges
- Risk Manager currently BLOCKING: 30% WR, −0.44% rolling PnL → paused
- WebSocket errors (112 in current log session)

### Bot 2: Bitget USDT (spot)
- Dynamic coin discovery + manual pair fallback
- ~$100 capital, currently BLOCKED: $3.62 free < $30 minimum
- SONIC stuck LIMIT SELL @ $0.046419 (1533 units) locking ~$71
- Cannot trade until stuck order is manually cancelled

### Bot 3: Bitget Futures (perpetual)
- 37 manual USDT pairs, 3× leverage, HEDGE mode
- ~$50 capital, currently BLOCKED: $9.09–$9.25 < $15 minimum
- Direction: AUTO (long/short based on trend)
- Exchange-side TPSL orders (survives bot crashes)

### Shared mechanics (all 3 bots):
1. **Trend-based coin selection** — ranks coins by multi-indicator consensus
   trend score (EMA + linear regression + volatility-normalized + raw %),
   weighted across 1h/4h/24h timeframes
2. **Grid deployment** — places grid levels with ATR-based asymmetric
   ranges (down: 1.5×ATR / up: 2.0×ATR), or fixed fallback (−4% to +12%)
3. **Regime detection** — classifies market as BULL/CHOP/BEAR using
   consensus×0.80 + ATR_expansion×0.20, with hysteresis buffers
4. **Coin rotation** — switches coins when better trends appear, with
   smart-switch cost analysis, cooldowns, and session blacklists
5. **Multi-layer exit** — profit tiers (1%→breakeven, 2%→+0.7%, 3%→+1.5%),
   soft hold (2h trend-aware), hard hold (6h forced), emergency exit (−12%)
6. **Entry filters** — RSI, VWAP, ATR, spike detection, parabolic filter,
   BTC macro filter, multi-timeframe confirmation

## Actual performance data

> **Attach the latest data snapshot** with this round.
> File: `.github/data-snapshot-YYYY-MM-DD.md`
> Re-run the queries in that file before each review to get fresh data.
> Latest available: `.github/data-snapshot-2026-03-08.md`
>
> The snapshot contains: per-pair performance, close type distributions,
> error frequencies, WHY-NO-TRADE summaries, rotation timeout logs,
> and all SQL queries + bash commands to regenerate it.

## What I need you to evaluate

### 1. Does this strategy have real edge?
- Grid trading profits from mean-reversion within the grid range
- But the bot SELECTS coins by TREND — is there a contradiction?
  Trending coins move directionally; grids profit from oscillation.
  When does this combination work? When does it fail?
- **DATA SHOWS: 97–99% of executors never get a single fill.**
  The bot creates grids but they expire unfilled. Is the grid range
  too narrow? Are the entry filters killing the strategy?
- After Kraken fees (~0.16–0.26%), spread, and slippage, what is
  the realistic per-grid expected value? Current evidence: −€73 over
  2,216 executors with €2,236 volume = effectively near-zero edge.

### 2. Why is the fill rate so low?
- Current WHY-NO-TRADE data (today, March 8):
  - NO_ORDERBOOK_DATA: 35–44% of rejections (persistent)
  - RSI_OVERBOUGHT: 7–30% of rejections
  - SPREAD_TOO_WIDE: 0.1–9%
  - STALE_PRICE: 0.5–6%
- Kraken USD: close type 7 (no-fill timeout) = 210/212 executors
- Is the grid range too tight? Are the filters too restrictive?
- The bot approves 15–56% of intents hourly but still can't fill grids

### 3. Coin rotation: edge or overhead?
- Rotation is actively happening but dysfunctional:
  - Bitget Spot: SONIC-USDT stuck in 3-min rotation loop (21+ timeouts)
  - Kraken USD: SUI-USD hitting monitoring timeout repeatedly
- Rotation has costs: unrealized losses on exit, spread on new entry
- The bot uses 180-update timeout + 600s min switch interval
- Is this too aggressive? Evidence shows constant churn without fills

### 4. Capital adequacy problem
- Kraken USD: €300 → "Dynamic slots capped by min order size: 6→4"
- Bitget Spot: $3.62 free < $30 minimum (SONIC stuck order blocks $71)
- Bitget Futures: $9.09 < $15 minimum
- 2 of 3 bots are currently UNABLE TO TRADE due to capital constraints
- Is €300–€500 viable for this strategy at all?

### 5. Futures performance: is 3× leverage hiding a flawed strategy?
- 96% of filled futures trades closed via stop-loss (close type 8)
- ETH-USDT: 3 filled trades, all losses, −$62.78 total
- BTC-USDT: 3 filled trades, all losses, −$28.84 total
- SOL-USDT: only consistently profitable pair (+$9.31 from 2 fills)
- Total futures PnL: −$155 on $50 capital = −310% return
- Is the grid-on-futures approach fundamentally unsuitable?

### 6. Regime detector: effective or just adding complexity?
- BULL threshold: score ≥ 5.0, BEAR: < −3.0, CHOP: between
- During BEAR: slots reduce to 0.25× (1 slot for small capital)
- Risk Manager blocks SUI-USD repeatedly: "WR 30.0%, PnL −0.44%"
- Question: does the regime detector + risk manager effectively
  prevent the bot from ever trading? Is there a feedback loop where
  losses → pause → miss recovery → more losses?

## Attachments I'll provide
- [ ] Main controller source (9,182 lines)
- [ ] Production config YAMLs (Kraken USD + Bitget Spot + Bitget Futures)
- [ ] **Data snapshot** (`.github/data-snapshot-YYYY-MM-DD.md` — freshly generated)
- [ ] Error frequency summaries (included in data snapshot)

## Output format requirements (apply to all findings)

For every major conclusion, provide an evidence table:

| Finding | Evidence (code/config/logs/data) | Impact | Recommendation | Confidence (high/med/low) |
|---------|----------------------------------|--------|----------------|---------------------------|
| ...     | ...                              | ...    | ...            | ...                       |

Separate clearly between:
- **Confirmed findings** — directly proven from code, logs, or data
- **Reasonable inferences** — likely true but not fully proven
- **Unknowns** — requires more data to determine (state what data is needed)

For each recommendation, rate:
- **Impact on PnL** (high / medium / low)
- **Impact on safety** (high / medium / low)
- **Implementation effort** (hours / days / weeks)
- **Urgency** (immediate / next sprint / backlog)

## What to keep
Identify which parts of the strategy design are worth preserving, and why.
Not everything needs to change — call out what works well and should NOT
be refactored away.

## Capital scaling verdict
Based on your reviewed evidence, state the maximum capital range you
would currently trust this bot with:
- [ ] Paper trading only
- [ ] Small live capital (< €500)
- [ ] Medium live capital (€500–€5,000)
- [ ] Larger serious capital (€5,000–€50,000)
- [ ] Professional capital (> €50,000)

Explain why, and what must change to move to the next tier.

## Expected output
1. **Edge assessment**: real edge, marginal edge, or no edge — with math
2. **Strategy contradictions**: where trend selection conflicts with grid mechanics
3. **Optimal operating conditions**: when this strategy works and when it doesn't
4. **Top 5 profitability leaks** with estimated impact (evidence table format)
5. **Concrete parameter suggestions** (grid levels, range, rotation frequency, regime thresholds)
6. **What to keep**: design decisions that are sound and should be preserved
7. **Capital scaling verdict**: current tier + what's needed for next tier
```

---

## Round 2: Architecture & Code Quality Review

```
Act as a senior Python software architect with expertise in async
trading systems, Hummingbot's StrategyV2 framework, and production
bot design. You have built and maintained trading systems handling
$10M+ daily volume.

## Architecture overview

| Component | Lines | Files | Purpose |
|-----------|-------|-------|---------|
| Controller (God class) | 9,182 | 1 | Everything: discovery, trends, filtering, risk, grids, monitoring, switching, reporting |
| Config model | 1,610 | 1 | Pydantic config with 200+ parameters |
| Utils | 7,595 | 21 | Trend calc, pair mgmt, order validation, regime detection, budget allocation |
| Monitoring | 3,190 | 10 | Telegram, dashboard, SQLite monitoring (335 MB production DB) |
| Core | 2,436 | 10 | Risk mgmt, drawdown, performance tracking |
| Filters | 1,765 | 6 | Smart entry, regime, parabolic, time-based |
| Observability | 1,700 | 5 | Event logging, console reporting, why-no-trade diagnostics |
| Logic | 1,184 | 6 | Coin selection, grid building, liquidity sizing |
| Risk | 968 | 4 | PnL tracker, risk manager, risk guard |
| Futures variant | 2,382 | 5 | Bitget perpetual futures specific |
| Tests | 25,551 | 87 | Unit + integration tests |
| **Total** | **~63,600** | **~190** | |

**Critical architectural fact:** The entire codebase is duplicated:
- `multi_coin_grid_pro/` — development package
- `hummingbot/multi_coin_grid_controllers/` + `hummingbot/multi_coin_grid_utils/` — deployed copy

Both are byte-identical (manually synced). ~18,700 lines duplicated.

**3 bot instances share the same controller code** with different configs:
- Kraken USD: `spot_grid_kraken_usd.yaml` (831 lines)
- Bitget Spot: `spot_grid_bitget.yaml`
- Bitget Futures: `futures_grid_bitget.yaml` (extends base controller)

**4 SQLite databases** with real trade data:
- `multi_coin_grid_v2.sqlite` (12 MB, Kraken EUR — historical)
- `multi_coin_grid_v2_usd.sqlite` (8 MB, Kraken USD)
- `spot_grid_bitget.sqlite` (6 MB, Bitget spot)
- `futures_grid_bitget.sqlite` (3 MB, Bitget futures)

## What I need you to evaluate

### 1. The God-class problem
- `MultiCoinGridController` is 9,182 lines, 79 methods, one file
- It handles: coin discovery, trend ranking, regime classification,
  entry filtering, grid creation, executor management, position tracking,
  budget allocation, risk checks, coin rotation, smart switching,
  orphan detection, stale order cleanup, monitoring, status reporting
- What should be extracted? Propose a concrete decomposition with
  class boundaries and dependency diagram

### 2. Full code duplication
- Two identical copies manually synced
- No symlinks, no package references, no build step
- What is the proper solution? Consider that the bot needs to work
  both as a standalone dev package and inside Hummingbot's plugin system

### 3. State management complexity
- State is scattered across: instance variables (~50+), SQLite DBs (5+),
  in-memory dicts, connector private attributes (`_in_flight_orders`,
  `_account_balances`)
- Accessing connector private attributes (`_in_flight_orders`) is fragile
- No clear state machine or lifecycle diagram

### 4. Async patterns
- The main loop is `determine_executor_actions()` called by Hummingbot's
  event loop. Inside it does sync-blocking work (trend calculations,
  DB queries) mixed with async calls
- Rate limiting via `time.time()` checks instead of proper async throttling
- `time` module imported inside methods instead of top-level

### 5. Config surface area
- 831-line YAML, 1,610-line Pydantic model, 200+ parameters
- Many params interact non-obviously (regime thresholds × filter thresholds
  × slot scaling × grid sizing = combinatorial explosion)
- Is this configurable or is it effectively un-tunable?

### 6. Test quality
- 87 test files, 25,551 lines — coverage unknown
- Real Telegram integration tests mixed with unit tests (no @pytest.mark.integration)
- How well do the tests cover the critical paths?

## Attachments I'll provide
- [ ] Full controller source (9,182 lines)
- [ ] Config model source (1,610 lines)
- [ ] Directory tree of multi_coin_grid_pro/
- [ ] 3 representative test files
- [ ] Budget allocator source (shows Decimal precision pattern)

## Output format requirements (apply to all findings)

For every major conclusion, provide an evidence table:

| Finding | Evidence (code/config/logs/data) | Impact | Recommendation | Confidence (high/med/low) |
|---------|----------------------------------|--------|----------------|---------------------------|
| ...     | ...                              | ...    | ...            | ...                       |

Separate clearly between:
- **Confirmed findings** — directly proven from code, logs, or data
- **Reasonable inferences** — likely true but not fully proven
- **Unknowns** — requires more data to determine (state what data is needed)

For each recommendation, rate:
- **Impact on PnL** (high / medium / low)
- **Impact on safety** (high / medium / low)
- **Implementation effort** (hours / days / weeks)
- **Urgency** (immediate / next sprint / backlog)

## What to keep
Identify which modules, patterns, or design choices are well-implemented
and should be preserved during any refactoring. Explain why they work.

## Expected output
1. **Architecture score** (1–10) with justification
2. **Decomposition proposal**: concrete class extraction plan for the God class
3. **Duplication solution**: recommended approach with trade-offs
4. **State management redesign**: what a clean state model looks like
5. **Top 10 code quality issues** ranked by severity (evidence table format)
6. **Technical debt inventory** with estimated effort to fix
7. **What to keep**: modules/patterns that are well-designed and should survive refactoring
```

---

## Round 3: Risk Management & Failure Modes

```
Act as a trading risk engineer who has managed risk systems for
crypto market makers and prop desks. You think in terms of worst-case
scenarios, tail risks, and "what happens when everything goes wrong
at the same time."

## Current risk controls

### Kill Switch (RiskGuardV2)
- Daily loss: 30% (temporarily raised from 10% — PnL tracking bug)
- Weekly loss: 7%, Monthly: 10%
- Absolute daily cap: €100
- Per-coin exposure: 80%, Total exposure: 80%
- Triggers: disable all trading + Telegram critical alert

### Professional Risk Manager
- ATR-based dynamic stops: 2×ATR, clamped [2%, 8%]
- Context-aware time exits (6h, requires stall + no fills > 45min)
- Profit lock tiers (breakeven at +1%, +0.7% at +2%, +1.5% at +3%)
- Rolling 20-trade PnL < −2% → 2h cooldown
- Win rate monitoring (35% acceptable for grid bots)

### Entry Filters
- RSI regime-based (buy/extreme/block per BULL/CHOP/BEAR)
- VWAP deviation + slope guard (dual 5m/15m confirmation)
- ATR volatility band (min/max for grid suitability)
- 5m spike filter (news/chaos detection)
- Parabolic detector (60 min cooldown, SQLite persistent)
- BTC macro filter (dump detection → 60 min cooldown)
- Altcoin breadth (≥30% of [ETH, SOL, BNB, AVAX, LINK] bullish)
- Multi-timeframe buy protection (1h ≥ 0%, 4h ≥ 0%, 24h ≥ −2.5%)

### Position-Level
- Stop-loss: DISABLED (null)
- Emergency exit: −12%, Hard stop: −15%
- Take profit: 5%
- Budget allocator: 0.2% fee buffer + 5% reserve + Decimal("0.01") tolerance

### Futures-Specific (Bitget 3× leverage)
- 6-guard system: hard loss (−8%), max time (1h), grid depth (65%),
  trend break (1h < −1.5%), ATR explosion (>2.2× baseline)
- Liquidation buffer: 20%, stop at 50% distance to liquidation
- Exchange-side TPSL orders (survives bot crashes)

## Known failure history
| Incident | Impact | Root cause |
|----------|--------|------------|
| Stop-loss → immediate re-buy | Lost money twice on same coin | No cooldown after stop-loss |
| 97–99% zero-fill rate | Bot creates grids but they expire unfilled | Grid too tight + filters too restrictive |
| Grid sells below buys | Guaranteed loss per fill | Grid placement logic bug |
| SQLite overflow crash | Bot crash during trading | Timestamp double-multiplication |
| Memory leak (92→625 MB) | Degraded performance over days | Unbounded executor tracking sets |
| NL restriction infinite retry | API rate limit exhaustion | No blacklist on regulatory errors |
| Bitget stuck LIMIT SELL | $71 budget locked, bot cannot trade | No stale order cleanup at startup |
| Kraken WebSocket 112+ errors | Missed fills, stale data, NO_ORDERBOOK_DATA | Kraken-side instability |
| Futures −310% return | −$155 on $50 capital in 9 days | 96% of filled trades hit stop-loss |
| 2/3 bots capital-blocked | Cannot trade at all | Stuck orders + insufficient capital |
| Rotation timeout loops | SONIC-USDT rotates every 3 min without progress | Rotation logic doesn't detect stuck state |
| Risk Manager permanent pause | SUI-USD blocked indefinitely (WR 30%, PnL −0.44%) | No recovery path from pause state |

## What I need you to evaluate

### 1. Catastrophic scenario analysis
What happens under each scenario:
- Flash crash (−30% in 5 minutes)
- Exchange API down for 30 minutes during open positions
- Bot crash and restart with 6 active grids
- Correlated dump (all 6 coins drop simultaneously)
- Partial fills → stuck inventory across multiple coins
- Database corruption during trading

### 2. Risk control gaps
- Stop-loss disabled + emergency exit at −12% = up to 12% loss per coin
  with 6 coins = potential 72% portfolio hit. Is this acceptable?
- Daily loss at 30% is dangerously high — what should it be?
- No correlation risk control on spot (futures has it but disabled)
- No max drawdown from peak (only period-based loss limits)

### 3. Recovery and reconciliation
- On restart: does the bot correctly load open orders, positions,
  and reconcile with exchange state?
- Orphaned position detection exists (Telegram alert only, no auto-recovery)
- Stale order cleanup exists (alert only, no auto-cancel)
- Is this sufficient? What's missing?

### 4. Edge cases in the risk chain
- What if the risk guard errors? Does it fail-open or fail-closed?
- What if PnL tracking is wrong (known bug — daily limit at 30%)?
- What if the trend calculator returns stale data?
- Rate limiting: what if Kraken rate-limits during a risk event?

## Attachments I'll provide
- [ ] RiskGuardV2 source
- [ ] ProfessionalRiskManager source
- [ ] SmartEntryFilter source
- [ ] **Data snapshot** (`.github/data-snapshot-YYYY-MM-DD.md` — error logs + trade history)

## Output format requirements (apply to all findings)

For every major conclusion, provide an evidence table:

| Finding | Evidence (code/config/logs/data) | Impact | Recommendation | Confidence (high/med/low) |
|---------|----------------------------------|--------|----------------|---------------------------|
| ...     | ...                              | ...    | ...            | ...                       |

Separate clearly between:
- **Confirmed findings** — directly proven from code, logs, or data
- **Reasonable inferences** — likely true but not fully proven
- **Unknowns** — requires more data to determine (state what data is needed)

For each recommendation, rate:
- **Impact on PnL** (high / medium / low)
- **Impact on safety** (high / medium / low)
- **Implementation effort** (hours / days / weeks)
- **Urgency** (immediate / next sprint / backlog)

## What to keep
Identify which risk controls are already well-designed and should be
preserved. Not every layer needs replacing — call out what works.

## Capital scaling verdict
Based on the risk review, state the maximum capital you would trust
this bot with given the CURRENT risk controls:
- [ ] Paper trading only
- [ ] Small live capital (< €500)
- [ ] Medium live capital (€500–€5,000)
- [ ] Larger serious capital (€5,000–€50,000)
- [ ] Professional capital (> €50,000)

Explain what risk improvements are needed for each tier upgrade.

## Expected output
1. **Risk score** (1–10) with justification
2. **Catastrophic scenario playbook**: what happens and what should happen
3. **Missing safeguards** ranked by severity (evidence table format)
4. **Recommended risk parameters** (with math, not gut feel)
5. **Recovery gaps** and what to implement
6. **Risk architecture verdict**: is the layered approach sound or fragile?
7. **What to keep**: risk controls that are already well-designed
8. **Capital scaling verdict**: current max safe capital + upgrade path
```

---

## Round 4: Production Readiness & Roadmap

```
Act as a DevOps/SRE engineer and trading infrastructure architect who
has deployed and operated crypto trading bots at scale. You evaluate
production readiness, operational maturity, and what separates a
hobby bot from professional infrastructure.

## Current operational setup
- Runs on a single Linux machine
- Python 3.11+, Hummingbot framework
- **3 active bot instances**: Kraken USD, Bitget Spot, Bitget Futures
- 4 SQLite trade databases (3–12 MB each) + 3 cooldown DBs
- Telegram bot for alerts (critical, warnings, status)
- Structured event logging via custom EventLogger
- WHY-NO-TRADE diagnostic reports (hourly)
- Console status reporting via to_format_status()
- No containerization in production
- Manual sync between two code directories
- Start scripts: start_bot.sh, start_bot_usd.sh, start_hummingbot.sh

## Current state of bots (March 8, 2026)
- **Kraken USD**: Running but Risk Manager blocks most trades (WR 30%)
- **Bitget Spot**: BLOCKED — insufficient capital ($3.62 free)
- **Bitget Futures**: BLOCKED — insufficient capital ($9 free)
- Only 1 of 3 bots is actively attempting to trade

## Current monitoring & observability
- EventLogger: structured events for signals, risk blocks, orders, fills, PnL
- WhyNoTrade diagnostics: hourly summaries per bot with rejection breakdown
- Console status: multi-section formatted output (positions, PnL, regime, slots)
- Telegram: real-time alerts for trades, risk events, anomalies
- Per-bot report logs: bitget_multi_coin_grid_report_*.log, kraken_*_report_*.log
- No Prometheus/Grafana, no centralized logging, no alerting rules
- No cross-bot dashboard or aggregated P&L view

## Known operational issues
- WebSocket instability on Kraken (112+ errors in current session)
- Bitget Spot: stuck LIMIT SELL order blocks all trading ($71 locked)
- Bitget Futures: insufficient capital after losses ($9 of $50 remains)
- Memory leak (fixed but indicates potential for regression)
- Manual code deployment (copy files between two directories)
- No automated testing in CI/CD
- No config validation beyond Pydantic (no semantic validation)
- Restart recovery: orphan detection + stale cleanup exist but alert-only
- Rotation timeout loops: SONIC-USDT rotates every 3 min without progress
- Risk Manager pause has no automatic recovery path
- NO_ORDERBOOK_DATA is #1 rejection reason across all bots (35–44%)

## What I need you to evaluate

### 1. Maturity assessment
Rate on a scale: hobby → intermediate → advanced → professional → institutional
For each dimension:
- Code quality and maintainability
- Testing and CI/CD
- Monitoring and alerting
- Deployment and operations
- Disaster recovery
- Documentation

### 2. What would break at scale?
- What if capital grows to €50K? €500K?
- What if number of coins grows to 50? 100?
- What if running on 3 exchanges simultaneously?
- Database performance at 1 GB? 10 GB?
- Memory usage with 50 concurrent executors?

### 3. Operational gaps
- No health checks, no auto-restart, no process supervision
- No database backup strategy
- No config change audit trail
- No A/B testing framework for strategy changes
- No performance regression detection

### 4. Professionalization roadmap
Build a phased plan with effort estimates:

**Phase 1 — Must-fix (1–2 weeks)**
What needs to happen before increasing capital?

**Phase 2 — Robustness (2–4 weeks)**
What makes this bot reliable for unattended operation?

**Phase 3 — Professional (1–2 months)**
What turns this into infrastructure you'd trust with serious money?

## Attachments I'll provide
- [ ] Start scripts and deployment setup
- [ ] Monitoring module source
- [ ] EventLogger source
- [ ] **Data snapshot** (`.github/data-snapshot-YYYY-MM-DD.md` — operational state + logs)

## Output format requirements (apply to all findings)

For every major conclusion, provide an evidence table:

| Finding | Evidence (code/config/logs/data) | Impact | Recommendation | Confidence (high/med/low) |
|---------|----------------------------------|--------|----------------|---------------------------|
| ...     | ...                              | ...    | ...            | ...                       |

Separate clearly between:
- **Confirmed findings** — directly proven from code, logs, or data
- **Reasonable inferences** — likely true but not fully proven
- **Unknowns** — requires more data to determine (state what data is needed)

For each roadmap item, rate:
- **Impact on PnL** (high / medium / low)
- **Impact on safety** (high / medium / low)
- **Implementation effort** (hours / days / weeks)
- **Urgency** (immediate / next sprint / backlog)

## What to keep
Identify which operational components, monitoring tools, or infrastructure
choices are already good and should be preserved. Avoid recommending
replacement of things that work well.

## Capital scaling verdict
Based on the production readiness review, state the maximum capital you
would trust this bot with given the CURRENT operational maturity:
- [ ] Paper trading only
- [ ] Small live capital (< €500)
- [ ] Medium live capital (€500–€5,000)
- [ ] Larger serious capital (€5,000–€50,000)
- [ ] Professional capital (> €50,000)

State which Phase roadmap items must complete for each tier upgrade.

## Expected output
1. **Maturity scorecard** (per dimension)
2. **Top 10 operational risks** ranked (evidence table format)
3. **Scaling bottlenecks** with projected failure points
4. **Phase 1/2/3 roadmap** with specific tasks, effort estimates, and priority×effort scores
5. **Infrastructure recommendations** (concrete tools, not generic advice)
6. **What to keep**: operational choices that are already working well
7. **Capital scaling verdict**: current max safe capital + phase gates
8. **Final verdict**: what's the ceiling of this system?
```

---

## Data Extraction

All queries and commands are documented in the data snapshot file.
Before each review round:

1. Copy `.github/data-snapshot-2026-03-08.md` to a new file with today's date
2. Re-run the queries from the "How to regenerate" section at the top
3. Update the tables with fresh results
4. Attach the new snapshot file with the review round

---

## Review Rules (include at bottom of every round)

```
Important rules for this review:
- Be brutally honest and specific
- Do not praise by default
- Do not give generic best-practice advice unless tied to this bot
- Every major claim must reference evidence from code, config, logs,
  database, or trade data
- Distinguish facts, inferences, and unknowns
- Prioritize recommendations by impact, urgency, and implementation effort
- Explicitly state what should be kept, what should be redesigned,
  and what should be removed
- Assume the goal is to evolve this system toward professional-grade
  live trading, not just academic correctness
- If data is missing to support a conclusion, say exactly what data
  you need rather than speculating
- Use the evidence table format for all major findings
```

---

## Usage Notes

1. **One round at a time** — don't combine rounds, the reviewer needs focus
2. **Attach actual code** — paste the source, don't just link it
3. **Generate a fresh data snapshot** before each round:
   - Copy `.github/data-snapshot-2026-03-08.md` as a template
   - Re-run the queries from the "How to regenerate" section
   - Attach the snapshot file contents with the review round
4. **Be specific about what changed** — if you fixed issues between rounds, mention it
5. **Ask follow-up questions** — after each round, ask "what data would help you be more specific?"
6. **Save the scores** — track Round 1–4 scores to measure improvement over time
7. **Copy the Review Rules block** — paste it at the bottom of each round when you submit
