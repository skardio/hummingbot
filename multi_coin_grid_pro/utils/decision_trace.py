"""
Decision Trace System - Production-Grade Debugging voor Trading Pair Acceptance

Dit systeem traced EXACT waarom een trading pair wordt geaccepteerd of afgewezen.
Elke filter check wordt gelogd met input values, thresholds, en resultaat.

Usage:
    trace = PairDecisionTrace(
        trading_pair="CHZ-USDT",
        exchange="bitget",
        enabled=config.debug_trace_enabled
    )

    trace.add_check("consensus_trend", value=16.25, threshold=0.5, passed=True)
    trace.add_check("rsi", value=79.3, threshold=72.0, passed=False, reason="overbought")

    trace.finalize(accepted=False, rejected_by="rsi")

    logger.info(trace.to_compact_log())
    trace.to_json()  # For analysis/dashboard

Author: Senior Quant Developer
Date: 2025-12-20
"""

import json
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class FilterCheck:
    """Single filter check result"""
    filter_name: str
    value: Any
    threshold: Optional[Any] = None
    threshold_min: Optional[Any] = None  # For range checks
    threshold_max: Optional[Any] = None
    passed: bool = False
    reason: Optional[str] = None
    operator: str = ">="  # >=, <=, ==, !=, range

    def __post_init__(self):
        """Auto-generate reason if not provided"""
        if self.reason is None:
            if self.threshold is not None:
                status = "✅ PASS" if self.passed else "❌ FAIL"
                self.reason = f"{self.value} {self.operator} {self.threshold} → {status}"
            elif self.threshold_min is not None and self.threshold_max is not None:
                status = "✅ PASS" if self.passed else "❌ FAIL"
                self.reason = f"{self.threshold_min} <= {self.value} <= {self.threshold_max} → {status}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to structured dict"""
        return {
            "filter": self.filter_name,
            "value": self._serialize(self.value),
            "threshold": self._serialize(self.threshold),
            "threshold_min": self._serialize(self.threshold_min),
            "threshold_max": self._serialize(self.threshold_max),
            "passed": self.passed,
            "reason": self.reason,
            "operator": self.operator
        }

    @staticmethod
    def _serialize(val: Any) -> Any:
        """Convert Decimal/complex types to JSON-serializable"""
        if isinstance(val, Decimal):
            return float(val)
        return val

    def to_compact(self) -> str:
        """Compact single-line representation"""
        symbol = "✅" if self.passed else "❌"

        if self.threshold_min is not None and self.threshold_max is not None:
            return f"{symbol} {self.filter_name}: {self._format(self.value)} in [{self._format(self.threshold_min)}, {self._format(self.threshold_max)}]"
        elif self.threshold is not None:
            return f"{symbol} {self.filter_name}: {self._format(self.value)} {self.operator} {self._format(self.threshold)}"
        else:
            return f"{symbol} {self.filter_name}: {self.reason}"

    @staticmethod
    def _format(val: Any) -> str:
        """Format value for display"""
        if val is None:
            return "N/A"
        if isinstance(val, (float, Decimal)):
            if abs(val) >= 100:
                return f"{val:.1f}"
            elif abs(val) >= 1:
                return f"{val:.2f}"
            else:
                return f"{val:.4f}"
        return str(val)


@dataclass
class PairDecisionTrace:
    """
    Complete trace of a trading pair acceptance/rejection decision.

    Tracks all filter checks and provides multiple output formats.
    Designed to be lightweight with zero performance impact when disabled.
    """

    trading_pair: str
    exchange: str
    enabled: bool = True
    timestamp: float = field(default_factory=time.time)

    # Results
    checks: List[FilterCheck] = field(default_factory=list)
    accepted: Optional[bool] = None
    rejected_by: Optional[str] = None
    final_reason: Optional[str] = None

    # Metadata
    strategy: str = "spot_grid"
    slot_index: Optional[int] = None

    def add_check(
        self,
        filter_name: str,
        value: Any,
        threshold: Optional[Any] = None,
        threshold_min: Optional[Any] = None,
        threshold_max: Optional[Any] = None,
        passed: bool = False,
        reason: Optional[str] = None,
        operator: str = ">="
    ) -> 'PairDecisionTrace':
        """
        Add a filter check result.
        Returns self for method chaining.
        """
        if not self.enabled:
            return self

        check = FilterCheck(
            filter_name=filter_name,
            value=value,
            threshold=threshold,
            threshold_min=threshold_min,
            threshold_max=threshold_max,
            passed=passed,
            reason=reason,
            operator=operator
        )
        self.checks.append(check)
        return self

    def finalize(
        self,
        accepted: bool,
        rejected_by: Optional[str] = None,
        final_reason: Optional[str] = None
    ) -> 'PairDecisionTrace':
        """
        Finalize the decision trace.
        Returns self for method chaining.
        """
        if not self.enabled:
            return self

        self.accepted = accepted
        self.rejected_by = rejected_by
        self.final_reason = final_reason

        # Auto-detect rejected_by if not provided
        if not accepted and rejected_by is None:
            for check in self.checks:
                if not check.passed:
                    self.rejected_by = check.filter_name
                    break

        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert to structured dictionary"""
        if not self.enabled:
            return {}

        return {
            "timestamp": self.timestamp,
            "exchange": self.exchange,
            "trading_pair": self.trading_pair,
            "strategy": self.strategy,
            "slot_index": self.slot_index,
            "decision": {
                "accepted": self.accepted,
                "rejected_by": self.rejected_by,
                "reason": self.final_reason
            },
            "checks": [check.to_dict() for check in self.checks],
            "summary": {
                "total_checks": len(self.checks),
                "passed_checks": sum(1 for c in self.checks if c.passed),
                "failed_checks": sum(1 for c in self.checks if not c.passed)
            }
        }

    def to_json(self, indent: Optional[int] = 2) -> str:
        """Convert to JSON string for storage/API"""
        if not self.enabled:
            return "{}"
        return json.dumps(self.to_dict(), indent=indent)

    def to_compact_log(self) -> str:
        """
        Compact single-line log format for production logs.

        Example:
        CHZ-USDT [bitget] REJECTED by RSI | ✅ consensus_trend: 16.25% >= 0.5% | ✅ warmup_1h: -1.00% >= -1.5% | ❌ rsi: 79.3 > 72.0
        """
        if not self.enabled:
            return ""

        decision = "ACCEPTED" if self.accepted else "REJECTED"
        decision_color = "🟢" if self.accepted else "🔴"

        # Header
        header = f"{decision_color} {self.trading_pair} [{self.exchange}] {decision}"

        # Add rejected_by if applicable
        if self.rejected_by:
            header += f" by {self.rejected_by}"

        # Compact checks
        checks_str = " | ".join(check.to_compact() for check in self.checks)

        return f"{header} | {checks_str}"

    def to_detailed_log(self) -> str:
        """
        Multi-line detailed log format for debugging.

        Example:
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        🔍 DECISION TRACE: CHZ-USDT [bitget]
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        FILTERS:
          ✅ consensus_trend: 16.25% >= 0.5% → PASS
          ✅ warmup_1h: -1.00% >= -1.5% → PASS
          ✅ down_acceleration: -2.89% >= -4.0% → PASS
          ❌ rsi: 79.3 > 72.0 → FAIL (overbought)

        DECISION: 🔴 REJECTED
        REASON: rejected_by = rsi (overbought)
        SUMMARY: 3/4 checks passed
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        """
        if not self.enabled:
            return ""

        lines = [
            "━" * 60,
            f"🔍 DECISION TRACE: {self.trading_pair} [{self.exchange}]",
            "━" * 60,
            "FILTERS:"
        ]

        # Add all checks
        for check in self.checks:
            lines.append(f"  {check.to_compact()}")

        lines.append("")

        # Decision
        decision_icon = "🟢" if self.accepted else "🔴"
        decision_text = "ACCEPTED" if self.accepted else "REJECTED"
        lines.append(f"DECISION: {decision_icon} {decision_text}")

        # Reason
        if self.rejected_by:
            reason_text = self.final_reason or "check failed"
            lines.append(f"REASON: rejected_by = {self.rejected_by} ({reason_text})")
        elif self.final_reason:
            lines.append(f"REASON: {self.final_reason}")

        # Summary
        passed = sum(1 for c in self.checks if c.passed)
        total = len(self.checks)
        lines.append(f"SUMMARY: {passed}/{total} checks passed")

        lines.append("━" * 60)

        return "\n".join(lines)

    def get_failed_filters(self) -> List[str]:
        """Get list of failed filter names"""
        if not self.enabled:
            return []
        return [check.filter_name for check in self.checks if not check.passed]

    def get_passed_filters(self) -> List[str]:
        """Get list of passed filter names"""
        if not self.enabled:
            return []
        return [check.filter_name for check in self.checks if check.passed]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_trace(
    trading_pair: str,
    exchange: str,
    enabled: bool = True,
    strategy: str = "spot_grid",
    slot_index: Optional[int] = None
) -> PairDecisionTrace:
    """
    Factory function to create a decision trace.
    Use this in your controller/strategy code.
    """
    return PairDecisionTrace(
        trading_pair=trading_pair,
        exchange=exchange,
        enabled=enabled,
        strategy=strategy,
        slot_index=slot_index
    )


def trace_percentage_check(
    trace: PairDecisionTrace,
    name: str,
    value: float,
    threshold: float,
    operator: str = ">="
) -> bool:
    """
    Helper for common percentage threshold checks.
    Returns the check result and adds to trace.
    """
    if operator == ">=":
        passed = value >= threshold
    elif operator == "<=":
        passed = value <= threshold
    elif operator == ">":
        passed = value > threshold
    elif operator == "<":
        passed = value < threshold
    else:
        raise ValueError(f"Unsupported operator: {operator}")

    trace.add_check(
        filter_name=name,
        value=value,
        threshold=threshold,
        passed=passed,
        operator=operator
    )

    return passed


def trace_range_check(
    trace: PairDecisionTrace,
    name: str,
    value: float,
    min_val: float,
    max_val: float
) -> bool:
    """
    Helper for range checks (value must be between min and max).
    Returns the check result and adds to trace.
    """
    passed = min_val <= value <= max_val

    trace.add_check(
        filter_name=name,
        value=value,
        threshold_min=min_val,
        threshold_max=max_val,
        passed=passed,
        operator="range"
    )

    return passed


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

def example_usage():
    """Example showing how to use the decision trace system"""

    # Create trace (controlled by config)
    trace = create_trace(
        trading_pair="CHZ-USDT",
        exchange="bitget",
        enabled=True,  # config.debug_trace_enabled
        strategy="spot_grid",
        slot_index=0
    )

    # Example filter checks
    consensus_ok = trace_percentage_check(trace, "consensus_trend", 16.25, 0.5, ">=")
    warmup_ok = trace_percentage_check(trace, "warmup_1h", -1.00, -1.5, ">=")
    accel_ok = trace_percentage_check(trace, "down_acceleration", -2.89, -4.0, ">=")

    # RSI range check
    rsi_value = 79.3
    rsi_ok = trace_range_check(trace, "rsi", rsi_value, 20.0, 72.0)
    if not rsi_ok:
        trace.checks[-1].reason = "overbought"

    # VWAP deviation check
    vwap_dev = 5.05
    vwap_ok = trace.add_check(
        filter_name="vwap_deviation",
        value=vwap_dev,
        threshold=5.0,
        passed=vwap_dev <= 5.0,
        operator="<="
    )

    # Finalize decision
    all_passed = all([consensus_ok, warmup_ok, accel_ok, rsi_ok])
    trace.finalize(
        accepted=all_passed,
        rejected_by="rsi" if not rsi_ok else None,
        final_reason="overbought" if not rsi_ok else None
    )

    # Output examples
    print("\n=== COMPACT LOG (for production) ===")
    print(trace.to_compact_log())

    print("\n=== DETAILED LOG (for debugging) ===")
    print(trace.to_detailed_log())

    print("\n=== JSON (for analysis/dashboard) ===")
    print(trace.to_json())

    print("\n=== STRUCTURED DICT ===")
    import pprint
    pprint.pprint(trace.to_dict())


if __name__ == "__main__":
    example_usage()
