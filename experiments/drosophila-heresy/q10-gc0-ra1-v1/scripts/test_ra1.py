"""Unit and post-run checks for Q10-GC0-RA1."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import run_ra1 as RA1  # noqa: E402


class PrimitiveTests(unittest.TestCase):
    def test_coverage_partitions_mismatch(self) -> None:
        result = RA1.coverage({1, 2, 3}, {2, 4})
        self.assertEqual(result["covered_mismatch_rows"], [2])
        self.assertEqual(result["uncovered_mismatch_rows"], [1, 3])
        self.assertEqual(result["covered_mismatch_count"], 1)
        self.assertAlmostEqual(result["coverage_fraction"], 1.0 / 3.0)

    def test_stratum_is_unique_for_representative_sizes(self) -> None:
        contract, _ = RA1.load_local_seal()
        self.assertEqual(RA1.stratum(contract, 1), "raw_size_1")
        self.assertEqual(RA1.stratum(contract, 3), "raw_size_2_3")
        self.assertEqual(RA1.stratum(contract, 16), "raw_size_8_16")
        self.assertEqual(RA1.stratum(contract, 17), "rh1_secondary_size_17_31")
        self.assertEqual(RA1.stratum(contract, 32), "rh1_primary_size_32_plus")

    def test_finite_effects_rejects_nonfinite_geometry(self) -> None:
        good = {
            "finite_effects": True,
            "legal_prefixes": [{"effect_bits": [0, 0xFFFF_FFFF], "geometry": {"axis": 0.0}}],
        }
        bad = {
            "finite_effects": True,
            "legal_prefixes": [{"effect_bits": [0], "geometry": {"axis": float("inf")}}],
        }
        self.assertTrue(RA1.finite_effects(good))
        self.assertFalse(RA1.finite_effects(bad))

    def test_mismatch_rows_uses_bitwise_readout(self) -> None:
        state = SimpleNamespace(
            baseline_readout_bits=(0x8000_0000, 0x3F80_0000, 0x4000_0000),
            target_readout_bits=(0x8000_0000, 0x3F80_0001, 0x3F80_0000),
        )
        self.assertEqual(RA1.mismatch_rows(state), {1, 2})


class SealTests(unittest.TestCase):
    def test_local_seal_is_preexecution_only(self) -> None:
        contract, preexecution = RA1.load_local_seal()
        self.assertEqual(contract["identity"], "q10-gc0-ra1-v1")
        self.assertTrue(preexecution["parent_bindings_sealed"])


class PostRunTests(unittest.TestCase):
    def test_result_is_authority_audit_only(self) -> None:
        if not RA1.OUTPUT.is_file():
            self.skipTest("RA1 execution has not run")
        execution = RA1.load_json(RA1.OUTPUT)
        self.assertEqual(execution["protocol"], "Q10-GC0-RA1")
        self.assertTrue(execution["firewall"]["engineering_only"])
        self.assertFalse(execution["firewall"]["scientific_promotion"])
        self.assertFalse(execution["firewall"]["candidate_generation"])
        self.assertFalse(execution["firewall"]["constructor_run"])
        self.assertEqual(execution["counts"]["raw_group_count"], 801)
        self.assertTrue(execution["gate"]["raw_support_complete"])
        self.assertFalse(execution["gate"]["all_raw_coordinate_pairs_complete"])


if __name__ == "__main__":
    unittest.main()
