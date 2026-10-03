import unittest
import numpy as np
from ranking import target_ranks,recorder,paired_gain

class RankingTests(unittest.TestCase):
    def test_padding_cannot_win_and_ties_follow_canonical_order(self):
        scores=np.array([[5.,5.,100.]])
        mask=np.array([[True,True,False]])
        self.assertEqual(target_ranks(scores,mask,np.array([[False,True,False]])).tolist(),[2])
    def test_type_excluded_target_gets_zero_hit_without_fallback(self):
        scores=np.array([[.1,.9,.8],[.1,.9,.8]])
        mask=np.ones((2,3),bool);types=np.array([[1,2,2],[1,2,2]])
        selected=np.array([0,0]);opt=np.array([[True,False,False],[True,False,False]])
        meta=[{'renderer':'V1'},{'renderer':'V2'}]
        report,raw=recorder(scores,mask,selected,opt,types,np.array([1,1]),meta)
        self.assertEqual(report['learned_type']['selected']['MRR'],0.)
        self.assertEqual(report['gold_type']['selected']['top1_hit'],1.)
        self.assertEqual(raw['learned_type']['selected_rank'].tolist(),[-1,-1])
    def test_best_optimal_rank_uses_any_optimal_member(self):
        self.assertEqual(target_ranks(np.array([[1.,3.,2.]]),np.ones((1,3),bool),np.array([[True,False,True]])).tolist(),[2])
    def test_paired_gain_retains_renderer_pair_unit(self):
        result=paired_gain(np.array([2,2,1,1]),np.array([1,1,1,1]))
        self.assertEqual(result['roots'],2);self.assertEqual(result['difference'],.5)
    def test_nonfinite_scores_rejected(self):
        with self.assertRaises(ValueError):target_ranks(np.array([[np.nan]]),np.array([[True]]),np.array([[True]]))

if __name__=='__main__':unittest.main()
