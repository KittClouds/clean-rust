from __future__ import annotations

import unittest

import numpy as np

from analyze_s12_v01 import metric_summary, target_margin


class S12AnalysisTests(unittest.TestCase):
    def test_target_margin_is_target_minus_best_rival(self) -> None:
        logits = np.asarray([[1.0, 3.5, 2.0], [4.0, -1.0, 2.5]], dtype=np.float32)
        labels = np.asarray([0, 2], dtype=np.int64)
        np.testing.assert_array_equal(target_margin(logits, labels), np.asarray([-2.5, -1.5], dtype=np.float64))

    def test_metric_summary_uses_true_rows_and_predicted_columns(self) -> None:
        labels = np.asarray([0, 0, 1, 1, 2, 2], dtype=np.int64)
        predictions = np.asarray([0, 1, 1, 1, 0, 2], dtype=np.int64)
        result = metric_summary(labels, predictions)
        self.assertEqual(result["confusion_matrix_true_rows_pred_columns"], [[1, 1, 0], [0, 2, 0], [1, 0, 1]])
        self.assertEqual(result["per_class_support"], [2, 2, 2])
        self.assertEqual(result["per_class_recall"], [0.5, 1.0, 0.5])
        self.assertAlmostEqual(result["accuracy"], 4 / 6)
        self.assertAlmostEqual(result["balanced_accuracy"], 2 / 3)

    def test_invalid_prediction_id_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            metric_summary(np.asarray([0]), np.asarray([3]))

    def test_nonfinite_logits_fail_instead_of_entering_margins(self) -> None:
        with self.assertRaises(RuntimeError):
            target_margin(np.asarray([[np.nan, 0.0, 1.0]]), np.asarray([0]))


if __name__ == "__main__":
    unittest.main()
