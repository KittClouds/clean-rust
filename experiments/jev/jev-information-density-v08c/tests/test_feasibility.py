from __future__ import annotations

import importlib.util
import sys
import unittest
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "solve_feasibility.py"
SPEC = importlib.util.spec_from_file_location("jev_v08c_feasibility", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FeasibilityMathTests(unittest.TestCase):
    def test_integer_histogram_tv_matches_direct_tv_at_boundary(self) -> None:
        reference = Counter({1: 48, 2: 52})
        selected = Counter({1: 50, 2: 50})
        self.assertTrue(MODULE.histogram_tv_integer_pass(selected, reference, 100, 100))

    def test_integer_histogram_tv_rejects_above_boundary(self) -> None:
        reference = Counter({1: 48, 2: 52})
        selected = Counter({1: 51, 2: 49})
        self.assertFalse(MODULE.histogram_tv_integer_pass(selected, reference, 100, 100))

    def test_integer_histogram_tv_handles_variable_unique_count(self) -> None:
        reference = Counter({1: 24, 2: 26})
        selected = Counter({1: 25, 2: 25})
        self.assertTrue(MODULE.histogram_tv_integer_pass(selected, reference, 50, 50))

    def test_unique_count_interval_rounds_outward(self) -> None:
        self.assertEqual(MODULE.outward_interval(25_700), (25_186, 26_214))
        self.assertEqual(MODULE.outward_interval(25_190), (24_686, 25_694))

    def test_entropy_band_boundaries(self) -> None:
        self.assertEqual(MODULE.entropy_band(0.199999), "very_low")
        self.assertEqual(MODULE.entropy_band(0.20), "low")
        self.assertEqual(MODULE.entropy_band(0.55), "medium")
        self.assertEqual(MODULE.entropy_band(0.95), "high")
        self.assertEqual(MODULE.entropy_band(1.30), "very_high")


if __name__ == "__main__":
    unittest.main()
