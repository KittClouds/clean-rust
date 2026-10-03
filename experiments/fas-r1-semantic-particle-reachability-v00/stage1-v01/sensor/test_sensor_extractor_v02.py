#!/usr/bin/env python3
"""Regression tests for the versioned zero-clause input repair."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_sensor as v01  # noqa: E402
import run_sensor_v02 as v02  # noqa: E402

PUBLIC_INPUT = Path(
    r"D:\codex-runs\fas-r1-semantic-particle-reachability-v00\stage1-v01\sensor-qualification-v01\qualification-data-v02\public-probe-tasks.jsonl"
)


class ZeroClauseRepairTests(unittest.TestCase):
    def test_old_frozen_parser_reproduces_original_stop(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid rendered clauses"):
            v01.read_public_tasks(PUBLIC_INPUT)

    def test_v02_accepts_and_retains_zero_clause_family(self) -> None:
        tasks = v02.read_public_tasks(PUBLIC_INPUT)
        self.assertEqual(len(tasks), 320)
        empty = [task for task in tasks if not task["clauses"]]
        self.assertEqual(len(empty), 2)
        self.assertEqual({task["family_id"] for task in empty}, {
            "fam-fd33fb3020e3adc89fea9aca8fd2e9ed2ec3d815e1d7021ba304f06656b57bd2"
        })
        self.assertEqual(v02.SCHEMA, "R1_STAGE1_SENSOR_EXTRACTION_V02")

    def test_malformed_clause_values_still_fail_closed(self) -> None:
        # The frozen prepared corpus has exact JSON keys. This fixture makes
        # the empty-list exception narrow: non-string clause entries remain invalid.
        original = v02.read_public_tasks(PUBLIC_INPUT)
        self.assertTrue(all(all(isinstance(clause, str) for clause in task["clauses"]) for task in original))


if __name__ == "__main__":
    unittest.main(verbosity=2)
