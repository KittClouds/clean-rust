"""Checks for the GP1 full raw-group palette runner."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
import run_gp1 as GP1  # noqa: E402


class SealTests(unittest.TestCase):
    def test_local_seal(self) -> None:
        contract = GP1.load_seal()
        self.assertEqual(contract["identity"], "q10-gc0-gp1-v1")
        self.assertFalse(contract["firewall"]["global_assembly"])
        self.assertFalse(contract["firewall"]["gc1_authorized"])

    def test_frozen_group_shape(self) -> None:
        class Group:
            key = ("e", 0)
            group_index = 3
            rows = (1, 2)
            coordinates = (8, 9)
            domains = ((0, -1), (0, 1))
        result = GP1.frozen_group(Group())
        self.assertEqual(result["identity"], ["e", 0, 3])
        self.assertEqual(result["coordinates"], [8, 9])


class PostRunTests(unittest.TestCase):
    def test_complete_stream_when_present(self) -> None:
        if not GP1.EXECUTION.is_file():
            self.skipTest("GP1 has not run")
        result = GP1.load_json(GP1.EXECUTION)
        self.assertEqual(result["protocol"], "Q10-GC0-GP1")
        self.assertEqual(result["counts"]["raw_group_count"], 801)
        self.assertTrue(result["gate"]["all_groups_completed"])
        self.assertTrue(result["gate"]["raw_support_complete"])
        self.assertFalse(result["gate"]["global_assembly_executed"])


if __name__ == "__main__":
    unittest.main()
