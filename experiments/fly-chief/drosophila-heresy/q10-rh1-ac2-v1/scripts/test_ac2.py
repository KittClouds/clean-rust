"""Qualification tests for Q10-RH1-AC2 helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_ac2 as AC2  # noqa: E402


class AC2Tests(unittest.TestCase):
    def test_prefix_domain_is_frozen(self) -> None:
        self.assertEqual(AC2.PREFIX_DOMAIN, (0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16))

    def test_contract_is_hash_bound(self) -> None:
        bindings = AC2.verify_contract()
        self.assertEqual(len(bindings), 5)

    def test_support_index_is_deterministic(self) -> None:
        class State:
            rows = ((0, 2, 2), (1,), (0, 1))
        rows, counts = AC2.support_index(State())
        self.assertEqual(rows[0], [0, 2])
        self.assertEqual(counts[2], [(0, 2)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
