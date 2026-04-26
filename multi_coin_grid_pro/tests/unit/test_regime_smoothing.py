"""
Unit tests for V2-02: Regime Smoothing

Tests the smoothing logic that requires N consecutive identical regime
detections before accepting a regime switch. Uses a minimal stub — no
network calls, no wall-clock dependencies.
"""
import unittest

# ---------------------------------------------------------------------------
# Minimal standalone smoother extracted from the controller logic so tests
# don't need to instantiate the full heavy controller.
# ---------------------------------------------------------------------------


class RegimeSmoother:
    """
    Pure-logic extraction of the V2-02 smoothing algorithm.
    Mirrors exactly what the controller does:

        smoothing_count = config.get('regime_smoothing_count', 1)

    State:
        _last_detected_regime  — the currently accepted (confirmed) regime
        _regime_candidate      — the pending new regime being accumulated
        _regime_candidate_count — how many consecutive ticks we've seen it
    """

    def __init__(self, smoothing_count: int = 3):
        self.smoothing_count = smoothing_count
        self._last_detected_regime: str | None = None
        self._regime_candidate: str | None = None
        self._regime_candidate_count: int = 0
        self.debug_messages: list[str] = []

    def feed(self, detected: str) -> str:
        """Feed one raw detection tick. Returns the accepted (smoothed) regime."""
        if detected == self._last_detected_regime:
            self._regime_candidate = None
            self._regime_candidate_count = 0
            return detected

        if self.smoothing_count <= 1:
            self._last_detected_regime = detected
            self._regime_candidate = None
            self._regime_candidate_count = 0
            return detected

        # Accumulate candidate
        if detected != self._regime_candidate:
            self._regime_candidate = detected
            self._regime_candidate_count = 1
        else:
            self._regime_candidate_count += 1

        if self._regime_candidate_count >= self.smoothing_count:
            self._last_detected_regime = detected
            self._regime_candidate = None
            self._regime_candidate_count = 0
            return detected
        else:
            msg = f"regime_candidate | {detected} ({self._regime_candidate_count}/{self.smoothing_count})"
            self.debug_messages.append(msg)
            return self._last_detected_regime or detected


class TestRegimeSmoothing(unittest.TestCase):

    # ------------------------------------------------------------------
    # count=3 — normal operation
    # ------------------------------------------------------------------

    def test_no_switch_on_single_flicker(self):
        """One tick of a new regime must not switch."""
        sm = RegimeSmoother(smoothing_count=3)
        sm._last_detected_regime = "BULL"
        result = sm.feed("BEAR")
        self.assertEqual(result, "BULL")

    def test_no_switch_on_two_ticks(self):
        """Two consecutive ticks of a new regime must not switch."""
        sm = RegimeSmoother(smoothing_count=3)
        sm._last_detected_regime = "BULL"
        sm.feed("BEAR")
        result = sm.feed("BEAR")
        self.assertEqual(result, "BULL")

    def test_switch_on_exactly_n_ticks(self):
        """Exactly N consecutive ticks must trigger the switch."""
        sm = RegimeSmoother(smoothing_count=3)
        sm._last_detected_regime = "BULL"
        sm.feed("BEAR")
        sm.feed("BEAR")
        result = sm.feed("BEAR")
        self.assertEqual(result, "BEAR")
        self.assertEqual(sm._last_detected_regime, "BEAR")

    def test_counter_resets_on_interrupted_sequence(self):
        """If the candidate changes mid-accumulation, counter resets to 1."""
        sm = RegimeSmoother(smoothing_count=3)
        sm._last_detected_regime = "BULL"
        sm.feed("BEAR")   # count=1
        sm.feed("BEAR")   # count=2
        sm.feed("CHOP")   # interruption → candidate switches, count=1
        result = sm.feed("CHOP")  # count=2, still not 3
        self.assertEqual(result, "BULL")
        self.assertEqual(sm._regime_candidate_count, 2)

    def test_stays_on_current_during_accumulation(self):
        """During accumulation the bot keeps trading under the current regime."""
        sm = RegimeSmoother(smoothing_count=3)
        sm._last_detected_regime = "CHOP"
        results = [sm.feed("BEAR") for _ in range(2)]
        self.assertTrue(all(r == "CHOP" for r in results))

    def test_same_regime_keeps_stable(self):
        """Repeated same-regime detections must never change accepted regime."""
        sm = RegimeSmoother(smoothing_count=3)
        sm._last_detected_regime = "CHOP"
        for _ in range(10):
            result = sm.feed("CHOP")
            self.assertEqual(result, "CHOP")

    def test_candidate_resets_after_confirmed_switch(self):
        """After a confirmed switch, candidate state must be clean."""
        sm = RegimeSmoother(smoothing_count=3)
        sm._last_detected_regime = "BULL"
        sm.feed("BEAR")
        sm.feed("BEAR")
        sm.feed("BEAR")
        self.assertIsNone(sm._regime_candidate)
        self.assertEqual(sm._regime_candidate_count, 0)

    def test_debug_log_emitted_during_accumulation(self):
        """Debug messages must be emitted while accumulating."""
        sm = RegimeSmoother(smoothing_count=3)
        sm._last_detected_regime = "BULL"
        sm.feed("BEAR")
        sm.feed("BEAR")
        self.assertEqual(len(sm.debug_messages), 2)
        self.assertIn("regime_candidate | BEAR (1/3)", sm.debug_messages[0])
        self.assertIn("regime_candidate | BEAR (2/3)", sm.debug_messages[1])

    # ------------------------------------------------------------------
    # count=1 — backward-compatible immediate switch
    # ------------------------------------------------------------------

    def test_count_1_immediate_switch(self):
        """smoothing_count=1 must reproduce the old immediate-switch behavior."""
        sm = RegimeSmoother(smoothing_count=1)
        sm._last_detected_regime = "BULL"
        result = sm.feed("BEAR")
        self.assertEqual(result, "BEAR")
        self.assertEqual(sm._last_detected_regime, "BEAR")

    def test_count_1_no_candidate_state(self):
        """With count=1 no candidate state should accumulate."""
        sm = RegimeSmoother(smoothing_count=1)
        sm._last_detected_regime = "BULL"
        sm.feed("BEAR")
        self.assertIsNone(sm._regime_candidate)
        self.assertEqual(sm._regime_candidate_count, 0)

    # ------------------------------------------------------------------
    # Initial state (cold start — no confirmed regime yet)
    # ------------------------------------------------------------------

    def test_cold_start_accepts_first_regime(self):
        """On cold start (_last_detected_regime=None), accept first detection."""
        sm = RegimeSmoother(smoothing_count=3)
        result = sm.feed("CHOP")
        self.assertEqual(result, "CHOP")

    def test_cold_start_accumulates_toward_new(self):
        """Cold start with smoothing: first tick same as None resets candidate."""
        sm = RegimeSmoother(smoothing_count=3)
        # Feed a signal when there's no current regime — should accept immediately
        # because None != "BULL" and smoothing allows fallback to `detected`
        result = sm.feed("BULL")
        # Since _last_detected_regime is None and we fall through to candidate path,
        # the fallback `self._last_detected_regime or detected` returns detected.
        self.assertEqual(result, "BULL")

    # ------------------------------------------------------------------
    # Multi-step transition sequence
    # ------------------------------------------------------------------

    def test_full_bull_to_bear_transition(self):
        """Full sequence: BULL → 3× BEAR = BEAR, then 3× CHOP = CHOP."""
        sm = RegimeSmoother(smoothing_count=3)
        sm._last_detected_regime = "BULL"

        # 3 BEAR detections → switches to BEAR
        self.assertEqual(sm.feed("BEAR"), "BULL")
        self.assertEqual(sm.feed("BEAR"), "BULL")
        self.assertEqual(sm.feed("BEAR"), "BEAR")

        # 3 CHOP detections → switches to CHOP
        self.assertEqual(sm.feed("CHOP"), "BEAR")
        self.assertEqual(sm.feed("CHOP"), "BEAR")
        self.assertEqual(sm.feed("CHOP"), "CHOP")


if __name__ == "__main__":
    unittest.main()
