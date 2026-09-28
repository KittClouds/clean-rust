from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("aggregate_rh1", HERE / "aggregate_rh1.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AggregateRH1Tests(unittest.TestCase):
    def test_completed_execution_has_two_cohorts_and_four_arms(self) -> None:
        execution, grouped, issues = MODULE.load_and_validate(MODULE.EXECUTION)
        self.assertEqual(execution["status"], "RH1_F2_ENGINEERING_FACTORIAL_COMPLETE")
        self.assertEqual(len(grouped), 55)
        self.assertEqual(len(execution["results"]), 220)
        self.assertEqual(issues, [])
        self.assertEqual(
            {row["cohort"] for row in execution["results"]},
            {"primary", "secondary"},
        )

    def test_provenance_audit_is_complete_for_corrected_identity(self) -> None:
        findings = MODULE.provenance_findings()
        self.assertIn("declared_row_count_desc", findings["contract_authority_order"])
        self.assertTrue(findings["runner_uses_declared_row_count"])
        self.assertFalse(findings["runner_uses_declared_support_count"])
        self.assertIsNone(findings["authority_mapping_issue"])
        self.assertEqual(findings["missing_preexecution_provenance_fields"], [])
        self.assertTrue(all(findings["preexecution_provenance_matches"].values()))

    def test_primary_horizon_pairing_is_complete(self) -> None:
        execution, grouped, issues = MODULE.load_and_validate(MODULE.EXECUTION)
        report = MODULE.build_report(execution, grouped, issues)
        primary_pairs = [
            item for item in report["cohorts"]["primary"]["paired_comparisons"]
            if item["domain"] == "D"
        ]
        self.assertEqual(len(primary_pairs), 4)
        self.assertTrue(all(item["n"] == 32 for item in primary_pairs))


if __name__ == "__main__":
    unittest.main(verbosity=2)
