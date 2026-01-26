# REFACTOR: Multi-Coin Grid Controller Split
## Breaking Down 8100+ Line Monolith into Maintainable Modules

**Status**: 📋 PLANNED (Post v3.4.x)
**Priority**: HIGH - Technical Debt + Duplicate File Problem
**Created**: 2026-01-03
**Updated**: 2026-01-24
**Owner**: Mo
**Estimated Effort**: 2-3 weeks

---

## 🚨 CRITICAL: Duplicate Controller Files

**We have TWO identical 8100+ line files that must stay in sync!**

| Location | Size | Purpose |
|----------|------|---------|
| `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py` | 8143 lines | Main package version |
| `hummingbot/multi_coin_grid_controllers/multi_coin_grid_controller.py` | 8152 lines | Legacy hummingbot location |

**Problems:**
1. **Double maintenance**: Every change must be applied to BOTH files
2. **Sync errors**: Files drift out of sync, causing mysterious bugs
3. **Confusion**: Which is the "real" one?
4. **Wasted disk/git**: 360KB × 2 = 720KB of duplicate code

**Immediate Fix (Before Full Refactor):**
```bash
# Option A: Symlink (recommended)
rm hummingbot/multi_coin_grid_controllers/multi_coin_grid_controller.py
ln -s ../../multi_coin_grid_pro/controllers/multi_coin_grid_controller.py \
      hummingbot/multi_coin_grid_controllers/multi_coin_grid_controller.py

# Option B: Import redirect
# In hummingbot/multi_coin_grid_controllers/multi_coin_grid_controller.py:
from multi_coin_grid_pro.controllers.multi_coin_grid_controller import *
```

---

## Problem Statement

**Current State:**
- `multi_coin_grid_controller.py`: **8100+ lines, 360KB** (× 2 copies!)
- Single file contains ALL logic: ranking, risk, execution, observability
- VS Code save conflicts (file watcher overload)
- Merge conflicts frequent
- Hard to test individual components
- Onboarding nightmare (new devs can't understand flow)

**Pain Points:**
1. **IDE Performance**: VS Code struggles with 360KB file (auto-save conflicts)
2. **Git Conflicts**: Multiple devs = constant merge issues
3. **Testing**: Can't unit test coin selection without loading entire controller
4. **Code Navigation**: Finding specific logic = needle in haystack
5. **Circular Dependencies**: Everything imports from one mega-file

**Example Issue (Today):**
```
Failed to save 'multi_coin_grid_controller.py':
The content of the file is newer.
Please compare your version with the file contents or overwrite.
```

---

## Proposed Architecture

### Phase 0: Eliminate Duplicate (Week 0 - FIRST!)

**Before any refactor, fix the duplicate file problem:**

```bash
# 1. Verify files are identical
diff multi_coin_grid_pro/controllers/multi_coin_grid_controller.py \
     hummingbot/multi_coin_grid_controllers/multi_coin_grid_controller.py

# 2. Keep multi_coin_grid_pro as source of truth
# 3. Replace hummingbot version with symlink or import redirect
```

**Decision:** Keep `multi_coin_grid_pro/controllers/` as the canonical location.

### Target Structure

```
hummingbot/multi_coin_grid_controllers/
├── multi_coin_grid_controller.py       # 500 lines (orchestrator only)
├── modules/
│   ├── __init__.py
│   ├── coin_selection.py               # 1200 lines
│   ├── risk_management.py              # 800 lines
│   ├── executor_factory.py             # 1000 lines
│   ├── observability.py                # 600 lines
│   ├── trend_analysis.py               # 500 lines (optional)
│   └── config_manager.py               # 400 lines (optional)
└── tests/
    └── unit/
        ├── test_coin_selection.py
        ├── test_risk_management.py
        ├── test_executor_factory.py
        └── test_observability.py
```

---

## Module Breakdown

### Module 1: `coin_selection.py` (~1200 lines)

**Responsibilities:**
- Candidate ranking logic
- Multi-factor scoring (trend, momentum, orderbook)
- VWAP filter integration
- Smart Entry filter v2 integration
- Coin blacklist/cooldown management

**Public API:**
```python
class CoinSelector:
    def __init__(self, config, connectors, market_data_provider):
        ...

    def select_best_candidate(
        self,
        candidates: List[str],
        active_positions: Dict[str, Executor]
    ) -> Optional[CoinCandidate]:
        """Main entry point for coin selection"""
        ...

    def rank_candidates(
        self,
        candidates: List[str]
    ) -> List[CoinCandidate]:
        """Rank all candidates with scores"""
        ...

    def apply_smart_entry_filters(
        self,
        candidate: CoinCandidate
    ) -> Tuple[bool, str]:
        """Apply SmartEntry v2 filters"""
        ...
```

**Extracted Methods:**
- `select_best_coin()` → `CoinSelector.select_best_candidate()`
- `_calculate_coin_scores()` → `CoinSelector._score_candidates()`
- `_check_smart_entry_v2()` → `CoinSelector.apply_smart_entry_filters()`
- `_get_orderbook_depth()` → `CoinSelector._evaluate_orderbook()`
- All trend/momentum calculation helpers

**Dependencies:**
- SmartEntryFilterV2
- TrendCalculator
- MarketDataProvider

---

### Module 2: `risk_management.py` (~800 lines)

**Responsibilities:**
- Daily loss tracking
- Kill switch logic
- Per-symbol loss caps
- Position size limits
- Exposure management

**Public API:**
```python
class RiskManager:
    def __init__(self, config):
        ...

    def check_daily_loss_limit(self) -> Tuple[bool, str]:
        """Returns (is_safe, reason)"""
        ...

    def register_close_trade(
        self,
        symbol: str,
        realised_pnl_quote: Decimal,
        now: float
    ):
        """Track closed trade for loss limits"""
        ...

    def get_max_position_size(
        self,
        symbol: str,
        market_conditions: dict
    ) -> Decimal:
        """Calculate safe position size"""
        ...

    def should_halt_trading(self) -> Tuple[bool, str]:
        """Check all risk conditions"""
        ...
```

**Extracted Methods:**
- `_should_block_entry_by_daily_loss()` → `RiskManager.check_daily_loss_limit()`
- `register_close_trade()` → stays but simplified
- `_calculate_max_position_size()` → `RiskManager.get_max_position_size()`
- Kill switch logic
- Loss tracking database interactions

**Dependencies:**
- None (pure logic + database)

---

### Module 3: `executor_factory.py` (~1000 lines)

**Responsibilities:**
- Grid parameter calculation
- GridExecutorConfig creation
- Triple barrier config setup
- Adaptive timeout logic (Story D1)
- Leverage/futures handling

**Public API:**
```python
class ExecutorFactory:
    def __init__(self, config, connectors):
        ...

    def create_grid_executor(
        self,
        symbol: str,
        entry_price: Decimal,
        market_conditions: dict
    ) -> GridExecutorConfig:
        """Create complete grid executor config"""
        ...

    def calculate_grid_range(
        self,
        symbol: str,
        atr: Decimal,
        trend_strength: Decimal
    ) -> Tuple[Decimal, Decimal]:
        """Calculate start_price, end_price"""
        ...

    def get_adaptive_timeout(
        self,
        symbol: str,
        volatility: Decimal
    ) -> int:
        """Story D1: Volatility-adjusted timeout"""
        ...
```

**Extracted Methods:**
- `_create_executor_config()` → `ExecutorFactory.create_grid_executor()`
- Grid range calculation logic
- Triple barrier setup
- Leverage configuration
- Story D1 adaptive timeout

**Dependencies:**
- GridExecutorConfig
- TripleBarrierConfig
- Market data for ATR/volatility

---

### Module 4: `observability.py` (~600 lines)

**Responsibilities:**
- Structured logging
- Event emission
- Status formatting
- Metrics tracking
- Decision trace logging

**Public API:**
```python
class ObservabilityManager:
    def __init__(self, logger, config):
        ...

    def log_coin_selection(
        self,
        selected: str,
        rejected: List[Tuple[str, str]],
        scores: Dict[str, float]
    ):
        """Log selection decision with reasons"""
        ...

    def log_decision_trace(
        self,
        trace: DecisionTrace
    ):
        """Story 6: EPIC v3.4 decision traces"""
        ...

    def emit_entry_event(
        self,
        symbol: str,
        entry_price: Decimal,
        filters_applied: Dict[str, bool]
    ):
        """Emit structured entry event"""
        ...

    def format_status_display(
        self,
        portfolio: dict,
        executors: List[Executor]
    ) -> List[str]:
        """Format for terminal display"""
        ...
```

**Extracted Methods:**
- `_log_decision_trace()` → `ObservabilityManager.log_decision_trace()`
- All `StructuredLogger` calls → centralized
- Status formatting methods
- Event emission logic

**Dependencies:**
- StructuredLogger
- EventEmitter (if exists)

---

### Module 5 (Optional): `trend_analysis.py` (~500 lines)

**Responsibilities:**
- Trend calculation
- Momentum indicators
- Regime detection integration
- Market condition assessment

**Public API:**
```python
class TrendAnalyzer:
    def __init__(self, trend_calculator):
        ...

    def get_trend_strength(self, symbol: str) -> Decimal:
        """Unified trend strength metric"""
        ...

    def assess_market_conditions(
        self,
        symbol: str
    ) -> MarketConditions:
        """Volatility, trend, momentum in one object"""
        ...
```

---

### Module 6 (Optional): `config_manager.py` (~400 lines)

**Responsibilities:**
- Config validation
- Dynamic config updates
- Regime-specific parameter resolution
- Coin profile overrides

**Public API:**
```python
class ConfigManager:
    def __init__(self, base_config):
        ...

    def get_filter_params(
        self,
        symbol: str,
        regime: str
    ) -> FilterParams:
        """Resolve with precedence: coin_profile > regime > baseline"""
        ...

    def validate_config(self) -> List[str]:
        """Returns list of validation errors"""
        ...
```

---

## Orchestrator Controller (~500 lines)

**What Remains:**
```python
class MultiCoinGridController:
    def __init__(self, config, connectors):
        # Initialize modules
        self.coin_selector = CoinSelector(config, connectors, mdp)
        self.risk_manager = RiskManager(config)
        self.executor_factory = ExecutorFactory(config, connectors)
        self.observability = ObservabilityManager(logger, config)

    async def control_task(self):
        """Main loop - orchestrates modules"""
        # 1. Check risk limits
        if not self.risk_manager.should_halt_trading():
            return

        # 2. Select coin
        candidate = self.coin_selector.select_best_candidate(...)
        if not candidate:
            return

        # 3. Create executor
        config = self.executor_factory.create_grid_executor(...)

        # 4. Execute + observe
        self.observability.log_coin_selection(...)
        action = CreateExecutorAction(...)
        return [action]
```

**Only Orchestration Logic:**
- Module initialization
- Control loop coordination
- High-level state management
- Executor lifecycle (start/stop)

---

## Migration Strategy

### Phase 1: Extract Pure Logic (Week 1)
**No Behavioral Changes - Just Move Code**

1. Create `modules/` directory
2. Extract `risk_management.py` first (least dependencies)
   - Move methods
   - Update imports in controller
   - Run tests: `pytest test/hummingbot/strategy_v2/`
3. Extract `observability.py` (logging only)
4. Extract `executor_factory.py` (grid config creation)

**Success Criteria:**
- ✅ All existing tests pass unchanged
- ✅ Bot behavior identical (verify in staging)
- ✅ Controller file < 5000 lines

### Phase 2: Extract Coin Selection (Week 2)
**Most Complex - Has Many Dependencies**

1. Create `CoinSelector` class stub
2. Move ranking methods one-by-one
3. Update `select_best_coin()` to delegate to `CoinSelector`
4. Gradually replace direct calls with module calls

**Success Criteria:**
- ✅ Coin selection tests isolated
- ✅ Can test ranking without controller
- ✅ Controller file < 3000 lines

### Phase 3: Polish + Documentation (Week 3)
**Clean Up + Add Tests**

1. Add unit tests for each module
2. Update documentation
3. Add module-level docstrings
4. Remove dead code revealed by split
5. Run full production validation

**Success Criteria:**
- ✅ >80% test coverage per module
- ✅ Controller file ~500 lines
- ✅ No production incidents
- ✅ Dev onboarding time reduced by 50%

---

## Testing Strategy

### Unit Tests (Per Module)
```python
# test/multi_coin_grid_pro/test_coin_selection.py
def test_rank_candidates_by_trend():
    selector = CoinSelector(config, mock_connectors, mock_mdp)
    candidates = ["BTC-EUR", "ETH-EUR"]
    ranked = selector.rank_candidates(candidates)
    assert ranked[0].score > ranked[1].score

def test_smart_entry_filter_rejection():
    selector = CoinSelector(config, ...)
    candidate = CoinCandidate(symbol="PEPE-EUR", ...)
    passed, reason = selector.apply_smart_entry_filters(candidate)
    assert not passed
    assert "VWAP_SLOPE_FLAT" in reason
```

### Integration Tests (Controller)
```python
# test/multi_coin_grid_pro/test_controller_integration.py
def test_full_selection_flow():
    controller = MultiCoinGridController(config, connectors)
    actions = await controller.control_task()
    assert len(actions) <= 1
    if actions:
        assert isinstance(actions[0], CreateExecutorAction)
```

### Regression Tests (Production Validation)
- Run refactored bot in staging for 24h
- Compare metrics: entry rate, rejection reasons, PnL
- Must match production bot within 5% variance

---

## Rollout Plan

### Staging Rollout (Week 3)
1. Deploy refactored bot to staging environment
2. Run parallel with production (same config)
3. Monitor for 48 hours:
   - Compare entry decisions (should be identical)
   - Check CPU/memory usage (should be same or better)
   - Verify no new errors in logs

### Production Rollout (Week 4)
1. Enable on 1 bot first (Bitget or Kraken)
2. Monitor for 24h
3. If stable → enable on second bot
4. Full rollout after 48h clean run

---

## Benefits

### Developer Experience
- ✅ **Faster Onboarding**: New devs understand 500-line orchestrator vs 7127-line monolith
- ✅ **Parallel Development**: 3 devs can work on different modules without conflicts
- ✅ **Easier Testing**: Test coin selection without booting entire controller

### Code Quality
- ✅ **Single Responsibility**: Each module has ONE job
- ✅ **Testability**: 80%+ coverage achievable (vs 30% now)
- ✅ **Maintainability**: Bug fixes isolated to one module

### Performance
- ✅ **IDE Performance**: VS Code no longer chokes on 360KB file
- ✅ **Build Times**: Faster compilation (smaller files)
- ✅ **Git**: Smaller diffs = easier code reviews

### Future Enhancements
- ✅ **Plugin Architecture**: Easy to add new selection strategies
- ✅ **A/B Testing**: Swap `CoinSelector` implementations
- ✅ **Microservices Ready**: Modules can become separate services later

---

## Risks & Mitigations

### Risk 1: Behavioral Changes
**Mitigation:**
- Move code verbatim (no logic changes in Phase 1)
- Comprehensive regression tests
- Staging validation before production

### Risk 2: Import Cycles
**Mitigation:**
- Dependency graph analysis before moving code
- Use dependency injection (pass objects, don't import)
- Abstract interfaces where needed

### Risk 3: Performance Regression
**Mitigation:**
- Profile before/after with `cProfile`
- Monitor CPU/memory in staging
- Benchmark critical paths (coin selection loop)

### Risk 4: Merge Conflicts During Refactor
**Mitigation:**
- Do refactor in dedicated branch
- Pause other feature work on controller
- Complete in 2-3 week sprint (minimize drift)

---

## Success Metrics

### Quantitative
- ✅ Duplicate files: 2 → **1** (eliminate copy)
- ✅ Controller file: 8100+ lines → **<600 lines** (93% reduction)
- ✅ Test coverage: 30% → **>80%** per module
- ✅ VS Code save conflicts: 5/week → **0/week**
- ✅ Onboarding time: 2 weeks → **<1 week**

### Qualitative
- ✅ Devs can explain code flow in 10 minutes (vs 2 hours)
- ✅ Unit tests run in <5 seconds (vs 30+ seconds)
- ✅ Code reviews focus on logic, not "where is this?"
- ✅ New features go in obvious module (not "add to controller")

---

## Dependencies

### Blockers (Must Complete First)
- ✅ EPIC v3.4 complete (avoid conflicts with active development)
- ✅ EPIC v3.4.x complete (crash recovery uses controller state)

### Nice-to-Have (Can Do In Parallel)
- Story 7: Replay harness (would benefit from modular design)
- Performance profiling baseline (for before/after comparison)

---

## Alternative Approaches Considered

### Alt 1: Keep Monolith, Just Add Comments
**Rejected**: Doesn't solve IDE performance, merge conflicts, or testability

### Alt 2: Split into 2 Files (controller + helpers)
**Rejected**: Still 3500+ lines per file, not enough improvement

### Alt 3: Microservices (Separate Processes)
**Rejected**: Too complex for now, premature optimization

### Alt 4: Use Mixins/Inheritance
**Rejected**: Makes dependency graph worse, harder to test

---

## References

**Related Issues:**
- VS Code save conflicts (daily occurrence)
- Merge conflicts in controller (weekly)
- Test suite slowness (30+ seconds)

**Similar Refactors:**
- Hummingbot core split (2022): `ExchangeBase` → modular connectors
- Pandas refactor (2019): Monolithic core → modular `ops/`

**Best Practices:**
- Clean Code (Robert Martin): Single Responsibility Principle
- Domain-Driven Design: Module per bounded context

---

**Document Version**: 1.0
**Last Updated**: 2026-01-03
**Next Review**: After EPIC v3.4.x completion
**Owner**: Mo
**Status**: Ready for Implementation
