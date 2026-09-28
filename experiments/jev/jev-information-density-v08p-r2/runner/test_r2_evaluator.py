"""Synthetic-only evaluator contract and cardinality smoke tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SOURCE = Path(__file__).with_name("evaluate_r2_trajectory.py")
SPEC = importlib.util.spec_from_file_location("jev_r2_evaluator_test", SOURCE)
assert SPEC is not None and SPEC.loader is not None
EVALUATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATOR)


class EvaluatorContractTests(unittest.TestCase):
    def test_full_cell_inventory_is_381_in_frozen_order(self) -> None:
        cells = EVALUATOR.expected_cells()
        self.assertEqual(len(cells), 381)
        self.assertEqual(cells[:4], [
            (3243871208, "COMMON_INIT", 0),
            (3243871208, "B-DUP", 40),
            (3243871208, "B-MATCHED", 40),
            (3243871208, "B-SHAM", 40),
        ])
        self.assertEqual(cells[-1], (3076094663, "B-SHAM", 120))
        trained = [cell for cell in cells if cell[1] in EVALUATOR.ARMS]
        self.assertEqual(len(trained), 378)
        self.assertEqual([step for seed, arm, step in trained if seed == 3243871208 and arm == "B-DUP"],
                         list(EVALUATOR.CHECKPOINT_STEPS))

    def test_prediction_validator_accepts_simplex_and_rejects_bad_shapes(self) -> None:
        valid = {"prediction": [0.4, 0.3, 0.2, 0.1], "gold": [0.7, 0.1, 0.1, 0.1]}
        EVALUATOR.validate_prediction(valid)
        with self.assertRaises(RuntimeError):
            EVALUATOR.validate_prediction({"prediction": [0.5, 0.5], "gold": [0.5, 0.5]})

    def test_prediction_validator_rejects_nonfinite_or_unnormalized_rows(self) -> None:
        with self.assertRaises(RuntimeError):
            EVALUATOR.validate_prediction({"prediction": [0.4, 0.3, float("nan"), 0.3],
                                            "gold": [0.25, 0.25, 0.25, 0.25]})
        with self.assertRaises(RuntimeError):
            EVALUATOR.validate_prediction({"prediction": [0.4, 0.3, 0.2, 0.2],
                                            "gold": [0.25, 0.25, 0.25, 0.25]})


if __name__ == "__main__":
    unittest.main()
