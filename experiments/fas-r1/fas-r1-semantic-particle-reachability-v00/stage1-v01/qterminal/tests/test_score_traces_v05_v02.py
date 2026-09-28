from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyze_trace_selector_v02 import selected_valid  # noqa: E402
from score_traces_v05_v02 import assignment_key, probability, sidecar_filename  # noqa: E402
from verify_qterminal_v05_v02_score_smoke_v02 import compare_scores  # noqa: E402


class TraceScoringTests(unittest.TestCase):
    def test_assignment_key_is_byte_stable(self):
        value = [index % 3 for index in range(20)]
        self.assertEqual(assignment_key(value, "task"), bytes(value))

    def test_assignment_key_rejects_invalid_role(self):
        value = [0] * 20
        value[7] = 3
        with self.assertRaises(ValueError):
            assignment_key(value, "task")

    def test_calibrated_probability_is_finite_at_extreme_scores(self):
        self.assertEqual(probability(1000.0, 0.05), 1.0)
        self.assertLess(probability(-1000.0, 0.05), 1e-30)

    def test_sidecar_filename_is_short_and_deterministic(self):
        name = sidecar_filename(12, "qualification-trace-identifier")
        self.assertEqual(name, sidecar_filename(12, "qualification-trace-identifier"))
        self.assertLessEqual(len(name), 40)
        self.assertNotIn("/", name)
        self.assertNotIn("\\", name)

    def test_sidecar_filename_rejects_negative_index(self):
        with self.assertRaises(ValueError):
            sidecar_filename(-1, "trace")

    def test_score_readback_accepts_bounded_logit_rounding(self):
        reference = {
            "scoring_semantics": "same",
            "ranking_scores_initial": [-2.0],
            "ranking_scores_events": [-1.0, -1.00001],
            "probabilities_initial": [0.0],
            "probabilities_events": [0.0, 0.0],
        }
        candidate = {
            **reference,
            "ranking_scores_events": [-1.00002, -1.0],
        }
        comparison = compare_scores(reference, candidate)
        self.assertTrue(comparison["global_argmax_changed"])
        self.assertLessEqual(comparison["max_abs_logit_difference"], 1e-4)

    def test_score_readback_rejects_probability_or_large_logit_change(self):
        reference = {
            "scoring_semantics": "same",
            "ranking_scores_initial": [-2.0],
            "ranking_scores_events": [-1.0],
            "probabilities_initial": [0.0],
            "probabilities_events": [0.0],
        }
        changed_logit = {**reference, "ranking_scores_events": [-0.9]}
        with self.assertRaises(ValueError):
            compare_scores(reference, changed_logit)
        changed_probability = {**reference, "probabilities_events": [1.0]}
        with self.assertRaises(ValueError):
            compare_scores(reference, changed_probability)

    def test_selector_ranking_uses_max_score_across_initial_and_events(self):
        self.assertTrue(selected_valid([0.1], [-1.0, 0.9], False, [False, True]))
        self.assertFalse(selected_valid([1.0], [0.5], False, [True]))


if __name__ == "__main__":
    unittest.main()
