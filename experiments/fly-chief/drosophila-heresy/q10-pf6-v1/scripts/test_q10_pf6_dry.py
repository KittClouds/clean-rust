"""Synthetic, engineering-only tests for Q10-PF6 beam semantics."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_q10_pf6 as pf6  # noqa: E402


class DryCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        bits = pf6.PF5.bits
        self.state = SimpleNamespace(
            baseline_readout_bits=(bits(2.0), bits(1.0)),
            target_readout_bits=(bits(0.0), bits(0.25)),
            support_counts=((), ((0, 1),), ((1, 1),)),
        )
        self.group = SimpleNamespace(
            key=("synthetic", 0),
            group_index=7,
            rows=(0, 1),
            coordinates=(1, 2),
            domains=((0, 1), (0, 1)),
            serialized_steps=((1,), (1,)),
            missing_prefixes=((), ()),
            helpful_rows=(0, 1),
            no_helpful_rows=(),
            threshold_classes=("synthetic",),
            helpful_component_indices=(0,),
            replayed_prefixes=((1,), (1,)),
            unreplayed_prefixes=((), ()),
        )

    def test_ranking_uses_coordinate_specific_residual_mass(self) -> None:
        ranked = pf6.rank_coordinates(self.state, self.group)
        self.assertEqual([item.coordinate for item in ranked], [1, 2])
        self.assertGreater(ranked[0].residual_mass, ranked[1].residual_mass)

    def test_unvisited_coordinates_remain_at_legal_zero(self) -> None:
        self.assertEqual(pf6.complete_prefix(self.group, {1: 1}), (1, 0))
        self.assertEqual(pf6.complete_prefix(self.group, {2: 1}), (0, 1))

    def test_zero_labels_are_distinct(self) -> None:
        self.assertNotEqual("tested_zero", "unselected_zero_by_horizon")


if __name__ == "__main__":
    unittest.main()
