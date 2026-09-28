"""Qualification tests for Q10-RH1-Q1."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_q1 as Q1  # noqa: E402


class Q1Tests(unittest.TestCase):
    def test_contract_is_hash_bound(self) -> None:
        self.assertEqual(len(Q1.verify_contract()), 4)

    def test_mapping_choice_is_deterministic(self) -> None:
        self.assertEqual(Q1.CQ.canonical_state({3: 2, 1: -1}), ((1, -1), (3, 2)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
