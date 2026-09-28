from __future__ import annotations

import collections
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve()
sys.path.insert(0, str(HERE.parents[1]))
import balanced_policy_cycles_v06 as cycles  # noqa: E402


def edge(out_state: str, in_state: str, out_count: int, in_count: int):
    return cycles.Edge(
        SimpleNamespace(input_state=out_state, group_id=f"out-{out_state}"),
        SimpleNamespace(input_state=in_state, group_id=f"in-{in_state}"),
        out_count,
        in_count,
        1.0,
        f"{out_state}-{in_state}",
    )


def fake_item(group_id: str, state: str):
    axes = cycles.v08e.core.FAMILY_AXES
    return SimpleNamespace(
        group_id=group_id,
        episode_id=f"episode-{group_id}",
        stratum_id='["same-stratum"]',
        input_state=state,
        input_selector=f"selector-{group_id}",
        root_id=f"root-{group_id}",
        family_items=tuple((axis, f"family-{axis}") for axis in axes),
        topology=("chain",),
        intervention="reveal",
        kind="choice",
        view="closed",
        candidate_count=4,
        open_world=False,
        probability_source="exact_generative_posterior",
    )


class BalancedCycleTests(unittest.TestCase):
    def test_cycle_builder_finds_complementary_occupancy_moves(self) -> None:
        selected_rows = (
            [fake_item(f"a{i}", "A") for i in range(3)]
            + [fake_item("b0", "B")]
            + [fake_item(f"c{i}", "C") for i in range(2)]
            + [fake_item(f"d{i}", "D") for i in range(2)]
        )
        incoming_rows = [fake_item("b1", "B"), fake_item("d2", "D")]
        support = selected_rows + incoming_rows
        selected = {item.group_id: item for item in selected_rows}
        state_counts = collections.Counter(item.input_state for item in selected_rows)
        quality = {item.group_id: 0.0 for item in selected_rows}
        quality["b1"] = 1.0
        quality["d2"] = 1.0
        candidates, _ = cycles.build_cycles(support, selected, state_counts, quality, "curated", 0)
        self.assertTrue(candidates)
        self.assertTrue(any(cycles.cycle_state_balanced(candidate, state_counts) for candidate in candidates))

    def test_complementary_two_edge_cycle_preserves_state_histogram(self) -> None:
        state_counts = collections.Counter({"A": 3, "B": 1, "C": 2, "D": 2})
        first = edge("A", "B", 3, 1)
        second = edge("C", "D", 2, 2)
        self.assertTrue(cycles.state_cycle_is_balanced(
            state_counts,
            (first.outgoing, first.incoming),
            (second.outgoing, second.incoming),
        ))

    def test_cycle_rejects_wrong_complementary_occupancy(self) -> None:
        state_counts = collections.Counter({"A": 3, "B": 1, "C": 3, "D": 2})
        first = edge("A", "B", 3, 1)
        second = edge("C", "D", 3, 2)
        self.assertFalse(cycles.state_cycle_is_balanced(
            state_counts,
            (first.outgoing, first.incoming),
            (second.outgoing, second.incoming),
        ))

    def test_cycle_rejects_shared_state_identity(self) -> None:
        state_counts = collections.Counter({"A": 3, "B": 1, "C": 2, "D": 2})
        first = edge("A", "B", 3, 1)
        second = edge("C", "A", 2, 2)
        self.assertFalse(cycles.state_cycle_is_balanced(
            state_counts,
            (first.outgoing, first.incoming),
            (second.outgoing, second.incoming),
        ))

    def test_sparse_histogram_update_matches_full_rebuild(self) -> None:
        counts = collections.Counter({"a": 3, "b": 1, "c": 2, "d": 2})
        updated = cycles.hist_after_cycle(counts, (
            ("a", -1), ("b", 1), ("c", -1), ("d", 1),
        ))
        full = collections.Counter({2: 2, 1: 1, 3: 1})
        self.assertEqual(updated, full)

    def test_profile_tracker_sparse_apply_matches_full_rebuild(self) -> None:
        selected = [
            fake_item("a1", "A"), fake_item("a2", "A"), fake_item("a3", "A"),
            fake_item("b1", "B"),
            fake_item("c1", "C"), fake_item("c2", "C"),
            fake_item("d1", "D"), fake_item("d2", "D"),
        ]
        outgoing = [selected[0], selected[4]]
        incoming = [fake_item("b2", "B"), fake_item("d3", "D")]
        tracker = cycles.ProfileTracker(selected)
        reference = cycles.v08e.core.profile(selected)
        limits = {"unique_relative_error_max": 0.02, "occurrence_histogram_tv_max": 0.02, "marginal_tv_max": 0.02}
        required = {axis: {f"family-{axis}"} for axis in cycles.v08e.core.FAMILY_AXES}
        passed, checks = tracker.check(outgoing, incoming, [reference], limits, required)
        self.assertTrue(passed, checks)
        tracker.apply(outgoing, incoming)
        rebuilt = cycles.v08e.core.profile([row for row in selected if row not in outgoing] + incoming)
        for key in tracker.profile():
            if key == "group_count":
                self.assertEqual(tracker.profile()[key], rebuilt[key])
            else:
                self.assertEqual(tracker.profile()[key], rebuilt[key], key)


if __name__ == "__main__":
    unittest.main()
