"""Checks for the PAR1 parallel palette runner."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
import run_par1 as PAR1  # noqa: E402


class SealTests(unittest.TestCase):
    def test_local_seal(self) -> None:
        contract = PAR1.load_seal()
        self.assertEqual(contract["identity"], "q10-gc0-gp1-par1-v1")
        self.assertEqual(contract["execution"]["worker_count"], 4)
        self.assertFalse(contract["firewall"]["global_assembly"])

    def test_parent_paths_are_sealed(self) -> None:
        contract = PAR1.load_seal()
        self.assertGreaterEqual(len(contract["parent_bindings"]), 8)


class PostRunTests(unittest.TestCase):
    def test_complete_stream_when_present(self) -> None:
        if not PAR1.EXECUTION.is_file():
            self.skipTest("PAR1 has not run")
        result = PAR1.load_json(PAR1.EXECUTION)
        self.assertEqual(result["protocol"], "Q10-GC0-GP1-PAR1")
        self.assertEqual(result["counts"]["raw_group_count"], 801)
        self.assertTrue(result["gate"]["all_groups_completed"])
        self.assertTrue(result["gate"]["raw_support_complete"])
        self.assertFalse(result["gate"]["global_assembly_executed"])


if __name__ == "__main__":
    unittest.main()
