from __future__ import annotations

import unittest

import pandas as pd

from analysis import classify_count, continuous_table, coverage_table, shannon


class AnalysisTests(unittest.TestCase):
    def test_entropy_balanced_exceeds_concentrated(self):
        balanced = pd.Series(["A", "B", "A", "B"])
        concentrated = pd.Series(["A", "A", "A", "B"])
        self.assertGreater(shannon(balanced)[0], shannon(concentrated)[0])
        self.assertEqual(shannon(balanced)[1], 1.0)

    def test_coverage_retains_count_share_and_censoring(self):
        frame = pd.DataFrame({"region": ["CORE", "CORE", "ABOVE"], "status": ["RESOLVED", "RIGHT_CENSORED", "RESOLVED"]})
        table = coverage_table(frame, "episode", ["region"], frame.status.ne("RESOLVED"))
        core = table.loc[table.value == "CORE"].iloc[0]
        self.assertEqual(core["count"], 2)
        self.assertAlmostEqual(core["share"], 2 / 3)
        self.assertEqual(core["censored_count"], 1)
        self.assertEqual(core["censoring_rate"], 0.5)

    def test_continuous_missingness_and_quantiles(self):
        frame = pd.DataFrame({"x": [1.0, 2.0, None, 4.0]})
        table = continuous_table(frame, "attempt", ["x"], pd.Series([False, False, True, False]))
        row = table.iloc[0]
        self.assertEqual(row["count"], 3)
        self.assertEqual(row["missing_count"], 1)
        self.assertEqual(row["median"], 2.0)

    def test_readiness_thresholds(self):
        self.assertEqual(classify_count(0), "EMPTY")
        self.assertEqual(classify_count(6), "INSUFFICIENT")
        self.assertEqual(classify_count(20), "PRELIMINARY_ONLY")
        self.assertEqual(classify_count(30), "READY_DESCRIPTIVE")

    def test_right_censored_rows_remain_in_denominator(self):
        frame = pd.DataFrame({"resolution": ["REJECT", "REJECT", "TIMEOUT"],
                              "status": ["RIGHT_CENSORED", "RESOLVED", "RESOLVED"]})
        table = coverage_table(frame, "episode", ["resolution"], frame.status.ne("RESOLVED"))
        reject = table.loc[table.value == "REJECT"].iloc[0]
        self.assertEqual(reject["count"], 2)
        self.assertEqual(reject["censored_count"], 1)
        self.assertEqual(reject["censoring_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
