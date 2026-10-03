"""Regression fixtures for repaired harness; no bank/model exposure."""
import unittest

import torch

from common import Interface, masked_forward, variance_floor_loss, balanced_bce
from dataset import candidate_indices
from train import pair_loss, PRIMARY, PRESERVE, configure_isolation, losses
from diagnostics import positive_control


class RepairTests(unittest.TestCase):
    def test_packed_indices_and_renderer_permutation(self):
        action = [{'type':'MOVE','args':{'src':'a','dst':'b'}}]
        one = candidate_indices(action,['a','b'],0,{'a','b'})
        two = candidate_indices(action,['b','a'],2,{'a','b'})
        E = torch.tensor([10,20,200,100])
        self.assertEqual(E[torch.tensor(one[0][:2])].tolist(),[10,20])
        self.assertEqual(E[torch.tensor(two[0][:2])].tolist(),[100,200])

    def test_missing_candidate_binding_stops(self):
        with self.assertRaises(ValueError):
            candidate_indices([{'type':'MOVE','args':{'src':'a'}}],['b'],0,{'a','b'})

    def test_padding_excluded(self):
        model = Interface(8,64,32,['solvable'],[PRESERVE,PRIMARY],28)
        with torch.no_grad():
            model.heads.a.weight.zero_();model.heads.a.bias.fill_(-4)
        H = {'row':torch.randn(2,6,8),'ent':torch.randn(4,8),
             'cand_ent':torch.full((2,28,3),-1,dtype=torch.long),
             'cand_type':torch.zeros(2,28,dtype=torch.long),
             'cand_mask':torch.zeros(2,28,dtype=torch.bool)}
        H['cand_mask'][:,:2]=True
        a = masked_forward(model,H)[4]
        self.assertTrue(bool((a.argmax(1)<2).all()))
        self.assertTrue(bool((a[:,2:]<-1e8).all()))
        self.assertTrue(torch.isfinite(torch.nn.functional.cross_entropy(a,torch.tensor([0,1]))))

    def test_variance_floor_has_gradient(self):
        s = (torch.randn(8,64)*.01).requires_grad_()
        v = variance_floor_loss(s,torch.ones(64))
        v.backward()
        self.assertTrue(v.requires_grad)
        self.assertTrue(torch.isfinite(s.grad).all())
        self.assertGreater(float(s.grad.abs().sum()),0)

    def test_nan_padding_filtered_before_loss(self):
        logits = torch.zeros(3,requires_grad=True)
        labels = torch.tensor([0.,1.,float('nan')])
        mask = torch.isfinite(labels)
        l = balanced_bce(logits[mask],labels[mask],.5)
        l.backward()
        self.assertTrue(torch.isfinite(l))
        self.assertEqual(float(logits.grad[2]),0)

    def test_dev_pair_rejected(self):
        with self.assertRaises(ValueError):
            pair_loss(None,{'split':'DEV'},(0,1),{},False)

    def test_known_solvable_control(self):
        torch.set_num_threads(2)
        r = positive_control('cpu')
        self.assertGreaterEqual(r['result']['balanced_accuracy'],.95)

    def test_isolation_and_train_pair_have_real_gradients(self):
        torch.manual_seed(0)
        model = Interface(8,64,32,['solvable'],[PRESERVE,PRIMARY],28)
        initial = {n:p.detach().clone() for n,p in model.state_dict().items()}
        configure_isolation(model)
        for n,p in model.state_dict().items():
            self.assertTrue(torch.equal(p,initial[n]))
        H = {'row':torch.randn(2,6,8),'ent':torch.randn(4,8),
             'cand_ent':torch.full((2,28,3),-1,dtype=torch.long),
             'cand_type':torch.zeros(2,28,dtype=torch.long),
             'cand_mask':torch.zeros(2,28,dtype=torch.bool)}
        H['cand_mask'][:,:2]=True
        H['cand_ent'][0,0,0]=0;H['cand_ent'][1,0,0]=2
        d = {'split':'TRAIN','row_ids':['TRAIN:0','TRAIN:0@S2'],'H':H}
        p = pair_loss(model,d,(0,1),{},True)
        p.backward()
        self.assertGreater(float(model.graft.rho_e[0].weight.grad.abs().sum()),0)
        self.assertIsNone(model.heads.a.weight.grad)
        self.assertIsNone(model.heads.g['solvable'].weight.grad)
        self.assertIsNotNone(model.heads.c[PRIMARY].weight.grad)
        self.assertFalse(model.heads.a.weight.requires_grad)


if __name__=='__main__':
    unittest.main()
