import unittest
import numpy as np
import torch
from response_tools import paired_interval,candidate_counts,loss_by_root


class ResponseTests(unittest.TestCase):
    def test_cluster_pairing_and_direction(self):
        result=paired_interval(np.zeros(20),np.ones(20),repetitions=100)
        self.assertEqual(result['delta'],1.)
        self.assertEqual(result['ci95'],[1.,1.])

    def test_padding_not_loss_or_counts(self):
        mask=torch.tensor([[True,False],[True,False]])
        y=torch.tensor([[1.,0.],[0.,1.]])
        p=torch.tensor([[10.,-100.],[-10.,100.]])
        self.assertEqual(candidate_counts(p,y,mask).tolist(),[[1.,1.,0.,0.],[0.,0.,1.,1.]])
        loss=loss_by_root(p,y,mask,.5)
        self.assertTrue(np.all(loss<.001))


if __name__=='__main__':
    unittest.main()
