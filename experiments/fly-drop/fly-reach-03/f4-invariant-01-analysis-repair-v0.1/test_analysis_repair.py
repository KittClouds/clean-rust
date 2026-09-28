from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fit_contract import weighted_accuracy, weighted_balanced_error


class WeightedScoringRegressionTests(unittest.TestCase):
    def test_empty_numpy_arrays_return_null(self) -> None:
        empty = np.asarray([], dtype=np.int64)
        empty_weights = np.asarray([], dtype=np.float64)
        self.assertIsNone(weighted_accuracy(empty, empty, empty_weights))
        self.assertIsNone(weighted_balanced_error(empty, empty, empty_weights))

    def test_nonempty_numpy_targets_score_without_truthiness(self) -> None:
        signs = np.asarray([1, -1, -1, -1], dtype=np.int64)
        targets = np.asarray([1, -1, 1, -1], dtype=np.int64)
        weights = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
        self.assertAlmostEqual(weighted_accuracy(signs, targets, weights), 0.7, places=15)

    def test_one_class_block_has_undefined_balanced_error(self) -> None:
        signs = np.asarray([1, 1], dtype=np.int64)
        targets = np.asarray([1, 1], dtype=np.int64)
        weights = np.asarray([1.0, 2.0], dtype=np.float64)
        self.assertIsNone(weighted_balanced_error(signs, targets, weights))
        self.assertAlmostEqual(weighted_accuracy(signs, targets, weights), 1.0, places=15)

    def test_two_class_balanced_error_matches_frozen_weighting(self) -> None:
        signs = np.asarray([1, -1, -1, -1], dtype=np.int64)
        targets = np.asarray([1, -1, 1, -1], dtype=np.int64)
        weights = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float64)
        self.assertAlmostEqual(weighted_balanced_error(signs, targets, weights), 0.375, places=15)


if __name__ == "__main__":
    unittest.main()
