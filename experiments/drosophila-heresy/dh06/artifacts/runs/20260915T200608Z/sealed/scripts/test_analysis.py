import unittest

import numpy as np

from analyze import factorial_matrix, summarize


class AnalysisTests(unittest.TestCase):
    def test_seed_bundle_averages_declared_taus(self):
        matrix = np.asarray([[0.1, 0.3], [0.2, 0.4]])
        indices = np.tile(np.arange(2), (20, 1))
        result = summarize(matrix, indices, [4.0, 16.0])
        self.assertAlmostEqual(result["mean"], 0.25)
        self.assertEqual(result["n_seed_bundles"], 2)

    def test_factorial_effects_use_paired_four_cell_contrast(self):
        class Lookup(dict):
            pass

        config = {"taus": [4.0, 16.0], "seeds": [1, 2], "primary_arm": "E"}
        lookup = Lookup()
        values = {"neither": 1.0, "parallel_only": 3.0, "perpendicular_only": 5.0, "both": 9.0}
        for condition, value in values.items():
            for seed in config["seeds"]:
                for tau in config["taus"]:
                    lookup["R", tau, seed, "E", condition] = {"result": {"trajectory": [{"x": value}]}}
        result = factorial_matrix(lookup, config, "R", "x", checkpoint=0)
        self.assertTrue(np.all(result["parallel_effect"] == 3.0))
        self.assertTrue(np.all(result["perpendicular_effect"] == 5.0))
        self.assertTrue(np.all(result["interaction"] == 2.0))

    def test_primary_interval_uses_familywise_quantiles(self):
        matrix = np.asarray([[0.0, 0.0], [1.0, 1.0]])
        indices = np.asarray([[0, 0], [1, 1]])
        result = summarize(matrix, indices, [4.0, 16.0], "ci97_5")
        self.assertIn("ci97_5", result)
        self.assertNotIn("ci95", result)


if __name__ == "__main__":
    unittest.main()
