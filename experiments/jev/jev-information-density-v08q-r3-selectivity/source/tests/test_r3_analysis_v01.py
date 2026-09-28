import math
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import analyze_r3_confirmatory_v01 as analysis


class R3AnalysisTests(unittest.TestCase):
    @staticmethod
    def cells(anchor, fact_minus_anchor):
        return {(family, direction): {
            "anchor_new_old_logit_mean": anchor,
            "fact_minus_anchor_mean": fact_minus_anchor,
        } for family in analysis.FAMILIES for direction in analysis.DIRECTIONS}

    def test_median_order_statistic_interval_is_symmetric_and_at_least_95_percent(self):
        values = list(range(1, 193))
        result = analysis.order_stat_median_interval(values)
        self.assertEqual(result["median"], 96.5)
        self.assertLessEqual(result["lower"], result["median"])
        self.assertGreaterEqual(result["upper"], result["median"])
        self.assertGreaterEqual(result["nominal_coverage"], 0.95)
        self.assertEqual(result["lower_order"] + result["upper_order"], 193)

    def test_proportional_ratio_is_conditional_but_additive_d_is_universal(self):
        one = {"S": 0.05, "cells": self.cells(0.0, 0.05)}
        half = {"S": 0.04, "cells": self.cells(0.1, 0.04)}
        values = analysis.branch_contrasts(one, half)
        self.assertAlmostEqual(values["D"], -0.01)
        self.assertTrue(values["ratio_eligible"])
        self.assertAlmostEqual(values["R"], math.log(0.8))
        half_low = {"S": 0.005, "cells": self.cells(0.1, 0.005)}
        values_low = analysis.branch_contrasts(one, half_low)
        self.assertAlmostEqual(values_low["D"], -0.045)
        self.assertFalse(values_low["ratio_eligible"])
        self.assertIsNone(values_low["R"])

    def test_hc3_slope_tracks_synthetic_linear_effect(self):
        x = [index / 10 for index in range(1, 25)]
        y = [0.3 - 0.2 * value + (0.01 if index % 2 else -0.01)
             for index, value in enumerate(x)]
        result = analysis.hc3_slope(x, y)
        self.assertAlmostEqual(result["beta"], -0.2, delta=0.002)
        self.assertGreater(result["standard_error_HC3"], 0)
        self.assertLess(result["lower_95"], result["upper_95"])
        self.assertAlmostEqual(analysis.student_t_quantile(0.975, 190), 1.97253, delta=0.0002)

    def test_family_direction_output_keys_are_json_safe_and_ordered(self):
        encoded = analysis.serializable_cells(self.cells(0.0, 0.1))
        self.assertEqual(list(encoded), [f"{family}|{direction}"
            for family in analysis.FAMILIES for direction in analysis.DIRECTIONS])
        self.assertIsInstance(json.dumps(encoded), str)


if __name__ == "__main__":
    unittest.main()
