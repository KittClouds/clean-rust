import unittest
from collections import Counter
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import validate_phase2b_witnesses as audit


class WitnessAuditUnitTests(unittest.TestCase):
    def test_holdout_is_stable_and_bundle_scoped(self):
        self.assertEqual(audit.is_held_out("bundle-a"), audit.is_held_out("bundle-a"))
        self.assertIsInstance(audit.is_held_out("bundle-b"), bool)

    def test_entropy_boundaries(self):
        self.assertEqual(audit.entropy_band(0.199999), "very_low")
        self.assertEqual(audit.entropy_band(0.20), "low")
        self.assertEqual(audit.entropy_band(0.55), "medium")
        self.assertEqual(audit.entropy_band(0.95), "high")
        self.assertEqual(audit.entropy_band(1.30), "very_high")

    def test_histogram_tv(self):
        self.assertEqual(audit.tv(Counter({1: 4, 2: 2}), Counter({1: 4, 2: 2})), 0.0)
        self.assertAlmostEqual(audit.tv(Counter({1: 6}), Counter({1: 3, 2: 3})), 0.5)

    def test_phase2_priority_objective_and_cell_relaxed_bound(self):
        cell_a = ("w", "b", "choice", "2", "q1", "low")
        cell_b = ("w", "b", "ordinal", "3", "q2", "medium")
        items = [
            (b"a", "g1", cell_a),
            (b"b", "g2", cell_a),
            (b"c", "g3", cell_b),
        ]
        result = audit.rank_objective(
            items,
            "random",
            {"R": {"g2", "g3"}},
            {"R": Counter({cell_a: 1, cell_b: 1})},
        )
        self.assertEqual(result["selected_priority_sums"]["R"], 3)
        self.assertEqual(result["cell_relaxed_valid_upper_bounds"]["R"], 4)

    def test_original_r100_largest_remainder_selection_is_deterministic(self):
        strata = {
            '["a"]': [(b"b", "g2"), (b"a", "g1")],
            '["b"]': [(b"c", "g3")],
        }
        # Tiny helper tests use the production total exactly as a denominator;
        # the selection target is intentionally overridden only for the test.
        old_limit = audit.GROUP_LIMIT
        try:
            audit.GROUP_LIMIT = 2
            first = audit.original_r100_selection(strata, total=3)
            second = audit.original_r100_selection(strata, total=3)
        finally:
            audit.GROUP_LIMIT = old_limit
        self.assertEqual(first, second)
        self.assertEqual(len(first), 2)


if __name__ == "__main__":
    unittest.main()
