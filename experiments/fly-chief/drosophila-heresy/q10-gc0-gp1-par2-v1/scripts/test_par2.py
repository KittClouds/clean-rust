"""Checks for PAR2 group-granular palette execution."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
import run_par2 as PAR2  # noqa: E402


class SealTests(unittest.TestCase):
    def test_local_seal(self) -> None:
        contract = PAR2.load_seal()
        self.assertEqual(contract["identity"], "q10-gc0-gp1-par2-v1")
        self.assertEqual(contract["execution"]["task_granularity"], "one raw group")
        self.assertEqual(contract["execution"]["chunksize"], 1)
        self.assertFalse(contract["firewall"]["global_assembly"])


class PostRunTests(unittest.TestCase):
    def test_complete_stream_when_present(self) -> None:
        if not PAR2.EXECUTION.is_file():
            self.skipTest("PAR2 has not run")
        result = PAR2.load_json(PAR2.EXECUTION)
        self.assertEqual(result["counts"]["raw_group_count"], 801)
        self.assertTrue(result["gate"]["all_groups_completed"])
        self.assertTrue(result["gate"]["raw_support_complete"])
        self.assertFalse(result["gate"]["global_assembly_executed"])


if __name__ == "__main__":
    unittest.main()
