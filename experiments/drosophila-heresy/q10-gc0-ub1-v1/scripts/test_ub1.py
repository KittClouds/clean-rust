"""Unit and post-run checks for the Q10-GC0-UB1 support audit."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import run_ub1 as UB1  # noqa: E402


class PrimitiveTests(unittest.TestCase):
    def test_coverage_partitions_mismatch_rows(self) -> None:
        result = UB1.coverage({1, 2, 3}, {2, 4})
        self.assertEqual(result["physical_support_count"], 2)
        self.assertEqual(result["covered_mismatch_count"], 1)
        self.assertEqual(result["uncovered_mismatch_count"], 2)
        self.assertEqual(result["covered_mismatch_rows"], [2])
        self.assertEqual(result["uncovered_mismatch_rows"], [1, 3])
        self.assertAlmostEqual(result["coverage_fraction"], 1.0 / 3.0)

    def test_size_strata_are_unique_and_cover_positive_sizes(self) -> None:
        contract, _ = UB1.load_local_seal()
        for size in range(1, 157):
            labels = UB1.strata_for(contract, size)
            self.assertEqual(len(labels), 1, size)

    def test_bits_hash_is_little_endian_u32_sequence(self) -> None:
        self.assertEqual(
            UB1.bits_hash([0, 1, 0xFFFF_FFFF]),
            "DE25D19943926B201C1693709BC5ECA70ECF04229C1668E2F276249F9BEBE043",
        )

    def test_mismatch_records_keep_exact_bits(self) -> None:
        state = SimpleNamespace(
            baseline_readout_bits=(0x8000_0000, 0x3F80_0000, 0x4000_0000),
            target_readout_bits=(0x8000_0000, 0x3F80_0001, 0x3F80_0000),
        )
        self.assertEqual(
            UB1.mismatch_records(state, {2, 1}),
            [
                {"row": 1, "baseline_bits": 0x3F80_0000, "target_bits": 0x3F80_0001},
                {"row": 2, "baseline_bits": 0x4000_0000, "target_bits": 0x3F80_0000},
            ],
        )


class SealTests(unittest.TestCase):
    def test_local_plan_and_contract_are_sealed(self) -> None:
        contract, preexecution = UB1.load_local_seal()
        self.assertEqual(contract["identity"], "q10-gc0-ub1-v1")
        self.assertTrue(preexecution["parent_bindings_sealed"])
        self.assertFalse(preexecution["execution_started"])


class PostRunTests(unittest.TestCase):
    def test_full_result_when_present_is_support_only(self) -> None:
        path = UB1.OUTPUT
        if not path.is_file():
            self.skipTest("full audit has not run yet")
        execution = UB1.load_json(path)
        self.assertEqual(execution["protocol"], "Q10-GC0-UB1")
        self.assertFalse(execution["firewall"]["scientific_promotion"])
        self.assertFalse(execution["firewall"]["behavioral_probe"])
        self.assertFalse(execution["firewall"]["gc1_authorized"])
        self.assertEqual(execution["counts"]["endpoint_set_count"], 14)
        gate = execution["raw_group_upper_bound"]
        self.assertEqual(gate["baseline_mismatch_count"], gate["covered_mismatch_count"] + gate["uncovered_mismatch_count"])
        self.assertEqual(execution["counts"]["raw_group_count"], sum(item["raw_group_count"] for item in execution["endpoint_set_results"]))


if __name__ == "__main__":
    unittest.main()
