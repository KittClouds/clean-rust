"""Unit and receipt smoke tests for Q10-PF6-S1A."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import reconstruct_s1a as S1A  # noqa: E402


class S1ATest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = S1A.reconstruct()

    def test_known_receipt_counts(self) -> None:
        self.assertEqual(self.result["counts"]["groups"], 84)
        self.assertEqual(self.result["counts"]["valid_groups"], 72)
        self.assertEqual(self.result["counts"]["exact_groups"], 0)
        self.assertEqual(self.result["counts"]["corrected_valid_late_groups"], 15)
        self.assertEqual(self.result["counts"]["corrected_valid_post8_groups"], 28)

    def test_exposure_and_termination(self) -> None:
        self.assertEqual(self.result["round_exposure"]["9"], 81)
        self.assertEqual(self.result["round_exposure"]["13"], 59)
        self.assertEqual(self.result["termination_counts"], {
            "HORIZON": 55,
            "NATURAL_COORDINATE_END": 29,
        })

    def test_support_and_coverage_boundaries(self) -> None:
        support = self.result["spatial_support_summary"]
        self.assertEqual(support["global_mismatch_outside_support_min"], 210)
        self.assertEqual(support["global_mismatch_outside_support_max"], 275)
        self.assertEqual(self.result["coverage"]["receipt_semantics_coverage"], "COMPLETE")
        self.assertEqual(self.result["coverage"]["numerical_replay_coverage"], "PARTIAL")

    def test_hash_refusal(self) -> None:
        contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
        tampered = copy.deepcopy(contract)
        tampered["parent"]["execution_sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            S1A.verify_bindings(tampered)

    def test_prefix_identity_is_not_weight_state(self) -> None:
        for group in self.result["groups"]:
            self.assertEqual(group["best_state_hash_semantics"], "prefix_identity_only")
            self.assertIn("equal_score_prefix_drift", group)


if __name__ == "__main__":
    unittest.main(verbosity=2)
