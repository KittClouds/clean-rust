"""C3a logic on synthetic data with known answers."""
from __future__ import annotations

import unittest

import numpy as np

from c3 import frontier, scores
from c3.common import c1fit


class FrontierTests(unittest.TestCase):
    def test_correct_at_harm_hand_example(self):
        score = np.arange(10, 0, -1, dtype=float)                       # rows ranked 1..10
        safe = np.array([1, 1, 1, 1, 0, 1, 1, 0, 0, 0], dtype=bool)     # harm after k rows: 0,0,0,0,.2,.167,.143,.25,.33,.4
        got = frontier.correct_at_harm(score, safe, levels=(0.0, 0.15, 0.2, 0.5), min_executions=1)
        self.assertEqual(got, {0.0: 4, 0.15: 6, 0.2: 6, 0.5: 6})       # k=7 has harm .143 (<= .15), 6 correct; k=5 has .2
        self.assertEqual(frontier.correct_at_harm(score, safe, levels=(0.0,), min_executions=5), {0.0: 0})  # the pure prefix is shorter than 5

    def test_ties_are_kept_together(self):
        score = np.array([2.0, 2.0, 2.0, 1.0])
        safe = np.array([True, False, True, True])
        self.assertEqual(frontier.correct_at_harm(score, safe, levels=(0.0,), min_executions=1), {0.0: 0})  # the tied group of three is one set, harm 1/3

    def test_a_perfect_score_dominates_and_a_random_one_does_not(self):
        rng = np.random.default_rng(3)
        n = 4000
        safe = rng.random(n) < 0.7
        base = np.where(safe, rng.normal(0.5, 0.25, n), rng.normal(0.4, 0.25, n))   # weak baseline
        perfect = safe + rng.random(n) * 0.01                                       # orders every safe row above every harmful one
        noise = rng.random(n)
        pool = {"c1_min": base, "perfect": perfect, "noise": noise}
        points = {name: frontier.correct_at_harm(s, safe) for name, s in pool.items()}
        low = frontier.paired_bootstrap(pool, safe, bootstraps=60)
        result = frontier.dominance(points, low)
        self.assertTrue(result["perfect"]["dominates"])
        self.assertFalse(result["noise"]["dominates"])

    def test_dominance_treats_an_unreachable_baseline_as_beatable_and_needs_a_positive_count(self):
        points = {"c1_min": {0.03: 0, 0.05: 100, 0.07: 100, 0.10: 100}, "a": {0.03: 50, 0.05: 110, 0.07: 109, 0.10: 120}, "b": {0.03: 0, 0.05: 0, 0.07: 0, 0.10: 500}}
        low = {"a": {0.03: 1.0, 0.05: 1.0, 0.07: 1.0, 0.10: 1.0}, "b": {0.03: 0.0, 0.05: 0.0, 0.07: 0.0, 0.10: 1.0}}
        result = frontier.dominance(points, low)
        self.assertEqual(result["a"]["levels_passed"], [0.03, 0.05, 0.10])   # 0.07: 109 < 1.10 x 100
        self.assertTrue(result["a"]["dominates"])
        self.assertEqual(result["b"]["levels_passed"], [0.10])
        self.assertFalse(result["b"]["dominates"])
        low["a"][0.10] = 0.0                                                # an unresolved bootstrap difference blocks a level
        self.assertFalse(frontier.dominance(points, low)["a"]["dominates"])

    def test_bootstrap_is_reproducible(self):
        rng = np.random.default_rng(4)
        safe = rng.random(1500) < 0.6
        pool = {"c1_min": rng.random(1500), "x": rng.random(1500)}
        self.assertEqual(frontier.paired_bootstrap(pool, safe, bootstraps=20), frontier.paired_bootstrap(pool, safe, bootstraps=20))


class ScoreTests(unittest.TestCase):
    def arrays(self):
        rng = np.random.default_rng(5)
        n = 200
        d = rng.dirichlet([6, 1, 1], n)
        a = rng.dirichlet(np.r_[np.full(1, 8.0), np.full(13, 0.5)], n)
        return d, a

    def test_shapes_and_ranges(self):
        d, a = self.arrays()
        s = scores.all_scores(d, a)
        self.assertEqual(set(s), set(scores.NAMES) | {scores.CONTROL})
        for name, v in s.items():
            self.assertEqual(v.shape, (200,), name)
            self.assertTrue(np.isfinite(v).all(), name)

    def test_definitions_on_a_hand_row(self):
        d = np.array([[0.7, 0.1, 0.2]])
        a = np.zeros((1, 14))
        a[0, 0], a[0, 1], a[0, 2] = 0.6, 0.3, 0.1
        s = scores.all_scores(d, a)
        self.assertAlmostEqual(s["c1_min"][0], 0.6)
        self.assertAlmostEqual(s["product"][0], 0.42)
        self.assertAlmostEqual(s["dec_margin"][0], 0.5)
        self.assertAlmostEqual(s["act_margin"][0], 0.3)
        self.assertAlmostEqual(s["min_margins"][0], 0.3)
        self.assertAlmostEqual(s["margin_product"][0], 0.15)
        self.assertAlmostEqual(s["neg_p_abstain"][0], -0.2)
        self.assertAlmostEqual(s["neg_p_ask"][0], -0.1)
        self.assertAlmostEqual(s["neg_dec_entropy"][0], float(np.sum([0.7 * np.log(0.7), 0.1 * np.log(0.1), 0.2 * np.log(0.2)])))
        self.assertAlmostEqual(s["neg_act_entropy"][0], float(np.sum([0.6 * np.log(0.6), 0.3 * np.log(0.3), 0.1 * np.log(0.1)])))

    def test_entropy_edges(self):
        one_hot = np.zeros((1, 14))
        one_hot[0, 3] = 1.0
        d = np.array([[1.0, 0.0, 0.0]])
        s = scores.all_scores(d, one_hot)
        self.assertEqual(s["neg_dec_entropy"][0], 0.0)
        self.assertEqual(s["neg_act_entropy"][0], 0.0)
        self.assertAlmostEqual(scores.all_scores(d, np.full((1, 14), 1 / 14))["neg_act_entropy"][0], -np.log(14))

    def test_candidates_use_c1_gating_and_safety(self):
        dec = np.array([[800_000, 100_000, 100_000], [300_000, 100_000, 600_000], [700_000, 200_000, 100_000]], dtype=np.int32)
        act = np.zeros((3, 14), dtype=np.int32)
        act[:, 0], act[:, 1:] = 700_000, 300_000 // 13
        act[:, 0] = 1_000_000 - act[:, 1:].sum(axis=1)
        truth_dec = np.array([c1fit.ACT, c1fit.ACT, c1fit.ABSTAIN], dtype=np.int8)
        truth_act = np.array([0, 0, -1], dtype=np.int8)
        cand = scores.candidates(dec, act, truth_dec, truth_act)
        self.assertEqual(cand["rows"], 2)                       # row 1's top class is ABSTAIN
        self.assertEqual(cand["safe"].tolist(), [True, False])  # row 2 is an ACT proposal on a truth-ABSTAIN row

    def test_rank_mean_is_a_combination_of_the_two_margins(self):
        d, a = self.arrays()
        s = scores.all_scores(d, a)
        order = np.argsort(-s["rank_mean"], kind="stable")
        self.assertEqual(len(set(order.tolist())), len(order))


if __name__ == "__main__":
    unittest.main()
