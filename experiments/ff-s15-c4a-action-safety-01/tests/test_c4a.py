"""C4a logic: the per-action oracle DP is checked against brute force on small random cases; census pieces on synthetic data."""
from __future__ import annotations

import itertools
import unittest

import numpy as np

from c4 import census, oracle
from c4.common import ACTIONS, c1fit, correct_at_harm


def brute_force(groups, level, min_executions):
    """Every combination of one prefix per group; the best total correct with harm <= level and >= min_executions rows."""
    curves = [oracle.prefix_curve(s, sf) for s, sf in groups]
    best = 0
    for picks in itertools.product(*[range(len(c["harmful"])) for c in curves]):
        h = sum(int(c["harmful"][i]) for c, i in zip(curves, picks))
        c_ = sum(int(c["correct"][i]) for c, i in zip(curves, picks))
        if c_ > 0 and h <= level / (1 - level) * c_ + 1e-9 and h + c_ >= min_executions:
            best = max(best, c_)
    return best


def random_groups(rng, sizes, quality):
    groups = []
    for n, q in zip(sizes, quality):
        safe = rng.random(n) < 0.6
        score = np.round(np.where(safe, rng.normal(q, 0.2, n), rng.normal(q - 0.25, 0.2, n)), 2)  # rounded, so ties occur
        groups.append((score, safe))
    return groups


class OracleTests(unittest.TestCase):
    def test_matches_brute_force_on_small_cases(self):
        rng = np.random.default_rng(11)
        for trial in range(12):
            groups = random_groups(rng, [int(x) for x in rng.integers(6, 14, 3)], rng.uniform(0.3, 0.9, 3))
            total_safe = sum(int(sf.sum()) for _, sf in groups)
            for level in (0.10, 0.25, 0.40):
                curves = [oracle.prefix_curve(s, sf) for s, sf in groups]
                got = oracle.solve(curves, (level,), oracle.hcap_for(total_safe, level) + 5, min_executions=3)[level]["correct"]
                self.assertEqual(got, brute_force(groups, level, 3), (trial, level))

    def test_one_group_equals_the_global_frontier_rule(self):
        rng = np.random.default_rng(12)
        score = rng.random(2000)
        safe = rng.random(2000) < 0.6 + 0.3 * score
        levels = (0.03, 0.05, 0.10)
        got = oracle.solve([oracle.prefix_curve(score, safe)], levels, oracle.hcap_for(int(safe.sum()), 0.10))
        expect = correct_at_harm(score, safe, levels)
        for level in levels:
            self.assertEqual(got[level]["correct"], expect[level])

    def test_the_oracle_is_never_below_the_global_threshold(self):
        rng = np.random.default_rng(13)
        n = 3000
        action = rng.integers(0, 3, n)
        safe = rng.random(n) < 0.65
        score = np.where(safe, rng.normal(0.7, 0.2, n), rng.normal(0.45, 0.2, n))
        levels = (0.03, 0.05, 0.07, 0.10)
        real = census.oracle_at_levels(score, safe, action, [0, 1, 2])
        base = correct_at_harm(score, safe, levels)
        for level in levels:
            self.assertGreaterEqual(real[level]["correct"], base[level])

    def test_a_real_action_effect_shows_gain_above_the_noise_band_and_no_effect_does_not(self):
        rng = np.random.default_rng(14)
        n = 6000
        action = rng.integers(0, 3, n)
        # action 0 is intrinsically safe at any confidence, action 2 is intrinsically dangerous: the same score means different harm
        p_safe = np.array([0.97, 0.75, 0.30])[action]
        safe = rng.random(n) < p_safe
        score = np.clip(rng.normal(0.55, 0.12, n) + 0.25 * safe, 0, 1)   # confidence separates safe from harmful, so the global baseline is reachable at 5%
        cand = {"score": score, "safe": safe, "action": action, "dec_ppm": (score * 1e6).astype(int), "act_ppm": (score * 1e6).astype(int)}
        # eligibility needs real support; here every action has ~2000 rows
        out = census.analyze(cand, None, np.zeros(n, dtype=np.int8), np.zeros(n, dtype=np.int8), permutations=25)
        self.assertEqual(len(out["eligible_actions"]), 3)
        self.assertGreater(out["oracle_gain"]["0.05"], 0.10)
        self.assertGreater(out["oracle_gain"]["0.05"], out["noise_band"]["0.05"]["p95"])
        homogeneous = {"score": score, "safe": rng.random(n) < 0.8, "action": action, "dec_ppm": cand["dec_ppm"], "act_ppm": cand["act_ppm"]}
        flat = census.analyze(homogeneous, None, np.zeros(n, dtype=np.int8), np.zeros(n, dtype=np.int8), permutations=25)
        self.assertFalse(flat["gate_passed"])

    def test_gain_convention_and_sanitizing(self):
        self.assertEqual(census.gain(110, 100), 0.10000000000000009)
        self.assertEqual(census.gain(0, 0), 0.0)
        self.assertEqual(census.gain(5, 0), float("inf"))            # a baseline with no qualifying set is beaten by any positive count
        self.assertEqual(census.sanitize({"a": [float("inf"), 1.5], "b": {"c": float("inf")}}), {"a": ["inf", 1.5], "b": {"c": "inf"}})

    def test_noise_band_is_reproducible(self):
        rng = np.random.default_rng(15)
        n = 2500
        action = rng.integers(0, 3, n)
        safe = rng.random(n) < 0.7
        score = rng.random(n)
        cand = {"score": score, "safe": safe, "action": action, "dec_ppm": (score * 1e6).astype(int), "act_ppm": (score * 1e6).astype(int)}
        a = census.analyze(cand, None, np.zeros(n, dtype=np.int8), np.zeros(n, dtype=np.int8), permutations=10)
        b = census.analyze(cand, None, np.zeros(n, dtype=np.int8), np.zeros(n, dtype=np.int8), permutations=10)
        self.assertEqual(a["noise_band"], b["noise_band"])

    def test_tracked_solution_adds_up(self):
        rng = np.random.default_rng(16)
        groups = random_groups(rng, [400, 500, 300], [0.7, 0.55, 0.4])
        curves = [oracle.prefix_curve(s, sf) for s, sf in groups]
        got = oracle.solve(curves, (0.10,), oracle.hcap_for(sum(int(sf.sum()) for _, sf in groups), 0.10), track=True)[0.10]
        picks = got["per_action"]
        self.assertEqual(sum(p["correct"] for p in picks), got["correct"])
        self.assertEqual(sum(p["harmful"] for p in picks), got["harmful"])
        self.assertLessEqual(got["harmful"], 0.10 / 0.90 * got["correct"] + 1e-9)
        for (s, sf), p in zip(groups, picks):   # the reported threshold reproduces the reported counts
            chosen = s >= p["threshold"]
            self.assertEqual((int(chosen.sum()), int((chosen & sf).sum())), (p["executed"], p["correct"]))


class EligibilityAndCoherenceTests(unittest.TestCase):
    def test_eligibility_needs_both_candidates_and_safe_support(self):
        action = np.array([0] * 400 + [1] * 400 + [2] * 100)
        safe = np.array([True] * 200 + [False] * 200 + [True] * 50 + [False] * 350 + [True] * 100)
        self.assertEqual(census.eligible_actions(action, safe), [0])   # action 1 has 400 candidates but only 50 safe; action 2 has 100 candidates

    def test_coherence_counts_impossible_actions(self):
        move, request = ACTIONS.index("MOVE"), ACTIONS.index("REQUEST")
        cand = {"action": np.array([move, move, request, request]), "safe": np.array([True, False, False, False]),
                "dec_ppm": np.array([900_000, 900_000, 900_000, 100_000]), "act_ppm": np.array([900_000, 900_000, 900_000, 900_000])}
        out = census.coherence(cand, 800_000)
        self.assertEqual((out["impossible_action_candidates"], out["impossible_action_safe"]), (2, 0))
        self.assertEqual((out["c1_executed"], out["c1_harmful"], out["c1_harmful_impossible"]), (3, 2, 1))
        self.assertEqual(census.coherence(cand, None)["c1_executed"], 0)

    def test_top_k_harm_and_c1_executions_by_action(self):
        score = np.r_[np.linspace(1.0, 0.5, 60), np.linspace(1.0, 0.5, 60)]
        safe = np.r_[np.ones(30, dtype=bool), np.zeros(30, dtype=bool), np.zeros(60, dtype=bool)]   # action 0: 30 safe at the top; action 1: nothing safe
        action = np.r_[np.zeros(60, dtype=int), np.ones(60, dtype=int)]
        got = census.top_k_harm(score, safe, action, [0, 1], ks=(25, 50, 100))
        self.assertEqual(got[ACTIONS[0]], {"25": 0.0, "50": 0.4, "100": None})
        self.assertEqual(got[ACTIONS[1]]["25"], 1.0)
        cand = {"action": action[:6], "safe": np.array([True, True, False, False, False, False]), "dec_ppm": np.array([900_000] * 6), "act_ppm": np.array([900_000, 900_000, 900_000, 100_000, 900_000, 900_000])}
        ex = census.c1_executions_by_action(cand, 800_000)
        self.assertEqual(ex[ACTIONS[0]], {"executed": 5, "correct": 2, "harmful": 3})   # row 3 is below the threshold, rows 0-2 and 4-5 fire (action 0 for all six)
        self.assertEqual(census.c1_executions_by_action(cand, None), {})

    def test_global_threshold_hand_example(self):
        # 150 safe rows on top, then 50 harmful: harm after k rows is 0 for k <= 150 and (k - 150) / k after, so harm <= 10% allows k = 166 (16/166 = 9.6%; k = 167 is 10.2%)
        score = np.arange(200, 0, -1, dtype=float)
        safe = np.r_[np.ones(150, dtype=bool), np.zeros(50, dtype=bool)]
        self.assertEqual(census.global_threshold(score, safe, 0.10), score[165])
        self.assertEqual(census.global_threshold(score, safe, 0.0), score[149])
        self.assertIsNone(census.global_threshold(score[:80], safe[:80], 0.10))   # fewer than 100 executions can never qualify


if __name__ == "__main__":
    unittest.main()
