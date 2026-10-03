from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "emit_reports.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("jev_v08_emit_reports", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class SelectionCompositionTests(unittest.TestCase):
    def test_total_variation_detects_bank_mix_shift(self) -> None:
        self.assertEqual(MODULE.total_variation({"a": 50, "b": 50}, {"a": 50, "b": 50}), 0.0)
        self.assertAlmostEqual(
            MODULE.total_variation({"a": 80, "b": 20}, {"a": 20, "b": 80}),
            0.6,
        )

    def test_entropy_quintile_matches_selector_boundary_convention(self) -> None:
        thresholds = [0.2, 0.4, 0.6, 0.8]
        self.assertEqual(MODULE.entropy_quintile_for(0.2, thresholds), "q2")
        self.assertEqual(MODULE.entropy_quintile_for(0.199, thresholds), "q1")
        self.assertEqual(MODULE.entropy_quintile_for(0.8, thresholds), "q5")

    def test_report_marks_unmatched_strata_and_lower_input_coverage(self) -> None:
        random = {
            "group_count": 100,
            "unique_model_input_count": 20,
            "model_input_unique_fraction": 0.2,
            "repeated_model_input_occurrences": 80,
            "world_family_counts": {"w": 100},
            "query_view_counts": {"choice": 50, "ordinal": 50},
            "candidate_cardinality_bin_counts": {"3-4": 50, "5-8": 50},
            "posterior_entropy_quintile_counts": {"q1": 50, "q5": 50},
            "gold_entropy_band_counts": {"low": 50, "high": 50},
            "selection_stratum_counts": {"[\"w\",\"choice\",\"3-4\",\"q1\"]": 50},
        }
        curated = {
            **random,
            "unique_model_input_count": 10,
            "model_input_unique_fraction": 0.1,
            "repeated_model_input_occurrences": 90,
            "query_view_counts": {"choice": 80, "ordinal": 20},
            "selection_stratum_counts": {"[\"w\",\"choice\",\"3-4\",\"q1\"]": 40},
        }
        report = MODULE.selection_composition_report(random, curated)
        self.assertTrue(report["same_group_budget"])
        self.assertFalse(report["exact_predeclared_strata_match"])
        self.assertAlmostEqual(
            report["marginal_comparisons"]["query_view_type"]["total_variation_distance"],
            0.3,
        )
        self.assertEqual(
            report["model_visible_input_coverage"]["c100_minus_r100_unique_input_count"],
            -10,
        )


if __name__ == "__main__":
    unittest.main()
