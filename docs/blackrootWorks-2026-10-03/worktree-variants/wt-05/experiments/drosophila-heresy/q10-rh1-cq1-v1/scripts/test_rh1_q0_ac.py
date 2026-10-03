"""Tests for RH1-Q0 and RH1-AC qualification-only work."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rh1_q0_ac as Q  # noqa: E402


class RH1Q0ACTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.q0 = Q.run_q0()
        cls.ac = Q.run_ac()

    def test_q0_canonical_and_f32_invariants(self) -> None:
        self.assertTrue(all(self.q0["checks"].values()))
        self.assertEqual(self.q0["status"], "RH1_Q0_CANONICAL_RUNTIME_QUALIFIED_FIXTURE_ONLY")

    def test_q0_has_stable_identity_and_readout(self) -> None:
        self.assertEqual(len(self.q0["state_identity"]), 64)
        self.assertEqual(len(self.q0["tie_hash"]), 64)
        self.assertEqual(len(self.q0["sequential_f32_readout"]), 2)

    def test_ac_cohorts_and_scope(self) -> None:
        self.assertEqual(self.ac["cohorts"], {"primary": 32, "secondary": 23, "excluded": 29})
        self.assertFalse(self.ac["scope"]["measured_factorial_started"])
        self.assertFalse(self.ac["scope"]["behavioral_probe"])

    def test_ac_missing_is_unknown(self) -> None:
        self.assertTrue(self.ac["missing_is_unknown"])
        self.assertEqual(self.ac["coverage_tiers"].get("UNKNOWN", 0), 0)
        self.assertGreater(self.ac["coverage_tiers"].get("MEASURED_PARTIAL", 0), 0)

    def test_ac_does_not_promote_partial_authority(self) -> None:
        self.assertFalse(self.ac["authority_arm_ready"])
        self.assertEqual(self.ac["authority_arm_gate"], "ALL_COORDINATE_PREFIX_AND_ROW_COVERAGE_COMPLETE")

    def test_ac_row_coverage_is_bounded(self) -> None:
        coverage = self.ac["row_authority_coverage"]
        self.assertGreaterEqual(coverage["minimum"], 0.0)
        self.assertLessEqual(coverage["maximum"], 1.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
