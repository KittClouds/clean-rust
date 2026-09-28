from __future__ import annotations

import importlib.util
import sys
import unittest
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "audit_factorial_feasibility.py"
SPEC = importlib.util.spec_from_file_location("jev_v08b_preflight", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class FeasibilityAuditTests(unittest.TestCase):
    def test_multiplicity_capacity_bound_accepts_supported_targets(self) -> None:
        report = MODULE.capacity_assignment_bound(Counter({3: 2, 1: 1}), [5, 3, 1, 1])
        self.assertTrue(report["necessary_capacity_bound_pass"])
        self.assertEqual(report["deficit_signature_count"], 0)

    def test_multiplicity_capacity_bound_rejects_insufficient_capacity(self) -> None:
        report = MODULE.capacity_assignment_bound(Counter({4: 1, 2: 1}), [3, 2])
        self.assertFalse(report["necessary_capacity_bound_pass"])
        self.assertEqual(report["deficit_signature_count"], 1)
        self.assertEqual(report["total_missing_occurrence_capacity"], 1)

    def test_entropy_band_boundaries_are_stable(self) -> None:
        self.assertEqual(MODULE.gold_entropy_band(0.199), "very_low")
        self.assertEqual(MODULE.gold_entropy_band(0.2), "low")
        self.assertEqual(MODULE.gold_entropy_band(0.55), "medium")
        self.assertEqual(MODULE.gold_entropy_band(0.95), "high")
        self.assertEqual(MODULE.gold_entropy_band(1.3), "very_high")

    def test_tv_distance_includes_absent_categories(self) -> None:
        self.assertAlmostEqual(MODULE.tv_distance(Counter({"a": 8, "b": 2}), Counter({"a": 2, "b": 8})), 0.6)
        self.assertEqual(MODULE.tv_distance(Counter({"a": 1}), Counter({"b": 1})), 1.0)


if __name__ == "__main__":
    unittest.main()
