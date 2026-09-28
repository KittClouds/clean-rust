import unittest

import numpy as np

from analyze import effect_vectors, summarize_effect, validate


class AnalysisTests(unittest.TestCase):
    def test_taus_are_averaged_inside_seed_for_factorial_effects(self):
        config = {
            "seeds": [1, 2, 3],
            "taus": [4.0, 16.0],
        }
        lookup = {}
        for seed in config["seeds"]:
            for tau in config["taus"]:
                sign = 1 if tau == 4 else -1
                values = {
                    "retain_both": 0.5 + seed * 0.1 * sign,
                    "suppress_eligibility": 0.5,
                    "restore_state": 0.5 + seed * 0.1 * sign,
                    "suppress_both": 0.5,
                }
                for condition, value in values.items():
                    lookup["R", tau, seed, "E", condition] = {
                        "result": {"outcome": {"probe_reversal": value}}
                    }
        vectors = effect_vectors(lookup, config, "R", "probe_reversal")
        indices = np.tile(np.arange(3), (100, 1))
        result = summarize_effect(
            vectors["eligibility"], indices, config["taus"], (0.95, 0.975)
        )
        self.assertEqual(result["n_seed_bundles"], 3)
        self.assertAlmostEqual(result["mean"], 0.0)
        self.assertTrue(all(abs(value) < 1e-15 for value in result["ci95"]))
        self.assertTrue(all(abs(value) < 1e-15 for value in result["ci97.5"]))

    def test_factorial_formula_has_declared_signs(self):
        config = {"seeds": [1], "taus": [4.0]}
        values = {
            "retain_both": 0.8,
            "suppress_eligibility": 0.6,
            "restore_state": 0.7,
            "suppress_both": 0.5,
        }
        lookup = {
            ("R", 4.0, 1, "E", condition): {
                "result": {"outcome": {"probe_reversal": value}}
            }
            for condition, value in values.items()
        }
        vectors = effect_vectors(lookup, config, "R", "probe_reversal")
        self.assertAlmostEqual(vectors["eligibility"][0, 0], 0.2)
        self.assertAlmostEqual(vectors["state"][0, 0], 0.1)
        self.assertAlmostEqual(vectors["interaction"][0, 0], 0.0)

    def test_missing_cell_is_not_silently_dropped(self):
        with self.assertRaises(AssertionError):
            validate([], {"sides": ["R"], "taus": [4.0], "seeds": [1], "arms": ["E", "Z"]})

    def test_duplicate_cell_is_rejected(self):
        row = {"side": "R", "tau": 4.0, "seed": 1, "arm": "E", "condition": "quiet"}
        with self.assertRaises(AssertionError):
            validate([row, row], {"sides": ["R"], "taus": [4.0], "seeds": [1], "arms": ["E", "Z"]})


if __name__ == "__main__":
    unittest.main()
