"""Census logic on synthetic data with known answers."""
from __future__ import annotations

import unittest

import numpy as np

from nli import census


def brute_best_recall(score, y, target=0.5, min_rows=50):
    best = None
    for t in np.unique(score):
        m = score >= t
        n = int(m.sum())
        if n >= min_rows and (m & y).sum() / n >= target:
            r = (m & y).sum() / y.sum()
            best = r if best is None else max(best, r)
    return best


def world(seed=0, n=6000):
    """A ranks positives above most negatives but a block of high-A negatives (the false positives) has low B; B is otherwise noise."""
    rng = np.random.default_rng(seed)
    y = rng.random(n) < 0.06
    a = np.where(y, rng.normal(600_000, 150_000, n), rng.normal(360_000, 150_000, n)).clip(0, 999_999).astype(int)
    b = rng.integers(0, 1_000_000, n)
    fp_block = (~y) & (a > 450_000)
    b[fp_block] = rng.integers(0, 200_000, int(fp_block.sum()))   # NLI says "not unknown" on the confusable negatives
    b[y] = rng.integers(500_000, 1_000_000, int(y.sum()))         # ...and "unknown" on the real ASK rows
    return a, b, y


class UsableSetTests(unittest.TestCase):
    def test_matches_brute_force(self):
        rng = np.random.default_rng(1)
        for _ in range(5):
            y = rng.random(2000) < 0.07
            score = np.where(y, rng.normal(0.6, 0.2, 2000), rng.normal(0.35, 0.2, 2000)) * 1_000_000
            score = score.astype(int)
            found = census.usable_set(score, y)
            expect = brute_best_recall(score, y)
            if expect is None:
                self.assertIsNone(found)
            else:
                self.assertAlmostEqual((found["mask"] & y).sum() / y.sum(), expect)

    def test_unreachable_target_and_ties(self):
        y = np.zeros(500, dtype=bool)
        y[:20] = True
        self.assertIsNone(census.usable_set(np.full(500, 5), y))            # all tied: one set, precision 0.04
        self.assertIsNone(census.usable_set(np.arange(500), np.zeros(500, dtype=bool)))
        s = census.stats(np.arange(500) >= 490, np.arange(500) >= 490)
        self.assertEqual((s["rows"], s["true_positives"], s["precision"], s["recall"]), (10, 10, 1.0, 1.0))

    def test_size_matched_takes_the_top_k_deterministically(self):
        score = np.array([5, 9, 1, 9, 3])
        self.assertEqual(census.size_matched(score, 2).tolist(), [False, True, False, True, False])


class ConjunctionTests(unittest.TestCase):
    def test_a_real_veto_shows_headroom_above_the_noise_band(self):
        a, b, y = world()
        found = census.best_conjunction(a, b, y)
        self.assertIsNotNone(found["baseline_recall"])
        self.assertGreater(found["headroom"], 0.25)
        self.assertGreater(found["b"], 0)
        noise = census.noise_band(a, b, y, permutations=40)
        self.assertGreater(found["headroom"], noise["p95"])

    def test_noise_scores_show_no_headroom_beyond_the_noise_band(self):
        a, _, y = world(seed=2)
        rng = np.random.default_rng(9)
        b = rng.integers(0, 1_000_000, len(a))
        found = census.best_conjunction(a, b, y)
        noise = census.noise_band(a, b, y, permutations=40)
        self.assertLessEqual(found["headroom"], noise["p95"] + 0.10)  # a random score is one draw from the noise band

    def test_noise_band_is_reproducible(self):
        a, b, y = world()
        self.assertEqual(census.noise_band(a, b, y, permutations=10), census.noise_band(a, b, y, permutations=10))

    def test_perfect_veto_ceiling(self):
        a, b, y = world()
        allowed = ~((~y) & (a > 450_000))  # veto exactly the confusable negatives
        ceiling = census.veto_ceiling(a, allowed, y)
        self.assertGreater(ceiling["headroom"], 0.25)
        self.assertGreaterEqual(ceiling["precision"], 0.5)
        none_vetoed = census.veto_ceiling(a, np.ones(len(a), dtype=bool), y)
        self.assertAlmostEqual(none_vetoed["headroom"], 0.0)


class UnionAndLiftTests(unittest.TestCase):
    def test_union_view_accounting(self):
        a, b, y = world()
        view = census.union_view(a, b, y)
        self.assertTrue(view["available"])
        A, N, inter, union = view["A"], view["N"], view["intersection"], view["union"]
        self.assertEqual(union["rows"], A["rows"] + N["rows"] - inter["rows"])
        self.assertEqual(union["true_positives"], A["true_positives"] + N["true_positives"] - inter["true_positives"])
        self.assertEqual(view["misses_recovered_by_n"] + (A["true_positives"] + view["ask_misses"] - view["misses_recovered_by_n"] - view["ask_misses"]) * 0, view["misses_recovered_by_n"])
        self.assertEqual(view["a_false_positives"], A["false_positives"])
        self.assertEqual(view["false_positives_removed_if_n_required"] + view["false_positives_shared_with_n"], view["a_false_positives"])
        self.assertLessEqual(view["oracle_union_headroom"] + 1e-12, N["true_positives"] / A["true_positives"] + 1)
        self.assertGreaterEqual(view["oracle_union_headroom"], view["realizable_union_headroom"] - 1e-12)

    def test_lift_table_shape_and_totals(self):
        a, b, y = world()
        t = census.lift_table(a, b, y)
        self.assertEqual((len(t["rows"]), len(t["rows"][0])), (10, 3))
        self.assertEqual(sum(sum(r) for r in t["rows"]), len(a))

    def test_the_decision_rule(self):
        union_dead = {"available": True, "union": {"precision": 0.3}, "realizable_union_headroom": 0.5}
        base = {"union": union_dead, "conjunction": {"headroom": 0.40}, "noise": {"p95": 0.10}, "ceiling": {"headroom": 0.60}}
        self.assertTrue(census.decide(base)["V_veto_earned"])
        self.assertFalse(census.decide(base)["U_union_earned"])
        self.assertTrue(census.decide(base)["route_earned"])
        low_ceiling = base | {"ceiling": {"headroom": 0.20}}
        self.assertFalse(census.decide(low_ceiling)["route_earned"])          # a head cannot beat its perfect-NLI ceiling
        inside_noise = base | {"noise": {"p95": 0.45}}
        self.assertFalse(census.decide(inside_noise)["route_earned"])
        union_ok = base | {"conjunction": {"headroom": 0.05}, "union": {"available": True, "union": {"precision": 0.55}, "realizable_union_headroom": 0.30}}
        self.assertTrue(census.decide(union_ok)["U_union_earned"])
        self.assertFalse(census.decide(base | {"conjunction": {"headroom": None}, "union": {"available": False}})["route_earned"])


if __name__ == "__main__":
    unittest.main()
