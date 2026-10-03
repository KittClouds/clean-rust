"""Regression tests for the read-only Q10-PF5 qualification layer."""
from __future__ import annotations

import unittest
from pathlib import Path

try:
    from .qualify_q10_pf5 import (
        BeamState,
        GeometryDebt,
        Objective,
        QualificationError,
        classify_endpoint,
        replay_plan,
        resolve_receipt_path,
        select_beam,
    )
    from .run_q10_pf5 import (
        RawGroup,
        build_raw_groups,
        load_endpoint_states,
        load_lineage,
        load_topology,
        legal_prefix_bits,
        replay_group,
    )
except ImportError:
    from qualify_q10_pf5 import (
        BeamState,
        GeometryDebt,
        Objective,
        QualificationError,
        classify_endpoint,
        replay_plan,
        resolve_receipt_path,
        select_beam,
    )
    from run_q10_pf5 import (
        RawGroup,
        build_raw_groups,
        load_endpoint_states,
        load_lineage,
        load_topology,
        legal_prefix_bits,
        replay_group,
    )


class ReceiptPathTests(unittest.TestCase):
    def test_manifest_path_keeps_qualification_prefix(self) -> None:
        rmt_root = Path("q10-rmt-v1")
        actual = resolve_receipt_path(
            rmt_root,
            "qualification/sample-9731-9732",
            "qualification/sample-9731-9732/execution.json",
        )
        self.assertEqual(
            actual,
            Path("q10-rmt-v1/qualification/sample-9731-9732/execution.json"),
        )

    def test_manifest_path_cannot_escape_canonical_root(self) -> None:
        with self.assertRaises(QualificationError):
            resolve_receipt_path(
                Path("q10-rmt-v1"),
                "qualification/sample-9731-9732",
                "qualification/sample-9731-9732/../../STATUS.json",
            )


class ContractPrimitiveTests(unittest.TestCase):
    def test_replay_plan_selects_exact_beam_and_oversize_paths(self) -> None:
        self.assertEqual(replay_plan(((0, -1, 1),) * 3).mode, "EXACT_ENUMERATION")
        self.assertEqual(replay_plan(((0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16),) * 4).mode, "OVERSIZE_UNTESTED")
        self.assertEqual(replay_plan(((0, -1, 1, -2, 2),) * 4 + ((0, -1, 1, -2, 2, -4, 4),)).mode, "BOUNDED_BEAM")

    def test_prefix_respects_the_frozen_reserve(self) -> None:
        raw = 0x3F800000
        self.assertEqual(legal_prefix_bits(raw, 0), raw)
        self.assertIsNotNone(legal_prefix_bits(raw, 16))
        self.assertIsNone(legal_prefix_bits(16, -16))

    def test_exploit_and_explore_lanes_are_retained(self) -> None:
        states = tuple(
            BeamState(
                prefix_tuple=(index,),
                objective=Objective(index, index, float(index), float(index), (index,)),
                debt=GeometryDebt(0.0, 0.0, 0.0),
                threshold_class=f"class-{index}",
                coverage_signature=(index,),
            )
            for index in range(40)
        )
        selected = select_beam(states)
        self.assertEqual(len(selected), 32)
        self.assertEqual(len(selected[:24]), 24)
        self.assertEqual(len(selected[24:]), 8)

    def test_no_helpful_row_cannot_become_a_partial_domain_block(self) -> None:
        self.assertEqual(
            classify_endpoint(
                exact_target=False,
                improved=False,
                final_geometry_pass=False,
                coverage_complete=False,
                bounded_search_exhausted=True,
            ),
            "INCONCLUSIVE_BOUNDED_SEARCH",
        )

    def test_exact_coverage_with_geometry_pruning_is_still_complete(self) -> None:
        self.assertEqual(
            classify_endpoint(
                exact_target=False,
                improved=False,
                final_geometry_pass=False,
                coverage_complete=True,
                bounded_search_exhausted=False,
            ),
            "BLOCKED_WITHIN_DECLARED_DOMAIN",
        )


class RealReceiptSliceTests(unittest.TestCase):
    def test_reconstructs_all_primary_endpoints_and_raw_groups(self) -> None:
        protocol_root = Path(__file__).resolve().parents[1]
        lineage = load_lineage(protocol_root)
        states = load_endpoint_states(lineage)
        topology = load_topology(lineage)
        self.assertEqual(len(states), 28)
        groups = build_raw_groups(states[0], topology, lineage)
        self.assertGreater(len(groups), 0)
        self.assertEqual(groups[0].coordinates, (20196, 20290))
        self.assertEqual(groups[0].domains[0], (0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16))
        self.assertTrue(any(groups[0].missing_prefixes[0]))

    def test_exact_replay_slice_measures_every_tuple(self) -> None:
        protocol_root = Path(__file__).resolve().parents[1]
        lineage = load_lineage(protocol_root)
        state = load_endpoint_states(lineage)[0]
        topology = load_topology(lineage)
        group = build_raw_groups(state, topology, lineage)[0]
        result = replay_group(state, group, lineage.contract)
        self.assertEqual(result["replay_plan"]["mode"], "EXACT_ENUMERATION")
        self.assertEqual(result["replay_plan"]["nodes_replayed"], 121)
        self.assertEqual(result["replay_plan"]["cartesian_product"], 121)
        self.assertEqual(result["coverage_state"], "complete")
        self.assertGreater(result["replay_plan"]["guard_pruned"], 0)
        self.assertEqual(result["status"], "PARTIAL_FEASIBILITY_FOUND")

    def test_bounded_beam_path_is_executable(self) -> None:
        protocol_root = Path(__file__).resolve().parents[1]
        lineage = load_lineage(protocol_root)
        state = load_endpoint_states(lineage)[0]
        coordinates = tuple(
            coordinate
            for coordinate, permitted in enumerate(state.permitted)
            if permitted and coordinate in state.interior
            and all(legal_prefix_bits(state.baseline_weight_bits[coordinate], choice) is not None for choice in (0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16))
        )[:5]
        self.assertEqual(len(coordinates), 5)
        domains = (
            (0, -1, 1, -2, 2),
            (0, -1, 1, -2, 2),
            (0, -1, 1, -2, 2),
            (0, -1, 1, -2, 2),
            (0, -1, 1, -2, 2, -4, 4),
        )
        group = RawGroup(state.key, 999, (0,), coordinates, domains, ((),) * 5, ((),) * 5, (), (0,), (), ())
        result = replay_group(state, group, lineage.contract)
        self.assertEqual(result["replay_plan"]["mode"], "BOUNDED_BEAM")
        self.assertEqual(result["replay_plan"]["coverage"], "partial")
        self.assertLessEqual(result["replay_plan"]["nodes_replayed"], 8192)


if __name__ == "__main__":
    unittest.main()
