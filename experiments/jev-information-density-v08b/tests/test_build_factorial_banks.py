from __future__ import annotations

import importlib.util
import sys
import unittest
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "build_factorial_banks.py"
SPEC = importlib.util.spec_from_file_location("jev_v08b_builder", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def group(group_id: str, input_id: str, root: str) -> MODULE.v08.Group:
    return MODULE.v08.Group(
        group_id=group_id,
        episode_id=f"episode-{group_id}",
        root_id=root,
        families=tuple((axis, f"{axis}-value") for axis in MODULE.v08.FAMILY_AXES),
        strata=("world", "choice", "4", "q1"),
        features=tuple((f"axis-{axis}",) for axis in range(len(MODULE.v08.COVERAGE_AXES))),
        overlap_keys=(f"model_input:{input_id}",),
        split_family_bundle_id="bundle",
        posterior_entropy_nats=0.1,
    )


class FactorialSelectionTests(unittest.TestCase):
    def test_cell_selection_preserves_exact_input_multiplicity_profile(self) -> None:
        cell = ("world", "bundle", "choice", "4", "q1", "very_low")
        candidates = {
            "input-a": [group("a1", "input-a", "root-a"), group("a2", "input-a", "root-b")],
            "input-b": [group("b1", "input-b", "root-c")],
            "input-c": [group("c1", "input-c", "root-d"), group("c2", "input-c", "root-e")],
        }
        scores = {group_id: float(index) for index, group_id in enumerate(("a1", "a2", "b1", "c1", "c2"))}
        demand = Counter({2: 1, 1: 1})
        selected = MODULE.choose_cell(cell, candidates, demand, "random", "test-seed", scores)
        self.assertEqual(Counter(selected.values()), demand)
        self.assertEqual(sum(selected.values()), 3)

    def test_cell_selection_fails_closed_when_capacity_is_short(self) -> None:
        cell = ("world", "bundle", "choice", "4", "q1", "very_low")
        candidates = {"input-a": [group("a1", "input-a", "root-a")]}
        with self.assertRaisesRegex(ValueError, "needs 1 inputs with capacity 2"):
            MODULE.choose_cell(cell, candidates, Counter({2: 1}), "random", "test-seed", {"a1": 0.5})

    def test_ranked_attempts_visit_deterministic_distinct_windows(self) -> None:
        cell = ("world", "bundle", "choice", "4", "q1", "very_low")
        candidates = {
            f"input-{letter}": [group(f"{letter}1", f"input-{letter}", f"root-{letter}")]
            for letter in "abcdef"
        }
        scores = {f"{letter}1": 0.5 for letter in "abcdef"}
        demand = Counter({1: 2})
        attempt0 = MODULE.choose_cell(
            cell, candidates, demand, "random", "seed", scores, attempt_index=0
        )
        attempt1 = MODULE.choose_cell(
            cell, candidates, demand, "random", "seed", scores, attempt_index=1
        )
        repeated = MODULE.choose_cell(
            cell, candidates, demand, "random", "seed", scores, attempt_index=1
        )
        self.assertNotEqual(set(attempt0), set(attempt1))
        self.assertEqual(attempt1, repeated)
        self.assertEqual(Counter(attempt1.values()), demand)

    def test_ranked_window_is_bounded_at_tail(self) -> None:
        values = list("abcdef")
        self.assertEqual(MODULE.ranked_window(values, 2, 0), ["a", "b"])
        self.assertEqual(MODULE.ranked_window(values, 2, 1), ["c", "d"])
        self.assertEqual(MODULE.ranked_window(values, 2, 99), ["e", "f"])

    def test_b_matching_obeys_exact_input_and_root_degrees(self) -> None:
        cell = ("world", "bundle", "choice", "4", "q1", "very_low")
        candidates = {
            cell: {
                "input-a": [
                    group("a-r1", "input-a", "root-1"),
                    group("a-r2", "input-a", "root-2"),
                ],
                "input-b": [group("b-r1", "input-b", "root-1")],
            }
        }
        demands = {(cell, "input-a"): 2, (cell, "input-b"): 1}
        root_demands = {"root-1": 2, "root-2": 1}
        scores = {"a-r1": 0.3, "a-r2": 0.2, "b-r1": 0.1}
        selected, receipt = MODULE.assign_groups_by_flow(
            demands, candidates, root_demands, "random", "test-seed", scores
        )
        self.assertEqual(receipt["achieved_flow"], 3)
        self.assertEqual(Counter(row.root_id for row in selected), Counter(root_demands))
        self.assertEqual(
            Counter(MODULE.model_input_id(row) for row in selected),
            Counter({"input-a": 2, "input-b": 1}),
        )

    def test_b_matching_fails_when_root_degrees_are_disconnected(self) -> None:
        cell = ("world", "bundle", "choice", "4", "q1", "very_low")
        candidates = {cell: {"input-a": [group("a1", "input-a", "root-1")]}}
        with self.assertRaises(MODULE.MatchingFlowIncomplete) as raised:
            MODULE.assign_groups_by_flow(
                {(cell, "input-a"): 1}, candidates, {"root-2": 1},
                "random", "test-seed", {"a1": 0.5}
            )
        self.assertEqual((raised.exception.achieved, raised.exception.target), (0, 1))


if __name__ == "__main__":
    unittest.main()
