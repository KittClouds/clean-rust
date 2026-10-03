from __future__ import annotations

import unittest
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

from s09_math import effective_geometry, layer_surface_vectors, subspace_comparison, transition_table


class S09MathTests(unittest.TestCase):
    def test_extracts_two_surfaces_from_all_layer_states(self) -> None:
        states = tuple(torch.full((1, 4, 2048), float(i), dtype=torch.float32) for i in range(17))
        views = layer_surface_vectors(states, sequence_length=4)
        self.assertEqual(tuple(views.shape), (16, 2, 2048))
        self.assertTrue(torch.equal(views[0, 0], torch.full((2048,), 1.0)))
        self.assertTrue(torch.equal(views[-1, 1], torch.full((2048,), 16.0)))

    def test_three_class_linear_observer_has_two_dimensional_plane(self) -> None:
        weights = np.zeros((3, 2048), dtype=np.float32)
        weights[0, 0] = 1.0
        weights[1, 1] = 1.0
        weights[2, 0] = -1.0
        geom = effective_geometry(weights, np.zeros(3), np.zeros(2048), np.ones(2048))
        self.assertEqual(geom["rank"], 2)
        cmp = subspace_comparison(geom, geom)
        np.testing.assert_allclose(cmp["principal_angle_degrees"], [0.0, 0.0], atol=2e-6)

    def test_transition_table_is_paired_and_exact(self) -> None:
        y = np.array([0, 1, 2, 0], dtype=np.int64)
        before = np.array([0, 0, 2, 1], dtype=np.int64)
        after = np.array([1, 1, 2, 2], dtype=np.int64)
        result = transition_table(y, before, after)
        self.assertEqual(result["both_correct"], 1)
        self.assertEqual(result["source_only_correct"], 1)
        self.assertEqual(result["target_only_correct"], 1)
        self.assertEqual(result["both_incorrect"], 1)


if __name__ == "__main__":
    unittest.main()
