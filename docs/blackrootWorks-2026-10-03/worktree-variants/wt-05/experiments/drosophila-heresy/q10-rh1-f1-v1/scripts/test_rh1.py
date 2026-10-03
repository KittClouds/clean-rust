"""Unit tests for RH1-F1 runtime helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_rh1 as RH1  # noqa: E402


class RH1Tests(unittest.TestCase):
    def test_contract_and_ac2_bindings(self) -> None:
        bindings = RH1.verify_contract()
        self.assertEqual(len(bindings), 8)
        self.assertEqual(len(RH1.load_features()), 2707)

    def test_cohorts(self) -> None:
        primary, secondary = RH1.frozen_groups()
        self.assertEqual(len(primary), 32)
        self.assertEqual(len(secondary), 23)

    def test_canonical_group_has_sorted_coordinates(self) -> None:
        self.assertEqual(RH1.CQ.canonical_state({9: 0, 3: 2}), ((3, 2), (9, 0)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
