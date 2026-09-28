"""Unit and smoke tests for Q10-PF6-RH1-CQ1."""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common_runtime as CQ  # noqa: E402


class CommonRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.result = CQ.qualify()

    def test_canonical_identity_ignores_visit_order(self) -> None:
        left = {91: 2, 17: -4, 43: 0}
        right = {43: 0, 91: 2, 17: -4}
        self.assertEqual(CQ.canonical_state(left), ((17, -4), (43, 0), (91, 2)))
        self.assertEqual(CQ.state_identity(left), CQ.state_identity(right))
        self.assertEqual(CQ.cache_key(("endpoint", 0, 7), left), CQ.cache_key(("endpoint", 0, 7), right))

    def test_cohorts_and_coverage(self) -> None:
        self.assertEqual(self.result["cohorts"], {"primary": 32, "secondary": 23, "excluded": 29})
        self.assertEqual(self.result["authority"]["coverage_fraction"], 1.0)
        self.assertTrue(self.result["authority"]["missing_is_unknown"])

    def test_budget_and_scope(self) -> None:
        self.assertEqual(self.result["budget"], {"B16": 32768, "B32": 65536, "scaling": "B32_equals_2_times_B16"})
        self.assertFalse(self.result["measured_factorial_started"])
        self.assertFalse(self.result["scope"]["rh1_f1_authorized"])

    def test_parent_hash_refusal(self) -> None:
        contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
        tampered = copy.deepcopy(contract)
        tampered["provenance"]["parent_bindings"][0]["sha256"] = "0" * 64
        with self.assertRaises(RuntimeError):
            CQ._load_parent_bindings(tampered)

    def test_unknown_authority_tier_is_explicit(self) -> None:
        observations = {}
        group = {"endpoint": "e", "set_index": 0, "coordinates": [7], "rows": [1]}
        ranked = CQ.authority_rank(group, observations, {("ep", 0, 1): 5})
        self.assertEqual(ranked[0]["coverage_tier"], "UNKNOWN")
        self.assertEqual(ranked[0]["helpful_row_count"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
