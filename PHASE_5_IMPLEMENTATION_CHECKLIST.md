# Phase 5 Implementation Checklist

**Goal:** Multi-currency support (EUR/USD/USDT)
**Timeline:** Days 1-5
**Owner:** Implementation Team

---

## ✅ Day 1: Core Infrastructure

### Morning - Setup & Planning
- [ ] Review `/PHASE_5_MULTI_CURRENCY_PLAN.md`
- [ ] Review `/PHASE_5_QUICK_REFERENCE.md`
- [ ] Set up feature branch: `git checkout -b feature/multi-currency`
- [ ] Create implementation tracker
- [ ] Notify stakeholders

### Afternoon - MultiCurrencyPairManager

#### File: `/multi_coin_grid_pro/utils/multi_currency_manager.py`
- [ ] Create class `MultiCurrencyPairManager`
- [ ] Implement `__init__(quote_asset, exchange)`
- [ ] Implement `get_trading_pairs(coins: List[str]) -> List[str]`
- [ ] Implement `pair_exists(pair: str) -> bool`
- [ ] Implement `get_fallback_pair(coin: str) -> Optional[str]`
- [ ] Add pair caching mechanism
- [ ] Add unit tests (8 tests)
  - [ ] Test pair exists (EUR, USD)
  - [ ] Test fallback logic
  - [ ] Test cache behavior
  - [ ] Test empty list
  - [ ] Test all currencies

### Late Afternoon - Config Updates

#### File: `/multi_coin_grid_pro/controllers/multi_coin_grid_config.py`
- [ ] Add `quote_asset: str = "EUR"`
- [ ] Add `capital_eur: float`
- [ ] Add `quote_asset_balance: float`
- [ ] Add `multi_currency: Dict` section
  - [ ] `enabled: bool = True`
  - [ ] `primary_asset: str`
  - [ ] `fallback_assets: List[str]`
  - [ ] `fx_cache_ttl_seconds: int = 300`

#### File: `/multi_coin_grid_pro/config/config.prod.yaml`
- [ ] Add `quote_asset: EUR`
- [ ] Add `capital_eur: 5000`
- [ ] Add multi_currency section
- [ ] Test config loads without errors

### End of Day
- [ ] All tests passing ✓
- [ ] No merge conflicts
- [ ] Code review: pair manager
- [ ] **Commit:** "feat: add MultiCurrencyPairManager"

**Day 1 Status:** ✅ Core infrastructure ready (should take 6-8 hours)

---

## ✅ Day 2: Capital Tracking

### Morning - MultiCurrencyCapitalTracker

#### File: `/multi_coin_grid_pro/utils/currency_converter.py`
- [ ] Create class `MultiCurrencyCapitalTracker`
- [ ] Implement `__init__(exchange)`
- [ ] Implement `get_capital_in_eur(amount, quote_asset) -> float`
- [ ] Implement `get_capital_in_quote(amount_eur, quote_asset) -> float`
- [ ] Implement `get_fx_rate(pair: str) -> float`
- [ ] Add FX rate caching (5-min TTL)
- [ ] Add `calculate_max_order_size(capital_eur, max_risk_pct, quote_asset) -> float`

#### Unit Tests (10 tests)
- [ ] EUR to USD conversion
- [ ] USD to EUR conversion
- [ ] EUR to USDT conversion
- [ ] USDT to EUR conversion
- [ ] FX rate caching works
- [ ] Cache TTL expires
- [ ] Large numbers (€100k)
- [ ] Small numbers (€1)
- [ ] Order size calculation EUR
- [ ] Order size calculation USD

### Afternoon - Integration Testing

#### File: `/multi_coin_grid_pro/tests/unit/test_multi_currency.py`
- [ ] Add test file with all 10 tests above
- [ ] Test all edge cases
- [ ] Test error handling (invalid currency, etc.)
- [ ] All tests passing ✓

### Late Afternoon - Documentation
- [ ] Add docstrings to all methods
- [ ] Add type hints
- [ ] Add usage examples
- [ ] Code review: capital tracker

### End of Day
- [ ] All tests passing ✓
- [ ] No regressions in existing tests
- [ ] **Commit:** "feat: add MultiCurrencyCapitalTracker with FX conversion"

**Day 2 Status:** ✅ Capital tracking complete (6-8 hours)

---

## ✅ Day 3: Drawdown Integration

### Morning - MultiCurrencyDrawdownTracker

#### File: `/multi_coin_grid_pro/core/multi_currency_drawdown_tracker.py`
- [ ] Extend existing `DrawdownTracker` class
- [ ] Inject `MultiCurrencyCapitalTracker`
- [ ] Override `track_trade()` to convert P&L
- [ ] Implement P&L EUR conversion
- [ ] Override logging to show currency
- [ ] Ensure all risk limits stay in EUR
- [ ] Add `quote_asset` parameter to methods

#### Implementation Details
- [ ] Convert P&L on every trade: `pnl_eur = converter.get_capital_in_eur(pnl_quote, quote_asset)`
- [ ] All drawdown limits unchanged (still EUR)
- [ ] Logs show: "Daily loss: €5.50 (from $6.05 USD)"
- [ ] Handle currency switch during period

#### Unit Tests (7 tests)
- [ ] Track trade EUR (baseline)
- [ ] Track trade USD (convert to EUR)
- [ ] Track trade USDT (convert to EUR)
- [ ] Daily limit still works
- [ ] Weekly limit still works
- [ ] Pause logic works
- [ ] Logging shows currency

### Afternoon - Integration with Controller

#### File: `/multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
- [ ] Find line ~188 where drawdown tracker initialized
- [ ] Update initialization to pass currency tracker
- [ ] Verify no breaking changes to existing code
- [ ] Update all `track_trade()` calls to pass `quote_asset`

#### Testing
- [ ] Existing drawdown tests still pass
- [ ] New multi-currency tests pass
- [ ] Live test: EUR trades tracked correctly
- [ ] Live test: Switch to USD (if positions exist?)

### Late Afternoon - Code Review

- [ ] Drawdown tracker code review
- [ ] Test coverage >90%
- [ ] All tests passing ✓

### End of Day
- [ ] All tests passing ✓
- [ ] No impact on existing features
- [ ] **Commit:** "feat: add MultiCurrencyDrawdownTracker with P&L conversion"

**Day 3 Status:** ✅ Drawdown tracking complete (6-8 hours)

---

## ✅ Day 4: Bot Integration

### Morning - Controller Enhancement

#### File: `/multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
- [ ] Create extended controller class (or modify existing)
- [ ] Initialize `MultiCurrencyPairManager` in `on_startup()`
- [ ] Initialize `MultiCurrencyCapitalTracker` in `on_startup()`
- [ ] Log: "✅ Currency Support: Primary={quote_asset}"

#### Integration Points
- [ ] Line ~200: Replace hardcoded pairs with `pair_manager.get_trading_pairs()`
- [ ] Line ~500: Replace hardcoded order sizes with `capital_tracker.calculate_max_order_size()`
- [ ] Line ~2179: Already uses dynamic sizes (verify)
- [ ] Line ~1923: Verify drawdown tracker gets `quote_asset` parameter

#### Testing
- [ ] EUR mode works (existing tests)
- [ ] USD mode works (new tests)
- [ ] Order sizes correct in each currency
- [ ] Pairs correct in each currency

### Afternoon - Bot Initialization

#### File: `/multi_coin_grid_pro/bot_v2.py`
- [ ] Verify bot uses controller correctly
- [ ] Verify currency is passed to all relevant components
- [ ] Check logging for currency info
- [ ] No hardcoded assumptions about EUR

#### End-to-End Tests
- [ ] Start bot with EUR config
- [ ] Bot initializes successfully
- [ ] Correct pairs loaded (EUR)
- [ ] Correct order sizes
- [ ] Stop bot gracefully

- [ ] Start bot with USD config (manual test)
- [ ] Bot initializes successfully
- [ ] Correct pairs loaded (USD)
- [ ] Correct order sizes
- [ ] Stop bot gracefully

### Late Afternoon - Integration Tests

#### File: `/multi_coin_grid_pro/tests/unit/test_multi_currency_controller.py`
- [ ] Add integration test file
- [ ] Test controller initialization (EUR)
- [ ] Test controller initialization (USD)
- [ ] Test pair manager integration
- [ ] Test capital tracker integration
- [ ] Test drawdown tracker integration
- [ ] All 8 integration tests passing

### End of Day
- [ ] All tests passing ✓ (60+ tests now!)
- [ ] Bot starts in EUR mode ✓
- [ ] Bot starts in USD mode ✓ (manual)
- [ ] No regressions ✓
- [ ] **Commit:** "feat: integrate MultiCurrency components into controller"

**Day 4 Status:** ✅ Controller integration complete (8-10 hours)

---

## ✅ Day 5: Switching & Validation

### Morning - Runtime Currency Switching

#### File: `/multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
- [ ] Add method `switch_currency(new_asset: str) -> bool`
- [ ] Step 1: Check for open positions (`_has_open_orders()`)
- [ ] Step 2: Refuse if positions exist
  - [ ] Log: "Cannot switch: XX open positions exist"
  - [ ] Return False
- [ ] Step 3: Update `self.quote_asset = new_asset`
- [ ] Step 4: Recreate pair manager: `self.pair_manager = MultiCurrencyPairManager(...)`
- [ ] Step 5: Reload pairs: `self._load_trading_pairs()`
- [ ] Step 6: Log: "✅ Currency switched to {new_asset}"
- [ ] Step 7: Resume trading

#### Safeguards
- [ ] Validate new asset is supported (EUR, USD, USDT)
- [ ] Check exchange has pairs in new currency
- [ ] Verify FX rates available
- [ ] Test on timeout (if switching takes >30s, fail)

#### Unit Tests (5 tests)
- [ ] Switch EUR to USD (no positions)
- [ ] Switch USD to EUR (no positions)
- [ ] Refuse switch with open positions
- [ ] Verify pairs updated after switch
- [ ] Verify capital converted after switch

### Afternoon - Config Validation

#### File: `/multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
- [ ] Add method `validate_multi_currency_config() -> bool`
- [ ] Validate `quote_asset` is in [EUR, USD, USDT]
- [ ] Validate `capital_eur > 0`
- [ ] Validate `quote_asset_balance > 0`
- [ ] Validate exchange has at least 1 pair in quote asset
- [ ] Validate FX rates are available
- [ ] Log any issues
- [ ] Call on startup

### Late Afternoon - Enhanced Logging

#### Throughout codebase
- [ ] Add logs to pair manager (8-10 key points)
- [ ] Add logs to capital tracker (5-7 key points)
- [ ] Add logs to drawdown tracker (3-5 key points)
- [ ] Add logs to controller (5-7 key points)
- [ ] Example log format:
  ```
  [INFO] 📍 Quote Asset: USD
  [INFO] 💰 Capital: 5000.00 EUR ≈ 5500.00 USD
  [INFO] 📊 Order Size: 110.00 USD (€100 EUR equiv)
  [INFO] ✅ [TRADE] SUI-USD P&L: +2.50 USD (+€2.27 EUR equiv)
  [INFO] ⚠️  [FALLBACK] SUI-USD unavailable, using SUI-EUR
  [INFO] 🔄 [SWITCH] Currency: EUR → USD (no positions)
  ```

### End of Day - Testing Checklist

- [ ] All 60+ existing tests still passing ✓
- [ ] All 35+ new multi-currency tests passing ✓
- [ ] Config validation passes ✓
- [ ] Logging is clear and helpful ✓
- [ ] No regressions in existing features ✓

**End of Day Commit:**
- **Commit:** "feat: add runtime currency switching with validation and enhanced logging"

**Day 5 Status:** ✅ Switching complete (6-8 hours)

---

## 🧪 Days 6-7: Live Testing & Polish

### Day 6: Live Testing

#### Morning - EUR Baseline
- [ ] Start bot with EUR config
- [ ] Let it run for 1-2 hours
- [ ] Monitor logs for:
  - [ ] Correct pairs loaded
  - [ ] EUR order sizes
  - [ ] EUR P&L tracking
  - [ ] Drawdown limits in EUR
  - [ ] No errors or warnings
- [ ] Verify existing functionality unaffected
- [ ] **Checkpoint:** EUR mode works like before ✓

#### Afternoon - USD Mode
- [ ] Stop bot gracefully
- [ ] Switch config to USD
- [ ] Restart bot
- [ ] Let it run for 1-2 hours
- [ ] Monitor logs for:
  - [ ] Correct USD pairs loaded
  - [ ] USD order sizes
  - [ ] P&L converted to EUR correctly
  - [ ] Drawdown limits still in EUR
  - [ ] Better spreads than EUR
  - [ ] No crashes or errors
- [ ] **Checkpoint:** USD mode works ✓

#### Late Afternoon - Switch Attempt
- [ ] Stop bot
- [ ] Manually call `switch_currency('EUR')`
- [ ] Restart bot
- [ ] Verify it comes back in EUR mode
- [ ] Monitor for any issues
- [ ] **Checkpoint:** Switching works ✓

### Day 7: Final Polish & Documentation

#### Morning - Edge Case Testing
- [ ] Test pair fallback (force coin unavailable in primary currency)
- [ ] Test FX rate cache TTL expiry
- [ ] Test with zero FX rate (error handling)
- [ ] Test with stale FX rates
- [ ] Test config validation with invalid asset
- [ ] Test config validation with missing balance
- [ ] All edge cases handled gracefully ✓

#### Afternoon - Documentation
- [ ] Update README with multi-currency section
- [ ] Update `INTEGRATION_V3.3_COMPLETE.md` with v3.5 status
- [ ] Add examples to docstrings
- [ ] Create FAQ for common issues
- [ ] Document config examples for each currency
- [ ] Document logging output examples

#### Late Afternoon - Final Checks
- [ ] All 100+ tests passing ✓
- [ ] No warnings or deprecations
- [ ] Code coverage >90% ✓
- [ ] Performance check (FX cache works)
- [ ] Merge request ready for review
- [ ] Documentation complete ✓

---

## 📊 Daily Progress Tracking

### Day 1 Progress
```
⏰ Morning:  Setup (1h) ✓
⏰ Midday:   Pair Manager (4h) ✓
⏰ Afternoon: Config (2-3h) ✓
📊 Total: 7-8h | Tests: 8 passing
```

### Day 2 Progress
```
⏰ Morning:  Capital Tracker (4h) ✓
⏰ Midday:   Testing (2h) ✓
⏰ Afternoon: Docs (1-2h) ✓
📊 Total: 7-8h | Tests: 18 passing
```

### Day 3 Progress
```
⏰ Morning:  Drawdown Tracker (4h) ✓
⏰ Midday:   Controller Integration (2h) ✓
⏰ Afternoon: Testing (2-3h) ✓
📊 Total: 8-9h | Tests: 32 passing
```

### Day 4 Progress
```
⏰ Morning:  Controller Setup (3h) ✓
⏰ Midday:   Bot Integration (3h) ✓
⏰ Afternoon: E2E Tests (2-3h) ✓
📊 Total: 8-9h | Tests: 60+ passing
```

### Day 5 Progress
```
⏰ Morning:  Currency Switching (3h) ✓
⏰ Midday:   Config Validation (2h) ✓
⏰ Afternoon: Logging (2h) ✓
📊 Total: 7-8h | Tests: 95+ passing
```

### Days 6-7 Progress
```
⏰ Day 6:    Live Testing (8h) ✓
⏰ Day 7:    Edge Cases + Docs (8h) ✓
📊 Total: 16h | Tests: 100+ passing ✓
```

---

## 🎯 Definition of Done

### Code Quality
- ✅ All tests passing (100+)
- ✅ Code review approved
- ✅ No merge conflicts
- ✅ Type hints on all functions
- ✅ Docstrings on all classes/methods
- ✅ No warnings or deprecations

### Functionality
- ✅ EUR mode works (backward compatible)
- ✅ USD mode works
- ✅ USDT mode works (or at least architecture supports it)
- ✅ Currency switching works (with safeguards)
- ✅ Pair fallback works
- ✅ Capital conversion works
- ✅ P&L conversion works
- ✅ Drawdown limits unchanged (still EUR)

### Testing
- ✅ 100+ unit tests passing
- ✅ 8+ integration tests passing
- ✅ Live testing EUR mode (2h)
- ✅ Live testing USD mode (2h)
- ✅ Edge cases covered
- ✅ Error handling tested

### Documentation
- ✅ README updated
- ✅ Docstrings complete
- ✅ Examples provided
- ✅ Config examples for each currency
- ✅ Logging examples clear
- ✅ FAQ for common issues

### Performance
- ✅ No latency regressions
- ✅ FX cache reduces API calls
- ✅ Pair manager uses cache
- ✅ Capital conversions <1ms
- ✅ Startup time <500ms

---

## 🚀 Success Criteria

### Minimum (Day 3 - MVP)
- [ ] Pair manager working (EUR & USD)
- [ ] Capital converter working
- [ ] 30+ tests passing
- [ ] Bot starts in EUR mode
- [ ] No regressions

### Target (Day 5 - Full Feature)
- [ ] All components working
- [ ] Runtime switching implemented
- [ ] 95+ tests passing
- [ ] Both EUR and USD modes tested
- [ ] Production-ready

### Stretch (Day 7 - Polish)
- [ ] Edge cases handled
- [ ] 100+ tests passing
- [ ] Comprehensive docs
- [ ] Live testing complete
- [ ] Ready for v3.5 release

---

## 📞 Blockers & Escalations

### Potential Issues
| Issue | Severity | Mitigation |
|-------|----------|-----------|
| Pair not on Kraken | MEDIUM | Fallback to other currencies, skip coin |
| FX rate API down | MEDIUM | Cache rates, use 1h old rate, fall back to EUR |
| Exchange rate stale | LOW | Refresh every 5 min, validate freshness |
| Switch with open orders | HIGH | Check before switch, refuse if positions |
| P&L rounding errors | LOW | Use Decimal, round to 2 places, audit trail |

### Escalation Path
- Issues with exchange API → Contact Kraken support
- Performance issues → Review caching strategy
- Merge conflicts → Contact code owner
- Test failures → Debug in isolation first

---

## 📝 Sign-Off

### Before Merging to Main

- [ ] **Code Review:** Approved by 2+ reviewers
- [ ] **Test Results:** 100+ tests passing, >90% coverage
- [ ] **Performance:** No regressions, FX caching works
- [ ] **Documentation:** README, docstrings, examples complete
- [ ] **Live Testing:** EUR and USD modes tested
- [ ] **QA Sign-Off:** All features working as expected

### Release v3.5

- [ ] Tag release: `git tag -a v3.5 -m "Multi-currency support"`
- [ ] Update INTEGRATION_V3.3_COMPLETE.md → v3.5 status
- [ ] Push tag: `git push origin v3.5`
- [ ] Announce release

---

**Ready to implement? Start with Day 1 Morning! 🚀**
