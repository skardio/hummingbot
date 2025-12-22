# Multi-Coin Grid Pro - Test Suite

Comprehensive unit tests for the Multi-Coin Grid Pro trading bot features.

## Test Coverage

### Core Features

#### 1. Regime Detector Tests (`test_regime_detector.py`)
Tests for market regime detection (BULL/BEAR/CHOP):
- ✅ Bullish regime detection
- ✅ Bearish regime detection
- ✅ Choppy/sideways regime detection
- ✅ Insufficient data handling
- ✅ Regime duration tracking
- ✅ Configuration validation
- ✅ Volatility calculations

#### 2. Decision Trace Tests (`test_decision_trace.py`)
Tests for decision logging and tracking:
- ✅ Buy decision tracing
- ✅ Sell decision tracing
- ✅ Rejected decision tracking
- ✅ Filter result recording
- ✅ History management (max limits)
- ✅ Statistics generation
- ✅ Multi-pair tracking

#### 3. Adaptive Filter Tests (`test_adaptive_filter_resolver.py`)
Tests for dynamic filter adjustment:
- ✅ Bull regime filter resolution
- ✅ Bear regime filter resolution
- ✅ Chop regime filter resolution
- ✅ Fallback to base filters
- ✅ Filter preset management
- ✅ Configuration updates
- ✅ Filter validation

#### 4. Integration Tests (`test_decision_trace_integration.py`)
Tests for feature integration:
- ✅ Buy decision integration
- ✅ Sell decision integration
- ✅ Multi-pair integration
- ✅ Disabled trace handling
- ✅ Filter conversion
- ✅ Decorator integration

### Existing Tests

#### 5. Smart Entry Tests (`test_smart_entry.py`)
Tests for entry validation system

#### 6. Liquidity Aware Sizing Tests (`test_liquidity_aware_sizing.py`)
Tests for dynamic position sizing

#### 7. PnL and Risk Tests (`test_pnl_and_risk.py`)
Tests for risk management

#### 8. Grid Sizer Tests (`test_grid_sizer.py`)
Tests for dynamic grid sizing

## Running Tests

### Run All Tests
```bash
cd /home/mo/repos/hummingbot/multi_coin_grid_pro/tests
pytest -v
```

### Run Specific Test File
```bash
pytest test_regime_detector.py -v
pytest test_decision_trace.py -v
pytest test_adaptive_filter_resolver.py -v
```

### Run with Coverage
```bash
pytest --cov=multi_coin_grid_pro --cov-report=html
```

### Run Single Test
```bash
pytest test_regime_detector.py::TestRegimeDetector::test_detect_bull_regime -v
```

## Test Structure

```
multi_coin_grid_pro/tests/
├── __init__.py
├── conftest.py                          # Pytest configuration
├── fixtures/                            # Shared test fixtures
├── README.md                            # This file
├── test_regime_detector.py             # ✨ NEW: Regime detection tests
├── test_decision_trace.py              # ✨ NEW: Decision tracing tests
├── test_adaptive_filter_resolver.py    # ✨ NEW: Adaptive filter tests
├── test_decision_trace_integration.py  # ✨ NEW: Integration tests
├── test_smart_entry.py                 # Entry validation tests
├── test_liquidity_aware_sizing.py      # Position sizing tests
├── test_pnl_and_risk.py               # Risk management tests
└── test_grid_sizer.py                 # Grid sizing tests
```

## Test Requirements

Tests use standard Python unittest framework with some pytest features:
- `unittest` - Core test framework
- `pytest` - Test runner (optional but recommended)
- `unittest.mock` - Mocking for isolated tests
- `MagicMock` - For mocking dependencies

## Mock Data Helpers

Each test file includes helper methods to create test data:

### Regime Detector Helpers
- `_create_uptrend_candles()` - Mock bullish candles
- `_create_downtrend_candles()` - Mock bearish candles
- `_create_sideways_candles()` - Mock choppy candles
- `_create_volatile_candles()` - Mock high volatility candles

### Decision Trace Helpers
Uses simple dict structures for metrics and filter results

### Adaptive Filter Helpers
Uses FilterPreset and FilterSet dataclasses

## Coverage Goals

Current test coverage for new features:
- ✅ Regime Detector: ~90%
- ✅ Decision Trace: ~85%
- ✅ Adaptive Filters: ~80%
- ✅ Integration: ~75%

## Continuous Integration

These tests are designed to run in CI/CD pipelines:
- Fast execution (< 5 seconds per file)
- No external dependencies (mocked exchanges)
- Isolated tests (no shared state)
- Clear pass/fail criteria

## Adding New Tests

When adding new features, follow this pattern:

1. Create new test file: `test_feature_name.py`
2. Import the feature modules
3. Create test class inheriting from `unittest.TestCase`
4. Add `setUp()` method for test fixtures
5. Write individual test methods (prefix with `test_`)
6. Add helper methods for mock data (prefix with `_`)
7. Update this README with coverage info

Example:
```python
import unittest
from your_feature import YourFeature

class TestYourFeature(unittest.TestCase):
    def setUp(self):
        self.feature = YourFeature()

    def test_basic_functionality(self):
        result = self.feature.do_something()
        self.assertEqual(result, expected_value)
```

## Test Output Example

```
test_regime_detector.py::TestRegimeDetector::test_detect_bull_regime PASSED
test_regime_detector.py::TestRegimeDetector::test_detect_bear_regime PASSED
test_regime_detector.py::TestRegimeDetector::test_detect_chop_regime PASSED
test_decision_trace.py::TestDecisionTrace::test_trace_buy_decision PASSED
test_decision_trace.py::TestDecisionTrace::test_trace_sell_decision PASSED
test_adaptive_filter_resolver.py::TestAdaptiveFilterResolver::test_resolve_bull_regime_filters PASSED

========================= 45 passed in 2.34s =========================
```

## Debugging Failed Tests

If tests fail:

1. Run with verbose output: `pytest -vv`
2. Run single test: `pytest test_file.py::TestClass::test_method -v`
3. Add print statements in test
4. Use pytest debugger: `pytest --pdb`
5. Check mock data in helper methods

## Notes

- All tests use mocked data (no real API calls)
- Tests are independent (can run in any order)
- Each test cleans up after itself
- Mock exchanges and connectors where needed
- Focus on business logic, not I/O operations

## Next Steps

Future test improvements:
- [ ] Add integration tests with real data replay
- [ ] Add stress tests for high-frequency scenarios
- [ ] Add property-based tests (hypothesis)
- [ ] Add performance benchmarks
- [ ] Add mutation testing for coverage validation
