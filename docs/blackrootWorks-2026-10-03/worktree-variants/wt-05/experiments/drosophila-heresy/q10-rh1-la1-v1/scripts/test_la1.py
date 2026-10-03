"""Unit tests for receipt selection and endpoint decomposition guards."""
from __future__ import annotations

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import derive_la1 as DERIVE
import run_la1 as LA1


class LA1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        contract, _preexecution, hashes = LA1.verify_provenance()
        cls.contract = contract
        cls.f2 = LA1.validate_f2_inputs(contract, hashes)
        cls.context, cls.receipts = DERIVE.load_and_validate(DERIVE.ROOT / "qualification" / "execution" / "execution.json")

    def test_f2_primary_selection_is_receipt_derived(self) -> None:
        self.assertEqual(len(self.f2["evaluated"]), 32)
        self.assertEqual(len(self.f2["selected"]), 16)
        self.assertTrue(all(item["authority_h32_strictly_beats_h16"] for item in self.f2["selected"]))

    def test_score_order_is_strict_lexicographic(self) -> None:
        better = {"mismatch_count": 1, "total_ulp_distance": 99, "residual_l2": 9.0, "maximum_absolute_residual": 9.0}
        worse = {"mismatch_count": 2, "total_ulp_distance": 0, "residual_l2": 0.0, "maximum_absolute_residual": 0.0}
        self.assertLess(LA1.score_key(better), LA1.score_key(worse))

    def test_prefix_identity_requires_sorted_complete_map(self) -> None:
        row = {
            "chosen_state": {
                "canonical_mapping": [[3, 0], [9, 2]],
                "state_identity": LA1.F2.CQ.state_identity(((3, 0), (9, 2))),
            }
        }
        self.assertEqual(LA1.prefix_from_receipt(row, (3, 9), "test"), (0, 2))
        bad = dict(row)
        bad["chosen_state"] = dict(row["chosen_state"])
        bad["chosen_state"]["canonical_mapping"] = [[9, 2], [3, 0]]
        with self.assertRaises(LA1.LA1Error):
            LA1.prefix_from_receipt(bad, (3, 9), "test")

    def test_geometry_policy_separates_actual_and_counterfactual(self) -> None:
        geometry = self.contract["geometry"]
        self.assertEqual(set(geometry["actual_endpoints_hard_gate"]), set(LA1.ACTUAL_ENDPOINTS))
        self.assertEqual(set(geometry["counterfactual_endpoints_diagnostic_only"]), set(LA1.COUNTERFACTUAL_ENDPOINTS))
        self.assertEqual(geometry["counterfactual_geometry_failure_policy"], "record_metrics_and_diagnostic_pass_flag_without_abort")

    def test_scope_is_engineering_only(self) -> None:
        self.assertTrue(self.contract["scope"]["engineering_only"])
        self.assertFalse(self.contract["scope"]["behavioral_probe"])
        self.assertFalse(self.contract["scope"]["scientific_promotion"])

    def test_derived_classification_policy_is_declared(self) -> None:
        policy = DERIVE.CLASSIFICATION_POLICY
        self.assertEqual(policy["thresholds"]["domain_score_min_count"], 2)
        self.assertEqual(policy["thresholds"]["interaction_support_min_rows"], 1)
        self.assertEqual({rule["label"] for rule in policy["rules"]}, set(DERIVE.MECHANISM_CLASSES))

    def test_derived_classification_counts_are_deterministic(self) -> None:
        expected = {
            "LATE_INDEPENDENT": 3,
            "LATE_CONTEXTUAL": 1,
            "EARLY_CONFIGURATION_IMPROVED": 5,
            "GEOMETRY_BALANCING_DOMINANT": 7,
            "MIXED": 0,
            "UNRESOLVED": 0,
        }
        counts = {label: 0 for label in DERIVE.MECHANISM_CLASSES}
        for receipt in self.receipts:
            classification = DERIVE.classify_group(receipt)
            counts[classification["mechanism_class"]] += 1
            self.assertTrue(classification["descriptive_only"])
            self.assertIn("morphology", receipt)
        self.assertEqual(counts, expected)

    def test_classification_preserves_interaction_and_geometry_debt(self) -> None:
        for receipt in self.receipts:
            classification = DERIVE.classify_group(receipt)
            self.assertTrue(classification["row_interaction"]["exact_receipt_reused"])
            self.assertEqual(classification["row_interaction"]["sha256"], receipt["row_interaction_sha256"])
            self.assertEqual(set(classification["geometry_debt"]), set(DERIVE.ENDPOINT_NAMES))
            self.assertEqual(set(classification["score_comparisons"]), {
                "early_vs_historical_h16",
                "full_vs_early_direct_late",
                "late_only_vs_W0",
            })


if __name__ == "__main__":
    unittest.main(verbosity=2)
