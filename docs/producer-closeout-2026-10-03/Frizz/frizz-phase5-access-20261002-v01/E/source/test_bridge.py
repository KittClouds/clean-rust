import unittest
import torch

from bridge_model import Bridge, CORE_TARGETS
from dataset import argument_indices
from objective import renderer_consistency, variance_floor, supervised
from evaluate import binary_metric


class BridgeTests(unittest.TestCase):
    def setUp(self):
        torch.set_num_threads(2)
        torch.manual_seed(0)
        self.model=Bridge({n:['0','1'] for n in CORE_TARGETS},width=8)
        self.H={'row':torch.randn(2,6,8),'ent':torch.randn(8,8),
                'cand_ent':torch.tensor([[[0,1,2,3],[4,5,-1,-1],[-1]*4]]*2),
                'cand_type':torch.tensor([[0,1,0]]*2),
                'cand_mask':torch.tensor([[True,True,False]]*2)}

    def test_exhaustive_shape_and_padding(self):
        out=self.model(self.H)
        self.assertEqual(out['action'].shape,(2,3))
        self.assertTrue(torch.isneginf(out['action'][:,2]).all())
        self.assertTrue(torch.equal(out['e'][:,2],torch.zeros(2,32)))

    def test_fourth_argument_preserved(self):
        a={'args':{'a':'e0','b':'e1','c':'e2','d':'e3'}}
        self.assertEqual(argument_indices(a,['e0','e1','e2','e3'],10),[10,11,12,13])
        before=self.model(self.H)['c_local'].detach()
        self.H['ent'][3]+=10
        self.assertFalse(torch.equal(before,self.model(self.H)['c_local']))

    def test_unbound_argument_keeps_its_slot(self):
        a={'args':{'a':'e0','b':'unobserved','c':'e1','d':'e2'}}
        self.assertEqual(argument_indices(a,['e0','e1','e2'],10),[10,-1,11,12])

    def test_variance_is_differentiable(self):
        x=torch.randn(10,64,requires_grad=True)
        loss=variance_floor(x,torch.ones(64)*10)
        loss.backward()
        self.assertGreater(float(x.grad.abs().sum()),0)

    def test_pair_mismatch_rejected(self):
        out=self.model(self.H)
        self.H['cand_mask'][1,1]=False
        with self.assertRaises(ValueError):
            renderer_consistency(out,self.H['cand_mask'],torch.tensor([True,True]))

    def test_no_recurrence_or_conflict_head(self):
        self.assertNotIn('conflict',self.model.core)
        self.assertEqual(set(self.model.candidate),{'candidate_legal','candidate_satisfies_goal'})

    def test_supervised_step_masks_and_gradients(self):
        out=self.model(self.H)
        d={'candidate':{n:torch.tensor([[1.,0.,0.]]*2) for n in out['candidate']},
           'binary':{n:torch.tensor([0.,1.]) for n in out['binary']},
           'binary_mask':{n:torch.tensor([True,True]) for n in out['binary']},
           'core':{n:torch.tensor([0,1]) for n in out['core']},'action':torch.tensor([0,-1])}
        pis={n:.5 for n in (*d['candidate'],*d['binary'])}
        terms=supervised(out,d,torch.arange(2),self.H['cand_mask'],pis)
        loss=sum(terms.values())
        self.assertTrue(torch.isfinite(loss));loss.backward()
        self.assertIsNotNone(self.model.rho_e[-1].weight.grad)
        changed={n:x.clone() for n,x in d['candidate'].items()}
        for x in changed.values():
            x[:,2]=1000
        d['candidate']=changed
        new=supervised(out,d,torch.arange(2),self.H['cand_mask'],pis)
        self.assertTrue(torch.equal(terms['candidate_legal'],new['candidate_legal']))

    def test_one_class_binary_undefined_not_zero(self):
        result=binary_metric(torch.ones(3),torch.ones(3))
        self.assertIsNone(result['balanced_accuracy'])


if __name__=='__main__':
    unittest.main()
