import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_r3_independent_replay_v01 as replay


class IndependentReplayTests(unittest.TestCase):
    @staticmethod
    def cell_values(anchor: float):
        return {(family, direction): {"anchor_new_old_logit_mean": anchor,
            "fact_minus_anchor_mean": 0.0}
            for family in replay.FAMILIES for direction in replay.DIRECTIONS}

    def test_median_order_interval_matches_contract_rank_rule(self):
        result = replay.median_interval([float(index) for index in range(192)])
        self.assertEqual((result["n"], result["lower_order"], result["upper_order"]), (192, 82, 111))
        self.assertGreaterEqual(result["nominal_coverage"], 0.95)

    def test_ratio_requires_both_positive_branch_separations_above_floor(self):
        one = {"S": 0.02, "cells": self.cell_values(0.0)}
        half = {"S": 0.018, "cells": self.cell_values(0.1)}
        result = replay.independent_contrast(one, half)
        self.assertTrue(result["ratio_eligible"])
        self.assertAlmostEqual(result["R"], math.log(0.9))
        half["S"] = 0.009
        result = replay.independent_contrast(one, half)
        self.assertFalse(result["ratio_eligible"])
        self.assertIsNone(result["R"])
        self.assertAlmostEqual(result["D"], -0.011)

    def test_exact_tcritical_and_tolerance_are_fixed(self):
        self.assertEqual(replay.T_CRIT_190, 1.97253)
        self.assertLessEqual(replay.TOL, 3e-6)


if __name__ == "__main__":
    unittest.main()
