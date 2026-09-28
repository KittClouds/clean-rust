from __future__ import annotations

import unittest
import sys
from pathlib import Path

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

from s09_math import effective_geometry, layer_surface_vectors, subspace_comparison, transition_table, verify_affine_margin_identities
from run_analysis import state_for_subspace, verify_condition_metric_reproduction


class S09MathTests(unittest.TestCase):
    def test_terminal_metric_reproduction_ignores_only_aggregate_and_provenance(self) -> None:
        calculated = {
            "ALL_TEST_ROWS": {"accuracy": 0.75},
            "CONTEXT": {"accuracy": 0.8, "support": 10},
        }
        expected = {
            "CONTEXT": {"accuracy": 0.8, "support": 10, "interpretation_scope": "exploratory"},
        }
        verify_condition_metric_reproduction(calculated, expected)

    def test_terminal_metric_reproduction_rejects_numeric_differences(self) -> None:
        calculated = {"ALL_TEST_ROWS": {}, "CONTEXT": {"accuracy": 0.8, "support": 10}}
        expected = {"CONTEXT": {"accuracy": 0.81, "support": 10, "interpretation_scope": "exploratory"}}
        with self.assertRaisesRegex(RuntimeError, "CONTEXT"):
            verify_condition_metric_reproduction(calculated, expected)

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

    def test_subspace_geometry_uses_runtime_float32_scaler_values(self) -> None:
        scaler_mean = np.asarray([0.123456789123, -7.65432198765], dtype=np.float64)
        scaler_scale = np.asarray([1.23456789123, 9.87654321987], dtype=np.float64)
        state = state_for_subspace({
            "weights": np.ones((3, 2), dtype=np.float32),
            "bias": np.zeros(3, dtype=np.float32),
            "mean": scaler_mean,
            "scale": scaler_scale,
        })
        np.testing.assert_array_equal(state["mean"], scaler_mean.astype(np.float32).astype(np.float64))
        np.testing.assert_array_equal(state["scale"], scaler_scale.astype(np.float32).astype(np.float64))
        self.assertEqual(state["mean"].dtype, np.float64)

    def test_three_affine_margin_forms_match_for_every_row_and_pair(self) -> None:
        hidden = np.asarray([
            [0.25, -1.0, 2.0, 0.125],
            [1.5, 0.0, -0.5, 2.0],
            [-2.0, 1.25, 0.75, -0.25],
            [0.0, 0.5, 0.0, -1.0],
        ], dtype=np.float32)
        weights = np.asarray([[0.25, 0.5, -0.75, 1.0], [-0.5, 0.125, 0.25, -0.25], [1.0, -0.25, 0.5, 0.75]], dtype=np.float32)
        bias = np.asarray([0.125, -0.25, 0.5], dtype=np.float32)
        mean = np.asarray([0.1, -0.2, 0.3, -0.4], dtype=np.float64)
        scale = np.asarray([0.5, 1.5, 2.0, 0.75], dtype=np.float64)
        check = verify_affine_margin_identities(hidden, np.arange(len(hidden)), weights, bias, mean, scale)
        self.assertEqual(check["rows_checked"], len(hidden))
        self.assertEqual(check["pair_count"], 3)
        for key in (
            "max_abs_residual_direct_vs_raw",
            "max_abs_residual_direct_vs_centered",
            "max_abs_residual_raw_vs_centered",
            "max_abs_residual_beta_identity",
        ):
            self.assertLessEqual(check[key], 1e-12)


if __name__ == "__main__":
    unittest.main()
