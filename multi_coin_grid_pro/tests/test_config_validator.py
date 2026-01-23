"""
Tests for US-009: Config Sanity Check

Tests the config validator that checks for problematic settings at startup.
"""
# Direct import to avoid utils/__init__.py heavy dependencies
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

_spec = importlib.util.spec_from_file_location(
    "config_validator",
    Path(__file__).parent.parent / "utils" / "config_validator.py"
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

ConfigValidator = _module.ConfigValidator
ConfigIssue = _module.ConfigIssue
IssueSeverity = _module.IssueSeverity
ValidationResult = _module.ValidationResult
ConfigValidationError = _module.ConfigValidationError


@dataclass
class MockConfig:
    """Mock config for testing."""
    # Risk settings
    stop_loss_pct: float = 0.03  # 3%
    take_profit_pct: float = 0.05  # 5%

    # RSI settings
    smart_entry_filter: Optional[Dict[str, Any]] = None

    # Position settings
    total_amount_quote: float = 100.0
    max_simultaneous_coins: int = 2
    num_grids: int = 3
    quote_asset: str = "USDT"

    # Timeframes
    trend_lookback_short_minutes: int = 60
    trend_lookback_mid_minutes: int = 240
    trend_lookback_long_minutes: int = 1440

    # Risk limits
    max_daily_loss_pct: float = 5.0
    max_weekly_loss_pct: float = 10.0
    max_monthly_loss_pct: float = 15.0

    # Exit thresholds
    emergency_exit_pct: float = -2.0
    hard_stop_pct: float = -3.0

    # Paper trading
    paper_trading: bool = True


class TestConfigValidator:
    """Test suite for ConfigValidator."""

    def test_valid_config_passes(self):
        """Test that a valid config passes all checks."""
        config = MockConfig()
        validator = ConfigValidator(config)

        result = validator.validate()

        assert result.has_issues is False
        assert result.has_critical is False
        assert result.has_warnings is False

    def test_negative_expectancy_detected(self):
        """Test detection of stop_loss > take_profit."""
        config = MockConfig(
            stop_loss_pct=0.05,  # 5%
            take_profit_pct=0.035  # 3.5% - LESS THAN SL!
        )
        validator = ConfigValidator(config)

        result = validator.validate()

        assert result.has_critical is True
        assert any(i.code == "NEG_EXPECTANCY" for i in result.issues)

    def test_rsi_overbought_warning(self):
        """Test warning when RSI thresholds allow overbought entries."""
        config = MockConfig(
            smart_entry_filter={'rsi_buy_max': 85.0}
        )
        validator = ConfigValidator(config)

        result = validator.validate()

        assert result.has_warnings is True
        assert any(i.code == "RSI_OVERBOUGHT" for i in result.issues)

    def test_order_too_small_critical(self):
        """Test critical issue when order size below min notional."""
        config = MockConfig(
            total_amount_quote=10.0,  # Small capital
            max_simultaneous_coins=5,  # Divided by 5
            num_grids=5  # Divided by 5 again = 10/5/5 = 0.4 per order
        )
        validator = ConfigValidator(config)

        result = validator.validate()

        assert result.has_critical is True
        assert any(i.code == "ORDER_TOO_SMALL" for i in result.issues)

    def test_order_near_min_warning(self):
        """Test warning when order size close to min notional."""
        config = MockConfig(
            total_amount_quote=50.0,  # Limited capital
            max_simultaneous_coins=2,  # Divided by 2
            num_grids=4  # Divided by 4 = 50/2/4 = 6.25 per order (close to 5 min)
        )
        validator = ConfigValidator(config)

        result = validator.validate()

        # Should get warning for being close to min
        assert any(i.code == "ORDER_NEAR_MIN" for i in result.issues)

    def test_timeframe_order_warning(self):
        """Test warning for incorrect timeframe ordering."""
        config = MockConfig(
            trend_lookback_short_minutes=240,  # Same as mid!
            trend_lookback_mid_minutes=240,
            trend_lookback_long_minutes=1440
        )
        validator = ConfigValidator(config)

        result = validator.validate()

        assert any(i.code == "TF_ORDER" for i in result.issues)

    def test_risk_daily_high_warning(self):
        """Test warning for overly aggressive daily loss limit."""
        config = MockConfig(
            max_daily_loss_pct=15.0  # 15% daily loss allowed - very high
        )
        validator = ConfigValidator(config)

        result = validator.validate()

        assert any(i.code == "RISK_DAILY_HIGH" for i in result.issues)

    def test_risk_order_warning(self):
        """Test warning for inverted risk limits."""
        config = MockConfig(
            max_daily_loss_pct=10.0,
            max_weekly_loss_pct=5.0,  # Weekly LESS than daily!
            max_monthly_loss_pct=15.0
        )
        validator = ConfigValidator(config)

        result = validator.validate()

        assert any(i.code == "RISK_ORDER" for i in result.issues)

    def test_exit_sign_critical(self):
        """Test critical when exit thresholds are positive."""
        config = MockConfig(
            emergency_exit_pct=2.0,  # Should be negative!
            hard_stop_pct=3.0
        )
        validator = ConfigValidator(config)

        result = validator.validate()

        assert result.has_critical is True
        assert any(i.code == "EXIT_SIGN" for i in result.issues)

    def test_exit_order_warning(self):
        """Test warning when emergency is more negative than hard stop."""
        config = MockConfig(
            emergency_exit_pct=-5.0,  # More aggressive than hard stop!
            hard_stop_pct=-3.0
        )
        validator = ConfigValidator(config)

        result = validator.validate()

        assert any(i.code == "EXIT_ORDER" for i in result.issues)

    def test_validate_and_log_blocks_production(self):
        """Test that critical issues block production startup."""
        config = MockConfig(
            stop_loss_pct=0.05,
            take_profit_pct=0.03,  # Negative expectancy
            paper_trading=False  # Production mode
        )
        validator = ConfigValidator(config)

        with pytest.raises(ConfigValidationError):
            validator.validate_and_log(block_on_critical=True)

    def test_validate_and_log_allows_paper_trading(self):
        """Test that critical issues are allowed in paper trading."""
        config = MockConfig(
            stop_loss_pct=0.05,
            take_profit_pct=0.03,  # Negative expectancy
            paper_trading=True  # Paper trading mode
        )
        validator = ConfigValidator(config)

        # Should not raise even with critical issues
        result = validator.validate_and_log(block_on_critical=False)
        assert result.has_critical is True  # Issue is still flagged


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_empty_result(self):
        """Test empty result properties."""
        result = ValidationResult()

        assert result.has_issues is False
        assert result.has_warnings is False
        assert result.has_critical is False
        assert result.warning_count == 0
        assert result.critical_count == 0

    def test_result_with_issues(self):
        """Test result with various issues."""
        result = ValidationResult(issues=[
            ConfigIssue(
                severity=IssueSeverity.WARNING,
                code="TEST_WARN",
                message="Test warning",
                current_value="x",
                recommended_value="y",
                remediation="Fix it"
            ),
            ConfigIssue(
                severity=IssueSeverity.CRITICAL,
                code="TEST_CRIT",
                message="Test critical",
                current_value="a",
                recommended_value="b",
                remediation="Fix it now"
            ),
        ])

        assert result.has_issues is True
        assert result.has_warnings is True
        assert result.has_critical is True
        assert result.warning_count == 1
        assert result.critical_count == 1

    def test_to_log_lines(self):
        """Test log line formatting."""
        result = ValidationResult(issues=[
            ConfigIssue(
                severity=IssueSeverity.WARNING,
                code="TEST",
                message="Test message",
                current_value="100",
                recommended_value="50",
                remediation="Reduce value"
            )
        ])

        lines = result.to_log_lines()

        assert len(lines) == 4  # One issue = 4 lines
        assert "TEST" in lines[0]
        assert "100" in lines[1]
        assert "50" in lines[2]
        assert "Reduce" in lines[3]


class TestConfigIssue:
    """Test ConfigIssue dataclass."""

    def test_str_representation(self):
        """Test string representation of issue."""
        issue = ConfigIssue(
            severity=IssueSeverity.CRITICAL,
            code="TEST_CODE",
            message="Test message here",
            current_value="bad",
            recommended_value="good",
            remediation="Do the thing"
        )

        result = str(issue)

        assert "CRITICAL" in result
        assert "TEST_CODE" in result
        assert "Test message" in result


class TestIssueSeverity:
    """Test IssueSeverity enum."""

    def test_severity_values(self):
        """Test severity enum values."""
        assert IssueSeverity.INFO.value == "INFO"
        assert IssueSeverity.WARNING.value == "WARNING"
        assert IssueSeverity.CRITICAL.value == "CRITICAL"
