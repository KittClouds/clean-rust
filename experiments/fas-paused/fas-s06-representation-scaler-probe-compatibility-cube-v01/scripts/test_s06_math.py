from __future__ import annotations

import unittest

import numpy as np

from s06_analyze import _effective_geometry, _margin_row, _nearest_rank, _semantic_logits
from s06_common import CELL_INFO, CELL_ORDER


class S06MathTests(unittest.TestCase):
    def test_factorial_cube_has_eight_bundled_and_eight_split_scalers(self) -> None:
        self.assertEqual(len(CELL_ORDER), 16)
        self.assertEqual(len(set(CELL_ORDER)), 16)
        bundled = [cell for cell in CELL_ORDER if CELL_INFO[cell]["center_source"] == CELL_INFO[cell]["scale_source"]]
        split = [cell for cell in CELL_ORDER if CELL_INFO[cell]["center_source"] != CELL_INFO[cell]["scale_source"]]
        self.assertEqual((len(bundled), len(split)), (8, 8))
        self.assertIn("R_M_C_F_D_M_W_M", split)
        self.assertIn("R_M_C_M_D_F_W_M", split)

    def test_s01_semantic_class_mapping_is_applied_after_slot_logits(self) -> None:
        row = {"candidate_identity_order": [2, 0, 1], "state_by_candidate_identity": {"0": 1, "1": 2, "2": 0}}
        np.testing.assert_array_equal(_semantic_logits(np.asarray([5.0, 7.0, 9.0]), row), [5.0, 7.0, 9.0])
        row["state_by_candidate_identity"] = {"0": 0, "1": 1, "2": 2}
        np.testing.assert_array_equal(_semantic_logits(np.asarray([5.0, 7.0, 9.0]), row), [7.0, 9.0, 5.0])

    def test_analytic_normals_and_intercepts_match_affine_formula(self) -> None:
        width = 2048
        w_m = np.zeros((3, width), dtype=np.float32)
        w_f = np.zeros((3, width), dtype=np.float32)
        w_m[0, 0], w_m[1, 1], w_m[2, 2] = 2.0, 3.0, 4.0
        w_f[0, 0], w_f[1, 1], w_f[2, 2] = -1.0, 5.0, 6.0
        states = {"S01_CONTROLLED": {
            "M": {"weights": w_m, "bias": np.asarray([1, 2, 3], dtype=np.float32),
                  "replay_mean": np.full(width, 0.5, dtype=np.float32), "replay_scale": np.full(width, 2.0, dtype=np.float32)},
            "F": {"weights": w_f, "bias": np.asarray([4, 5, 6], dtype=np.float32),
                  "replay_mean": np.full(width, -0.25, dtype=np.float32), "replay_scale": np.full(width, 4.0, dtype=np.float32)},
        }}
        result = _effective_geometry("S01_CONTROLLED", states)
        cell = result["cells"]["R_M_C_F_D_M_W_M"]
        expected_normal = w_m.astype(np.float64) / 2.0
        expected_intercept = np.asarray([1.0, 2.0, 3.0]) - expected_normal @ np.full(width, -0.25)
        np.testing.assert_allclose(cell["effective_class_normals"], expected_normal, rtol=0, atol=0)
        np.testing.assert_allclose(cell["effective_intercepts"], expected_intercept, rtol=0, atol=0)

    def test_pair_margins_and_nearest_rank_rule(self) -> None:
        margins = _margin_row(np.asarray([3.0, 1.0, 2.0]), target=2)
        self.assertEqual(margins["class_0_minus_class_1"], 2.0)
        self.assertEqual(margins["class_0_minus_class_2"], 1.0)
        self.assertEqual(margins["class_1_minus_class_2"], -1.0)
        self.assertEqual(margins["target_vs_best_rival"], -1.0)
        self.assertEqual(_nearest_rank(np.asarray([7.0, 1.0, 4.0, 2.0, 9.0]), 0.8), 7.0)


if __name__ == "__main__":
    unittest.main()
