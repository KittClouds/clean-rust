from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "analyze_phase_b.py"
SPEC = importlib.util.spec_from_file_location("jev_phase_b_analysis_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
ANALYSIS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYSIS)


def row(role: str, prediction: list[float], gold: list[float]) -> dict:
    return {
        "group_id": f"g-{role}", "contrast_anchor_id": "anchor-1",
        "contrast_role": role, "contrast_family_id": "heldout-family-a",
        "expected_old_winner_id": "A", "expected_new_winner_id": "B",
        "candidate_semantic_ids": ["A", "B"],
        "prediction": prediction, "gold": gold,
    }


class DirectContrastAnalysisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [
            row("anchor", [0.8, 0.2], [0.9, 0.1]),
            row("fact_flip", [0.3, 0.7], [0.1, 0.9]),
            row("sham", [0.79, 0.21], [0.9, 0.1]),
        ]

    def test_fact_flip_and_sham_metrics_are_separate(self) -> None:
        result = ANALYSIS.analyze_triplets(self.rows)
        self.assertEqual(result["pair_count"], 1)
        fact = result["fact_flip"]["overall"]
        self.assertEqual(fact["new_winner_probability_movement"]["correct_direction_rate"], 1.0)
        self.assertEqual(fact["map_response"]["strict_old_to_new_transition_rate"], 1.0)
        self.assertAlmostEqual(fact["new_winner_probability_movement"]["mean_absolute_delta_error"], 0.3)
        sham = result["sham_invariance"]["overall"]
        self.assertAlmostEqual(sham["mean_prediction_distribution_l1"], 0.02)
        self.assertAlmostEqual(sham["mean_exact_gold_distribution_l1"], 0.0)
        self.assertEqual(sham["map_flip_rate"], 0.0)

    def test_incomplete_triplet_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            ANALYSIS.analyze_triplets(self.rows[:2])

    def test_duplicate_role_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            ANALYSIS.analyze_triplets(self.rows + [self.rows[0]])

    def test_candidate_reordering_is_aligned_by_semantic_id(self) -> None:
        bad = [dict(item) for item in self.rows]
        bad[1]["candidate_semantic_ids"] = ["B", "A"]
        bad[1]["prediction"] = [0.7, 0.3]
        bad[1]["gold"] = [0.9, 0.1]
        result = ANALYSIS.analyze_triplets(bad)
        fact = result["fact_flip"]["overall"]
        self.assertEqual(fact["new_winner_probability_movement"]["correct_direction_rate"], 1.0)
        self.assertEqual(fact["map_response"]["strict_old_to_new_transition_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
