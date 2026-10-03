from __future__ import annotations

import unittest

import pandas as pd

from lifecycle_audit import MAX_ATTEMPT_BARS, _epoch, _interval_gap, _phase


class LifecycleAuditTests(unittest.TestCase):
    def test_interval_gap_overlaps(self) -> None:
        self.assertEqual(_interval_gap(10.0, 12.0, 11.0, 13.0), 0.0)

    def test_interval_gap_separated(self) -> None:
        self.assertEqual(_interval_gap(10.0, 12.0, 13.5, 14.0), 1.5)

    def test_terminal_phase_precedence(self) -> None:
        row = pd.Series({"contact": 1, "break": 2, "accepted": 3, "penetration_atr": 1.0})
        self.assertEqual(_phase(row), "ACCEPTED_PENDING_DEPARTURE")

    def test_timeout_boundary_contract(self) -> None:
        self.assertEqual(MAX_ATTEMPT_BARS + 1, 25)

    def test_mt5_timestamp_converts_to_unix_seconds(self) -> None:
        value = _epoch(pd.Series(["2025.12.15 01:05:06"])).iloc[0]
        self.assertEqual(value, 1765760706)


if __name__ == "__main__":
    unittest.main()
