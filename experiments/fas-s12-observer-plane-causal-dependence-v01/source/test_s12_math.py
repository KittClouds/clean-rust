from __future__ import annotations

import unittest

import numpy as np

from s12_math import draw_bootstrap_plan, matched_random_delta, orthonormal_row_basis, projected, random_plane, seed_from_label


class S12MathTests(unittest.TestCase):
    def test_rank_two_projector_is_symmetric_idempotent_and_contains_rows(self) -> None:
        rng = np.random.Generator(np.random.PCG64(19))
        rows = rng.standard_normal((3, 2048))
        rows[2] = rows[0] - rows[1]
        basis, receipt = orthonormal_row_basis(rows)
        projector = basis.T @ basis
        self.assertEqual(receipt["rank"], 2)
        self.assertLess(np.linalg.norm(projector - projector.T, ord="fro"), 1e-10)
        self.assertLess(np.linalg.norm(projector @ projector - projector, ord="fro"), 1e-9)
        self.assertLess(np.linalg.norm(rows - (rows @ basis.T) @ basis, ord="fro"), 1e-10)
        self.assertLess(receipt["source_pair_normal_relative_residual"], 1e-10)

    def test_random_delta_matches_target_norm_and_uses_fixed_plane(self) -> None:
        target_seed, _ = seed_from_label("target")
        random_seed, _ = seed_from_label("control")
        target = random_plane(target_seed)
        control = random_plane(random_seed)
        q = np.linspace(-2.0, 3.0, 2048, dtype=np.float64)
        target_delta = 0.5 * projected(target, q)
        control_delta = matched_random_delta(target_delta, control, q)
        self.assertAlmostEqual(float(np.linalg.norm(target_delta)), float(np.linalg.norm(control_delta)), delta=1e-12)
        np.testing.assert_array_equal(control, random_plane(random_seed))

    def test_zero_target_delta_produces_zero_control(self) -> None:
        seed, _ = seed_from_label("control-zero")
        basis = random_plane(seed)
        result = matched_random_delta(np.zeros(2048), basis, np.ones(2048))
        np.testing.assert_array_equal(result, np.zeros(2048))

    def test_zero_random_projection_fails_when_target_is_nonzero(self) -> None:
        basis = np.zeros((2, 2048), dtype=np.float64)
        basis[0, 0] = 1.0
        basis[1, 1] = 1.0
        q = np.zeros(2048, dtype=np.float64)
        with self.assertRaises(ValueError):
            matched_random_delta(np.ones(2048), basis, q)

    def test_bootstrap_is_deterministic_and_stratum_sized(self) -> None:
        labels = np.asarray([0] * 3 + [1] * 4 + [2] * 2, dtype=np.int64)
        first = draw_bootstrap_plan(labels, 777, replicates=7)
        second = draw_bootstrap_plan(labels, 777, replicates=7)
        np.testing.assert_array_equal(first, second)
        for row in first:
            self.assertEqual(np.count_nonzero(labels[row] == 0), 3)
            self.assertEqual(np.count_nonzero(labels[row] == 1), 4)
            self.assertEqual(np.count_nonzero(labels[row] == 2), 2)


if __name__ == "__main__":
    unittest.main()
