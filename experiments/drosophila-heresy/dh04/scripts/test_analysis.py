import unittest

import numpy as np

from analyze import classify, seed_tau_matrix, summarize, validate


class AnalysisTests(unittest.TestCase):
    def test_taus_are_averaged_inside_seed(self):
        config = {"seeds": [1, 2], "taus": [4.0, 16.0]}
        lookup = {}
        for seed in config["seeds"]:
            for tau in config["taus"]:
                sign = 1 if tau == 4 else -1
                for condition, base in [
                    ("eligibility_retained", 0.6),
                    ("eligibility_suppressed", 0.5),
                ]:
                    lookup["R", tau, seed, "E", condition] = {
                        "result": {
                            "paired_final_reversal_probe": base + seed * 0.1 * sign
                        }
                    }
        matrix = seed_tau_matrix(
            lookup,
            config,
            "R",
            ["paired_final_reversal_probe"],
            "eligibility_retained",
            "eligibility_suppressed",
        )
        indices = np.tile(np.arange(2), (20, 1))
        result = summarize(matrix, indices, config["taus"])
        self.assertEqual(result["n_seed_bundles"], 2)
        self.assertAlmostEqual(result["mean"], 0.1)

    def test_partial_erasure_rule_requires_every_component(self):
        positive = {"ci95": [0.01, 0.02]}
        negative = {"ci95": [-0.2, -0.1]}
        retained = {"ci95": [0.2, 0.8]}
        margin = {"ci95": [0.001, 0.003]}
        self.assertEqual(
            classify(positive, negative, retained, margin),
            "PARTIAL_ERASURE_SUPPORTED_IN_MODEL",
        )
        ambiguous = {"ci95": [-0.1, 0.1]}
        self.assertEqual(
            classify(positive, ambiguous, retained, margin), "MECHANISM_UNRESOLVED"
        )

    def test_reversed_acquisition_rule(self):
        positive = {"ci95": [0.01, 0.02]}
        negative_coordinate = {"ci95": [-0.4, -0.2]}
        negative_margin = {"ci95": [-0.03, -0.01]}
        self.assertEqual(
            classify(positive, {"ci95": [-0.2, -0.1]}, negative_coordinate, negative_margin),
            "REVERSED_ACQUISITION_SUPPORTED_IN_MODEL",
        )

    def test_missing_and_duplicate_cells_fail(self):
        config = {"sides": ["R"], "taus": [4.0], "seeds": [1], "arms": ["E", "Z"]}
        with self.assertRaises(AssertionError):
            validate([], [], config)
        row = {"side": "R", "tau": 4.0, "seed": 1, "arm": "E", "condition": "quiet"}
        with self.assertRaises(AssertionError):
            validate([row, row], [], config)


if __name__ == "__main__":
    unittest.main()
