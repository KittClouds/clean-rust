"""C-G1 logic against brute force and the properties that motivate the approach."""
from __future__ import annotations

import unittest

import numpy as np

from cg1 import transforms as T


def brute_percentile(keys, score):
    out = np.empty(len(score))
    for i in range(len(score)):
        same = keys == keys[i]
        out[i] = (score[same] <= score[i]).sum() / same.sum()
    return out


def brute_z(keys, score):
    out = np.empty(len(score))
    for i in range(len(score)):
        g = score[keys == keys[i]]
        iqr = max(np.quantile(g, 0.75) - np.quantile(g, 0.25), T.IQR_FLOOR)
        out[i] = (score[i] - np.median(g)) / iqr
    return out


class TransformTests(unittest.TestCase):
    def data(self, seed=0, n=600, groups=25):
        rng = np.random.default_rng(seed)
        keys = rng.integers(0, groups, n)
        score = np.round(rng.normal(0, 3, n), 1)   # rounded, so ties occur
        return keys, score

    def test_percentile_matches_brute_force_including_ties(self):
        for seed in range(4):
            keys, score = self.data(seed)
            np.testing.assert_allclose(T.group_percentile(keys, score), brute_percentile(keys, score))

    def test_robust_z_matches_brute_force(self):
        for seed in range(4):
            keys, score = self.data(seed)
            score = score + np.random.default_rng(seed).normal(0, 0.01, len(score))   # avoid a zero IQR
            np.testing.assert_allclose(T.robust_z(keys, score), brute_z(keys, score), atol=1e-9)

    def test_a_lone_pair_is_never_pruned_by_percentile_and_gets_z_of_zero(self):
        keys, score = np.array([0, 1, 1]), np.array([-5.0, 1.0, 2.0])
        self.assertEqual(T.group_percentile(keys, score)[0], 1.0)
        self.assertEqual(T.robust_z(keys, score)[0], 0.0)

    def test_a_per_world_shift_is_invisible_to_the_relative_transforms_and_not_to_the_raw_score(self):
        keys, score = self.data(3)
        shift = np.random.default_rng(9).normal(0, 4, keys.max() + 1)[keys]      # every world's scores move by its own constant
        scale = np.random.default_rng(10).uniform(0.5, 3, keys.max() + 1)[keys]  # and its own scale
        moved = score * scale + shift
        np.testing.assert_allclose(T.group_percentile(keys, moved), T.group_percentile(keys, score))
        np.testing.assert_allclose(T.robust_z(keys, moved), T.robust_z(keys, score), atol=1e-8)
        self.assertFalse(np.allclose(moved, score))

    def test_transform_dispatch_and_typepair_keys(self):
        row = np.array([0, 0, 0, 0, 1, 1])
        pair_type = np.array([1, 1, 2, 2, 1, 2])
        score = np.array([1.0, 3.0, 5.0, 4.0, 2.0, 2.0])
        np.testing.assert_allclose(T.transform("world_percentile", row, pair_type, score), [0.25, 0.5, 1.0, 0.75, 1.0, 1.0])
        np.testing.assert_allclose(T.transform("typepair_percentile", row, pair_type, score), [0.5, 1.0, 1.0, 0.5, 1.0, 1.0])   # row 1 has one pair per type pair
        np.testing.assert_allclose(T.transform("raw_logit", row, pair_type, score), score)
        with self.assertRaises(KeyError):
            T.transform("nope", row, pair_type, score)

    def test_shuffle_preserves_each_rows_multiset_and_is_reproducible(self):
        keys, score = self.data(5)
        a, b = T.shuffle_within_rows(keys, score, 1), T.shuffle_within_rows(keys, score, 1)
        np.testing.assert_array_equal(a, b)
        for k in np.unique(keys):
            np.testing.assert_allclose(np.sort(a[keys == k]), np.sort(score[keys == k]))
        self.assertFalse(np.array_equal(a, score))

    def test_fit_threshold_respects_the_budget_with_ties(self):
        t = np.array([0.1, 0.1, 0.2, 0.2, 0.3, 0.4, 0.5, 0.6])
        y = np.array([0, 0, 1, 0, 0, 1, 0, 0])
        threshold = T.fit_threshold(t, y, total_edges=2, eps=0.5)          # budget = 1 edge
        pruned = t <= threshold
        self.assertLessEqual(int((pruned & (y == 1)).sum()), 1)
        self.assertEqual(threshold, 0.3)                                    # 0.2 has one edge (ok), 0.3 adds none, 0.4 would add a second
        self.assertEqual(T.fit_threshold(t, y, total_edges=2, eps=0.0), 0.1)   # zero budget: only the edge-free prefix
        self.assertEqual(T.fit_threshold(np.array([0.1, 0.1]), np.array([1, 0]), 2, 0.0), float("-inf"))  # a tie that contains an edge cannot be pruned at zero budget

    def test_evaluate_and_gate(self):
        t = np.array([0.1, 0.2, 0.3, 0.4])
        y = np.array([0, 1, 0, 0])
        e = T.evaluate(t, y, 0.3, total_edges=1, total_non_edges=10, t0_non_edges=5)
        self.assertEqual((e["edges_lost"], e["edge_loss"]), (1, 1.0))
        self.assertAlmostEqual(e["pruned_share"], 0.7)
        self.assertAlmostEqual(e["gain"], 0.2)
        good = {"0.01": {"pooled": {"edge_loss": 0.019, "gain": 0.06}, "held": {"edge_loss": 0.03}}, "0.02": {"pooled": {"edge_loss": 0.04, "gain": 0.05}, "held": {"edge_loss": 0.05}}}
        self.assertTrue(T.gate(good)["advances"])
        for eps, part, key, value in (("0.01", "pooled", "edge_loss", 0.021), ("0.02", "held", "edge_loss", 0.0501), ("0.02", "pooled", "gain", 0.049)):
            bad = {k: {p: dict(v) for p, v in d.items()} for k, d in good.items()}
            bad[eps][part][key] = value
            self.assertFalse(T.gate(bad)["advances"], (eps, part, key))


if __name__ == "__main__":
    unittest.main()
