"""Metric positive controls, denominator guards and degenerate loss fixtures."""
import unittest
import torch
from gate import LegalGate,loss
from legal_metrics import rank,legality

class Tests(unittest.TestCase):
    def test_rejection(self):
        mask=torch.ones(2,3,dtype=torch.bool);end={'selected':torch.tensor([0,1]),
            'selected_eligible':torch.ones(2,dtype=torch.bool),'optimal':torch.tensor([[1,0,0],[0,1,0]]).bool(),
            'optimal_eligible':torch.tensor([True,False])}
        r=rank(torch.zeros(2,3),torch.zeros_like(mask),mask,end)
        self.assertEqual(r['selected']['eligible_roots'],2);self.assertEqual(r['selected']['MRR'],0)
        self.assertEqual(r['optimal']['eligible_roots'],1);self.assertEqual(r['gate_abstentions'],2)
    def test_gold_control(self):
        gold=torch.tensor([[1,0,0],[0,1,0]]).bool();mask=torch.tensor([[1,1,0],[1,1,0]]).bool()
        r=legality(gold.float()*2-1,gold,mask,torch.tensor([0,1]),torch.ones(2,dtype=torch.bool))
        for k in ('BA','precision','recall','F1','full_exact_set_recovery','root_mean_Jaccard'):self.assertEqual(r[k],1)
    def test_loss_single_class(self):
        for truth in (torch.ones(2,3).bool(),torch.zeros(2,3).bool()):
            x=torch.zeros(2,3,requires_grad=True);v=sum(loss(x,truth,torch.ones_like(truth)).values())
            self.assertTrue(torch.isfinite(v));v.backward();self.assertTrue(torch.isfinite(x.grad).all())
    def test_known_solvable_fit(self):
        torch.manual_seed(0);x=torch.tensor([[-1.],[-2.],[1.],[2.]])
        y=(x[:,0]>0).float();m=torch.nn.Linear(1,1);o=torch.optim.SGD(m.parameters(),lr=.2)
        for _ in range(80):
            v=torch.nn.functional.binary_cross_entropy_with_logits(m(x).flatten(),y)
            o.zero_grad();v.backward();o.step()
        self.assertTrue(torch.equal(m(x).flatten()>0,y.bool()))

if __name__=='__main__':unittest.main()
