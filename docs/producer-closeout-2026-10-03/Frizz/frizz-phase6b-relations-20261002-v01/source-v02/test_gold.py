import unittest
from gold import collision_stats


class GoldTests(unittest.TestCase):
    def test_descriptor_ties_are_not_choice_recovery(self):
        r={'selected':0,'same':[0,1,2],'factors':{'x':[[1],[1],[0]]}}
        v=collision_stats([r],['x'])
        self.assertEqual(v['oracle_tie_top1'],.5)
        self.assertEqual(v['remaining_collision_candidates'],1)
        self.assertEqual(v['distinguished_pairs'],1)


if __name__=='__main__':unittest.main()
