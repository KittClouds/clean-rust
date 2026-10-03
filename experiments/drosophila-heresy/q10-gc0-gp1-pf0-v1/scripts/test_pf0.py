"""Checks for the GP1 full-palette workload preflight."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
import run_pf0 as PF0  # noqa: E402


class PreflightTests(unittest.TestCase):
    def test_strata(self) -> None:
        self.assertEqual(PF0.group_stratum(1), "raw_size_1")
        self.assertEqual(PF0.group_stratum(16), "raw_size_8_16")
        self.assertEqual(PF0.group_stratum(32), "rh1_primary_size_32_plus")

    def test_local_seal(self) -> None:
        contract = PF0.load_seal()
        self.assertEqual(contract["identity"], "q10-gc0-gp1-pf0-v1")
        self.assertFalse(contract["firewall"]["candidate_generation"])
        self.assertFalse(contract["firewall"]["gc1_authorized"])

    def test_preflight_is_non_scientific(self) -> None:
        if not PF0.EXECUTION.is_file():
            self.skipTest("PF0 has not run")
        result = PF0.load_json(PF0.EXECUTION)
        self.assertEqual(result["counts"]["raw_group_count"], 801)
        self.assertEqual(result["counts"]["merged_authority_context_count"], 27075)
        self.assertFalse(result["gate"]["candidate_generation_executed"])


if __name__ == "__main__":
    unittest.main()
