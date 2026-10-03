from __future__ import annotations

import importlib.util
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "build_opening_range_oracle.py"
SPEC = importlib.util.spec_from_file_location("opening_range_oracle", MODULE_PATH)
ORACLE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = ORACLE
SPEC.loader.exec_module(ORACLE)


class GrammarGoldenTests(unittest.TestCase):
    def setUp(self) -> None:
        self.t0 = datetime(2026, 8, 13, 16, 35)

    def run_path(self, locations: list[int], gaps: set[int] | None = None):
        track = ORACLE.Track()
        events = []
        now = self.t0
        for index, loc in enumerate(locations):
            if gaps and index in gaps:
                now += timedelta(minutes=5)
            event, track = ORACLE.grammar(track, loc, now)
            events.append(event)
            now += timedelta(minutes=5)
        return events, track

    def test_boundary_is_in_zone(self) -> None:
        self.assertEqual(ORACLE.location(110.0, 110.0, 100.0), 1)
        self.assertEqual(ORACLE.location(100.0, 110.0, 100.0), 1)

    def test_one_bar_above_failure(self) -> None:
        events, track = self.run_path([1, 2, 1])
        self.assertEqual(events, [1, 2, 4])
        self.assertEqual(track.failed_above, 1)

    def test_multi_bar_above_return(self) -> None:
        events, track = self.run_path([2, 2, 1])
        self.assertEqual(events, [2, 3, 5])
        self.assertEqual(track.failed_above, 0)

    def test_one_bar_below_failure_mirror(self) -> None:
        events, track = self.run_path([1, 3, 1])
        self.assertEqual(events, [1, 6, 8])
        self.assertEqual(track.failed_below, 1)

    def test_cross_through_both_directions(self) -> None:
        events, track = self.run_path([2, 3, 2])
        self.assertEqual(events, [2, 10, 11])
        self.assertEqual((track.above, track.below), (2, 1))

    def test_gap_emits_resume_without_inferred_transition(self) -> None:
        events, track = self.run_path([2, 3, 1], gaps={1})
        self.assertEqual(events, [2, 14, 8])
        self.assertEqual(track.first_side, 1)


if __name__ == "__main__":
    unittest.main()
