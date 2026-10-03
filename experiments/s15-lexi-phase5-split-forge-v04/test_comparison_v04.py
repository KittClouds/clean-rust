import unittest

import numpy as np

from comparison_v04 import _axis_groups, paired_interval


class ComparisonNullDepthTests(unittest.TestCase):
    def test_null_axis_is_retained_and_sorts_after_numeric_values(self):
        meta = [
            {"root": "a", "axes": {"composition_depth": None}},
            {"root": "a", "axes": {"composition_depth": None}},
            {"root": "b", "axes": {"composition_depth": 2}},
            {"root": "b", "axes": {"composition_depth": 2}},
            {"root": "c", "axes": {"composition_depth": 0}},
            {"root": "c", "axes": {"composition_depth": 0}},
        ]
        groups = _axis_groups(meta, "composition_depth")
        self.assertEqual([value for _, value, _ in groups], [0, 2, None])
        self.assertEqual([key for key, _, _ in groups], ["0", "2", "not_applicable"])
        self.assertEqual([idx.tolist() for _, _, idx in groups], [[2], [1], [0]])

    def test_paired_root_bootstrap_is_deterministic(self):
        values = np.array([0.0, 0.5, 1.0, -0.5])
        self.assertEqual(paired_interval(values, seed=11), paired_interval(values, seed=11))
        self.assertEqual(paired_interval(values)["roots"], 4)

    def test_empty_stratum_is_explicit(self):
        self.assertEqual(paired_interval([]), {"roots": 0, "difference": None, "bootstrap95": None})

    def test_nonfinite_stratum_fails_closed(self):
        with self.assertRaises(ValueError):
            paired_interval([0.0, float("nan")])


if __name__ == "__main__":
    unittest.main()
