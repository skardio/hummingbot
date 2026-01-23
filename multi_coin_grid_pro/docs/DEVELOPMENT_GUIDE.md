# 🛠️ Development Guide - Multi-Coin Grid Pro

Dit document bevat alle informatie voor het ontwikkelen van nieuwe features en user stories.

---

## 🐍 Python Environment

### Activeer de juiste virtual environment
```bash
source ~/.venvs/bot/bin/activate
```

### Verificatie
```bash
which python
# Moet zijn: /home/mo/.venvs/bot/bin/python

python --version
# Python 3.12.x

# Check key packages
python -c "import pydantic, hummingbot; print('✅ Environment OK')"
```

---

## 🧪 Unit Tests

### Test Locaties
```
multi_coin_grid_pro/tests/
├── unit/                    # Unit tests per component
├── integration/             # Integration tests
├── core/                    # Core module tests
├── utils/                   # Utility tests
├── filters/                 # Filter tests
├── observability/           # Event/metrics tests
└── stress/                  # Stress tests
```

### Test Commands

```bash
# Activeer environment eerst!
source ~/.venvs/bot/bin/activate

# === ALLE TESTS ===
cd /home/mo/repos/hummingbot
pytest multi_coin_grid_pro/tests/ -v

# === SPECIFIEKE TEST FILE ===
pytest multi_coin_grid_pro/tests/core/test_reason_codes.py -v

# === SPECIFIEKE TEST FUNCTIE ===
pytest multi_coin_grid_pro/tests/core/test_reason_codes.py::TestReasonCodes::test_reason_code_count -v

# === MET COVERAGE ===
pytest multi_coin_grid_pro/tests/ --cov=multi_coin_grid_pro --cov-report=html
# Open: coverage_html_report/index.html

# === STOP BIJ EERSTE FAILURE ===
pytest multi_coin_grid_pro/tests/ -x -v

# === ALLEEN FAILED TESTS (re-run) ===
pytest multi_coin_grid_pro/tests/ --lf -v

# === PARALLEL (sneller) ===
pytest multi_coin_grid_pro/tests/ -n auto -v
```

### Test Naming Convention
```python
# File: test_<component>.py
# Class: Test<ComponentName>
# Method: test_<what_it_tests>

# Voorbeeld:
# File: test_smart_entry_filter.py
class TestSmartEntryFilter:
    def test_rsi_extreme_blocks_falling_knife(self):
        ...
    def test_atr_min_requires_volatility(self):
        ...
```

### Test Template
```python
"""Tests for <Component>."""
import pytest
from unittest.mock import Mock, patch, MagicMock

from multi_coin_grid_pro.<module> import <Class>


class Test<ClassName>:
    """Test suite for <ClassName>."""

    def setup_method(self):
        """Setup test fixtures."""
        self.mock_config = Mock()
        self.mock_config.some_setting = "value"

    def test_<feature>_<expected_behavior>(self):
        """Test that <feature> does <expected_behavior>."""
        # Arrange
        instance = <Class>(self.mock_config)

        # Act
        result = instance.some_method()

        # Assert
        assert result == expected_value

    @pytest.mark.asyncio
    async def test_async_method(self):
        """Test async functionality."""
        # Arrange
        instance = <Class>(self.mock_config)

        # Act
        result = await instance.async_method()

        # Assert
        assert result is not None
```

---

## 📝 Code Style - Flake8

### Configuratie
De flake8 config staat in `pyproject.toml` of `.flake8`:

```ini
[flake8]
max-line-length = 120
exclude = .git,__pycache__,build,dist,venv,.venv
ignore = E203, E266, E501, W503
per-file-ignores =
    __init__.py: F401
```

### Flake8 Commands

```bash
# Activeer environment eerst!
source ~/.venvs/bot/bin/activate

# === HELE PROJECT ===
cd /home/mo/repos/hummingbot
flake8 multi_coin_grid_pro/

# === SPECIFIEK BESTAND ===
flake8 multi_coin_grid_pro/controllers/multi_coin_grid_controller.py

# === MET STATISTICS ===
flake8 multi_coin_grid_pro/ --statistics

# === ALLEEN ERRORS (geen warnings) ===
flake8 multi_coin_grid_pro/ --select=E

# === AUTO-FIX (met autopep8) ===
autopep8 --in-place --aggressive multi_coin_grid_pro/utils/trend_calculator.py

# === CHECK BEFORE COMMIT ===
flake8 multi_coin_grid_pro/ && echo "✅ Flake8 passed"
```

### Veelvoorkomende Errors

| Code | Betekenis | Fix |
|------|-----------|-----|
| E501 | Line too long | Split line of verhoog max-line-length |
| E302 | Expected 2 blank lines | Voeg lege regel toe na class/function |
| E303 | Too many blank lines | Verwijder extra lege regels |
| E401 | Multiple imports on one line | Split imports |
| F401 | Module imported but unused | Verwijder unused import |
| F841 | Variable assigned but never used | Verwijder of gebruik variable |
| W503 | Line break before operator | Negeer (style preference) |

---

## 📋 User Story Template

### File: `docs/user_stories/US_XXX_<NAME>.md`

```markdown
# US-XXX: <Title>

## 📋 Story
Als [rol] wil ik [feature] zodat [benefit].

## ✅ Acceptance Criteria
1. [ ] Criterium 1
2. [ ] Criterium 2
3. [ ] Criterium 3

## 🎯 Technical Tasks
- [ ] Task 1: <beschrijving>
- [ ] Task 2: <beschrijving>
- [ ] Task 3: <beschrijving>

## 📁 Files to Modify
- `multi_coin_grid_pro/controllers/multi_coin_grid_controller.py`
- `multi_coin_grid_pro/utils/<new_utility>.py`

## 🧪 Test Cases
1. `test_<feature>_happy_path` - Normal flow
2. `test_<feature>_edge_case` - Edge case
3. `test_<feature>_error_handling` - Error scenario

## 📊 Config Changes
```yaml
# New config parameters
new_feature_enabled: true
new_feature_threshold: 0.5
```

## 🔍 Verification
```bash
# How to verify the feature works
grep -E "FEATURE_LOG" logs/*.log
```
```

---

## 🔄 Development Workflow

### 1. Start Feature
```bash
# Activeer environment
source ~/.venvs/bot/bin/activate

# Check huidige branch
git status
git checkout -b feature/US-XXX-feature-name
```

### 2. Schrijf Tests Eerst (TDD)
```bash
# Maak test file
touch multi_coin_grid_pro/tests/unit/test_new_feature.py

# Schrijf failing tests
pytest multi_coin_grid_pro/tests/unit/test_new_feature.py -v
# Moet FALEN (nog geen implementatie)
```

### 3. Implementeer Feature
```bash
# Edit code
# ...

# Run tests continu
pytest multi_coin_grid_pro/tests/unit/test_new_feature.py -v --tb=short
```

### 4. Code Quality Check
```bash
# Flake8
flake8 multi_coin_grid_pro/ --statistics

# Type hints (optioneel)
mypy multi_coin_grid_pro/

# Alle tests
pytest multi_coin_grid_pro/tests/ -v
```

### 5. Commit
```bash
# Stage changes
git add .

# Commit met US nummer
git commit -m "US-XXX: Implement feature description"

# Push
git push origin feature/US-XXX-feature-name
```

---

## 📁 Project Structure

```
multi_coin_grid_pro/
├── controllers/              # Main controller logic
│   ├── multi_coin_grid_controller.py   # Hoofd controller (7800+ lines)
│   └── multi_coin_grid_config.py       # Pydantic config model
├── core/                     # Core components
│   ├── reason_codes.py       # Rejection reason codes
│   ├── drawdown_tracker.py   # Risk management
│   ├── performance_tracker.py
│   └── config_loader.py
├── filters/                  # Entry filters
│   ├── smart_entry_filter.py # SmartEntry v2
│   └── time_based_filter.py
├── utils/                    # Utilities
│   ├── trend_calculator.py   # Price trends
│   ├── staleness_guard.py    # Data freshness
│   ├── coin_discovery.py     # Dynamic pair finding
│   ├── config_validator.py   # Config sanity checks
│   └── trace_generator.py    # Decision tracing
├── persistence/              # Data storage
│   └── cooldown_store.py     # SQLite cooldowns
├── observability/            # Logging & metrics
│   └── event_logger.py       # JSONL events
├── config/                   # YAML configs
│   └── spot_grid_kraken_eur.yaml
├── spot_bitget/config/       # Bitget configs
│   └── spot_grid_bitget.yaml
├── docs/                     # Documentation
│   ├── ANALYSIS_CONTEXT.md
│   └── DEVELOPMENT_GUIDE.md  # Dit bestand
└── tests/                    # All tests
    ├── unit/
    ├── integration/
    ├── core/
    └── utils/
```

---

## 🐛 Debugging

### Log Levels
```yaml
# In config YAML
log_level: DEBUG   # DEBUG, INFO, WARNING, ERROR
```

### Handige Debug Commands
```bash
# Real-time log watching
tail -f logs/logs_multi_coin_grid_v2_*.log | grep -E "ERROR|WARNING|SELECTED"

# Specifieke coin volgen
grep "DOT-EUR" logs/logs_multi_coin_grid_v2_*.log | tail -50

# Rejection reasons
grep -E "REJECTED|NO BUY" logs/logs_multi_coin_grid_v2_*.log | tail -20

# Grid creation events
grep -E "Creating grid|Grid created" logs/logs_multi_coin_grid_v2_*.log
```

### Python Debugging
```python
# In code toevoegen voor debugging
import pdb; pdb.set_trace()

# Of met breakpoint (Python 3.7+)
breakpoint()

# Logging in controller
self.logger().debug(f"🔧 DEBUG: variable={variable}")
```

---

## ✅ Pre-Commit Checklist

Voordat je commit:

```bash
# 1. Activeer environment
source ~/.venvs/bot/bin/activate

# 2. Flake8 check
flake8 multi_coin_grid_pro/ && echo "✅ Flake8 OK"

# 3. Run tests
pytest multi_coin_grid_pro/tests/ -v -x && echo "✅ Tests OK"

# 4. Check voor TODO/FIXME
grep -rn "TODO\|FIXME" multi_coin_grid_pro/*.py | head -10

# 5. Verify no secrets
grep -rn "api_key\|secret\|password" multi_coin_grid_pro/ --include="*.py" | grep -v "example\|test\|mock"
```

---

## 🔗 Related Docs

- [ANALYSIS_CONTEXT.md](ANALYSIS_CONTEXT.md) - Log locaties en analyse commands
- [PROFESSIONAL_RISK_MANAGEMENT_GUIDE.md](../../PROFESSIONAL_RISK_MANAGEMENT_GUIDE.md) - Risk management
- [PHASE_1_2_3_IMPLEMENTATION.md](../../PHASE_1_2_3_IMPLEMENTATION.md) - Feature implementation history

---

*Laatste update: 2026-01-17*
