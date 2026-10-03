import unittest
from analyze import contrast, validate


class AnalysisTests(unittest.TestCase):
    def test_tau_variants_are_not_independent_seeds(self):
        config = dict(seeds=[1,2,3], taus=[4.0,16.0], primary_metric='probe_reversal', bootstrap_seed=22, bootstrap_resamples=1000)
        lookup = {}
        for seed in config['seeds']:
            for tau in config['taus']:
                for condition in ['quiet','distractor']:
                    value = 0.5
                    if condition == 'quiet':
                        value += seed*0.1*(1 if tau == 4 else -1)
                    lookup['R',tau,seed,'E',condition] = {'result': {'outcome': {'probe_reversal': value}}}
        result = contrast(lookup, config, 'R')
        self.assertEqual(result['n_seed_bundles'],3)
        self.assertAlmostEqual(result['mean'],0.0)
        self.assertTrue(all(abs(v)<1e-15 for v in result['ci95']))

    def test_missing_cell_is_not_silently_dropped(self):
        with self.assertRaises(AssertionError):
            validate([],dict(sides=['R'],taus=[4.0],seeds=[1],arms=['E','Z']))

    def test_duplicate_cell_is_rejected(self):
        row = dict(side='R',tau=4.0,seed=1,arm='E',condition='quiet')
        with self.assertRaises(AssertionError):
            validate([row,row],dict(sides=['R'],taus=[4.0],seeds=[1],arms=['E','Z']))


if __name__ == '__main__':
    unittest.main()
