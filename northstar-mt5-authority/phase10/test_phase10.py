from __future__ import annotations

import unittest

from phase10 import js_divergence


class Phase10Tests(unittest.TestCase):
    def test_js_divergence_identical_is_zero(self) -> None:
        self.assertAlmostEqual(js_divergence({"A": 3, "B": 1}, {"A": 6, "B": 2}), 0.0)

    def test_js_divergence_detects_disjoint_support(self) -> None:
        self.assertAlmostEqual(js_divergence({"A": 1}, {"B": 1}), 1.0)


if __name__ == "__main__":
    unittest.main()
