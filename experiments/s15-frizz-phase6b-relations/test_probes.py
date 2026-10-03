import unittest
import torch
from probes import Pair,factor_metric,pair_metric


class ProbeTests(unittest.TestCase):
    def test_directional_swap(self):
        for family in ('linear','mlp'):
            for view in ('concat','difference'):
                x=torch.tensor([[1.,2.,3.,4.]])
                model=Pair(4,family,view)
                swapped=torch.cat(x.chunk(2,-1)[::-1],-1) if view=='concat' else -x
                self.assertTrue(torch.equal(model(x),-model(swapped)))

    def test_product_cannot_encode_orientation(self):
        for family in ('linear','mlp'):
            self.assertEqual(Pair(4,family,'product')(torch.ones(2,4)).tolist(),[0.,0.])

    def test_unknown_dev_value_is_failure(self):
        t={'same_mask':torch.tensor([[True,True]]),'labels':{'f':torch.tensor([[[0],[-1]]])},
           'vocab':{'f':[[4]]},'eligible':torch.tensor([True])}
        metric=factor_metric(torch.zeros(1,2,1),t,'f')
        self.assertEqual(metric['mean_component_accuracy'],.5)
        self.assertEqual(metric['components'][0]['unknown_DEV_values'],1)

    def test_pair_mask_excludes_padding(self):
        t={'pair_mask':torch.tensor([[True,True,False]]),'pair_labels':torch.tensor([[1.,0.,1.]])}
        m=pair_metric(torch.tensor([[1.,-1.,-10.]]),t)
        self.assertEqual(m['balanced_accuracy'],1.)
        self.assertEqual(m['pairs'],2)


if __name__=='__main__':unittest.main()
