from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import run_phase2c_cross_atom_search as search


class IncrementalProfileTests(unittest.TestCase):
    def test_occurrence_histogram_move_updates_unique_count(self) -> None:
        histogram = Counter({1: 1, 2: 1})
        moved = search.apply_hist_move(histogram, 1, 2)
        self.assertEqual(moved, Counter({3: 1}))
        self.assertEqual(search.moved_unique_count(2, 1, 2), 1)

    def test_new_input_updates_histogram_and_unique_count(self) -> None:
        histogram = Counter({1: 2, 3: 1})
        moved = search.apply_hist_move(histogram, 1, 0)
        self.assertEqual(moved, Counter({1: 2, 3: 1}))
        self.assertEqual(search.moved_unique_count(3, 1, 0), 3)

    def test_two_distinct_keys_in_same_bucket_update_frequency_histogram(self) -> None:
        source = Counter({1: 3, 2: 2})
        moved = search.apply_hist_move(source, 2, 2)
        self.assertEqual(moved, Counter({1: 4, 3: 1}))

    def test_counter_delta_removes_zero_categories(self) -> None:
        self.assertEqual(
            search.counter_after_delta(Counter({"a": 2}), ("a",), ("b",)),
            Counter({"a": 1, "b": 1}),
        )

    def test_supervised_distance_mass_update(self) -> None:
        current = Counter({"a": 2, "b": 1})
        reference = Counter({"a": 1, "b": 2})
        initial = sum(abs(current[k] - reference[k]) for k in current.keys() | reference.keys())
        updated = search.update_distance_mass(initial, current, reference, "a", "b")
        self.assertEqual(updated, 0)
        self.assertEqual(search.distance_from_mass(updated), 0.0)


if __name__ == "__main__":
    unittest.main()
