from __future__ import annotations

import collections
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
import state_exposure as v08e  # noqa: E402


class StateExposureTests(unittest.TestCase):
    def test_histogram_tv_uses_multiplicity_counts(self) -> None:
        left = collections.Counter({1: 3, 2: 1})
        right = collections.Counter({1: 1, 2: 2})
        self.assertAlmostEqual(v08e.histogram_tv(left, right), 5 / 12)

    def test_histogram_tv_identical_is_zero(self) -> None:
        histogram = collections.Counter({1: 4, 2: 8, 5: 3})
        self.assertEqual(v08e.histogram_tv(histogram, histogram), 0.0)

    def test_predicted_exchange_updates_exact_multiplicity_histogram(self) -> None:
        a = collections.Counter({"s1": 2, "s2": 2})
        b = collections.Counter({"s1": 1, "s2": 3})
        ha, hb = v08e.core.histogram(a), v08e.core.histogram(b)
        item_a = SimpleNamespace(input_state="s1")
        item_b = SimpleNamespace(input_state="s2")
        predicted = v08e.predicted_state_tv(a, b, ha, hb, [(item_a, item_b)])
        next_a, next_b = a.copy(), b.copy()
        next_a["s1"] -= 1
        next_a["s2"] += 1
        next_b["s1"] += 1
        next_b["s2"] -= 1
        expected = v08e.histogram_tv(v08e.core.histogram(next_a), v08e.core.histogram(next_b))
        self.assertAlmostEqual(predicted, expected)


if __name__ == "__main__":
    unittest.main()
