"""Synthetic tests for the pre-fit support and raw-weight summaries."""
from __future__ import annotations

import unittest

from build_support_surface import _scoped_weight_summary, weight_summary


class WeightDiagnosticTests(unittest.TestCase):
    def test_raw_q_fields(self) -> None:
        result = weight_summary([1.0, 2.0, 4.0])
        self.assertEqual(result["min_q"], 1.0)
        self.assertEqual(result["max_q"], 4.0)
        self.assertEqual(result["mean_q"], 7.0 / 3.0)
        self.assertEqual(result["sum_q"], 7.0)
        self.assertAlmostEqual(result["ess"], 49.0 / 21.0)

    def test_empty_cell_has_null_extrema_and_zero_mass(self) -> None:
        result = weight_summary([])
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["min_q"])
        self.assertIsNone(result["max_q"])
        self.assertIsNone(result["mean_q"])
        self.assertEqual(result["sum_q"], 0.0)
        self.assertEqual(result["ess"], 0.0)

    def test_class_specific_summaries_remain_separate(self) -> None:
        result = _scoped_weight_summary([(1, 2.0), (-1, 4.0), (1, 8.0)])
        self.assertEqual(result["target_positive"]["sum_q"], 10.0)
        self.assertEqual(result["target_negative"]["sum_q"], 4.0)
        self.assertEqual(result["all_rows"]["sum_q"], 14.0)


if __name__ == "__main__":
    unittest.main()
