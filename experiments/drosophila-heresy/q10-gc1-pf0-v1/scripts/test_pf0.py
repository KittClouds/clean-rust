"""Checks for the GC1 support/conflict preflight."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
import run_pf0 as PF0  # noqa: E402


class SealTests(unittest.TestCase):
    def test_local_seal(self) -> None:
        contract = PF0.load_seal()
        self.assertEqual(contract["identity"], "q10-gc1-pf0-v1")
        self.assertFalse(contract["firewall"]["global_assembly_executed"])
        self.assertFalse(contract["firewall"]["gc1_authorized"])

    def test_union_find(self) -> None:
        self.assertEqual(PF0.union_find([0, 1, 2], [(0, 1)]), [1, 2])


class PostRunTests(unittest.TestCase):
    def test_complete_preflight_when_present(self) -> None:
        if not PF0.EXECUTION.is_file():
            self.skipTest("GC1 PF0 has not run")
        result = PF0.load_json(PF0.EXECUTION)
        self.assertTrue(result["gate"]["palette_cardinality_complete"])
        self.assertTrue(result["gate"]["raw_support_complete"])
        self.assertFalse(result["gate"]["global_assembly_authorized"])


if __name__ == "__main__":
    unittest.main()
