import unittest

import numpy as np

from analyze import summarize


class AnalysisTests(unittest.TestCase):
    def test_seed_bundle_averages_eligibility_settings(self):
        matrix = np.asarray([[0.1, 0.3], [0.2, 0.4]])
        indices = np.tile(np.arange(2), (20, 1))
        result = summarize(matrix, indices, [4.0, 16.0])
        self.assertAlmostEqual(result["mean"], 0.25)
        self.assertEqual(result["n_seed_bundles"], 2)

    def test_bootstrap_is_paired_over_seed_bundles(self):
        matrix = np.asarray([[0.1, -0.1], [0.2, -0.2]])
        indices = np.tile(np.arange(2), (20, 1))
        result = summarize(matrix, indices, [4.0, 16.0])
        self.assertAlmostEqual(result["mean"], 0.0)
        self.assertTrue(all(abs(value) < 1e-15 for value in result["ci95"]))


if __name__ == "__main__":
    unittest.main()
