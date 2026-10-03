from __future__ import annotations

import unittest

import numpy as np

from s07_sparse import (
    choose_feature_groups,
    candidate_slot_to_state,
    feature_statistics,
    paired_margin_contributions,
    sparse_logits,
    state_to_slot,
    top_coactivation_partners,
)


class SparseCompatibilityTests(unittest.TestCase):
    def test_candidate_position_target_maps_to_semantic_state(self) -> None:
        candidate_identity_order = [1, 0, 2]
        state_by_identity = {0: 0, 1: 1, 2: 2}
        slot_to_state = np.asarray([state_by_identity[item] for item in candidate_identity_order], dtype=np.uint8)
        self.assertEqual(candidate_slot_to_state(slot_to_state, target_slot=1), 0)

    def test_candidate_slot_inverse_and_sparse_readout(self) -> None:
        slot_map = np.asarray([[2, 0, 1], [1, 2, 0]], dtype=np.int64)
        inverse = state_to_slot(slot_map)
        np.testing.assert_array_equal(inverse, [[1, 2, 0], [2, 0, 1]])
        decoder = np.zeros((4, 16_384), dtype=np.float32)
        decoder[:, 3] = [1, 2, 0, 0]
        decoder[:, 7] = [0, 1, 1, 0]
        code = {"indices": np.asarray([[3, 7], [7, 3]], dtype=np.uint16), "values": np.asarray([[2, 1], [3, 4]], dtype=np.float32)}
        probe = {"weights": np.asarray([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]], dtype=np.float32), "bias": np.zeros(3)}
        sparse = sparse_logits(code, decoder, np.zeros(4), probe)
        dense = np.asarray([[2, 5, 1, 0], [4, 11, 3, 0]], dtype=np.float64)
        np.testing.assert_allclose(sparse, dense[:, :3], atol=1e-7)
        ablated = sparse_logits(code, decoder, np.zeros(4), probe, zero_features=[3])
        self.assertTrue(np.all(np.isfinite(ablated)))
        self.assertFalse(np.array_equal(ablated, sparse))

    def test_feature_statistics_include_zero_mass(self) -> None:
        idx = np.asarray([[1, 4], [1, 2], [4, 2]], dtype=np.uint16)
        val = np.asarray([[2.0, 1.0], [3.0, 0.0], [1.0, 4.0]], dtype=np.float32)
        stats = feature_statistics(idx, val)
        self.assertEqual(int(stats["activation_count"][1]), 2)
        self.assertAlmostEqual(float(stats["activation_frequency"][1]), 2 / 3)
        self.assertAlmostEqual(float(stats["mean"][1]), 5 / 3)
        self.assertAlmostEqual(float(stats["zero_mass"][3]), 1.0)

    def test_paired_contributions_are_surface_differentials(self) -> None:
        code_m = {"indices": np.asarray([[5], [8]], dtype=np.uint16), "values": np.asarray([[2.0], [1.0]], dtype=np.float32)}
        code_f = {"indices": np.asarray([[5], [8]], dtype=np.uint16), "values": np.asarray([[3.0], [1.0]], dtype=np.float32)}
        decoder = np.zeros((2, 16_384), dtype=np.float32)
        decoder[:, 5] = [1, 0]
        decoder[:, 8] = [0, 1]
        wm = np.asarray([[1, 0], [0, 1], [-1, 0]], dtype=np.float32)
        wf = np.asarray([[0, 1], [1, 0], [0, -1]], dtype=np.float32)
        slot_map = np.tile(np.arange(3), (2, 1))
        result = paired_margin_contributions(code_m, code_f, decoder, wm, wf, slot_map)
        self.assertEqual(result["mean_delta"].shape, (3, 16_384))
        self.assertTrue(np.isfinite(result["mean_delta"]).all())

    def test_paired_contributions_align_by_feature_id_not_topk_slot(self) -> None:
        code_m = {"indices": np.asarray([[5]], dtype=np.uint16), "values": np.asarray([[1.0]], dtype=np.float32)}
        code_f = {"indices": np.asarray([[8]], dtype=np.uint16), "values": np.asarray([[1.0]], dtype=np.float32)}
        decoder = np.zeros((2, 16_384), dtype=np.float32)
        decoder[:, 5] = [1, 0]
        decoder[:, 8] = [0, 1]
        weights_m = np.asarray([[1, 0], [0, 0], [-1, 0]], dtype=np.float32)
        weights_f = np.asarray([[0, 1], [0, 0], [0, -1]], dtype=np.float32)
        slot_map = np.asarray([[0, 1, 2]], dtype=np.uint8)
        result = paired_margin_contributions(code_m, code_f, decoder, weights_m, weights_f, slot_map)
        self.assertAlmostEqual(float(result["mean_delta"][0, 5]), -1.0)
        self.assertAlmostEqual(float(result["mean_delta"][0, 8]), 1.0)

    def test_coactivation_ignores_zero_topk_ties(self) -> None:
        indices = {"M": np.asarray([[1, 2], [1, 2]], dtype=np.uint16), "F": np.asarray([[1, 2], [1, 2]], dtype=np.uint16)}
        values = {"M": np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32), "F": np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)}
        freq = {"M": np.asarray([0.0, 0.5, 0.5] + [0.0] * (16_384 - 3)), "F": np.asarray([0.0, 0.5, 0.5] + [0.0] * (16_384 - 3))}
        result = top_coactivation_partners(indices, values, freq, top_count=2, partner_count=1)
        self.assertEqual(result["surfaces"]["M"]["pair_count_nonzero"], 0)
        self.assertEqual(result["surfaces"]["F"]["pair_count_nonzero"], 0)

    def test_group_selection_has_disjoint_matched_controls(self) -> None:
        contributions = {"mean_delta": np.zeros((3, 16_384), dtype=np.float64)}
        for boundary in range(3):
            contributions["mean_delta"][boundary, boundary * 100:boundary * 100 + 64] = np.arange(64, 0, -1)
        frequency = np.linspace(0.01, 0.5, 16_384)
        nonzero = np.linspace(0.1, 1.0, 16_384)
        decoder = np.zeros((2, 16_384), dtype=np.float32)
        decoder[0] = 1.0
        result = choose_feature_groups(contributions, frequency, frequency[::-1], nonzero, nonzero[::-1], decoder)
        selected = set().union(*map(set, result["selected_groups"].values()))
        controls = [item for values in result["matched_control_groups"].values() for item in values]
        self.assertEqual(len(controls), 192)
        self.assertEqual(len(set(controls)), 192)
        self.assertFalse(selected.intersection(controls))
        self.assertTrue(result["control_features_are_unique"])


if __name__ == "__main__":
    unittest.main()
