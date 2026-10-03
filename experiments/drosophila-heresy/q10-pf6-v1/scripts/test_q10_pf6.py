"""Preflight and semantic contract tests for Q10-PF6."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


class ProtocolSemanticTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.contract = json.loads((root / "CONTRACT.json").read_text(encoding="utf-8"))
        self.search = self.contract["search"]

    def test_complete_endpoint_and_horizon_semantics(self) -> None:
        self.assertTrue(self.search["complete_endpoint_after_each_round"])
        self.assertTrue(self.search["one_final_choice_per_coordinate"])
        self.assertEqual(self.search["visited_coordinate_choice"], "chosen_legal_prefix")
        self.assertEqual(self.search["unvisited_coordinate_choice"], "legal_0")
        self.assertTrue(self.search["horizon_is_coordinate_selection_only"])
        self.assertEqual(self.search["round_16_endpoint"], "valid_complete_legal_endpoint")
        self.assertEqual(self.search["round_16_max_baseline_departures"], 16)

    def test_coordinate_specific_ranking_is_frozen(self) -> None:
        self.assertEqual(
            self.search["coordinate_order"]["primary_score"],
            "S_i=sum(e_j^2 for j in R_i intersect M_G)",
        )
        self.assertEqual(
            self.search["coordinate_residual_authority"],
            "S_i=sum(e_j^2 for j in R_i intersect M_G)",
        )
        self.assertEqual(
            self.search["coordinate_residual_rows"],
            "R_i intersect M_G",
        )
        self.assertEqual(
            self.search["coordinate_order"]["sort_terms"],
            [
                {"name": "S_i", "direction": "descending"},
                {"name": "raw_support_row_count", "direction": "descending"},
                {"name": "replayed_raw_prefix_count", "direction": "descending"},
                {"name": "coordinate_id", "direction": "ascending"},
            ],
        )

    def test_round_trajectory_is_diagnostic_and_complete(self) -> None:
        trajectory = self.search["trajectory_diagnostics"]
        self.assertEqual(trajectory["rounds_inclusive"], {"first": 0, "last": 16, "count": 17})
        self.assertTrue(trajectory["per_group"])
        self.assertTrue(trajectory["diagnostic_only"])
        self.assertTrue(trajectory["diagnostics_do_not_alter_stopping_or_objective"])
        self.assertEqual(
            trajectory["fields"],
            [
                "mismatch_count",
                "total_ulp_distance",
                "residual_l2",
                "max_residual",
                "geometry_debt",
                "active_coordinate_count",
                "selected_coordinate_ids",
                "unselected_coordinate_ids",
            ],
        )

    def test_unselected_zero_is_distinct_from_tested_zero(self) -> None:
        self.assertEqual(self.search["tested_zero_label"], "tested_zero")
        self.assertEqual(self.search["unselected_zero_label"], "unselected_zero_by_horizon")
        self.assertNotEqual(self.search["tested_zero_label"], self.search["unselected_zero_label"])
        self.assertEqual(
            self.search["unselected_coordinate_forbidden_labels"],
            ["ineffective", "no-authority"],
        )
        self.assertEqual(
            self.search["bounded_search_failure"],
            {"status": "INCONCLUSIVE_BOUNDED_SEARCH", "inconclusive": True},
        )


class PreflightTests(unittest.TestCase):
    def test_parent_audit_preflight(self) -> None:
        root = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [sys.executable, "-B", "scripts/preflight_q10_pf6.py"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("groups=1596 oversize=1457", result.stdout)


if __name__ == "__main__":
    unittest.main()
