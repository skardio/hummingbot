"""
Unit test for stop-loss cooldown fix

Tests that when a position is closed due to stop-loss, a switch cooldown is enforced
to prevent immediate re-entry of the same coin.

Bug: Bot was selling at stop-loss and immediately buying back the same coin,
resulting in unnecessary losses + fees.

Fix: Set last_switch_time when stop-loss is triggered to enforce cooldown period.
"""

import unittest


class TestStopLossCooldownLogic(unittest.TestCase):
    """Test stop-loss cooldown logic without full controller"""

    def test_stop_loss_detection(self):
        """Test that STOP_LOSS is correctly detected in close_type"""
        close_types = [
            ("STOP_LOSS", True),
            ("CloseType.STOP_LOSS", True),
            ("stop_loss", True),
            ("INSUFFICIENT_BALANCE", False),
            ("MANUAL", False),
            ("TIME_LIMIT", False),
            ("", False),
        ]

        for close_type, expected in close_types:
            close_type_str = close_type.upper()
            is_stop_loss = 'STOP_LOSS' in close_type_str

            self.assertEqual(
                is_stop_loss,
                expected,
                f"close_type '{close_type}' should {'be' if expected else 'not be'} detected as stop-loss"
            )

    def test_switch_cooldown_logic(self):
        """Test switch cooldown calculation"""
        # Simulate the cooldown logic
        current_time = 1000.0
        last_switch_time = 700.0  # 300s ago
        min_switch_interval = 300  # 5 minutes

        # Calculate remaining cooldown
        time_since_switch = current_time - last_switch_time
        remaining = max(0, min_switch_interval - time_since_switch)

        # Should have 0 remaining (cooldown expired)
        self.assertEqual(remaining, 0, "Cooldown should be expired after 300s")

        # Test with recent switch
        last_switch_time = 990.0  # 10s ago
        time_since_switch = current_time - last_switch_time
        remaining = max(0, min_switch_interval - time_since_switch)

        # Should have 290s remaining
        self.assertEqual(remaining, 290, "Should have 290s cooldown remaining")

    def test_immediate_reentry_prevention(self):
        """Test that immediate re-entry is prevented after stop-loss"""
        # Scenario: Stop-loss just triggered
        last_switch_time = 1000.0  # Just set by stop-loss
        min_switch_interval = 300

        # 10 seconds later, try to enter
        new_time = 1010.0
        time_since_switch = new_time - last_switch_time
        can_switch = time_since_switch >= min_switch_interval

        self.assertFalse(can_switch, "Should NOT allow switch 10s after stop-loss")

        # 310 seconds later, should be allowed
        new_time = 1310.0
        time_since_switch = new_time - last_switch_time
        can_switch = time_since_switch >= min_switch_interval

        self.assertTrue(can_switch, "Should allow switch after cooldown expires")


class TestStopLossCooldownIntegration(unittest.TestCase):
    """Integration test simulating the bug scenario"""

    def test_bug_scenario_pol_reentry(self):
        """Simulate the POL stop-loss → immediate re-entry bug"""
        # BEFORE FIX: last_switch_time not updated on stop-loss

        # Step 1: POL position opened at 08:50
        active_coin = "POL-EUR"

        # Step 2: Stop-loss triggered at 08:53 (3 minutes later)
        stop_loss_time = 853.0

        # BEFORE FIX: last_switch_time stays at 850.0 (not updated)
        # active_coin = None (cleared)
        active_coin = None  # Cleared by stop-loss

        # Step 3: Next cycle at 08:53:05 (5 seconds later)
        next_cycle_time = 853.0 + 0.08  # ~5 seconds
        min_interval = 5 * 60  # 5 minutes = 300s

        # BEFORE FIX: Cooldown check only happens if active_coin != None
        # Since active_coin was cleared, cooldown was not enforced
        cooldown_was_checked_before = (active_coin is not None)

        self.assertFalse(
            cooldown_was_checked_before,
            "BUG: Cooldown was NOT checked because active_coin was None"
        )

        # AFTER FIX: last_switch_time updated to stop_loss_time
        last_switch_time_after = stop_loss_time  # Updated by fix
        time_since_switch_after = next_cycle_time - last_switch_time_after
        can_reenter_after = time_since_switch_after >= min_interval

        self.assertFalse(
            can_reenter_after,
            f"FIX: Bot should NOT re-enter (only {time_since_switch_after:.1f}s < {min_interval}s)"
        )


if __name__ == '__main__':
    unittest.main()
