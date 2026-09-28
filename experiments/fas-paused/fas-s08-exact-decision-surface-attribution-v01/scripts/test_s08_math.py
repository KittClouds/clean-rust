from __future__ import annotations

import numpy as np
import unittest

from s08_math import (
    classification_metrics,
    concentration_counts,
    effective_geometry,
    matched_controls,
    subspace_comparison,
    top_indices,
    walsh_basis,
    walsh_transform,
)


class S08MathTests(unittest.TestCase):
    def test_walsh_reconstructs_all_sixteen_cells(self) -> None:
        cells = [f"R_{r}_C_{c}_D_{d}_W_{w}" for r in "MF" for c in "MF" for d in "MF" for w in "MF"]
        basis, _ = walsh_basis(cells)
        values = np.arange(2 * 16 * 3, dtype=np.float64).reshape(2, 16, 3) / 7
        coefficients, residual = walsh_transform(values, basis)
        self.assertLess(residual, 1e-12)
        self.assertTrue(np.allclose(np.einsum("nps,cs->ncp", coefficients, basis), values))


    def test_walsh_is_order_independent_after_cell_id_decode(self) -> None:
        cells = [f"R_{r}_C_{c}_D_{d}_W_{w}" for r in "MF" for c in "MF" for d in "MF" for w in "MF"]
        base, _ = walsh_basis(cells)
        order = np.random.default_rng(9).permutation(16)
        shuffled, _ = walsh_basis([cells[i] for i in order])
        margins = np.arange(16, dtype=np.float64)[None, :, None]
        a, _ = walsh_transform(margins, base)
        b, _ = walsh_transform(margins[:, order], shuffled)
        self.assertTrue(np.allclose(a, b))


    def test_effective_geometry_has_two_dimensional_three_class_plane(self) -> None:
        rng = np.random.default_rng(42)
        state = {
            "weights": rng.normal(size=(3, 12)),
            "bias": rng.normal(size=3),
            "replay_mean": rng.normal(size=12),
            "replay_scale": np.exp(rng.normal(size=12)),
        }
        geometry = effective_geometry(state)
        self.assertEqual(geometry["rank"], 2)
        comparison = subspace_comparison(geometry, geometry)
        self.assertLess(np.max(np.abs(comparison["principal_angle_degrees"])), 1e-6)


    def test_concentration_counts_known_vector(self) -> None:
        values = np.array([[8.0, 1.0, 1.0, 0.0]])
        result = concentration_counts(values, (0.5, 0.8, 0.9))
        self.assertEqual(result.tolist(), [[1, 1, 2]])


    def test_topk_ties_use_ascending_coordinate_id(self) -> None:
        self.assertEqual(top_indices(np.array([1.0, 4.0, 4.0, 0.0]), 3), [1, 2, 0])


    def test_matched_controls_are_unselected_unique_and_deterministic(self) -> None:
        scores = np.array([10.0, 9.0, 0.0, 0.0, 0.0, 0.0])
        cov = np.arange(12, dtype=np.float64).reshape(6, 2)
        first = matched_controls([0, 1], scores, cov)
        second = matched_controls([0, 1], scores, cov)
        self.assertEqual(first, second)
        self.assertEqual(len(set(first)), 2)
        self.assertFalse(set(first).intersection({0, 1}))


    def test_concentration_zero_vector_is_zero(self) -> None:
        self.assertEqual(concentration_counts(np.zeros((2, 8))).tolist(), [[0, 0, 0, 0], [0, 0, 0, 0]])

    def test_classification_metrics_reports_all_pairwise_margin_distributions(self) -> None:
        logits = np.asarray([[3.0, 1.0, 0.0], [0.0, 2.0, 1.0], [1.0, 0.0, 4.0]])
        result = classification_metrics(logits, np.asarray([0, 1, 2]))
        self.assertEqual(set(result["pairwise_margins"]), {
            "class_0_minus_class_1", "class_0_minus_class_2", "class_1_minus_class_2"
        })
        self.assertAlmostEqual(result["pairwise_margins"]["class_0_minus_class_1"]["mean"], 1.0 / 3.0)
        self.assertEqual(result["pairwise_margins"]["class_1_minus_class_2"]["mean"], -0.6666666666666666)
