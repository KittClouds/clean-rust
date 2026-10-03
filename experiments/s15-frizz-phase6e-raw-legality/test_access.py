import unittest
import torch
from common import setup,legality,rank
from panel import objective
from late_access import LowRank

class Tests(unittest.TestCase):
    def test_zero_adapter(self):
        torch.manual_seed(0);base=torch.nn.Linear(6,8,bias=False);m=LowRank(base);x=torch.randn(4,6)
        self.assertTrue(torch.equal(m(x),base(x)));self.assertFalse(base.weight.requires_grad)
        m(x).sum().backward();self.assertTrue(m.b.grad.abs().sum()>0)
        self.assertIsNone(base.weight.grad)
    def test_known_solvable_readouts(self):
        setup();x=torch.tensor([[[-2.],[2.]], [[-1.],[1.]]]);truth=x[:,:,0]>0;mask=torch.ones_like(truth)
        for family in ('linear','mlp'):
            torch.manual_seed(0)
            m=torch.nn.Linear(1,1) if family=='linear' else torch.nn.Sequential(torch.nn.Linear(1,64),torch.nn.GELU(),torch.nn.Linear(64,1))
            o=torch.optim.AdamW(m.parameters(),lr=.02)
            for _ in range(80):
                loss=objective(m(x).squeeze(-1),truth,mask);o.zero_grad();loss.backward();o.step()
            metrics=legality(m(x).squeeze(-1),truth,mask,torch.tensor([1,1]),torch.ones(2).bool())
            self.assertEqual(metrics['full_exact_set_recovery'],1);self.assertEqual(metrics['BA'],1)
    def test_gate_rejection_denominator(self):
        e={'selected':torch.tensor([0]),'selected_eligible':torch.tensor([True]),'optimal':torch.tensor([[True,False]]),'optimal_eligible':torch.tensor([True])}
        r=rank(torch.ones(1,2),torch.tensor([[False,True]]),torch.ones(1,2).bool(),e)
        self.assertEqual(r['selected']['eligible_roots'],1);self.assertEqual(r['selected']['MRR'],0)

if __name__=='__main__':unittest.main()
