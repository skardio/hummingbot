"""
Config Sanity Check - US-009

Validates trading configuration at startup to detect problematic settings
that could lead to losses.

Usage:
    from multi_coin_grid_pro.utils.config_validator import ConfigValidator

    validator = ConfigValidator(config, logger)
    issues = validator.validate()

    if issues.has_critical:
        if not force_start:
            raise ConfigValidationError(issues)
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class IssueSeverity(Enum):
    """Severity level of config issue."""
    INFO = "INFO"          # Informational - no action needed
    WARNING = "WARNING"    # Should fix, but won't block
    CRITICAL = "CRITICAL"  # Serious issue - blocks production startup


@dataclass
class ConfigIssue:
    """Single config validation issue."""
    severity: IssueSeverity
    code: str  # Short code like "NEG_EXPECTANCY", "RSI_OVERBOUGHT"
    message: str  # Human-readable description
    current_value: Any
    recommended_value: Any
    remediation: str  # How to fix

    def __str__(self) -> str:
        return f"[{self.severity.value}] {self.code}: {self.message}"


@dataclass
class ValidationResult:
    """Result of config validation."""
    issues: List[ConfigIssue] = field(default_factory=list)

    @property
    def has_issues(self) -> bool:
        return len(self.issues) > 0

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == IssueSeverity.WARNING for i in self.issues)

    @property
    def has_critical(self) -> bool:
        return any(i.severity == IssueSeverity.CRITICAL for i in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.WARNING)

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.CRITICAL)

    def to_log_lines(self) -> List[str]:
        """Format issues as log lines."""
        lines = []
        for issue in self.issues:
            emoji = {
                IssueSeverity.INFO: "ℹ️",
                IssueSeverity.WARNING: "⚠️",
                IssueSeverity.CRITICAL: "🚨"
            }.get(issue.severity, "❓")

            lines.append(f"{emoji} {issue}")
            lines.append(f"   Current: {issue.current_value}")
            lines.append(f"   Recommended: {issue.recommended_value}")
            lines.append(f"   Fix: {issue.remediation}")
        return lines


class ConfigValidator:
    """
    Validates trading configuration for common mistakes.

    Checks:
    - Negative expectancy (SL > TP)
    - RSI thresholds too permissive
    - Order size vs min notional
    - Conflicting settings
    """

    def __init__(
        self,
        config: Any,
        logger: Optional[logging.Logger] = None,
        exchange_min_notional: Optional[Dict[str, float]] = None
    ):
        """
        Initialize config validator.

        Args:
            config: MultiCoinGridConfig or similar config object
            logger: Optional logger instance
            exchange_min_notional: Optional dict of exchange min notionals by quote asset
        """
        self.config = config
        self.logger = logger or logging.getLogger(__name__)

        # Default min notional values by exchange/quote
        self.min_notional_defaults = exchange_min_notional or {
            "USDT": 5.0,   # Most exchanges require min 5 USDT
            "EUR": 5.0,    # Kraken typically 5 EUR
            "USD": 5.0,
            "BTC": 0.0001,
        }

    def validate(self) -> ValidationResult:
        """
        Run all validation checks.

        Returns:
            ValidationResult with list of issues found
        """
        result = ValidationResult()

        # Run all checks
        self._check_negative_expectancy(result)
        self._check_rsi_thresholds(result)
        self._check_order_size(result)
        self._check_timeframe_consistency(result)
        self._check_risk_limits(result)
        self._check_exit_thresholds(result)

        return result

    def validate_and_log(self, block_on_critical: bool = True) -> ValidationResult:
        """
        Validate and log all issues.

        Args:
            block_on_critical: If True, raise error on critical issues in production

        Returns:
            ValidationResult

        Raises:
            ConfigValidationError if block_on_critical and critical issues found
        """
        result = self.validate()

        if not result.has_issues:
            self.logger.info("✅ US-009: Config validation passed - no issues found")
            return result

        # Log all issues
        self.logger.warning("=" * 70)
        self.logger.warning("⚠️  US-009: CONFIG SANITY CHECK - Issues Found")
        self.logger.warning("=" * 70)

        for line in result.to_log_lines():
            if "CRITICAL" in line or "🚨" in line:
                self.logger.error(line)
            elif "WARNING" in line or "⚠️" in line:
                self.logger.warning(line)
            else:
                self.logger.info(line)

        self.logger.warning("=" * 70)
        self.logger.warning(
            f"Summary: {result.critical_count} critical, {result.warning_count} warnings"
        )
        self.logger.warning("=" * 70)

        # Block on critical in production
        if block_on_critical and result.has_critical:
            paper_trading = getattr(self.config, 'paper_trading', True)
            if not paper_trading:
                raise ConfigValidationError(
                    f"Critical config issues found ({result.critical_count}). "
                    "Fix issues or set paper_trading=true to bypass."
                )

        return result

    def _check_negative_expectancy(self, result: ValidationResult) -> None:
        """Check if stop_loss_pct > take_profit_pct (negative expectancy)."""
        stop_loss_pct = getattr(self.config, 'stop_loss_pct', None)
        take_profit_pct = getattr(self.config, 'take_profit_pct', None)

        if stop_loss_pct is None or take_profit_pct is None:
            return

        # Convert to float for comparison
        sl = float(stop_loss_pct) if not isinstance(stop_loss_pct, float) else stop_loss_pct
        tp = float(take_profit_pct) if not isinstance(take_profit_pct, float) else take_profit_pct

        if sl > tp:
            result.issues.append(ConfigIssue(
                severity=IssueSeverity.CRITICAL,
                code="NEG_EXPECTANCY",
                message=f"Stop-loss ({sl * 100:.1f}%) > Take-profit ({tp * 100:.1f}%) → Negative expectancy!",
                current_value=f"SL={sl * 100:.1f}%, TP={tp * 100:.1f}%",
                recommended_value=f"SL < TP (e.g., SL={tp * 100:.1f}%, TP={(tp + 0.01) * 100:.1f}%)",
                remediation="Reduce stop_loss_pct below take_profit_pct or increase take_profit_pct"
            ))

    def _check_rsi_thresholds(self, result: ValidationResult) -> None:
        """Check RSI thresholds for overbought entries."""
        smart_entry = getattr(self.config, 'smart_entry_filter', {})
        if not smart_entry:
            return

        rsi_buy_max = smart_entry.get('rsi_buy_max', 65.0)
        rsi_block_min = smart_entry.get('rsi_block_min', 80.0)

        # Check for overbought entry permission
        if rsi_buy_max > 70:
            result.issues.append(ConfigIssue(
                severity=IssueSeverity.WARNING,
                code="RSI_OVERBOUGHT",
                message=f"rsi_buy_max={rsi_buy_max} allows overbought entries (RSI > 70)",
                current_value=f"rsi_buy_max={rsi_buy_max}",
                recommended_value="rsi_buy_max <= 70 (or 65 for safer entries)",
                remediation="Set smart_entry_filter.rsi_buy_max: 65 in config YAML"
            ))

        # Check block threshold is reasonable
        if rsi_block_min > 85:
            result.issues.append(ConfigIssue(
                severity=IssueSeverity.INFO,
                code="RSI_BLOCK_HIGH",
                message=f"rsi_block_min={rsi_block_min} - very permissive, only blocks extreme RSI",
                current_value=f"rsi_block_min={rsi_block_min}",
                recommended_value="rsi_block_min=80 for moderate protection",
                remediation="Set smart_entry_filter.rsi_block_min: 80 in config YAML"
            ))

    def _check_order_size(self, result: ValidationResult) -> None:
        """Check if order size meets minimum notional requirements."""
        total_amount = getattr(self.config, 'total_amount_quote', None)
        max_coins = getattr(self.config, 'max_simultaneous_coins', 1)
        num_grids = getattr(self.config, 'num_grids', 3)
        quote_asset = getattr(self.config, 'quote_asset', 'USDT')

        if total_amount is None:
            return

        # Calculate order size per grid level
        try:
            per_coin_capital = float(total_amount) / max(1, max_coins)
            order_size = per_coin_capital / max(1, num_grids)

            # Get min notional for quote asset
            min_notional = self.min_notional_defaults.get(quote_asset, 5.0)

            if order_size < min_notional:
                result.issues.append(ConfigIssue(
                    severity=IssueSeverity.CRITICAL,
                    code="ORDER_TOO_SMALL",
                    message=f"Order size {order_size:.2f} {quote_asset} < min notional {min_notional} {quote_asset}",
                    current_value=f"{order_size:.2f} {quote_asset} per grid level",
                    recommended_value=f">= {min_notional} {quote_asset}",
                    remediation="Increase total_amount_quote, reduce max_simultaneous_coins, or reduce num_grids"
                ))
            elif order_size < min_notional * 2:
                result.issues.append(ConfigIssue(
                    severity=IssueSeverity.WARNING,
                    code="ORDER_NEAR_MIN",
                    message=f"Order size {order_size:.2f} {quote_asset} is close to min notional {min_notional} {quote_asset}",
                    current_value=f"{order_size:.2f} {quote_asset} per grid level",
                    recommended_value=f">= {min_notional * 2} {quote_asset} for safety margin",
                    remediation="Consider increasing capital or reducing grid levels"
                ))
        except Exception:
            pass  # Skip if calculation fails

    def _check_timeframe_consistency(self, result: ValidationResult) -> None:
        """Check for inconsistent timeframe settings."""
        short = getattr(self.config, 'trend_lookback_short_minutes', 60)
        mid = getattr(self.config, 'trend_lookback_mid_minutes', 240)
        long = getattr(self.config, 'trend_lookback_long_minutes', 1440)

        if short >= mid or mid >= long:
            result.issues.append(ConfigIssue(
                severity=IssueSeverity.WARNING,
                code="TF_ORDER",
                message=f"Timeframe order incorrect: short={short}m, mid={mid}m, long={long}m",
                current_value=f"short={short}, mid={mid}, long={long}",
                recommended_value="short < mid < long (e.g., 60 < 240 < 1440)",
                remediation="Adjust trend_lookback_*_minutes values"
            ))

    def _check_risk_limits(self, result: ValidationResult) -> None:
        """Check risk limit settings."""
        daily_loss = getattr(self.config, 'max_daily_loss_pct', 5.0)
        weekly_loss = getattr(self.config, 'max_weekly_loss_pct', 10.0)
        monthly_loss = getattr(self.config, 'max_monthly_loss_pct', 15.0)

        # Check for overly aggressive limits
        if daily_loss > 10.0:
            result.issues.append(ConfigIssue(
                severity=IssueSeverity.WARNING,
                code="RISK_DAILY_HIGH",
                message=f"Daily loss limit {daily_loss}% is very high",
                current_value=f"max_daily_loss_pct={daily_loss}%",
                recommended_value="max_daily_loss_pct <= 5%",
                remediation="Reduce max_daily_loss_pct for better risk management"
            ))

        # Check for inverted limits
        if daily_loss > weekly_loss or weekly_loss > monthly_loss:
            result.issues.append(ConfigIssue(
                severity=IssueSeverity.WARNING,
                code="RISK_ORDER",
                message="Risk limits should increase: daily < weekly < monthly",
                current_value=f"daily={daily_loss}%, weekly={weekly_loss}%, monthly={monthly_loss}%",
                recommended_value="daily < weekly < monthly",
                remediation="Adjust loss limits to proper order"
            ))

    def _check_exit_thresholds(self, result: ValidationResult) -> None:
        """Check exit threshold settings."""
        emergency = getattr(self.config, 'emergency_exit_pct', -2.0)
        hard_stop = getattr(self.config, 'hard_stop_pct', -3.0)

        # Both should be negative
        if emergency > 0 or hard_stop > 0:
            result.issues.append(ConfigIssue(
                severity=IssueSeverity.CRITICAL,
                code="EXIT_SIGN",
                message="Emergency exit thresholds should be negative percentages",
                current_value=f"emergency={emergency}%, hard_stop={hard_stop}%",
                recommended_value="Both should be negative (e.g., -2.0%, -3.0%)",
                remediation="Use negative values for emergency_exit_pct and hard_stop_pct"
            ))

        # Emergency should trigger before hard stop
        if emergency <= hard_stop:
            result.issues.append(ConfigIssue(
                severity=IssueSeverity.WARNING,
                code="EXIT_ORDER",
                message=f"Emergency exit ({emergency}%) should be less negative than hard stop ({hard_stop}%)",
                current_value=f"emergency={emergency}%, hard_stop={hard_stop}%",
                recommended_value="emergency_exit_pct > hard_stop_pct (e.g., -2.0% > -3.0%)",
                remediation="Emergency exit should trigger first (less negative)"
            ))


class ConfigValidationError(Exception):
    """Raised when critical config issues are found in production mode."""
    pass
