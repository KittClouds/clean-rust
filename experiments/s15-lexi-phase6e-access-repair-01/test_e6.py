import unittest
from e6 import *
class LossTests(unittest.TestCase):
    def test_exact_reference(self):
        z=torch.tensor([2.,-2.,1.,-1.],requires_grad=True);y=torch.tensor([1.,0.,1.,0.]);owner=torch.tensor([0,0,1,1]);loss,terms=losses(z,y,owner,2)
        p=z.sigmoid().reshape(2,2);expected=torch.nn.functional.binary_cross_entropy_with_logits(z,y)+.25*(1-(p[:,0]+1e-6)/(p.sum(1)+1-p[:,0]+1e-6)).mean()+.10*torch.nn.functional.softplus(torch.tensor([-3.,-1.])).mean()
        self.assertAlmostEqual(float(loss.detach()),float(expected.detach()),places=6);loss.backward();self.assertTrue(torch.isfinite(z.grad).all())
    def test_empty_class(self):
        for y in [torch.zeros(3),torch.ones(3)]:
            z=torch.zeros(3,requires_grad=True);loss,_=losses(z,y,torch.zeros(3,dtype=torch.long),1);loss.backward();self.assertTrue(torch.isfinite(z.grad).all())
    def test_row_normalization(self):
        a,_=losses(torch.tensor([1.,-1.]),torch.tensor([1.,0.]),torch.zeros(2,dtype=torch.long),1)
        b,_=losses(torch.tensor([1.,-1.,1.,-1.]),torch.tensor([1.,0.,1.,0.]),torch.tensor([0,0,1,1]),2)
        self.assertAlmostEqual(float(a),float(b),places=6)
    def test_firewall(self):
        with self.assertRaises(ValueError):prepare('TEST')
if __name__=='__main__':unittest.main()
