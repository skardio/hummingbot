"""
Unit tests for ReasonCode taxonomy and Stage mapping.

Tests:
- ReasonCode enum completeness
- JSON serialization
- Stage mapping correctness
- No duplicate values
"""

import json
import unittest

from multi_coin_grid_pro.core.reason_codes import ReasonCode, Stage, get_stage_for_reason


class TestReasonCodes(unittest.TestCase):
    """Test suite for ReasonCode enum and utilities"""

    def test_reason_code_count(self):
        """Verify we have exactly 53 rejection codes (includes Phase 2 momentum codes)"""
        codes = list(ReasonCode)
        self.assertEqual(len(codes), 54, f"Expected 54 codes, got {len(codes)}")

        # Verify no APPROVED code exists
        code_values = [code.value for code in codes]
        self.assertNotIn("APPROVED", code_values, "APPROVED should not exist (use trace.accepted=True instead)")

    def test_reason_code_serialization(self):
        """Test that ReasonCodes serialize to JSON cleanly"""
        code = ReasonCode.RSI_OVERBOUGHT
        stage = Stage.SMART_ENTRY

        data = {
            "reason_code": code,
            "stage": stage,
            "symbol": "BTC-EUR"
        }

        # Should convert enum to string in JSON
        json_str = json.dumps(
            data,
            default=lambda x: x.value if isinstance(x, (ReasonCode, Stage)) else str(x)
        )
        parsed = json.loads(json_str)

        self.assertEqual(parsed["reason_code"], "RSI_OVERBOUGHT")
        self.assertEqual(parsed["stage"], "SMART_ENTRY")
        self.assertEqual(parsed["symbol"], "BTC-EUR")

    def test_stage_mapping_smart_entry(self):
        """Test SmartEntry codes map to SMART_ENTRY stage"""
        smart_entry_codes = [
            ReasonCode.RSI_OVERBOUGHT,
            ReasonCode.VWAP_DEVIATION_TOO_HIGH,
            ReasonCode.ATR_TOO_LOW,
            ReasonCode.SPREAD_TOO_WIDE,
            ReasonCode.DEPTH_INSUFFICIENT,
        ]

        for code in smart_entry_codes:
            stage = get_stage_for_reason(code)
            self.assertEqual(
                stage,
                Stage.SMART_ENTRY,
                f"{code} should map to SMART_ENTRY, got {stage}"
            )

    def test_stage_mapping_mtf(self):
        """Test MTF codes map to MTF stage"""
        mtf_codes = [
            ReasonCode.MTF_INSUFFICIENT,
            ReasonCode.MTF_CRASH_DETECTED,
        ]

        for code in mtf_codes:
            stage = get_stage_for_reason(code)
            self.assertEqual(
                stage,
                Stage.MTF,
                f"{code} should map to MTF, got {stage}"
            )

    def test_stage_mapping_risk(self):
        """Test Risk codes map to RISK stage"""
        risk_codes = [
            ReasonCode.EXPOSURE_LIMIT,
            ReasonCode.DAILY_LOSS_LIMIT,
            ReasonCode.COOLDOWN_EXIT,
            ReasonCode.POSITION_LIMIT,
        ]

        for code in risk_codes:
            stage = get_stage_for_reason(code)
            self.assertEqual(
                stage,
                Stage.RISK,
                f"{code} should map to RISK, got {stage}"
            )

    def test_stage_mapping_execution(self):
        """Test Execution codes map to EXECUTION stage"""
        execution_codes = [
            ReasonCode.BLACKLIST,
            ReasonCode.SLOT_FULL,
            ReasonCode.ALREADY_TRADING,
            ReasonCode.NOT_TRADEABLE,
        ]

        for code in execution_codes:
            stage = get_stage_for_reason(code)
            self.assertEqual(
                stage,
                Stage.EXECUTION,
                f"{code} should map to EXECUTION, got {stage}"
            )

    def test_stage_mapping_regime(self):
        """Test Regime codes map to REGIME stage"""
        regime_codes = [
            ReasonCode.REGIME_BTC_DUMP,
            ReasonCode.REGIME_DUMP_COOLDOWN,
        ]

        for code in regime_codes:
            stage = get_stage_for_reason(code)
            self.assertEqual(
                stage,
                Stage.REGIME,
                f"{code} should map to REGIME, got {stage}"
            )

    def test_stage_mapping_momentum(self):
        """Test Momentum codes map to MOMENTUM stage"""
        momentum_codes = [
            ReasonCode.MOMENTUM_SCORE_TOO_LOW,
            ReasonCode.MOMENTUM_REGIME_BLOCKED,
            ReasonCode.MOMENTUM_CAPITAL_LIMIT,
            ReasonCode.MOMENTUM_POSITION_LIMIT,
            ReasonCode.MOMENTUM_COOLDOWN,
            ReasonCode.MOMENTUM_DUPLICATE,
            ReasonCode.MOMENTUM_RSI_TOO_HIGH,
            ReasonCode.MOMENTUM_VOLUME_TOO_LOW,
            ReasonCode.MOMENTUM_SPREAD_TOO_WIDE,
            ReasonCode.MOMENTUM_WICK_RISK_TOO_HIGH,
            ReasonCode.MOMENTUM_STOP_LOSS,
            ReasonCode.MOMENTUM_TRAILING_STOP,
            ReasonCode.MOMENTUM_TIME_STOP,
            ReasonCode.MOMENTUM_REGIME_EXIT,
        ]

        for code in momentum_codes:
            stage = get_stage_for_reason(code)
            self.assertEqual(
                stage,
                Stage.MOMENTUM,
                f"{code} should map to MOMENTUM, got {stage}"
            )

    def test_all_codes_have_unique_values(self):
        """Ensure no duplicate reason code values"""
        values = [code.value for code in ReasonCode]
        duplicates = [v for v in values if values.count(v) > 1]

        self.assertEqual(
            len(values),
            len(set(values)),
            f"Duplicate ReasonCode values detected: {set(duplicates)}"
        )

    def test_all_stages_have_unique_values(self):
        """Ensure no duplicate stage values"""
        values = [stage.value for stage in Stage]
        duplicates = [v for v in values if values.count(v) > 1]

        self.assertEqual(
            len(values),
            len(set(values)),
            f"Duplicate Stage values detected: {set(duplicates)}"
        )

    def test_stage_count(self):
        """Verify we have exactly 7 stages (includes MOMENTUM)"""
        stages = list(Stage)
        self.assertEqual(len(stages), 8, f"Expected 8 stages, got {len(stages)}")

        expected_stages = {"SMART_ENTRY", "MTF", "RISK", "EXECUTION", "REGIME", "MOMENTUM", "EXECUTOR_CREATE", "EDGE_GATE"}
        actual_stages = {stage.value for stage in stages}

        self.assertEqual(expected_stages, actual_stages, "Stage set mismatch")

    def test_code_name_matches_value(self):
        """Verify enum name matches value (consistency check)"""
        for code in ReasonCode:
            self.assertEqual(
                code.name,
                code.value,
                f"Code name {code.name} should match value {code.value}"
            )

    def test_stage_name_matches_value(self):
        """Verify stage name matches value (consistency check)"""
        for stage in Stage:
            self.assertEqual(
                stage.name,
                stage.value,
                f"Stage name {stage.name} should match value {stage.value}"
            )


if __name__ == "__main__":
    unittest.main()
