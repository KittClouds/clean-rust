"""C2a census logic on tiny hand-built cases (no C1 evidence needed)."""
from __future__ import annotations

import unittest

import numpy as np

from c2 import census
from c2.common import ACTIONS, fit

MOVE, ACTIVATE, NOOP = ACTIONS.index("MOVE"), ACTIONS.index("ACTIVATE"), ACTIONS.index("NOOP")


def arrays(rows):
    """rows: list of (decision class, decision ppm, action class, action ppm) -> integer ppm arrays shaped like the real ones."""
    dec = np.zeros((len(rows), 3), dtype=np.int32)
    act = np.zeros((len(rows), 14), dtype=np.int32)
    for i, (dc, dp, ac, ap) in enumerate(rows):
        rest = (1_000_000 - dp) // 2
        dec[i, :] = rest
        dec[i, dc] = 1_000_000 - 2 * rest
        act[i, :] = (1_000_000 - ap) // 13
        act[i, ac] = 1_000_000 - 13 * ((1_000_000 - ap) // 13)
    return {"dec": dec, "act": act}


THRESH = {"abstain": 600_000, "ask": None, "act": 800_000}
TRUTH_DEC = np.array([fit.ACT, fit.ACT, fit.ACT, fit.ABSTAIN, fit.ACT], dtype=np.int8)
TRUTH_ACT = np.array([MOVE, ACTIVATE, NOOP, -1, MOVE], dtype=np.int8)
A = arrays([(fit.ACT, 900_000, MOVE, 900_000),      # row0: A qualifies, correct
            (fit.ACT, 900_000, NOOP, 900_000),      # row1: A qualifies, wrong action -> harmful
            (fit.ACT, 500_000, NOOP, 900_000),      # row2: A does not qualify (low decision confidence)
            (fit.ACT, 900_000, MOVE, 900_000),      # row3: A qualifies on an ABSTAIN row -> harmful
            (fit.ABSTAIN, 900_000, MOVE, 900_000)])  # row4: A says abstain
B = arrays([(fit.ACT, 900_000, MOVE, 900_000),      # row0: B correct too
            (fit.ACT, 900_000, ACTIVATE, 900_000),  # row1: B correct where A was harmful
            (fit.ACT, 900_000, NOOP, 900_000),      # row2: B correct where A did not qualify
            (fit.ABSTAIN, 900_000, MOVE, 900_000),  # row3: B abstains (would veto)
            (fit.ACT, 900_000, MOVE, 900_000)])     # row4: B correct where A abstained


class SurfaceSetTests(unittest.TestCase):
    def test_sets(self):
        s = census.surface_sets(A, THRESH, TRUTH_DEC, TRUTH_ACT)
        self.assertEqual(s["Q"].tolist(), [True, True, False, True, False])
        self.assertEqual(s["C"].tolist(), [True, False, False, False, False])
        self.assertEqual(s["Hm"].tolist(), [False, True, False, True, False])
        self.assertEqual(s["raw_act"].tolist(), [True, True, True, True, False])
        self.assertEqual(s["raw_correct"].tolist(), [True, False, True, False, False])  # row2: raw ACT/NOOP is right even though it does not qualify

    def test_a_surface_without_an_act_rule_never_qualifies(self):
        s = census.surface_sets(A, {"abstain": None, "ask": None, "act": None}, TRUTH_DEC, TRUTH_ACT)
        self.assertFalse(s["Q"].any())
        self.assertFalse(s["veto"].any())


class PairAndGroupTests(unittest.TestCase):
    def setUp(self):
        self.a = census.surface_sets(A, THRESH, TRUTH_DEC, TRUTH_ACT)
        self.b = census.surface_sets(B, THRESH, TRUTH_DEC, TRUTH_ACT)

    def test_pair_counts(self):
        q = census.pair(self.a, self.b)["qualified"]
        self.assertEqual((q["both_qualify"], q["both_same_action"], q["both_correct"], q["both_harmful"]), (2, 1, 1, 0))
        self.assertEqual((q["correct_only_A"], q["correct_only_B"]), (0, 3))  # B alone finds rows 1, 2 and 4
        self.assertEqual((q["harmful_only_A"], q["harmful_only_B"]), (2, 0))
        self.assertEqual(q["union_correct"], 4)
        self.assertAlmostEqual(q["jaccard_correct"], 1 / 4)
        raw = census.pair(self.a, self.b)["raw"]
        self.assertEqual(raw["A_act_B_abstain"], 1)  # row3

    def test_group_headroom_and_veto(self):
        sets = {"middle_plus_final": self.a, "final_plus_mean": self.b}
        g = census.group(sets, TRUTH_DEC, np.array(["S0", "S0", "S1", "S1", "S1"]))
        self.assertEqual((g["primary_correct"], g["union_correct"], g["intersection_correct"]), (1, 4, 1))
        self.assertAlmostEqual(g["oracle_headroom"], 3.0)
        self.assertEqual(g["extra_correct_not_found_by_primary"], 3)
        self.assertEqual(g["rows_with_a_harmful_qualifier"], 2)
        self.assertAlmostEqual(g["pessimistic_union_harm_rate"], 2 / 5)
        veto = g["veto_census"]["final_plus_mean"]
        self.assertEqual((veto["vetoes_correct"], veto["vetoes_harmful"]), (0, 1))  # B's abstain on row3 blocks A's harmful act, costs nothing
        self.assertEqual(g["per_family"]["S0"]["headroom"], 1.0)   # rows 0,1: primary finds 1, union finds 2
        self.assertEqual(g["per_family"]["S1"]["primary_correct"], 0)
        self.assertIsNone(g["per_family"]["S1"]["headroom"])


class ExploratoryTests(unittest.TestCase):
    def cal(self):
        thr = {"a05": {"thresholds_ppm": THRESH}}
        return {"surfaces": {"middle_plus_final": A, "final_plus_mean": B, "layer_m4_final": B, "full_mean": B}, "truth_decision": TRUTH_DEC, "truth_action": TRUTH_ACT,
                "family": np.array(["S0"] * 5), "thresholds": {s: thr for s in ("middle_plus_final", "final_plus_mean", "layer_m4_final", "full_mean")}}

    def test_anatomy_counts_shared_errors(self):
        out = census.harmful_anatomy(self.cal(), "a05")
        self.assertEqual(out["primary_harmful"], 2)  # rows 1 and 3
        self.assertEqual(out["truth_of_those_rows"], {"ACT": 1, "ASK": 0, "ABSTAIN": 1})
        other = out["others"]["final_plus_mean"]
        self.assertEqual(other["says"], {"ACT": 1, "ASK": 0, "ABSTAIN": 1})  # B is right on row1 (ACT is right there) and abstains on row3
        self.assertEqual(other["also_qualifies_harmfully"], 0)

    def test_frontier_coverage_never_shrinks_as_alpha_loosens(self):
        rng = np.random.default_rng(5)
        n = 3000
        conf = rng.integers(400_000, 1_000_000, n)
        right = rng.random(n) < (conf / 1_000_000) ** 4
        dec = np.zeros((n, 3), dtype=np.int32)
        dec[:, 0], dec[:, 1], dec[:, 2] = conf, (1_000_000 - conf) // 2, 1_000_000 - conf - (1_000_000 - conf) // 2
        act = np.zeros((n, 14), dtype=np.int32)
        act[:, 0], act[:, 1] = conf, 1_000_000 - conf
        truth_action = np.where(right, 0, 1).astype(np.int8)
        cal = {"surfaces": {"middle_plus_final": {"dec": dec, "act": act}}, "truth_decision": np.zeros(n, dtype=np.int8), "truth_action": truth_action}
        rows = census.single_surface_frontier(cal, (0.02, 0.05, 0.1, 0.2))
        shares = [r["correct_act_share_of_true_act"] for r in rows if r["t_act_ppm"] is not None]
        self.assertEqual(shares, sorted(shares))


if __name__ == "__main__":
    unittest.main()
