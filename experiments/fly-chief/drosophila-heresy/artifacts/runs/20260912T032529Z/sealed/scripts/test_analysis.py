"""Test seed-level grouping and analysis against known synthetic contrasts."""
import unittest
from analyze import paired_effect


class AnalysisTests(unittest.TestCase):
    def test_settings_are_averaged_inside_seed_bundles(self):
        config = {'seeds': [1, 2, 3], 'settings': [{'name': 'x'}, {'name': 'y'}]}
        rows = []
        for seed in config['seeds']:
            for setting in ['x', 'y']:
                effect = 0.1 * seed if setting == 'x' else -0.1 * seed
                for arm, value in [('A', 0.5 + effect), ('B', 0.5)]:
                    rows.append(dict(seed=seed, setting=setting, arm=arm, suite='primary', outcome={'accuracy': value}))
        result = paired_effect(rows, 'primary', config)
        self.assertAlmostEqual(result['mean'], 0.0)
        self.assertEqual(result['n_seed_bundles'], 3)
        self.assertTrue(all(abs(v) < 1e-15 for v in result['ci95']))

    def test_missing_arm_fails_instead_of_dropping_seed(self):
        with self.assertRaises(KeyError):
            paired_effect([], 'primary', {'seeds': [1], 'settings': [{'name': 'x'}]})


if __name__ == '__main__':
    unittest.main()
