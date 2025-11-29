s# Multi-Coin Grid Bot - Test Suite

Unit tests voor de Multi-Coin Grid Trading Bot.

## Setup

### Install dependencies

```bash
cd /home/mo/repos/hummingbot
pip install pytest pytest-asyncio pytest-cov
```

### Run tests

```bash
# Run all tests
pytest multi_coin_grid_pro/tests/ -v

# Run only unit tests
pytest multi_coin_grid_pro/tests/unit/ -v

# Run specific test file
pytest multi_coin_grid_pro/tests/unit/test_multi_coin_grid_controller.py -v

# Run specific test
pytest multi_coin_grid_pro/tests/unit/test_multi_coin_grid_controller.py::TestMultiCoinGridController::test_create_stop_action_with_position -v

# Run with coverage
pytest multi_coin_grid_pro/tests/ --cov=multi_coin_grid_pro --cov-report=html
```

## Test Structure

```
tests/
├── unit/              # Unit tests (fast, isolated)
│   └── test_multi_coin_grid_controller.py
├── test_coin_discovery.py
├── test_trend_calculator.py
└── integration/       # Integration tests (slower, require full setup)
```

## Test Coverage

### Unit Tests (`test_multi_coin_grid_controller.py`)

1. **Position Closing Tests**
   - `test_create_stop_action_with_position`: Test dat stop action `keep_position=False` heeft wanneer executor positie heeft
   - `test_create_stop_action_no_position`: Test stop action zonder positie

2. **Position Limits Tests**
   - `test_position_limits_check`: Test dat position limits worden gehandhaafd

3. **Manual Trading Pairs Tests**
   - `test_manual_trading_pairs`: Test dat manual trading pairs auto-discovery overschrijven

4. **Switch Logic Tests**
   - `test_switch_logic_with_negative_trend`: Test early exit bij negatieve trend
   - `test_switch_cost_calculation`: Test switch cost berekening
   - `test_liquidity_requirements`: Test liquidity filtering

5. **Exposure Tracking Tests**
   - `test_exposure_tracking_reset`: Test dat exposure wordt gereset wanneer executor inactive wordt

6. **Grid Creation Tests**
   - `test_create_grid_action_validation`: Test validatie van grid parameters

7. **Startup Delay Tests**
   - `test_startup_delay_prevents_first_trade`: Test dat startup delay eerste trade blokkeert
   - `test_startup_delay_allows_trade_after_wait`: Test dat trade toegestaan wordt na wachttijd
   - `test_startup_delay_not_applied_to_switches`: Test dat startup delay alleen voor eerste trade geldt
   - `test_startup_delay_logs_remaining_time`: Test dat resterende wachttijd wordt gelogd

8. **GridExecutor Close Order Price Tests** (`test_grid_executor_close_order_price.py`)
   - `test_early_stop_with_valid_price`: Test dat early_stop() geldige prijs gebruikt voor market orders
   - `test_early_stop_fallback_to_get_price`: Test fallback naar get_price() wanneer metrics geen prijs hebben
   - `test_place_close_order_with_nan_price_fallback`: Test NaN prijs handling in place_close_order
   - `test_place_close_order_with_zero_price_fallback`: Test zero prijs handling
   - `test_place_close_order_with_valid_price_no_fallback`: Test dat geldige prijs direct wordt gebruikt
   - `test_early_stop_no_position_no_order`: Test dat geen order wordt geplaatst bij te kleine positie

9. **Auto-Blacklist & Error Handling Tests** (`test_multi_coin_grid_controller.py`)
   - `test_auto_blacklist_after_max_errors`: Test dat coins automatisch worden geblacklist na max errors
   - `test_auto_blacklist_excludes_coin_from_selection`: Test dat auto-blacklisted coins worden uitgesloten van selectie
   - `test_insufficient_balance_cooldown`: Test cooldown mechanisme na insufficient balance errors
   - `test_error_count_tracking_per_coin`: Test dat errors per coin worden getrackt
   - `test_combined_cooldown_and_blacklist_exclusion`: Test dat zowel cooldown als blacklisted coins worden uitgesloten

10. **GridExecutor Balance Check Tests** (`test_grid_executor_balance_check.py`)
    - `test_balance_check_sufficient_balance`: Test dat order wordt geplaatst bij voldoende balans
    - `test_balance_check_insufficient_balance_adjusts_amount`: Test dat order amount wordt aangepast bij onvoldoende balans
    - `test_balance_check_insufficient_balance_below_minimum`: Test dat geen order wordt geplaatst bij balans onder minimum
    - `test_balance_check_handles_exception`: Test exception handling in balance check
    - `test_balance_check_logs_warning_on_adjustment`: Test dat warning wordt gelogd bij amount adjustment
    - `test_balance_check_logs_error_on_insufficient`: Test dat error wordt gelogd bij onvoldoende balans

## Writing New Tests

### Example Test Structure

```python
async def test_feature_name(self, controller, mock_connector):
    """Test description"""
    # Setup
    controller.some_state = "value"

    # Execute
    result = controller.some_method()

    # Assert
    assert result == expected_value
```

### Mocking Best Practices

- Mock external dependencies (connectors, API calls)
- Use fixtures for common setup
- Keep tests isolated (don't depend on other tests)
- Test edge cases and error conditions

## Troubleshooting

### Import Errors

Als je import errors krijgt, zorg dat je in de juiste directory bent:

```bash
cd /home/mo/repos/hummingbot
export PYTHONPATH=/home/mo/repos/hummingbot:$PYTHONPATH
pytest multi_coin_grid_pro/tests/ -v
```

### Missing Dependencies

```bash
pip install -r multi_coin_grid_pro/requirements.txt
```

### Tests Fail

Check de logs voor meer details:

```bash
pytest multi_coin_grid_pro/tests/ -v --tb=long
```

## Continuous Integration

Tests kunnen automatisch draaien bij:
- Git commits (pre-commit hook)
- Pull requests
- Nightly builds

Zie `.github/workflows/tests.yml` voor CI configuratie.
