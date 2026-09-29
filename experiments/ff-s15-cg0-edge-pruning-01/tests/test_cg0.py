"""C-G0 logic on synthetic data: the frontier is checked against brute force; universe rule and head equivalence on small hand cases."""
from __future__ import annotations

import itertools
import unittest

import numpy as np

from cg import common, frontier, head, universe


def brute(label, pair_type, score, rank, eps):
    """Best pruned non-edge share over every (k, threshold) with edge loss <= floor(eps * E)."""
    E, Nn = int(label.sum()), int((1 - label).sum())
    allowed = int(np.floor(eps * E + 1e-9))
    best0 = best01 = -1.0
    g = rank[pair_type]
    for k in range(int(rank.max()) + 2):
        for t in [-np.inf] + sorted(set(score.tolist())):
            pruned = (g < k) | ((g >= k) & (score <= t))
            lost = int((pruned & (label == 1)).sum())
            if lost <= allowed:
                share = int((pruned & (label == 0)).sum()) / Nn
                best01 = max(best01, share)
                if t == -np.inf:
                    best0 = max(best0, share)
    return best0, best01


def world(rng, n=400, groups=4):
    pair_type = rng.integers(0, groups, n).astype(np.uint8)
    rates = np.array([0.0, 0.05, 0.3, 0.6][:groups])
    label = (rng.random(n) < rates[pair_type]).astype(np.int64)
    score = rng.normal(0, 1, n) + 1.5 * label - 0.0 * pair_type   # T1 sees the label through noise
    return label, pair_type, score


class FrontierTests(unittest.TestCase):
    def rank(self, groups=4, size=8):
        rates = np.array([0.0, 0.05, 0.3, 0.6] + [1.0] * (size - 4))[:size]
        return frontier.t0_rank(np.full(size, 1000), (rates * 1000).astype(int))

    def test_matches_brute_force(self):
        rng = np.random.default_rng(1)
        rank = self.rank()
        for trial in range(6):
            label, pair_type, score = world(rng, n=int(rng.integers(60, 140)))
            if label.sum() < 5:
                continue
            for eps in (0.05, 0.1, 0.2):
                got = frontier.frontier(label, pair_type, score, rank, (eps,))[str(eps)]
                b0, b01 = brute(label, pair_type, score, rank, eps)
                self.assertAlmostEqual(got["T0"]["pruned_share"], b0, msg=(trial, eps))
                self.assertAlmostEqual(got["T0+T1"]["pruned_share"], b01, msg=(trial, eps))

    def test_t0_orders_by_ascending_train_rate_and_puts_unseen_last(self):
        rank = frontier.t0_rank([100, 100, 100, 0], [50, 0, 10, 0])
        self.assertEqual(rank.tolist(), [2, 0, 1, 3])

    def test_t1_never_hurts_and_a_rate_zero_group_is_free(self):
        rng = np.random.default_rng(2)
        label, pair_type, score = world(rng, n=3000)
        f = frontier.frontier(label, pair_type, score, self.rank(), (0.01, 0.02))
        for eps in ("0.01", "0.02"):
            self.assertGreaterEqual(f[eps]["T0+T1"]["pruned_share"], f[eps]["T0"]["pruned_share"] - 1e-12)
            self.assertGreaterEqual(f[eps]["T0+T1"]["pruned_share"], f[eps]["T1"]["pruned_share"] - 1e-12)
            self.assertLessEqual(f[eps]["T0"]["edge_loss"], float(eps) + 1e-9)
        self.assertGreater(f["0.01"]["T0"]["pruned_share"], 0.0)   # the rate-0 type pair is pruned at no edge loss

    def test_apply_params_reproduces_the_fitted_point(self):
        rng = np.random.default_rng(3)
        label, pair_type, score = world(rng, n=2000)
        rank = self.rank()
        f = frontier.frontier(label, pair_type, score, rank, (0.02,))["0.02"]["T0+T1"]
        got = frontier.apply_params(label, pair_type, score, rank, f["k"], f["threshold"])
        self.assertAlmostEqual(got["pruned_share"], f["pruned_share"])
        self.assertAlmostEqual(got["edge_loss"], f["edge_loss"])

    def test_informative_scores_clear_the_noise_band_and_random_ones_do_not(self):
        rng = np.random.default_rng(4)
        label, pair_type, score = world(rng, n=6000)
        rank = self.rank()
        real = frontier.frontier(label, pair_type, score, rank, (0.02,))["0.02"]["gain"]
        band = frontier.noise_band(label, pair_type, score, rank, (0.02,), permutations=20)["0.02"]
        self.assertGreater(real, band["p95"])
        junk = rng.normal(0, 1, len(label))
        junk_gain = frontier.frontier(label, pair_type, junk, rank, (0.02,))["0.02"]["gain"]
        self.assertLessEqual(junk_gain, frontier.noise_band(label, pair_type, junk, rank, (0.02,), permutations=20)["0.02"]["p95"] + 0.03)

    def test_noise_band_is_reproducible(self):
        rng = np.random.default_rng(5)
        label, pair_type, score = world(rng, n=800)
        rank = self.rank()
        self.assertEqual(frontier.noise_band(label, pair_type, score, rank, (0.02,), permutations=5), frontier.noise_band(label, pair_type, score, rank, (0.02,), permutations=5))

    def test_within_pair_type_auc(self):
        rng = np.random.default_rng(6)
        label, pair_type, score = world(rng, n=5000)
        out = frontier.within_pair_type_auc(label, pair_type, score, head.auc)
        self.assertGreater(out["weighted_mean"], 0.8)
        self.assertNotIn(0, out["per_type_pair"])   # the rate-0 group has no edges, so it has no within-group AUC


class UniverseAndHeadTests(unittest.TestCase):
    def test_world_pairs_follow_the_candidate_rule(self):
        world_ = {"entities": [{"id": "obj_0"}, {"id": "loc_0"}, {"id": "loc_1"}, {"id": "sw_0"}],
                  "initial_state": [{"pred": "AT", "args": ["obj_0", "loc_0"]}, {"pred": "CONNECTED", "args": ["loc_0", "loc_1"]}, {"pred": "STATE", "args": ["sw_0"]},
                                    {"pred": "AT", "args": ["obj_0", "obj_0"]}, {"pred": "NOPE", "args": ["obj_0", "loc_1"]}, {"pred": "AT", "args": ["obj_0", "ghost"]}]}
        mentions = {"obj_0": (10, True), "loc_0": (11, True), "loc_1": (12, True), "sw_0": (13, False)}   # sw_0 has no matched span, so it is not a typed node
        nodes, positives = universe.world_pairs(world_, mentions)
        self.assertEqual([n[0] for n in nodes], [10, 11, 12])
        self.assertEqual(positives, {(10, 11), (11, 12)})   # unary, self-loop, unknown-predicate and untyped-object facts are not edges

    def test_type_codes(self):
        self.assertEqual(common.identifier_type("obj_3"), "OBJECT")
        self.assertEqual(common.identifier_type("e_unknown"), "UNKNOWN")
        self.assertEqual(common.pair_name(common.pair_code(common.type_code("obj_0"), common.type_code("loc_2"))), "OBJECT->LOCATION")

    def test_cached_projection_equals_the_concatenated_layer(self):
        import torch

        torch.manual_seed(0)
        mlp = torch.nn.Sequential(torch.nn.Linear(8, 5), torch.nn.GELU(), torch.nn.Linear(5, 1)).double()
        a, b = torch.randn(7, 4).double(), torch.randn(7, 4).double()
        direct = mlp(torch.cat([a, b], 1)).squeeze(1)
        w1, b1 = mlp[0].weight, mlp[0].bias
        cached = (torch.nn.functional.gelu(a @ w1[:, :4].T + b @ w1[:, 4:].T + b1) @ mlp[2].weight.T + mlp[2].bias).squeeze(1)
        self.assertTrue(torch.allclose(direct, cached, atol=1e-12))

    def test_auc_matches_hand_values(self):
        self.assertAlmostEqual(head.auc(np.array([0.9, 0.8, 0.7, 0.6]), np.array([1, 0, 1, 0])), 0.75)
        self.assertAlmostEqual(head.auc(np.full(6, 0.5), np.array([1, 1, 0, 0, 0, 0])), 0.5)


if __name__ == "__main__":
    unittest.main()
